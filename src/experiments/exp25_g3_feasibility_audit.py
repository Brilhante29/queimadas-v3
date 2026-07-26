"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp25_g3_feasibility_audit.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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

OUT_DIR = PROJECT_ROOT / "outputs" / "exp25_g3_feasibility_audit"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
EXP10_PREDICTIONS = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
CHAPADA_WEIGHTS = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
FIRMS_MULTI = PROJECT_ROOT / "data" / "snapshots" / "firms_multi_sensor_ce_v1" / "monthly_firms_features.csv"

GATE_YEARS = [2023, 2024]
CRITICAL_MONTHS = [10, 11]
G3_LIMITS = {"ceara": 0.20, "chapada_cariri": 0.25}
MC_DRAWS = 4000
SEED = 20260711


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def build_gate_cells() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Constroi a etapa `build gate cells` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df, _ = load_merged_target()
    df = build_features(df)
    exp10 = pd.read_csv(EXP10_PREDICTIONS)
    exp10 = exp10[exp10["model"] == "climatology_regional_intensity12"][["geocodigo", "ano", "mes", "y_pred"]]

    cells = []
    for year in GATE_YEARS:
        for month in CRITICAL_MONTHS:
            cut = pd.Period(f"{year}-{month:02d}", freq="M")
            train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
            test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
            hist = train.groupby("geocodigo")["fire_count"].count()
            eligible = hist[hist >= MIN_TRAIN_MONTHS].index
            test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()]
            cells.append(test)
    gate = pd.concat(cells, ignore_index=True)
    gate = gate.merge(exp10, on=["geocodigo", "ano", "mes"], how="left")
    if gate["y_pred"].isna().any():
        raise RuntimeError("Champion prediction coverage gap on gate cells")
    return df, gate[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]]


def scope_mask(gate: pd.DataFrame, scope: str, chapada: set[int]) -> pd.Series:
    """Executa a etapa `scope mask` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if scope == "ceara":
        return gate["uf"] == "CE"
    if scope == "chapada_cariri":
        return gate["geocodigo"].astype(int).isin(chapada)
    raise ValueError(scope)


def mc_floor(mu: np.ndarray, rng: np.random.Generator, dist: str, nb_r: float | None = None) -> dict[str, float]:
    """Executa a etapa `mc floor` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    mu = np.asarray(mu, dtype=float)
    wapes = np.empty(MC_DRAWS)
    for j in range(MC_DRAWS):
        if dist == "poisson":
            draws = rng.poisson(mu)
        elif dist == "nb":
            if nb_r is None or not np.isfinite(nb_r) or nb_r <= 0:
                raise RuntimeError("Invalid NB dispersion")
            p = nb_r / (nb_r + np.maximum(mu, 1e-12))
            draws = np.where(mu > 0, rng.negative_binomial(nb_r, p), 0)
        else:
            raise ValueError(dist)
        denom = draws.sum()
        wapes[j] = np.abs(draws - mu).sum() / denom if denom > 0 else np.nan
    valid = wapes[np.isfinite(wapes)]
    return {
        "mean": float(valid.mean()),
        "p2p5": float(np.percentile(valid, 2.5)),
        "p97p5": float(np.percentile(valid, 97.5)),
        "cells": int(len(mu)),
        "total_count": float(mu.sum()),
    }


def pooled_nb_dispersion(df: pd.DataFrame, geocodes: pd.Series) -> float:
    """Executa a etapa `pooled nb dispersion` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    hist = df[
        df["ano"].between(2015, 2022)
        & df["mes"].isin(CRITICAL_MONTHS)
        & df["fire_count"].notna()
        & df["geocodigo"].isin(geocodes)
    ]
    stats = hist.groupby(["geocodigo", "mes"])["fire_count"].agg(["mean", "var", "count"])
    stats = stats[(stats["count"] >= 4) & (stats["mean"] > 0)]
    excess = (stats["var"] - stats["mean"]).clip(lower=0.0)
    denom = float((stats["mean"] ** 2).sum())
    if denom <= 0:
        raise RuntimeError("Cannot estimate NB dispersion: no positive means")
    alpha = float(excess.sum() / denom)
    if alpha <= 1e-9:
        return float("inf")
    return 1.0 / alpha


def champion_wape(frame: pd.DataFrame) -> float:
    """Executa a etapa `champion wape` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    denom = float(frame["fire_count"].sum())
    if denom <= 0:
        return float("nan")
    return float(np.abs(frame["fire_count"] - frame["y_pred"]).sum() / denom)


def aggregate(frame: pd.DataFrame, level: str) -> pd.DataFrame:
    """Executa a etapa `aggregate` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if level == "municipal_month":
        return frame.copy()
    if level == "municipal_season":
        keys = ["geocodigo", "ano"]
    elif level == "scope_month":
        keys = ["ano", "mes"]
    elif level == "scope_season":
        keys = ["ano"]
    else:
        raise ValueError(level)
    return frame.groupby(keys, as_index=False)[["fire_count", "y_pred"]].sum()


def firms_measurement_gap(gate: pd.DataFrame, chapada: set[int]) -> dict[str, dict[str, float]]:
    """Executa a etapa `firms measurement gap` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp25_g3_feasibility_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    firms = pd.read_csv(FIRMS_MULTI)
    firms = firms[["geocodigo", "ano", "mes", "firms_fire_count"]]
    merged = gate.merge(firms, on=["geocodigo", "ano", "mes"], how="left")
    merged["firms_fire_count"] = merged["firms_fire_count"].fillna(0.0)
    out: dict[str, dict[str, float]] = {}
    for scope in G3_LIMITS:
        sl = merged[scope_mask(merged, scope, chapada)]
        inpe = sl["fire_count"].to_numpy(dtype=float)
        raw = sl["firms_fire_count"].to_numpy(dtype=float)
        scale = inpe.sum() / raw.sum() if raw.sum() > 0 else float("nan")
        rescaled = raw * scale
        out[scope] = {
            "wape_raw_firms_vs_inpe": float(np.abs(inpe - raw).sum() / inpe.sum()),
            "wape_total_rescaled_firms_vs_inpe": float(np.abs(inpe - rescaled).sum() / inpe.sum()),
            "rescale_factor": float(scale),
            "cells": int(len(sl)),
        }
    return out


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp25_g3_feasibility_audit.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    df, gate = build_gate_cells()
    chapada = set(pd.read_csv(CHAPADA_WEIGHTS)["geocodigo"].astype(int).unique().tolist())

    levels = ["municipal_month", "municipal_season", "scope_month", "scope_season"]
    results: dict[str, dict] = {}
    for scope, limit in G3_LIMITS.items():
        sl = gate[scope_mask(gate, scope, chapada)]
        nb_r = pooled_nb_dispersion(df, sl["geocodigo"].drop_duplicates())
        scope_res: dict[str, object] = {
            "g3_limit": limit,
            "nb_pooled_dispersion_r": nb_r if np.isfinite(nb_r) else None,
            "levels": {},
        }
        for level in levels:
            agg = aggregate(sl, level)
            mu = agg["fire_count"].to_numpy(dtype=float)
            poisson = mc_floor(mu, rng, "poisson")
            nb = mc_floor(mu, rng, "nb", nb_r=nb_r) if np.isfinite(nb_r) else None
            scope_res["levels"][level] = {
                "poisson_floor": poisson,
                "nb_floor": nb,
                "champion_wape": champion_wape(agg),
                "poisson_floor_exceeds_limit": bool(poisson["mean"] > limit),
            }
        base = scope_res["levels"]["municipal_month"]
        scope_res["verdict_municipal_month"] = (
            "INFEASIBLE_EVEN_FOR_PERFECT_MEAN_ORACLE"
            if base["poisson_floor"]["p2p5"] > limit
            else ("BORDERLINE_AT_POISSON_FLOOR" if base["poisson_floor"]["mean"] > limit else "NOT_PROVABLY_INFEASIBLE")
        )
        results[scope] = scope_res

    measurement = firms_measurement_gap(gate, chapada)

    report = {
        "experiment_id": "EXP-2026-07-11-25",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "The G3 WAPE limits (0.20 CE / 0.25 Chapada, 2023-2024 critical months, municipal-month) are below the irreducible statistical floor of the target, so no point-forecast model can pass them as written.",
        "rejection_condition": "If the Poisson perfect-mean floor is clearly below the limits (upper CI < limit), the hypothesis is rejected and the grid/cell modeling line remains a viable path to G3 as written.",
        "method": "Perfect-mean oracle Monte Carlo (prediction = realized count as true mean; outcomes ~ Poisson / NB with pooled historical dispersion), plus INPE-vs-FIRMS measurement disagreement and an aggregation feasibility frontier.",
        "seed": SEED,
        "mc_draws": MC_DRAWS,
        "gate_years": GATE_YEARS,
        "critical_months": CRITICAL_MONTHS,
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "exp10_predictions_sha256": sha256_file(EXP10_PREDICTIONS),
        "firms_snapshot_sha256": sha256_file(FIRMS_MULTI),
        "scopes": results,
        "measurement_disagreement_inpe_vs_firms": measurement,
        "caveats": [
            "Poisson floor assumes counts are at least Poisson-dispersed given the true mean; sub-Poisson counts would lower the floor (rare for fire counts).",
            "Perfect-mean oracle uses the realized count as the true mean, the most favorable assumption possible for a forecaster.",
            "NB dispersion is pooled from climatology residuals and includes predictable signal, so the NB floor overstates pure noise; treat as realistic reference.",
            "FIRMS disagreement is contextual: INPE is the defined target, so a model could in principle learn INPE-specific behavior.",
            "This audit does not change any gate, threshold or protocol; a G3 contract revision remains a human product decision.",
        ],
        "artifacts": ["feasibility_report.json", "feasibility_summary.csv"],
    }
    (OUT_DIR / "feasibility_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    rows = []
    for scope, res in results.items():
        for level, lv in res["levels"].items():
            rows.append(
                {
                    "scope": scope,
                    "level": level,
                    "g3_limit": res["g3_limit"],
                    "poisson_floor_mean": lv["poisson_floor"]["mean"],
                    "poisson_floor_p2p5": lv["poisson_floor"]["p2p5"],
                    "poisson_floor_p97p5": lv["poisson_floor"]["p97p5"],
                    "nb_floor_mean": lv["nb_floor"]["mean"] if lv["nb_floor"] else np.nan,
                    "champion_wape": lv["champion_wape"],
                    "cells": lv["poisson_floor"]["cells"],
                    "total_count": lv["poisson_floor"]["total_count"],
                }
            )
    summary = pd.DataFrame(rows)
    summary.to_csv(OUT_DIR / "feasibility_summary.csv", index=False)

    print("=== EXP-25 G3 feasibility audit ===")
    print(summary.to_string(index=False))
    for scope, res in results.items():
        print(f"{scope}: limit={res['g3_limit']} nb_r={res['nb_pooled_dispersion_r']} verdict={res['verdict_municipal_month']}")
    print("measurement:", json.dumps(measurement, indent=2))


if __name__ == "__main__":
    main()
