"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp24_inmet_observed_dryness_g3.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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
from src.utils.metrics import recall_at_k, wape, zero_indevido  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp24_inmet_observed_dryness_g3"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
INMET_MANIFEST = PROJECT_ROOT / "data" / "snapshots" / "inmet_automatic_station_observed_v1" / "manifest.json"
INMET_FEATURES = PROJECT_ROOT / "data" / "snapshots" / "inmet_automatic_station_observed_v1" / "municipal_monthly_station_features.csv"
EXP10_PREDICTIONS = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
CHAPADA_WEIGHTS = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
TEST_MONTHS = [pd.Period(f"{y}-{m:02d}", freq="M") for y in range(2015, 2025) for m in range(1, 13)]
CRITICAL_MONTHS = {10, 11}
DRY_MONTHS = {8, 9, 10, 11, 12}
G3_CE_LIMIT = 0.20
G3_CHAPADA_LIMIT = 0.25
BLEND_LAMBDAS = [0.10, 0.25, 0.50]
TILT_BETAS = [0.15, 0.30, 0.60]
BLEND_MODES = ["dry3_inv", "dry6_inv", "vpd1", "vpd3", "deficit3", "dry_rank_mix"]
TILT_MODES = ["vpd3", "dry3_inv", "deficit3"]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def normalized_share(values: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Executa a etapa `normalized share` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
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
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return set(pd.read_csv(CHAPADA_WEIGHTS)["geocodigo"].astype(int).unique().tolist())


def saturation_vapor_pressure_kpa(temp_c: pd.Series) -> pd.Series:
    """Executa a etapa `saturation vapor pressure kpa` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return 0.6108 * np.exp(17.27 * temp_c / (temp_c + 237.3))


def add_inmet_features(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `add inmet features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    obs = pd.read_csv(INMET_FEATURES, dtype={"geocodigo": str})
    obs["geocodigo"] = obs["geocodigo"].astype(int)
    keep = [
        "geocodigo",
        "ano",
        "mes",
        "inmet_precip_total_mm_idw",
        "inmet_temp_mean_c_idw",
        "inmet_rh_mean_pct_idw",
        "inmet_wind_mean_ms_idw",
        "inmet_station_count_any",
        "inmet_nearest_station_km",
        "inmet_observed_fraction_mean",
    ]
    merged = df.merge(obs[keep], on=["geocodigo", "ano", "mes"], how="left")
    merged = merged.sort_values(["geocodigo", "period"]).reset_index(drop=True)
    grouped = merged.groupby("geocodigo")

    es = saturation_vapor_pressure_kpa(merged["inmet_temp_mean_c_idw"])
    merged["inmet_vpd_kpa"] = es * (1.0 - merged["inmet_rh_mean_pct_idw"] / 100.0)

    merged["inmet_precip_lag1"] = grouped["inmet_precip_total_mm_idw"].shift(1)
    merged["inmet_precip_roll3"] = grouped["inmet_precip_total_mm_idw"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=3).sum()
    )
    merged["inmet_precip_roll6"] = grouped["inmet_precip_total_mm_idw"].transform(
        lambda s: s.shift(1).rolling(6, min_periods=6).sum()
    )
    merged["inmet_vpd_lag1"] = grouped["inmet_vpd_kpa"].shift(1)
    merged["inmet_vpd_roll3"] = grouped["inmet_vpd_kpa"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=3).mean()
    )
    merged["inmet_wind_lag1"] = grouped["inmet_wind_mean_ms_idw"].shift(1)

    # Expanding per-(municipality, calendar-month) climatology of the lagged
    # 3-month rainfall, shifted one year so month t only sees prior years.
    merged["inmet_precip_roll3_clim"] = merged.groupby(["geocodigo", "mes"])["inmet_precip_roll3"].transform(
        lambda s: s.shift(1).expanding(min_periods=2).mean()
    )
    merged["inmet_precip_deficit3"] = (merged["inmet_precip_roll3_clim"] - merged["inmet_precip_roll3"]).clip(lower=0.0)
    return merged


def fill_neutral(values: np.ndarray) -> np.ndarray:
    """Executa a etapa `fill neutral` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if finite.sum() == 0:
        return np.zeros(len(values), dtype=float)
    mean = float(values[finite].mean())
    out = values.copy()
    out[~finite] = mean
    return np.maximum(out, 0.0)


def month_zscore(values: np.ndarray) -> np.ndarray:
    """Executa a etapa `month zscore` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if finite.sum() < 2:
        return np.zeros(len(values), dtype=float)
    mean = float(values[finite].mean())
    std = float(values[finite].std())
    if std < 1e-12:
        return np.zeros(len(values), dtype=float)
    z = (values - mean) / std
    z[~finite] = 0.0
    return np.clip(z, -4.0, 4.0)


def month_rank_pct(values: np.ndarray) -> np.ndarray:
    """Executa a etapa `month rank pct` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    series = pd.Series(np.asarray(values, dtype=float))
    ranks = series.rank(pct=True, na_option="keep")
    return ranks.fillna(0.5).to_numpy(dtype=float)


def score_from_inmet(test: pd.DataFrame, mode: str) -> np.ndarray:
    """Calcula a etapa `score from inmet` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    precip3 = test["inmet_precip_roll3"].to_numpy(dtype=float)
    precip6 = test["inmet_precip_roll6"].to_numpy(dtype=float)
    vpd1 = test["inmet_vpd_lag1"].to_numpy(dtype=float)
    vpd3 = test["inmet_vpd_roll3"].to_numpy(dtype=float)
    deficit3 = test["inmet_precip_deficit3"].to_numpy(dtype=float)
    if mode == "dry3_inv":
        score = 1.0 / (1.0 + precip3)
    elif mode == "dry6_inv":
        score = 1.0 / (1.0 + precip6)
    elif mode == "vpd1":
        score = vpd1
    elif mode == "vpd3":
        score = vpd3
    elif mode == "deficit3":
        score = deficit3
    elif mode == "dry_rank_mix":
        score = 0.5 * month_rank_pct(1.0 / (1.0 + precip3)) + 0.5 * month_rank_pct(vpd3)
    else:
        raise ValueError(mode)
    return fill_neutral(score)


def tilt_signal(test: pd.DataFrame, mode: str) -> np.ndarray:
    """Executa a etapa `tilt signal` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if mode == "vpd3":
        raw = test["inmet_vpd_roll3"].to_numpy(dtype=float)
    elif mode == "dry3_inv":
        raw = 1.0 / (1.0 + test["inmet_precip_roll3"].to_numpy(dtype=float))
    elif mode == "deficit3":
        raw = test["inmet_precip_deficit3"].to_numpy(dtype=float)
    else:
        raise ValueError(mode)
    return month_zscore(raw)


def normalize_predictions(df: pd.DataFrame, model: str, family: str, note: str) -> pd.DataFrame:
    """Executa a etapa `normalize predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = df[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]].copy()
    out["cut"] = out["ano"].astype(str) + "-" + out["mes"].astype(str).str.zfill(2)
    out["model"] = model
    out["family"] = family
    out["note"] = note
    out["y_pred"] = np.maximum(out["y_pred"].astype(float), 0.0)
    return out


def build_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Constroi a etapa `build predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    exp10 = pd.read_csv(EXP10_PREDICTIONS)
    exp10 = exp10[exp10["model"] == "climatology_regional_intensity12"].copy()
    rows_by_model: dict[str, list[pd.DataFrame]] = {}
    notes: dict[str, tuple[str, str]] = {}
    champion_blocks: list[pd.DataFrame] = []

    blend_configs = [("blend", mode, lam) for mode in BLEND_MODES for lam in BLEND_LAMBDAS]
    tilt_configs = [("tilt", mode, beta) for mode in TILT_MODES for beta in TILT_BETAS]
    for kind, mode, param in blend_configs + tilt_configs:
        name = f"inmet_{kind}_{mode}_p{str(param).replace('.', 'p')}"
        rows_by_model[name] = []
        notes[name] = (
            f"inmet_dryness_{kind}",
            f"EXP-10 total-preserving allocation adjusted by lagged INMET observed dryness; kind={kind}, mode={mode}, param={param}.",
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

        for kind, mode, param in blend_configs:
            name = f"inmet_{kind}_{mode}_p{str(param).replace('.', 'p')}"
            score = score_from_inmet(test, mode)
            score_share = normalized_share(score, base_pred)
            pred = total * ((1.0 - param) * base_share + param * score_share)
            out = test.copy()
            out["y_pred"] = pred
            rows_by_model[name].append(out)

        for kind, mode, param in tilt_configs:
            name = f"inmet_{kind}_{mode}_p{str(param).replace('.', 'p')}"
            z = tilt_signal(test, mode)
            weights = base_share * np.exp(param * z)
            pred = total * normalized_share(weights, base_pred)
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
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if frame.empty or float(frame["fire_count"].sum()) == 0.0:
        return float("nan")
    return float(wape(frame["fire_count"].to_numpy(dtype=float), frame["y_pred"].to_numpy(dtype=float)))


def recall10_by_month(frame: pd.DataFrame) -> float:
    """Executa a etapa `recall10 by month` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    work = frame.rename(columns={"fire_count": "y_true", "geocodigo": "municipio_id"}).copy()
    return float(recall_at_k(work, k=10, group_cols=["ano", "mes"]))


def metric_block(p: pd.DataFrame, chapada_geocodes: set[int], hist_positive: pd.DataFrame) -> dict[str, object]:
    """Executa a etapa `metric block` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
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
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    work = target.sort_values(["geocodigo", "period"]).copy()
    work["hist_positive"] = (
        work.groupby("geocodigo")["fire_count"]
        .transform(lambda s: s.fillna(0.0).shift(1).fillna(0.0).cumsum())
        .astype(float)
    )
    return work[["geocodigo", "ano", "mes", "hist_positive"]]


def summarize(preds: pd.DataFrame, chapada_geocodes: set[int], hist_positive: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `summarize` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp24_inmet_observed_dryness_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
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
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp24_inmet_observed_dryness_g3.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    hist_positive = build_hist_positive(df)
    df = build_features(df)
    df = add_inmet_features(df)
    preds = build_predictions(df)
    chapada = load_chapada_geocodes()
    summary = summarize(preds, chapada, hist_positive)

    selected_ce = summary.sort_values("selection_2015_2022_wape_critical_ceara", na_position="last").iloc[0]
    selected_chapada = summary.sort_values("selection_2015_2022_wape_critical_chapada_cariri", na_position="last").iloc[0]
    best_gate_ce = summary.sort_values("gate_2023_2024_wape_critical_ceara").iloc[0]
    best_gate_chapada = summary.sort_values("gate_2023_2024_wape_critical_chapada_cariri").iloc[0]

    preds.to_csv(OUT_DIR / "predictions.csv", index=False)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    decision = "G3_PASS" if bool(selected_ce["passes_g3_ceara_wape"] or selected_chapada["passes_g3_chapada_cariri_wape"]) else "G3_FAIL"

    report = {
        "experiment_id": "EXP-2026-07-11-24",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Lagged observed INMET station dryness (precip deficit, VPD) improves EXP-10 municipal allocation because it is monthly-dynamic and spatially heterogeneous, unlike the failed static/annual allocators.",
        "protocol": "walk-forward 2015-2024; selection on 2015-2022 critical months by scope; frozen gate on 2023-2024 critical months; 2025+ untouched; all INMET features lagged >= 1 month",
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "inmet_manifest_sha256": sha256_file(INMET_MANIFEST),
        "inmet_features_sha256": sha256_file(INMET_FEATURES),
        "exp10_predictions_sha256": sha256_file(EXP10_PREDICTIONS),
        "g3_limits": {"ceara": G3_CE_LIMIT, "chapada_cariri": G3_CHAPADA_LIMIT},
        "candidate_grid": {
            "blend_modes": BLEND_MODES,
            "blend_lambdas": BLEND_LAMBDAS,
            "tilt_modes": TILT_MODES,
            "tilt_betas": TILT_BETAS,
        },
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
    print("=== EXP-24 INMET observed dryness allocation ===")
    print(summary[cols].head(30).to_string(index=False))
    print(f"SELECTED_CE: {selected_ce['model']}")
    print(f"SELECTED_CHAPADA: {selected_chapada['model']}")
    print(f"BEST_GATE_CE_AUDIT_ONLY: {best_gate_ce['model']} {best_gate_ce['gate_2023_2024_wape_critical_ceara']:.4f}")
    print(f"BEST_GATE_CHAPADA_AUDIT_ONLY: {best_gate_chapada['model']} {best_gate_chapada['gate_2023_2024_wape_critical_chapada_cariri']:.4f}")
    print(f"DECISION: {decision}")


if __name__ == "__main__":
    main()
