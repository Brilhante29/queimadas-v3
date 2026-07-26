"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g3_scope_gate_audit.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import load_merged_target  # noqa: E402
from src.utils.metrics import recall_at_k, wape, zero_indevido  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "g3_scope_gate_audit"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
CHAPADA_WEIGHTS = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
G5_REPORT = PROJECT_ROOT / "outputs" / "g5_conformal_ic95_guarded_exp10" / "g5_report.json"
CRITICAL_MONTHS = {10, 11}
SCOPE_CONFIG = {
    "ceara": {"threshold_wape": 0.20, "threshold_zero_indevido": 0.0, "threshold_recall10": 0.70},
    "chapada_cariri": {"threshold_wape": 0.25, "threshold_zero_indevido": 0.0, "threshold_recall10": 0.60},
}
PREDICTION_FILES = [
    ("EXP12", PROJECT_ROOT / "outputs" / "g3_frontier_sweep" / "candidate_predictions.csv"),
    ("EXP13", PROJECT_ROOT / "outputs" / "exp13_event_point_features_g3" / "predictions.csv"),
    ("EXP14", PROJECT_ROOT / "outputs" / "exp14_spatial_event_kernel_g3" / "predictions.csv"),
]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_scope_gate_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_hist_positive() -> pd.DataFrame:
    """Carrega a etapa `load hist positive` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_scope_gate_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    target, _ = load_merged_target()
    target = target.sort_values(["geocodigo", "period"]).copy()
    target["hist_positive"] = (
        target.groupby("geocodigo")["fire_count"]
        .transform(lambda s: s.fillna(0.0).shift(1).fillna(0.0).cumsum())
        .astype(float)
    )
    return target[["geocodigo", "ano", "mes", "hist_positive"]]


def load_predictions() -> pd.DataFrame:
    """Carrega a etapa `load predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_scope_gate_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for source, path in PREDICTION_FILES:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        needed = {"geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred", "model"}
        missing = needed - set(df.columns)
        if missing:
            raise RuntimeError(f"{path} missing columns: {sorted(missing)}")
        df = df[list(needed)].copy()
        df["prediction_source"] = source
        rows.append(df)
    if not rows:
        raise RuntimeError("No candidate prediction files found")
    return pd.concat(rows, ignore_index=True)


def recall10_by_month(frame: pd.DataFrame) -> float:
    """Executa a etapa `recall10 by month` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_scope_gate_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    work = frame.rename(columns={"fire_count": "y_true", "geocodigo": "municipio_id"}).copy()
    return float(recall_at_k(work, k=10, group_cols=["ano", "mes"]))


def scope_mask(df: pd.DataFrame, scope: str, chapada_geocodes: set[int]) -> pd.Series:
    """Executa a etapa `scope mask` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_scope_gate_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if scope == "ceara":
        return df["uf"].eq("CE")
    if scope == "chapada_cariri":
        return df["geocodigo"].astype(int).isin(chapada_geocodes)
    raise ValueError(scope)


def audit() -> tuple[pd.DataFrame, dict[str, object]]:
    """Executa a etapa `audit` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_scope_gate_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    hist = load_hist_positive()
    preds = load_predictions()
    chapada_geocodes = set(pd.read_csv(CHAPADA_WEIGHTS)["geocodigo"].astype(int).unique().tolist())

    preds = preds.merge(hist, on=["geocodigo", "ano", "mes"], how="left")
    if preds["hist_positive"].isna().any():
        missing = preds.loc[preds["hist_positive"].isna(), ["geocodigo", "ano", "mes"]].drop_duplicates()
        raise RuntimeError(f"Missing hist_positive rows: {missing.head().to_dict(orient='records')}")

    gate = preds[preds["ano"].between(2023, 2024) & preds["mes"].isin(CRITICAL_MONTHS)].copy()
    rows = []
    for (source, model), group in gate.groupby(["prediction_source", "model"], sort=False):
        for scope, cfg in SCOPE_CONFIG.items():
            frame = group[scope_mask(group, scope, chapada_geocodes)].copy()
            if frame.empty:
                continue
            y_true = frame["fire_count"].to_numpy(dtype=float)
            y_pred = frame["y_pred"].to_numpy(dtype=float)
            w = float(wape(y_true, y_pred))
            zi = float(zero_indevido(y_pred, frame["hist_positive"].to_numpy(dtype=float)))
            r10 = recall10_by_month(frame)
            reasons = []
            if w > cfg["threshold_wape"]:
                reasons.append(f"WAPE {w:.4f} > {cfg['threshold_wape']:.2f}")
            if zi > cfg["threshold_zero_indevido"]:
                reasons.append(f"zero indevido {zi:.4f} > {cfg['threshold_zero_indevido']:.1f}")
            if r10 < cfg["threshold_recall10"]:
                reasons.append(f"Recall@10 {r10:.4f} < {cfg['threshold_recall10']:.2f}")
            rows.append(
                {
                    "prediction_source": source,
                    "model": model,
                    "scope": scope,
                    "gate_window": "2023-2024 critical months Oct-Nov",
                    "n": int(len(frame)),
                    "y_total": float(frame["fire_count"].sum()),
                    "pred_total": float(frame["y_pred"].sum()),
                    "wape_critical": w,
                    "zero_indevido_critical": zi,
                    "recall10_critical_by_month": r10,
                    "threshold_wape": cfg["threshold_wape"],
                    "threshold_zero_indevido": cfg["threshold_zero_indevido"],
                    "threshold_recall10": cfg["threshold_recall10"],
                    "passes_g3_point_metrics": len(reasons) == 0,
                    "fail_reasons": "; ".join(reasons) if reasons else "PASS",
                }
            )
    audit_df = pd.DataFrame(rows).sort_values(["scope", "wape_critical", "prediction_source", "model"]).reset_index(drop=True)
    g5 = json.loads(G5_REPORT.read_text(encoding="utf-8")) if G5_REPORT.exists() else {}
    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "chapada_weights_sha256": sha256_file(CHAPADA_WEIGHTS),
        "g5_report_sha256": sha256_file(G5_REPORT) if G5_REPORT.exists() else None,
        "g5_gate_reference": g5.get("gate_G5", "UNKNOWN"),
        "prediction_files": [
            {"source": source, "path": str(path.relative_to(PROJECT_ROOT)), "sha256": sha256_file(path)}
            for source, path in PREDICTION_FILES
            if path.exists()
        ],
        "scopes": SCOPE_CONFIG,
        "best_by_scope": audit_df.groupby("scope").head(1).to_dict(orient="records"),
        "any_candidate_passes_g3_point_metrics": bool(audit_df["passes_g3_point_metrics"].any()),
    }
    return audit_df, manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/g3_scope_gate_audit.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    audit_df, manifest = audit()
    audit_df.to_csv(OUT_DIR / "g3_scope_gate_audit.csv", index=False)
    (OUT_DIR / "g3_scope_gate_audit.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("=== G3 scope gate audit ===")
    print(audit_df.groupby("scope").head(8).to_string(index=False))
    print(f"ANY_PASS: {manifest['any_candidate_passes_g3_point_metrics']}")


if __name__ == "__main__":
    main()
