"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp13_event_point_features_g3.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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

from src.experiments.backtest_real_baselines import (  # noqa: E402
    MIN_TRAIN_MONTHS,
    build_features,
    load_merged_target,
)
from src.utils.metrics import mae, wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp13_event_point_features_g3"
EVENT_FEATURES = PROJECT_ROOT / "data" / "snapshots" / "inpe_event_points_v1" / "monthly_event_features.csv"
EVENT_MANIFEST = PROJECT_ROOT / "data" / "snapshots" / "inpe_event_points_v1" / "manifest.json"
EXP10_PREDICTIONS = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
TEST_MONTHS = [pd.Period(f"{y}-{m:02d}", freq="M") for y in range(2015, 2025) for m in range(1, 13)]
CRITICAL_MONTHS = {10, 11}
DRY_MONTHS = {8, 9, 10, 11, 12}
G3_CE_LIMIT = 0.20
G3_CHAPADA_LIMIT = 0.25
RIDGE_GRID = [0.5, 2.0, 10.0, 50.0]
BLEND_WEIGHTS = [0.25, 0.50, 0.75]

RAW_EVENT_COLS = [
    "event_fire_count",
    "event_day_count",
    "event_frp_sum",
    "event_frp_mean",
    "event_frp_max",
    "event_frp_p90",
    "event_fire_risk_mean",
    "event_fire_risk_max",
    "event_days_no_rain_mean",
    "event_days_no_rain_max",
    "event_precip_mm_mean",
    "event_lat_std",
    "event_lon_std",
]

MODEL_EVENT_FEATURES = [
    "fire_count_lag1",
    "fire_count_lag2",
    "fire_count_lag3",
    "fire_count_lag6",
    "fire_count_lag12",
    "fire_roll3",
    "fire_roll6",
    "mes_sin",
    "mes_cos",
    "event_fire_count_lag1",
    "event_fire_count_lag3",
    "event_fire_count_lag12",
    "event_fire_count_roll3",
    "event_fire_count_roll12",
    "event_day_count_lag1",
    "event_frp_sum_lag1",
    "event_frp_sum_lag3",
    "event_frp_sum_lag12",
    "event_frp_sum_roll3",
    "event_frp_sum_roll12",
    "event_frp_p90_lag1",
    "event_fire_risk_mean_lag1",
    "event_fire_risk_max_lag1",
    "event_days_no_rain_mean_lag1",
    "event_days_no_rain_max_lag1",
    "event_lat_std_lag1",
    "event_lon_std_lag1",
]

LOG_FEATURE_PREFIXES = (
    "fire_count",
    "fire_roll",
    "event_fire_count",
    "event_day_count",
    "event_frp",
    "event_days_no_rain",
    "event_precip",
    "event_lat_std",
    "event_lon_std",
)


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def metric_block(p: pd.DataFrame) -> dict[str, object]:
    """Executa a etapa `metric block` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    critical = p[p["mes"].isin(CRITICAL_MONTHS)]
    dry = p[p["mes"].isin(DRY_MONTHS)]
    selection = critical[critical["ano"] <= 2022]
    gate = critical[critical["ano"].between(2023, 2024)]
    gate_all = p[p["ano"].between(2023, 2024)]
    gate_wape = wape(gate["fire_count"].to_numpy(), gate["y_pred"].to_numpy())
    return {
        "extended_wape_all": wape(p["fire_count"].to_numpy(), p["y_pred"].to_numpy()),
        "extended_wape_critical": wape(critical["fire_count"].to_numpy(), critical["y_pred"].to_numpy()),
        "extended_wape_dry": wape(dry["fire_count"].to_numpy(), dry["y_pred"].to_numpy()),
        "selection_2015_2022_wape_critical": wape(selection["fire_count"].to_numpy(), selection["y_pred"].to_numpy()),
        "gate_2023_2024_wape_critical": gate_wape,
        "gate_2023_2024_wape_all": wape(gate_all["fire_count"].to_numpy(), gate_all["y_pred"].to_numpy()),
        "gate_critical_n": int(len(gate)),
        "gate_critical_y_total": float(gate["fire_count"].sum()),
        "passes_g3_ceara": bool(gate_wape <= G3_CE_LIMIT),
        "passes_g3_chapada_cariri": bool(gate_wape <= G3_CHAPADA_LIMIT),
    }


def normalize_predictions(df: pd.DataFrame, model: str, family: str, note: str) -> pd.DataFrame:
    """Executa a etapa `normalize predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = df[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]].copy()
    out["cut"] = out["ano"].astype(str) + "-" + out["mes"].astype(str).str.zfill(2)
    out["model"] = model
    out["family"] = family
    out["note"] = note
    out["y_pred"] = np.maximum(out["y_pred"].astype(float), 0.0)
    return out


def add_event_features(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `add event features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    events = pd.read_csv(EVENT_FEATURES)
    event_cols = ["geocodigo", "ano", "mes", "source_name", *RAW_EVENT_COLS]
    events = events[event_cols].copy()
    merged = df.merge(
        events,
        left_on=["geocodigo", "ano", "mes", "target_source"],
        right_on=["geocodigo", "ano", "mes", "source_name"],
        how="left",
    )
    merged = merged.drop(columns=["source_name"], errors="ignore")
    for col in RAW_EVENT_COLS:
        merged[col] = merged[col].fillna(0.0)

    merged = merged.sort_values(["geocodigo", "period"]).reset_index(drop=True)
    by_geo = merged.groupby("geocodigo", sort=False)
    for col in RAW_EVENT_COLS:
        for lag in (1, 3, 12):
            merged[f"{col}_lag{lag}"] = by_geo[col].shift(lag)
        merged[f"{col}_roll3"] = by_geo[col].transform(lambda x: x.shift(1).rolling(3, min_periods=1).mean())
        merged[f"{col}_roll12"] = by_geo[col].transform(lambda x: x.shift(1).rolling(12, min_periods=1).mean())
    return merged


def transform_matrix(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Executa a etapa `transform matrix` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    x_train = train[cols].fillna(0.0).to_numpy(dtype=float)
    x_test = test[cols].fillna(0.0).to_numpy(dtype=float)
    for idx, col in enumerate(cols):
        if col.startswith(LOG_FEATURE_PREFIXES):
            x_train[:, idx] = np.log1p(np.maximum(x_train[:, idx], 0.0))
            x_test[:, idx] = np.log1p(np.maximum(x_test[:, idx], 0.0))
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std == 0] = 1.0
    x_train = (x_train - mean) / std
    x_test = (x_test - mean) / std
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    x_test = np.column_stack([np.ones(len(x_test)), x_test])
    return x_train, x_test


def ridge_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str], ridge: float) -> np.ndarray:
    """Executa a etapa `ridge predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    x_train, x_test = transform_matrix(train, test, cols)
    y = np.log1p(train["fire_count"].to_numpy(dtype=float))
    penalty = np.eye(x_train.shape[1]) * ridge
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(x_train.T @ x_train + penalty, x_train.T @ y)
    return np.maximum(np.expm1(x_test @ beta), 0.0)


def event_pressure_prediction(ctx_train: pd.DataFrame, ctx_test: pd.DataFrame, base_pred: np.ndarray) -> np.ndarray:
    # A deterministic, non-fit allocation pressure from strictly lagged event fields.
    """Executa a etapa `event pressure prediction` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    frp = np.log1p(ctx_test["event_frp_sum_roll12"].fillna(0.0).to_numpy(dtype=float))
    cnt = np.log1p(ctx_test["event_fire_count_roll12"].fillna(0.0).to_numpy(dtype=float))
    risk = ctx_test["event_fire_risk_max_lag1"].fillna(0.0).to_numpy(dtype=float)
    pressure = 0.50 * frp + 0.35 * cnt + 0.15 * risk
    if np.nanstd(pressure) == 0:
        return base_pred
    pressure = (pressure - np.nanmean(pressure)) / (np.nanstd(pressure) + 1e-9)
    multiplier = np.clip(1.0 + 0.20 * pressure, 0.50, 1.80)
    raw = np.maximum(base_pred * multiplier, 0.0)
    total_base = float(np.sum(base_pred))
    total_raw = float(np.sum(raw))
    if total_base > 0 and total_raw > 0:
        raw = raw * (total_base / total_raw)
    return raw


def build_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Constroi a etapa `build predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows_by_model: list[pd.DataFrame] = []
    skipped: list[str] = []
    exp10 = pd.read_csv(EXP10_PREDICTIONS)
    exp10 = exp10[exp10["model"] == "climatology_regional_intensity12"]

    ridge_pred_blocks: dict[float, list[pd.DataFrame]] = {ridge: [] for ridge in RIDGE_GRID}
    pressure_blocks: list[pd.DataFrame] = []

    for cut in TEST_MONTHS:
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
        test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        train = train[train["fire_count_lag12"].notna()].copy()
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
        if len(train) == 0 or len(test) == 0:
            skipped.append(str(cut))
            continue

        exp10_cut = exp10[(exp10["ano"] == cut.year) & (exp10["mes"] == cut.month)][["geocodigo", "y_pred"]]
        test_with_base = test.merge(exp10_cut, on="geocodigo", how="left", suffixes=("", "_exp10"))
        if test_with_base["y_pred"].isna().any():
            missing = sorted(test_with_base.loc[test_with_base["y_pred"].isna(), "geocodigo"].astype(int).unique().tolist())
            raise RuntimeError(f"EXP-10 prediction coverage gap for {cut}: {missing}")
        base_pred = test_with_base["y_pred"].to_numpy(dtype=float)

        pressure = test.copy()
        pressure["y_pred"] = event_pressure_prediction(train, test, base_pred)
        pressure_blocks.append(pressure)

        for ridge in RIDGE_GRID:
            pred = test.copy()
            pred["y_pred"] = ridge_predict(train, test, MODEL_EVENT_FEATURES, ridge)
            ridge_pred_blocks[ridge].append(pred)

    for ridge, blocks in ridge_pred_blocks.items():
        rows_by_model.append(
            normalize_predictions(
                pd.concat(blocks, ignore_index=True),
                model=f"event_ridge_r{ridge:g}",
                family="event_lag_ridge",
                note="Ridge log-linear model using only lagged INPE point-event features and target lags.",
            )
        )
    rows_by_model.append(
        normalize_predictions(
            pd.concat(pressure_blocks, ignore_index=True),
            model="event_pressure_allocator",
            family="event_pressure",
            note="EXP-10 total-preserving allocation adjusted by lagged event FRP/count/risk pressure.",
        )
    )

    champion = pd.read_csv(EXP10_PREDICTIONS)
    champion = champion[champion["model"] == "climatology_regional_intensity12"].copy()
    champion = normalize_predictions(
        champion.rename(columns={"y_pred": "y_pred"}),
        model="climatology_regional_intensity12",
        family="champion",
        note="Current EXP-10 champion.",
    )
    rows_by_model.append(champion)

    return pd.concat(rows_by_model, ignore_index=True)


def select_and_blend(all_preds: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa a etapa `select and blend` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    summary = summarize(all_preds)
    ridge_candidates = summary[summary["family"].isin(["event_lag_ridge", "event_pressure"])]
    selected_model = ridge_candidates.sort_values("selection_2015_2022_wape_critical").iloc[0]["model"]

    champion = all_preds[all_preds["model"] == "climatology_regional_intensity12"]
    selected = all_preds[all_preds["model"] == selected_model]
    key_cols = ["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]
    base = champion[key_cols + ["y_pred"]].rename(columns={"y_pred": "champion_pred"})
    cand = selected[key_cols + ["y_pred"]].rename(columns={"y_pred": "candidate_pred"})
    joined = base.merge(cand, on=key_cols, how="inner")

    blends = []
    for w in BLEND_WEIGHTS:
        out = joined[key_cols].copy()
        out["y_pred"] = w * joined["candidate_pred"] + (1.0 - w) * joined["champion_pred"]
        blends.append(
            normalize_predictions(
                out,
                model=f"blend_{selected_model}_w{w:g}",
                family="event_champion_blend",
                note=f"Blend selected on 2015-2022: {selected_model} weight {w:g}, EXP-10 weight {1.0-w:g}.",
            )
        )
    blend_preds = pd.concat(blends, ignore_index=True)
    combined = pd.concat([all_preds, blend_preds], ignore_index=True)
    return combined, summarize(combined)


def summarize(preds: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `summarize` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp13_event_point_features_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for (model, family), group in preds.groupby(["model", "family"], sort=False):
        row = {"model": model, "family": family, "note": group["note"].iloc[0]}
        row.update(metric_block(group))
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["selection_2015_2022_wape_critical", "gate_2023_2024_wape_critical"]
    ).reset_index(drop=True)


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp13_event_point_features_g3.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    df = build_features(df)
    df = add_event_features(df)

    raw_preds = build_predictions(df)
    all_preds, summary = select_and_blend(raw_preds)
    best_by_selection = summary.iloc[0]
    best_valid_gate = summary.sort_values("gate_2023_2024_wape_critical").iloc[0]

    all_preds.to_csv(OUT_DIR / "predictions.csv", index=False)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    report = {
        "experiment_id": "EXP-2026-07-09-13",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Lagged INPE point-event fields improve municipal allocation without current-month leakage.",
        "protocol": "walk-forward 2015-2024; selection on 2015-2022 critical months; frozen gate on 2023-2024 critical months; 2025+ untouched",
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "event_snapshot_manifest_sha256": sha256_file(EVENT_MANIFEST),
        "event_features_sha256": sha256_file(EVENT_FEATURES),
        "exp10_predictions_sha256": sha256_file(EXP10_PREDICTIONS),
        "g3_limits": {"ceara": G3_CE_LIMIT, "chapada_cariri": G3_CHAPADA_LIMIT},
        "ridge_grid": RIDGE_GRID,
        "blend_weights": BLEND_WEIGHTS,
        "feature_columns": MODEL_EVENT_FEATURES,
        "series_gaps_reindexed": [{"geocodigo": int(g), "missing_months": int(n)} for g, n in gaps],
        "selected_by_2015_2022": best_by_selection.to_dict(),
        "best_gate_2023_2024": best_valid_gate.to_dict(),
        "decision": "G3_PASS" if bool(best_by_selection["passes_g3_ceara"] or best_by_selection["passes_g3_chapada_cariri"]) else "G3_FAIL",
        "artifacts": ["summary.csv", "predictions.csv"],
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=== EXP-13 lagged INPE point-event features ===")
    print(summary[["model", "family", "selection_2015_2022_wape_critical", "gate_2023_2024_wape_critical", "passes_g3_ceara", "passes_g3_chapada_cariri"]].to_string(index=False))
    print(f"SELECTED_BY_SELECTION: {best_by_selection['model']}")
    print(f"DECISION: {report['decision']}")


if __name__ == "__main__":
    main()

