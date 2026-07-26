"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp22_local_ndvi_triage_g3.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_inpe_local import load_ibge_lookup, normalize_name  # noqa: E402
from src.experiments.backtest_real_baselines import MIN_TRAIN_MONTHS, build_features, load_merged_target  # noqa: E402
from src.utils.metrics import recall_at_k, wape, zero_indevido  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp22_local_ndvi_triage_g3"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
LOCAL_NDVI = REPO_ROOT / "NDVI_Ceara_Municipios_Mensal_FINAL.csv"
CONTRACT_SMOKE = PROJECT_ROOT / "outputs" / "mod13q1_contract_smoke" / "contract_smoke_report.json"
EXP10_PREDICTIONS = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
CHAPADA_WEIGHTS = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
TEST_MONTHS = [pd.Period(f"{y}-{m:02d}", freq="M") for y in range(2015, 2025) for m in range(1, 13)]
CRITICAL_MONTHS = {10, 11}
DRY_MONTHS = {8, 9, 10, 11, 12}
G3_CE_LIMIT = 0.20
G3_CHAPADA_LIMIT = 0.25
WINDOWS = [1, 3, 6, 12]
LAMBDAS = [0.10, 0.25, 0.50]
SCORE_MODES = ["low_ndvi", "green_fuel", "drop3", "drop6", "stress_drop3", "stress_roll3"]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def normalized_share(values: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Executa a etapa `normalized share` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    values = np.maximum(np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0), 0.0)
    total = float(values.sum())
    if total > 1e-12:
        return values / total
    fallback = np.maximum(np.nan_to_num(fallback, nan=0.0, posinf=0.0, neginf=0.0), 0.0)
    fallback_total = float(fallback.sum())
    if fallback_total > 1e-12:
        return fallback / fallback_total
    return np.ones(len(values), dtype=float) / max(len(values), 1)


def load_chapada_geocodes() -> set[int]:
    """Carrega a etapa `load chapada geocodes` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return set(pd.read_csv(CHAPADA_WEIGHTS)["geocodigo"].astype(int).unique().tolist())


def load_local_ndvi() -> pd.DataFrame:
    """Carrega a etapa `load local ndvi` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    raw = pd.read_csv(LOCAL_NDVI)
    required = {"city", "month", "year", "ndvi"}
    missing = required - set(raw.columns)
    if missing:
        raise RuntimeError(f"Local NDVI missing columns: {sorted(missing)}")
    geo = {k[0]: v for k, v in load_ibge_lookup().items() if k[1] == "CE"}
    df = raw.rename(columns={"city": "municipio", "month": "mes", "year": "ano"}).copy()
    df["key"] = df["municipio"].map(normalize_name)
    df["geocodigo"] = df["key"].map(lambda x: geo.get(x, (np.nan, None, None))[0])
    df = df.dropna(subset=["geocodigo"]).copy()
    df["geocodigo"] = df["geocodigo"].astype(int)
    df["ano"] = df["ano"].astype(int)
    df["mes"] = df["mes"].astype(int)
    df["ndvi"] = pd.to_numeric(df["ndvi"], errors="coerce")
    df["ndvi_valid"] = df["ndvi"].where(df["ndvi"] > 0)
    return df[["geocodigo", "ano", "mes", "ndvi_valid"]].rename(columns={"ndvi_valid": "ndvi"})


def add_ndvi_features(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `add ndvi features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    ndvi = load_local_ndvi()
    merged = df.merge(ndvi, on=["geocodigo", "ano", "mes"], how="left")
    eval_mask = merged["ano"].between(2015, 2024)
    coverage = merged.loc[eval_mask].groupby("geocodigo")["ndvi"].count()
    if int((coverage >= 100).sum()) < merged.loc[eval_mask, "geocodigo"].nunique():
        raise RuntimeError("Local NDVI coverage is insufficient for exploratory triage")
    merged = merged.sort_values(["geocodigo", "period"]).reset_index(drop=True)
    by_geo = merged.groupby("geocodigo", sort=False)
    for lag in (1, 2, 3, 6, 12):
        merged[f"ndvi_lag{lag}"] = by_geo["ndvi"].shift(lag)
    for window in (3, 6, 12):
        merged[f"ndvi_roll{window}"] = by_geo["ndvi"].transform(
            lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean()
        )
    merged["ndvi_drop3"] = merged["ndvi_lag3"] - merged["ndvi_lag1"]
    merged["ndvi_drop6"] = merged["ndvi_lag6"] - merged["ndvi_lag1"]
    return merged


def score_from_ndvi(test: pd.DataFrame, mode: str, window: int) -> np.ndarray:
    """Calcula a etapa `score from ndvi` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    lag_col = "ndvi_lag1" if window == 1 else f"ndvi_roll{window}"
    ndvi = test[lag_col].fillna(test["ndvi_lag1"]).fillna(test["ndvi_roll3"]).fillna(0.0).to_numpy(dtype=float)
    ndvi = np.clip(ndvi, 0.0, 1.0)
    low = 1.0 - ndvi
    green = ndvi
    drop3 = np.maximum(test["ndvi_drop3"].fillna(0.0).to_numpy(dtype=float), 0.0)
    drop6 = np.maximum(test["ndvi_drop6"].fillna(0.0).to_numpy(dtype=float), 0.0)
    if mode == "low_ndvi":
        score = low
    elif mode == "green_fuel":
        score = green
    elif mode == "drop3":
        score = drop3
    elif mode == "drop6":
        score = drop6
    elif mode == "stress_drop3":
        score = 0.65 * low + 0.35 * drop3
    elif mode == "stress_roll3":
        score = 0.70 * low + 0.30 * np.maximum(0.0, 0.55 - ndvi)
    else:
        raise ValueError(mode)
    return np.maximum(score, 0.0)


def normalize_predictions(df: pd.DataFrame, model: str, family: str, note: str) -> pd.DataFrame:
    """Executa a etapa `normalize predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = df[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]].copy()
    out["cut"] = out["ano"].astype(str) + "-" + out["mes"].astype(str).str.zfill(2)
    out["model"] = model
    out["family"] = family
    out["note"] = note
    out["y_pred"] = np.maximum(out["y_pred"].astype(float), 0.0)
    return out


def build_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Constroi a etapa `build predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    exp10 = pd.read_csv(EXP10_PREDICTIONS)
    exp10 = exp10[exp10["model"] == "climatology_regional_intensity12"].copy()
    rows_by_model: dict[str, list[pd.DataFrame]] = {}
    notes: dict[str, tuple[str, str]] = {}
    champion_blocks: list[pd.DataFrame] = []

    configs = [(mode, window, lam) for mode in SCORE_MODES for window in WINDOWS for lam in LAMBDAS]
    for mode, window, lam in configs:
        name = f"local_ndvi_{mode}_roll{window}_l{str(lam).replace('.', 'p')}"
        rows_by_model[name] = []
        notes[name] = (
            "local_ndvi_exploratory_allocator",
            f"EXP-10 total-preserving allocation blended with lagged local NDVI exploratory signal; mode={mode}, window={window}, lambda={lam}.",
        )

    for cut in TEST_MONTHS:
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
        test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
        if len(train) == 0 or len(test) == 0:
            continue

        exp10_cut = exp10[(exp10["ano"] == cut.year) & (exp10["mes"] == cut.month)][["geocodigo", "y_pred"]]
        test_with_base = test.merge(exp10_cut, on="geocodigo", how="left", suffixes=("", "_exp10"))
        if test_with_base["y_pred"].isna().any():
            missing = sorted(test_with_base.loc[test_with_base["y_pred"].isna(), "geocodigo"].astype(int).unique().tolist())
            raise RuntimeError(f"EXP-10 prediction coverage gap for {cut}: {missing}")
        base_pred = np.maximum(test_with_base["y_pred"].to_numpy(dtype=float), 0.0)
        total = float(base_pred.sum())
        base_share = normalized_share(base_pred, np.ones(len(base_pred), dtype=float))

        champ = test.copy()
        champ["y_pred"] = base_pred
        champion_blocks.append(champ)

        for mode, window, lam in configs:
            name = f"local_ndvi_{mode}_roll{window}_l{str(lam).replace('.', 'p')}"
            ndvi_score = score_from_ndvi(test, mode, window)
            ndvi_share = normalized_share(ndvi_score, base_pred)
            pred = total * ((1.0 - lam) * base_share + lam * ndvi_share)
            out = test.copy()
            out["y_pred"] = pred
            rows_by_model[name].append(out)

    rows = [
        normalize_predictions(
            pd.concat(champion_blocks, ignore_index=True),
            model="climatology_regional_intensity12",
            family="champion",
            note="Current EXP-10 regional-intensity champion.",
        )
    ]
    for model, blocks in rows_by_model.items():
        family, note = notes[model]
        rows.append(normalize_predictions(pd.concat(blocks, ignore_index=True), model=model, family=family, note=note))
    return pd.concat(rows, ignore_index=True)


def wape_frame(frame: pd.DataFrame) -> float:
    """Executa a etapa `wape frame` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if frame.empty or float(frame["fire_count"].sum()) == 0.0:
        return float("nan")
    return float(wape(frame["fire_count"].to_numpy(dtype=float), frame["y_pred"].to_numpy(dtype=float)))


def recall10_by_month(frame: pd.DataFrame) -> float:
    """Executa a etapa `recall10 by month` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    work = frame.rename(columns={"fire_count": "y_true", "geocodigo": "municipio_id"}).copy()
    return float(recall_at_k(work, k=10, group_cols=["ano", "mes"]))


def metric_block(p: pd.DataFrame, chapada_geocodes: set[int], hist_positive: pd.DataFrame) -> dict[str, object]:
    """Executa a etapa `metric block` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    p = p.merge(hist_positive, on=["geocodigo", "ano", "mes"], how="left")
    critical = p[p["mes"].isin(CRITICAL_MONTHS)]
    dry = p[p["mes"].isin(DRY_MONTHS)]
    selection = critical[critical["ano"].between(2015, 2022)]
    gate = critical[critical["ano"].between(2023, 2024)]
    gate_ce = gate[gate["uf"] == "CE"]
    gate_chapada = gate[gate["geocodigo"].astype(int).isin(chapada_geocodes)]
    selection_ce = selection[selection["uf"] == "CE"]
    selection_chapada = selection[selection["geocodigo"].astype(int).isin(chapada_geocodes)]
    gate_ce_wape = wape_frame(gate_ce)
    gate_chapada_wape = wape_frame(gate_chapada)
    return {
        "extended_wape_all": wape_frame(p),
        "extended_wape_critical": wape_frame(critical),
        "extended_wape_dry": wape_frame(dry),
        "selection_2015_2022_wape_critical_ceara": wape_frame(selection_ce),
        "selection_2015_2022_wape_critical_chapada_cariri": wape_frame(selection_chapada),
        "gate_2023_2024_wape_critical_ceara": gate_ce_wape,
        "gate_2023_2024_wape_critical_chapada_cariri": gate_chapada_wape,
        "gate_2023_2024_recall10_ceara": recall10_by_month(gate_ce),
        "gate_2023_2024_recall10_chapada_cariri": recall10_by_month(gate_chapada),
        "gate_2023_2024_zero_indevido_ceara": float(zero_indevido(gate_ce["y_pred"].to_numpy(dtype=float), gate_ce["hist_positive"].to_numpy(dtype=float))),
        "gate_2023_2024_zero_indevido_chapada_cariri": float(zero_indevido(gate_chapada["y_pred"].to_numpy(dtype=float), gate_chapada["hist_positive"].to_numpy(dtype=float))),
        "gate_critical_n_ceara": int(len(gate_ce)),
        "gate_critical_y_total_ceara": float(gate_ce["fire_count"].sum()),
        "gate_critical_n_chapada_cariri": int(len(gate_chapada)),
        "gate_critical_y_total_chapada_cariri": float(gate_chapada["fire_count"].sum()),
        "passes_g3_ceara_wape": bool(gate_ce_wape <= G3_CE_LIMIT) if np.isfinite(gate_ce_wape) else False,
        "passes_g3_chapada_cariri_wape": bool(gate_chapada_wape <= G3_CHAPADA_LIMIT) if np.isfinite(gate_chapada_wape) else False,
    }


def build_hist_positive(target: pd.DataFrame) -> pd.DataFrame:
    """Constroi a etapa `build hist positive` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    work = target.sort_values(["geocodigo", "period"]).copy()
    work["hist_positive"] = (
        work.groupby("geocodigo")["fire_count"]
        .transform(lambda s: s.fillna(0.0).shift(1).fillna(0.0).cumsum())
        .astype(float)
    )
    return work[["geocodigo", "ano", "mes", "hist_positive"]]


def summarize(preds: pd.DataFrame, chapada_geocodes: set[int], hist_positive: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `summarize` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp22_local_ndvi_triage_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for (model, family), group in preds.groupby(["model", "family"], sort=False):
        row = {"model": model, "family": family, "note": group["note"].iloc[0]}
        row.update(metric_block(group, chapada_geocodes, hist_positive))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["selection_2015_2022_wape_critical_ceara", "selection_2015_2022_wape_critical_chapada_cariri"],
        na_position="last",
    ).reset_index(drop=True)


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp22_local_ndvi_triage_g3.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    hist_positive = build_hist_positive(df)
    df = build_features(df)
    df = add_ndvi_features(df)
    preds = build_predictions(df)
    chapada = load_chapada_geocodes()
    summary = summarize(preds, chapada, hist_positive)

    selected_ce = summary.sort_values("selection_2015_2022_wape_critical_ceara", na_position="last").iloc[0]
    selected_chapada = summary.sort_values("selection_2015_2022_wape_critical_chapada_cariri", na_position="last").iloc[0]
    best_gate_ce = summary.sort_values("gate_2023_2024_wape_critical_ceara").iloc[0]
    best_gate_chapada = summary.sort_values("gate_2023_2024_wape_critical_chapada_cariri").iloc[0]

    preds.to_csv(OUT_DIR / "predictions.csv", index=False)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    would_pass = bool(selected_ce["passes_g3_ceara_wape"] or selected_chapada["passes_g3_chapada_cariri_wape"])
    decision = "EXPLORATORY_G3_SIGNAL" if would_pass else "EXPLORATORY_G3_FAIL"

    report = {
        "experiment_id": "EXP-2026-07-11-22",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Lagged local NDVI stress/fuel signals may indicate whether official MOD13Q1 QA ingestion is worth prioritizing.",
        "production_validity": "INVALID_FOR_PROMOTION_LOCAL_CSV_LACKS_QA_AVAILABLE_AT",
        "protocol": "walk-forward 2015-2024; selection on 2015-2022 critical months by scope; frozen gate on 2023-2024 critical months; 2025+ untouched; all NDVI features shifted",
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "local_ndvi_sha256": sha256_file(LOCAL_NDVI),
        "contract_smoke_sha256": sha256_file(CONTRACT_SMOKE),
        "exp10_predictions_sha256": sha256_file(EXP10_PREDICTIONS),
        "g3_limits": {"ceara": G3_CE_LIMIT, "chapada_cariri": G3_CHAPADA_LIMIT},
        "candidate_grid": {"score_modes": SCORE_MODES, "windows": WINDOWS, "lambdas": LAMBDAS},
        "series_gaps_reindexed": [{"geocodigo": int(g), "missing_months": int(n)} for g, n in gaps],
        "selected_ce_by_2015_2022": selected_ce.to_dict(),
        "selected_chapada_by_2015_2022": selected_chapada.to_dict(),
        "best_gate_ceara_audit_only": best_gate_ce.to_dict(),
        "best_gate_chapada_audit_only": best_gate_chapada.to_dict(),
        "decision": decision,
        "artifacts": ["summary.csv", "predictions.csv"],
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    cols = [
        "model",
        "family",
        "selection_2015_2022_wape_critical_ceara",
        "selection_2015_2022_wape_critical_chapada_cariri",
        "gate_2023_2024_wape_critical_ceara",
        "gate_2023_2024_wape_critical_chapada_cariri",
        "gate_2023_2024_recall10_ceara",
        "passes_g3_ceara_wape",
        "passes_g3_chapada_cariri_wape",
    ]
    print("=== EXP-22 local NDVI exploratory triage ===")
    print(summary[cols].head(25).to_string(index=False))
    print(f"SELECTED_CE: {selected_ce['model']}")
    print(f"SELECTED_CHAPADA: {selected_chapada['model']}")
    print(f"BEST_GATE_CE_AUDIT_ONLY: {best_gate_ce['model']} {best_gate_ce['gate_2023_2024_wape_critical_ceara']:.4f}")
    print(f"BEST_GATE_CHAPADA_AUDIT_ONLY: {best_gate_chapada['model']} {best_gate_chapada['gate_2023_2024_wape_critical_chapada_cariri']:.4f}")
    print(f"DECISION: {decision}")


if __name__ == "__main__":
    main()
