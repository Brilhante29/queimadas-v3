"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp26_g3_contract_v2_evaluation.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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

from src.experiments.backtest_real_baselines import MIN_TRAIN_MONTHS, build_features, load_merged_target  # noqa: E402
from src.utils.metrics import recall_at_k, zero_indevido  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp26_g3_contract_v2_evaluation"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
EXP10_PREDICTIONS = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
CHAPADA_WEIGHTS = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
EXP25_REPORT = PROJECT_ROOT / "outputs" / "exp25_g3_feasibility_audit" / "feasibility_report.json"

GATE_YEARS = [2023, 2024]
CRITICAL_MONTHS = [10, 11]
CHAMPION = "climatology_regional_intensity12"
BASELINE = "climatology_municipal"

CONTRACT_V2 = {
    "version": 2,
    "ceara": {
        "wape_scope_month_max": 0.25,
        "wape_scope_season_max": 0.20,
        "recall10_min": 0.70,
        "zero_indevido_max": 0.0,
    },
    "chapada_araripe": {
        "wape_scope_season_max": 0.40,
        "recall10_min": 0.60,
        "zero_indevido_max": 0.0,
    },
}


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp26_g3_contract_v2_evaluation.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def build_gate_frame() -> pd.DataFrame:
    """Constroi a etapa `build gate frame` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp26_g3_contract_v2_evaluation.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df, _ = load_merged_target()
    hist_positive = (
        df.sort_values(["geocodigo", "period"])
        .groupby("geocodigo")["fire_count"]
        .transform(lambda s: s.fillna(0.0).shift(1).fillna(0.0).cumsum())
    )
    df = df.assign(hist_positive=hist_positive.astype(float))
    df = build_features(df)
    preds = pd.read_csv(EXP10_PREDICTIONS)
    preds = preds[preds["model"].isin([CHAMPION, BASELINE])][["model", "geocodigo", "ano", "mes", "y_pred"]]

    cells = []
    for year in GATE_YEARS:
        for month in CRITICAL_MONTHS:
            cut = pd.Period(f"{year}-{month:02d}", freq="M")
            train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
            test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
            hist = train.groupby("geocodigo")["fire_count"].count()
            eligible = hist[hist >= MIN_TRAIN_MONTHS].index
            test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()]
            cells.append(test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "hist_positive"]])
    gate = pd.concat(cells, ignore_index=True)
    gate = gate.merge(preds, on=["geocodigo", "ano", "mes"], how="left")
    if gate["y_pred"].isna().any():
        raise RuntimeError("Prediction coverage gap on gate cells")
    return gate


def wape_of(frame: pd.DataFrame) -> float:
    """Executa a etapa `wape of` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp26_g3_contract_v2_evaluation.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    denom = float(frame["fire_count"].sum())
    if denom <= 0:
        return float("nan")
    return float(np.abs(frame["fire_count"] - frame["y_pred"]).sum() / denom)


def scope_metrics(frame: pd.DataFrame) -> dict[str, float]:
    """Executa a etapa `scope metrics` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp26_g3_contract_v2_evaluation.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    monthly = frame.groupby(["ano", "mes"], as_index=False)[["fire_count", "y_pred"]].sum()
    seasonal = frame.groupby(["ano"], as_index=False)[["fire_count", "y_pred"]].sum()
    ranking = frame.rename(columns={"fire_count": "y_true", "geocodigo": "municipio_id"}).copy()
    return {
        "wape_municipal_month_informational": wape_of(frame),
        "wape_scope_month": wape_of(monthly),
        "wape_scope_season": wape_of(seasonal),
        "recall10": float(recall_at_k(ranking, k=10, group_cols=["ano", "mes"])),
        "zero_indevido": float(
            zero_indevido(frame["y_pred"].to_numpy(dtype=float), frame["hist_positive"].to_numpy(dtype=float))
        ),
        "n_cells": int(len(frame)),
        "total_observed": float(frame["fire_count"].sum()),
    }


def evaluate_scope(metrics: dict[str, float], limits: dict[str, float]) -> dict[str, object]:
    """Calcula a etapa `evaluate scope` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp26_g3_contract_v2_evaluation.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    checks = {}
    if "wape_scope_month_max" in limits:
        checks["wape_scope_month"] = {
            "value": metrics["wape_scope_month"],
            "limit": limits["wape_scope_month_max"],
            "pass": bool(metrics["wape_scope_month"] <= limits["wape_scope_month_max"]),
        }
    checks["wape_scope_season"] = {
        "value": metrics["wape_scope_season"],
        "limit": limits["wape_scope_season_max"],
        "pass": bool(metrics["wape_scope_season"] <= limits["wape_scope_season_max"]),
    }
    checks["recall10"] = {
        "value": metrics["recall10"],
        "limit": limits["recall10_min"],
        "pass": bool(metrics["recall10"] >= limits["recall10_min"]),
    }
    checks["zero_indevido"] = {
        "value": metrics["zero_indevido"],
        "limit": limits["zero_indevido_max"],
        "pass": bool(metrics["zero_indevido"] <= limits["zero_indevido_max"]),
    }
    finite = all(np.isfinite(c["value"]) for c in checks.values())
    return {"checks": checks, "all_pass": bool(finite and all(c["pass"] for c in checks.values()))}


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp26_g3_contract_v2_evaluation.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gate = build_gate_frame()
    chapada = set(pd.read_csv(CHAPADA_WEIGHTS)["geocodigo"].astype(int).unique().tolist())

    results: dict[str, dict] = {}
    for model in [CHAMPION, BASELINE]:
        frame = gate[gate["model"] == model]
        ce = frame[frame["uf"] == "CE"]
        ch = frame[frame["geocodigo"].astype(int).isin(chapada)]
        results[model] = {
            "ceara": scope_metrics(ce),
            "chapada_araripe": scope_metrics(ch),
        }

    champion_eval = {
        "ceara": evaluate_scope(results[CHAMPION]["ceara"], CONTRACT_V2["ceara"]),
        "chapada_araripe": evaluate_scope(results[CHAMPION]["chapada_araripe"], CONTRACT_V2["chapada_araripe"]),
    }
    # G2 coherence on the v2 primary metrics: champion must not lose to the
    # baseline on any gating metric.
    coherence = {}
    for scope in ["ceara", "chapada_araripe"]:
        champ, base = results[CHAMPION][scope], results[BASELINE][scope]
        coherence[scope] = {
            "wape_scope_month_champion_le_baseline": bool(champ["wape_scope_month"] <= base["wape_scope_month"] + 1e-9),
            "wape_scope_season_champion_le_baseline": bool(champ["wape_scope_season"] <= base["wape_scope_season"] + 1e-9),
            "recall10_champion_ge_baseline": bool(champ["recall10"] >= base["recall10"] - 1e-9),
        }
    all_pass = champion_eval["ceara"]["all_pass"] and champion_eval["chapada_araripe"]["all_pass"]
    coherent = all(all(v for v in c.values()) for c in coherence.values())
    decision = "G3_PASS_V2" if (all_pass and coherent) else "G3_FAIL_V2"

    report = {
        "experiment_id": "EXP-2026-07-11-26",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "contract": CONTRACT_V2,
        "authorization": "Aprovado pelo owner humano em 2026-07-11 via chat (DECISION-G3-CONTRACT-V2); limites definidos com conhecimento do desempenho do champion; base estatistica = EXP-25 + superioridade sobre baseline.",
        "protocol": "Fatia de gate congelada de EXP-12..24: 2023-2024, meses criticos 10-11, mesma elegibilidade; predicoes EXP-10 imutaveis; nada re-ajustado.",
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "exp10_predictions_sha256": sha256_file(EXP10_PREDICTIONS),
        "exp25_report_sha256": sha256_file(EXP25_REPORT),
        "metrics": results,
        "champion_evaluation": champion_eval,
        "baseline_coherence": coherence,
        "decision": decision,
        "artifacts": ["contract_v2_report.json", "contract_v2_metrics.csv"],
    }
    (OUT_DIR / "contract_v2_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    rows = []
    for model, scopes in results.items():
        for scope, m in scopes.items():
            rows.append({"model": model, "scope": scope, **m})
    pd.DataFrame(rows).to_csv(OUT_DIR / "contract_v2_metrics.csv", index=False)

    print("=== EXP-26 G3 contract v2 evaluation ===")
    for scope in ["ceara", "chapada_araripe"]:
        print(f"-- {scope} --")
        for name, check in champion_eval[scope]["checks"].items():
            status = "PASS" if check["pass"] else "FAIL"
            print(f"  {name}: {check['value']:.4f} (limite {check['limit']}) -> {status}")
        print(f"  coherence vs baseline: {coherence[scope]}")
    print(f"DECISION: {decision}")


if __name__ == "__main__":
    main()
