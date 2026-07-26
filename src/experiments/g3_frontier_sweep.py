"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g3_frontier_sweep.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import (  # noqa: E402
    FEATURE_COLS,
    MIN_TRAIN_MONTHS,
    build_features,
    load_merged_target,
)
from src.models.baselines import (  # noqa: E402
    ClimatologyMunicipal,
    HistoricalMean,
    NaiveLag12,
)
from src.utils.metrics import brier_score, recall_at_k, wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "g3_frontier_sweep"
EXP10_PRED_PATH = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
SNAPSHOT_PATH = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
TEST_MONTHS = [pd.Period(f"{y}-{m:02d}", freq="M") for y in range(2015, 2025) for m in range(1, 13)]
CRITICAL_MONTHS = {10, 11}
DRY_MONTHS = {8, 9, 10, 11, 12}
G3_CE_LIMIT = 0.20
G3_CHAPADA_LIMIT = 0.25


@dataclass
class CutContext:
    """Representa `CutContext` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/experiments/g3_frontier_sweep.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    cut: pd.Period
    train: pd.DataFrame
    test: pd.DataFrame
    eligible: pd.Index
    base_pred: np.ndarray
    baseline_model: ClimatologyMunicipal


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def normalize_preds(preds: pd.DataFrame, model: str, family: str, note: str = "") -> pd.DataFrame:
    """Executa a etapa `normalize preds` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    cols = ["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]
    out = preds[cols].copy()
    out["cut"] = out["ano"].astype(str) + "-" + out["mes"].astype(str).str.zfill(2)
    out["model"] = model
    out["family"] = family
    out["note"] = note
    out["y_pred"] = np.maximum(out["y_pred"].astype(float), 0.0)
    return out


def metric_block(p: pd.DataFrame) -> dict:
    """Executa a etapa `metric block` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    critical = p[p["mes"].isin(CRITICAL_MONTHS)]
    dry = p[p["mes"].isin(DRY_MONTHS)]
    sel = critical[critical["ano"] <= 2022]
    gate = critical[critical["ano"].between(2023, 2024)]
    gate_all = p[p["ano"].between(2023, 2024)]
    return {
        "extended_wape_all": wape(p["fire_count"].values, p["y_pred"].values),
        "extended_wape_critical": wape(critical["fire_count"].values, critical["y_pred"].values),
        "extended_wape_dry": wape(dry["fire_count"].values, dry["y_pred"].values),
        "selection_2015_2022_wape_critical": wape(sel["fire_count"].values, sel["y_pred"].values),
        "gate_2023_2024_wape_critical": wape(gate["fire_count"].values, gate["y_pred"].values),
        "gate_2023_2024_wape_all": wape(gate_all["fire_count"].values, gate_all["y_pred"].values),
        "critical_n": int(len(critical)),
        "gate_critical_n": int(len(gate)),
        "gate_critical_y_total": float(gate["fire_count"].sum()),
        "passes_g3_ceara": bool(wape(gate["fire_count"].values, gate["y_pred"].values) <= G3_CE_LIMIT),
        "passes_g3_chapada_cariri": bool(wape(gate["fire_count"].values, gate["y_pred"].values) <= G3_CHAPADA_LIMIT),
    }


def summarize_candidates(preds: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `summarize candidates` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for (model, family), p in preds.groupby(["model", "family"], sort=False):
        row = {"model": model, "family": family}
        note = p["note"].iloc[0] if "note" in p and len(p) else ""
        row["note"] = note
        row.update(metric_block(p))
        rows.append(row)
    return (
        pd.DataFrame(rows)
        .sort_values(["gate_2023_2024_wape_critical", "selection_2015_2022_wape_critical"])
        .reset_index(drop=True)
    )


def build_cut_contexts(df: pd.DataFrame) -> list[CutContext]:
    """Constroi a etapa `build cut contexts` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    contexts: list[CutContext] = []
    for cut in TEST_MONTHS:
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
        test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
        if len(train) == 0 or len(test) == 0:
            continue
        baseline = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
        base_pred = np.asarray(baseline.predict(test), dtype=float)
        contexts.append(CutContext(cut=cut, train=train, test=test, eligible=eligible, base_pred=base_pred, baseline_model=baseline))
    return contexts


def from_contexts(
    contexts: list[CutContext],
    model: str,
    family: str,
    note: str,
    pred_fn: Callable[[CutContext], np.ndarray],
) -> pd.DataFrame:
    """Executa a etapa `from contexts` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    parts = []
    for ctx in contexts:
        p = ctx.test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]].copy()
        p["y_pred"] = np.asarray(pred_fn(ctx), dtype=float)
        parts.append(p)
    return normalize_preds(pd.concat(parts, ignore_index=True), model=model, family=family, note=note)


def load_exp10_predictions() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carrega a etapa `load exp10 predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    raw = pd.read_csv(EXP10_PRED_PATH)
    base = normalize_preds(
        raw[raw["model"] == "climatology_municipal"].copy(),
        "climatology_municipal",
        "historical_rule",
        "EXP-10 baseline municipal-month climatology.",
    )
    champion = normalize_preds(
        raw[raw["model"] == "climatology_regional_intensity12"].copy(),
        "climatology_regional_intensity12",
        "regional_memory",
        "Current internal champion from EXP-10.",
    )
    return base, champion


def oracle_monthly_total(contexts: list[CutContext]) -> pd.DataFrame:
    """Executa a etapa `oracle monthly total` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    def pred(ctx: CutContext) -> np.ndarray:
        """Executa a etapa `pred` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        total_pred = float(ctx.base_pred.sum())
        total_true = float(ctx.test["fire_count"].sum())
        scale = total_true / total_pred if total_pred > 0 else 0.0
        return ctx.base_pred * scale

    return from_contexts(
        contexts,
        model="oracle_monthly_total_climatology_shape",
        family="invalid_oracle_lower_bound",
        note="INVALID: uses actual target-month total. Diagnostic only for spatial allocation lower bound.",
        pred_fn=pred,
    )


def walk_forward_model(df: pd.DataFrame, model_factory: Callable[[], object], family: str, note: str) -> pd.DataFrame:
    """Executa a etapa `walk forward model` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    parts = []
    model_name = None
    for cut in TEST_MONTHS:
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
        test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
        if len(train) == 0 or len(test) == 0:
            continue
        model = model_factory()
        model_name = model.name
        model.fit(train, FEATURE_COLS, "fire_count")
        out = test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]].copy()
        out["y_pred"] = np.asarray(model.predict(test), dtype=float)
        parts.append(out)
    if not parts or model_name is None:
        raise RuntimeError(f"No predictions built for {model_factory}")
    return normalize_preds(pd.concat(parts, ignore_index=True), model_name, family, note)




def ridge_log_lag_regression(df: pd.DataFrame, ridge: float = 2.0) -> pd.DataFrame:
    """Executa a etapa `ridge log lag regression` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    feature_cols = [
        "fire_count_lag1",
        "fire_count_lag2",
        "fire_count_lag3",
        "fire_count_lag6",
        "fire_count_lag12",
        "fire_roll3",
        "fire_roll6",
        "mes_sin",
        "mes_cos",
    ]
    parts = []
    for cut in TEST_MONTHS:
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
        test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
        if len(train) == 0 or len(test) == 0:
            continue

        x_train_raw = train[feature_cols].fillna(0.0).to_numpy(dtype=float)
        x_test_raw = test[feature_cols].fillna(0.0).to_numpy(dtype=float)
        # Lag/count columns are heavy-tailed; log compression keeps the linear
        # solve stable while preserving as-of information only.
        x_train_raw[:, :7] = np.log1p(np.maximum(x_train_raw[:, :7], 0.0))
        x_test_raw[:, :7] = np.log1p(np.maximum(x_test_raw[:, :7], 0.0))
        mean = x_train_raw.mean(axis=0)
        std = x_train_raw.std(axis=0)
        std[std == 0] = 1.0
        x_train = (x_train_raw - mean) / std
        x_test = (x_test_raw - mean) / std
        x_train = np.column_stack([np.ones(len(x_train)), x_train])
        x_test = np.column_stack([np.ones(len(x_test)), x_test])

        y = np.log1p(train["fire_count"].to_numpy(dtype=float))
        penalty = np.eye(x_train.shape[1]) * ridge
        penalty[0, 0] = 0.0
        beta = np.linalg.solve(x_train.T @ x_train + penalty, x_train.T @ y)
        pred = np.expm1(x_test @ beta)

        out = test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]].copy()
        out["y_pred"] = np.maximum(pred, 0.0)
        parts.append(out)
    return normalize_preds(
        pd.concat(parts, ignore_index=True),
        model=f"ridge_log_lag_r{ridge:g}",
        family="regression",
        note="Fast log-linear ridge regression over lag/calendar features; no current-month data.",
    )

def municipal_ratio_candidate(contexts: list[CutContext], k: int, shrink: float, lam: float) -> pd.DataFrame:
    """Executa a etapa `municipal ratio candidate` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    def pred(ctx: CutContext) -> np.ndarray:
        """Executa a etapa `pred` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        prior_periods = pd.period_range(ctx.cut - k, ctx.cut - 1, freq="M")
        prior = ctx.train[
            ctx.train["period"].isin(prior_periods)
            & ctx.train["geocodigo"].isin(ctx.eligible)
            & ctx.train["fire_count"].notna()
        ].copy()
        if len(prior) == 0:
            return ctx.base_pred
        prior["expected"] = np.asarray(ctx.baseline_model.predict(prior), dtype=float)
        global_ratio = (float(prior["fire_count"].sum()) + shrink) / (float(prior["expected"].sum()) + shrink)
        by_geo = prior.groupby("geocodigo").agg(observed=("fire_count", "sum"), expected=("expected", "sum"))
        by_geo["ratio"] = (by_geo["observed"] + shrink) / (by_geo["expected"] + shrink)
        ratios = ctx.test["geocodigo"].map(by_geo["ratio"]).fillna(global_ratio).astype(float).to_numpy()
        blended = lam * ratios + (1.0 - lam) * global_ratio
        return ctx.base_pred * np.clip(blended, 0.25, 4.0)

    return from_contexts(
        contexts,
        model=f"municipal_recent_ratio_k{k}_s{int(shrink)}_l{lam:g}",
        family="municipal_memory",
        note="Municipal trailing observed/expected ratio blended with regional ratio; selected on 2015-2022.",
        pred_fn=pred,
    )


def select_municipal_ratio(contexts: list[CutContext]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa a etapa `select municipal ratio` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    grid = []
    candidates = []
    for k in [12]:
        for shrink in [5.0, 20.0, 100.0]:
            for lam in [0.50, 1.0]:
                preds = municipal_ratio_candidate(contexts, k=k, shrink=shrink, lam=lam)
                metrics = metric_block(preds)
                grid.append(
                    {
                        "model": preds["model"].iloc[0],
                        "k": k,
                        "shrink": shrink,
                        "lambda": lam,
                        **metrics,
                    }
                )
                candidates.append(preds)
    grid_df = pd.DataFrame(grid).sort_values("selection_2015_2022_wape_critical").reset_index(drop=True)
    selected = grid_df.iloc[0]["model"]
    selected_preds = next(p for p in candidates if p["model"].iloc[0] == selected)
    selected_preds["note"] = selected_preds["note"] + f" Selection winner: {selected}."
    return selected_preds, grid_df


def cluster_ratio_candidate(contexts: list[CutContext], k: int, shrink: float) -> pd.DataFrame:
    """Executa a etapa `cluster ratio candidate` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    def pred(ctx: CutContext) -> np.ndarray:
        """Executa a etapa `pred` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        geos = list(ctx.eligible)
        if len(geos) < k:
            return ctx.base_pred
        pivot = (
            ctx.train[ctx.train["geocodigo"].isin(geos)]
            .groupby(["geocodigo", "mes"])["fire_count"]
            .mean()
            .unstack("mes")
            .reindex(index=geos, columns=list(range(1, 13)))
            .fillna(0.0)
        )
        score = pivot[[8, 9, 10, 11, 12]].sum(axis=1) + 0.10 * pivot.sum(axis=1)
        if score.nunique() < k:
            labels = pd.Series(0, index=pivot.index)
        else:
            labels = pd.qcut(score.rank(method="first"), q=k, labels=False, duplicates="drop").astype(int)
        cluster_map = pd.Series(labels.to_numpy(), index=pivot.index)
        prior = ctx.train[
            ctx.train["period"].isin(pd.period_range(ctx.cut - 12, ctx.cut - 1, freq="M"))
            & ctx.train["geocodigo"].isin(ctx.eligible)
            & ctx.train["fire_count"].notna()
        ].copy()
        if len(prior) == 0:
            return ctx.base_pred
        prior["expected"] = np.asarray(ctx.baseline_model.predict(prior), dtype=float)
        prior["cluster"] = prior["geocodigo"].map(cluster_map)
        by_cluster = prior.groupby("cluster").agg(observed=("fire_count", "sum"), expected=("expected", "sum"))
        by_cluster["ratio"] = (by_cluster["observed"] + shrink) / (by_cluster["expected"] + shrink)
        global_ratio = (float(prior["fire_count"].sum()) + shrink) / (float(prior["expected"].sum()) + shrink)
        test_cluster = ctx.test["geocodigo"].map(cluster_map)
        ratios = test_cluster.map(by_cluster["ratio"]).fillna(global_ratio).astype(float).to_numpy()
        return ctx.base_pred * np.clip(ratios, 0.25, 4.0)

    return from_contexts(
        contexts,
        model=f"cluster_ratio_k{k}_s{int(shrink)}",
        family="cluster_memory",
        note="As-of dry-season profile quantile clusters; cluster trailing ratio selected on 2015-2022.",
        pred_fn=pred,
    )


def select_cluster_ratio(contexts: list[CutContext]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa a etapa `select cluster ratio` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    grid = []
    candidates = []
    for k in [3]:
        for shrink in [10.0, 25.0]:
            preds = cluster_ratio_candidate(contexts, k=k, shrink=shrink)
            metrics = metric_block(preds)
            grid.append({"model": preds["model"].iloc[0], "k": k, "shrink": shrink, **metrics})
            candidates.append(preds)
    grid_df = pd.DataFrame(grid).sort_values("selection_2015_2022_wape_critical").reset_index(drop=True)
    selected = grid_df.iloc[0]["model"]
    selected_preds = next(p for p in candidates if p["model"].iloc[0] == selected)
    selected_preds["note"] = selected_preds["note"] + f" Selection winner: {selected}."
    return selected_preds, grid_df


def select_lag_blend(df: pd.DataFrame, exp10: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa a etapa `select lag blend` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    join = df[["geocodigo", "ano", "mes", "fire_count_lag12", "fire_roll3", "fire_roll6"]].copy()
    base = exp10.merge(join, on=["geocodigo", "ano", "mes"], how="left", suffixes=("", "_feature"))
    signal_cols = {
        "lag12": "fire_count_lag12",
        "roll3": "fire_roll3",
        "roll6": "fire_roll6",
    }
    grid = []
    candidates = []
    for signal_name, col in signal_cols.items():
        signal = base[col].fillna(base["y_pred"]).clip(lower=0.0)
        for exp10_weight in [0.4, 0.6, 0.8]:
            preds = base[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]].copy()
            preds["y_pred"] = exp10_weight * base["y_pred"].astype(float) + (1.0 - exp10_weight) * signal.astype(float)
            out = normalize_preds(
                preds,
                model=f"exp10_{exp10_weight:g}_{signal_name}_{1.0 - exp10_weight:g}",
                family="lag_blend",
                note="Blend of EXP-10 point prediction with a strictly lagged signal; selected on 2015-2022.",
            )
            metrics = metric_block(out)
            grid.append({"model": out["model"].iloc[0], "signal": signal_name, "exp10_weight": exp10_weight, **metrics})
            candidates.append(out)
    grid_df = pd.DataFrame(grid).sort_values("selection_2015_2022_wape_critical").reset_index(drop=True)
    selected = grid_df.iloc[0]["model"]
    selected_preds = next(p for p in candidates if p["model"].iloc[0] == selected)
    selected_preds["note"] = selected_preds["note"] + f" Selection winner: {selected}."
    return selected_preds, grid_df


def occurrence_probabilities(contexts: list[CutContext]) -> pd.DataFrame:
    """Executa a etapa `occurrence probabilities` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    parts = []
    for ctx in contexts:
        occ_by_geo_month = (
            ctx.train.assign(occurrence=(ctx.train["fire_count"] > 0).astype(float))
            .groupby(["geocodigo", "mes"])["occurrence"]
            .mean()
        )
        occ_by_month = (
            ctx.train.assign(occurrence=(ctx.train["fire_count"] > 0).astype(float))
            .groupby("mes")["occurrence"]
            .mean()
        )
        p = ctx.test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]].copy()
        p["p_occurrence"] = [
            occ_by_geo_month.get((int(row.geocodigo), int(row.mes)), occ_by_month.get(int(row.mes), 0.0))
            for row in p.itertuples(index=False)
        ]
        parts.append(p)
    return pd.concat(parts, ignore_index=True)


def select_hurdle(exp10: pd.DataFrame, occ: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Executa a etapa `select hurdle` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    base = exp10.merge(occ[["geocodigo", "ano", "mes", "p_occurrence"]], on=["geocodigo", "ano", "mes"], how="left")
    base["p_occurrence"] = base["p_occurrence"].fillna(0.0)
    grid = []
    candidates = []
    for threshold in [0.05, 0.10, 0.20, 0.30, 0.40]:
        for low_scale in [0.0, 0.25, 0.50, 0.75]:
            preds = base[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]].copy()
            preds["y_pred"] = np.where(base["p_occurrence"] < threshold, preds["y_pred"] * low_scale, preds["y_pred"])
            out = normalize_preds(
                preds,
                model=f"hurdle_exp10_thr{threshold:g}_scale{low_scale:g}",
                family="classification_hurdle",
                note="Occurrence classifier gates EXP-10 magnitude; selected on 2015-2022.",
            )
            metrics = metric_block(out)
            grid.append({"model": out["model"].iloc[0], "threshold": threshold, "low_scale": low_scale, **metrics})
            candidates.append(out)
    grid_df = pd.DataFrame(grid).sort_values("selection_2015_2022_wape_critical").reset_index(drop=True)
    selected = grid_df.iloc[0]["model"]
    selected_preds = next(p for p in candidates if p["model"].iloc[0] == selected)
    selected_preds["note"] = selected_preds["note"] + f" Selection winner: {selected}."

    diag = {}
    for label, mask in {
        "selection_2015_2022": occ["ano"] <= 2022,
        "gate_2023_2024": occ["ano"].between(2023, 2024),
    }.items():
        d = occ[mask].copy()
        crit = d[d["mes"].isin(CRITICAL_MONTHS)].copy()
        if len(crit) == 0:
            continue
        crit["y_true"] = (crit["fire_count"] > 0).astype(int)
        crit["y_pred"] = crit["p_occurrence"]
        diag[label] = {
            "critical_brier_occurrence": brier_score(crit["y_true"].to_numpy(), crit["y_pred"].to_numpy()),
            "critical_recall10_occurrence": recall_at_k(
                crit.rename(columns={"geocodigo": "municipio_id"}),
                k=10,
                y_col="fire_count",
                pred_col="p_occurrence",
                id_col="municipio_id",
                group_cols=["ano", "mes"],
            ),
            "critical_n": int(len(crit)),
        }
    return selected_preds, grid_df, diag


def audit_old_v7_artifacts() -> dict:
    """Executa a etapa `audit old v7 artifacts` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    files = {
        "v7_model_comparison": PROJECT_ROOT / "outputs" / "v7_model_comparison.csv",
        "acceptance_gate_results": PROJECT_ROOT / "outputs" / "acceptance_gate_results.csv",
        "verification_backtest_ceara_2024_2025": PROJECT_ROOT / "outputs" / "verification" / "06_backtest_ceara_2024_2025.csv",
        "feature_manifest": PROJECT_ROOT / "outputs" / "04_feature_manifest.json",
    }
    out: dict[str, object] = {
        "decision": "DO_NOT_PROMOTE_TO_CURRENT_PROTOCOL",
        "reason": (
            "Older V6/V7 artifacts are not comparable to the current inpe_local_v2 "
            "walk-forward 2015-2024 protocol and include unresolved source/feature "
            "provenance risks."
        ),
        "files": {},
    }
    for name, path in files.items():
        entry: dict[str, object] = {"exists": path.exists(), "path": str(path.relative_to(PROJECT_ROOT))}
        if path.exists() and path.suffix == ".csv":
            df = pd.read_csv(path)
            entry["rows"] = int(len(df))
            entry["columns"] = list(df.columns)
            if "wape_critical_out_nov" in df.columns:
                entry["min_wape_critical_out_nov"] = float(pd.to_numeric(df["wape_critical_out_nov"], errors="coerce").min())
            if "wape_critical" in df.columns:
                entry["min_wape_critical"] = float(pd.to_numeric(df["wape_critical"], errors="coerce").min())
        if path.exists() and path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entry["top_level_keys"] = list(data.keys()) if isinstance(data, dict) else []
            except Exception as exc:  # pragma: no cover - diagnostics only
                entry["read_error"] = repr(exc)
        out["files"][name] = entry
    return out


def write_frontier_report(summary: pd.DataFrame, classification_diag: dict, old_v7_audit: dict) -> None:
    """Grava a etapa `write frontier report` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_frontier_sweep.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    best = summary.iloc[0]
    lines = [
        "# G3 frontier sweep",
        "",
        f"Run at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Bottom line",
        "",
        (
            f"Best valid frozen 2023-2024 critical WAPE: {best['gate_2023_2024_wape_critical']:.4f} "
            f"from `{best['model']}`. G3 target remains <= {G3_CE_LIMIT:.2f} for CE and "
            f"<= {G3_CHAPADA_LIMIT:.2f} for Chapada/Cariri."
        ),
        "",
        "The sweep did not find a production-valid G3 pass. The invalid oracle is included only to show whether "
        "perfect monthly regional intensity would be enough with the current spatial allocation shape.",
        "",
        "## Literature frontier mapped to FireCast",
        "",
        "- Multi-modal wildfire prediction separates risk occurrence from magnitude and uses conformal sets for magnitude: https://arxiv.org/abs/2207.13250",
        "- SeasFire-style datacubes combine climate, vegetation, ocean indices and human variables at sub-seasonal to seasonal scale: https://arxiv.org/abs/2312.07199",
        "- Seasonal deep models improve with longer input series and explicit spatial context: https://arxiv.org/abs/2404.06437",
        "- Causal GNNs target spurious correlations, imbalance and regime shifts: https://arxiv.org/abs/2403.08414",
        "- FireCastNet models Earth as a graph and reports gains from long-range teleconnections and local area modeling: https://arxiv.org/abs/2502.01550",
        "- WISP reframes next-day active fire as high-resolution ranked set prediction rather than coarse regional risk only: https://arxiv.org/abs/2605.10298",
        "- Conformal risk control and boundary-aware UQ emphasize operational safety metrics, not only global error: https://arxiv.org/abs/2603.22331 and https://arxiv.org/abs/2605.03148",
        "",
        "## Classification diagnostics",
        "",
        "```json",
        json.dumps(classification_diag, indent=2),
        "```",
        "",
        "## Old V7 artifact decision",
        "",
        "```json",
        json.dumps(old_v7_audit, indent=2),
        "```",
        "",
        "## Next hypotheses",
        "",
        "1. Replace monthly municipal allocation with grid/cell active-fire allocation, then aggregate to municipality.",
        "2. Add vegetation/fuel dryness, land-use/road/human-access and ocean-climate teleconnection signals with as-of snapshots.",
        "3. Split the task into occurrence classification, conditional intensity regression and ranked municipality/cell set prediction.",
        "4. Add graph features over neighboring municipalities and biome/land-cover similarity, evaluated with spatial holdout.",
        "5. Keep conformal calibration stratified by dry/wet and critical months; G5 now has a valid path, G3 remains the limiting gate.",
    ]
    (OUT_DIR / "frontier_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/g3_frontier_sweep.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    df = build_features(df)
    contexts = build_cut_contexts(df)
    baseline_exp10, champion_exp10 = load_exp10_predictions()

    candidate_blocks = [baseline_exp10, champion_exp10, oracle_monthly_total(contexts)]

    candidate_blocks.extend(
        [
            walk_forward_model(df, lambda: NaiveLag12(), "historical_rule", "Strict lag-12 baseline."),
            walk_forward_model(df, lambda: HistoricalMean(n_years=3), "historical_rule", "Recent 3-year municipal-month mean."),
            ridge_log_lag_regression(df, ridge=2.0),
        ]
    )

    municipal_selected, municipal_grid = select_municipal_ratio(contexts)
    cluster_selected, cluster_grid = select_cluster_ratio(contexts)
    lag_selected, lag_grid = select_lag_blend(df, champion_exp10)
    occ = occurrence_probabilities(contexts)
    hurdle_selected, hurdle_grid, classification_diag = select_hurdle(champion_exp10, occ)

    candidate_blocks.extend([municipal_selected, cluster_selected, lag_selected, hurdle_selected])
    all_preds = pd.concat(candidate_blocks, ignore_index=True)
    summary = summarize_candidates(all_preds)
    old_v7_audit = audit_old_v7_artifacts()

    all_preds.to_csv(OUT_DIR / "candidate_predictions.csv", index=False)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    municipal_grid.to_csv(OUT_DIR / "municipal_ratio_grid.csv", index=False)
    cluster_grid.to_csv(OUT_DIR / "cluster_ratio_grid.csv", index=False)
    lag_grid.to_csv(OUT_DIR / "lag_blend_grid.csv", index=False)
    hurdle_grid.to_csv(OUT_DIR / "hurdle_grid.csv", index=False)
    occ.to_csv(OUT_DIR / "occurrence_probabilities.csv", index=False)

    report = {
        "experiment_id": "EXP-2026-07-09-12",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "walk-forward 2015-2024, h=1; selection on 2015-2022 critical; frozen gate on 2023-2024 critical",
        "target_snapshot_sha256": sha256_file(SNAPSHOT_PATH),
        "exp10_predictions_sha256": sha256_file(EXP10_PRED_PATH),
        "g3_limits": {"ceara": G3_CE_LIMIT, "chapada_cariri": G3_CHAPADA_LIMIT},
        "series_gaps_reindexed": [{"geocodigo": int(g), "missing_months": int(n)} for g, n in gaps],
        "best_valid_candidate": summary[summary["family"] != "invalid_oracle_lower_bound"].iloc[0].to_dict(),
        "best_any_candidate": summary.iloc[0].to_dict(),
        "classification_diagnostics": classification_diag,
        "old_v7_audit": old_v7_audit,
        "decision": "G3_FAIL",
        "why": (
            "No valid tested family reaches the current critical WAPE target. "
            "The oracle diagnostic shows how much error remains when only regional monthly total is fixed."
        ),
        "artifacts": [
            "summary.csv",
            "candidate_predictions.csv",
            "municipal_ratio_grid.csv",
            "cluster_ratio_grid.csv",
            "lag_blend_grid.csv",
            "hurdle_grid.csv",
            "occurrence_probabilities.csv",
            "frontier_report.md",
        ],
    }
    (OUT_DIR / "frontier_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_frontier_report(summary, classification_diag, old_v7_audit)

    print("=== G3 frontier sweep ===")
    print(summary[["model", "family", "selection_2015_2022_wape_critical", "gate_2023_2024_wape_critical", "passes_g3_ceara", "passes_g3_chapada_cariri"]].to_string(index=False))
    print("DECISION: G3_FAIL")


if __name__ == "__main__":
    main()






