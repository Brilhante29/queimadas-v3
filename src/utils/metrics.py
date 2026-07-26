"""Modulo publico do FireCast para metricas e utilitarios compartilhados.

Arquivo `src/utils/metrics.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple


def wape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Executa a etapa `wape` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    denom = np.sum(np.abs(y_true))
    return np.nan if denom == 0 else float(np.sum(np.abs(y_true - y_pred)) / denom)


def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Executa a etapa `mape` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    mask = y_true > 0
    if mask.sum() == 0:
        return np.nan
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])))


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Executa a etapa `rmse` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Executa a etapa `mae` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(np.mean(np.abs(y_true - y_pred)))


def r2_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Executa a etapa `r2 score` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1 - ss_res / ss_tot)


def brier_score(y_true_binary: np.ndarray, prob: np.ndarray) -> float:
    """Executa a etapa `brier score` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(np.mean((prob - y_true_binary) ** 2))


def interval_coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    """Executa a etapa `interval coverage` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(np.mean((y >= lo) & (y <= hi)))


def interval_width(y_pred: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    """Executa a etapa `interval width` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(np.mean(hi - lo))


def zero_indevido(y_pred: np.ndarray, hist_positive: np.ndarray) -> float:
    """Executa a etapa `zero indevido` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    mask = hist_positive > 0
    if mask.sum() == 0:
        return 0.0
    return float(np.mean((y_pred[mask] <= 0)))


def recall_at_k(
    df: pd.DataFrame,
    k: int = 10,
    y_col: str = "y_true",
    pred_col: str = "y_pred",
    id_col: str = "municipio_id",
    group_cols: Optional[List[str]] = None,
) -> float:
    """Executa a etapa `recall at k` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if group_cols is None:
        true_top = set(df.nlargest(k, y_col)[id_col])
        pred_top = set(df.nlargest(k, pred_col)[id_col])
        return len(true_top & pred_top) / max(1, len(true_top))

    scores = []
    for _, g in df.groupby(group_cols):
        true_top = set(g.nlargest(k, y_col)[id_col])
        pred_top = set(g.nlargest(k, pred_col)[id_col])
        if len(true_top) > 0:
            scores.append(len(true_top & pred_top) / len(true_top))
    return float(np.mean(scores)) if scores else np.nan


def population_stability_index(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    """Executa a etapa `population stability index` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    expected_percents, bin_edges = np.histogram(expected, bins=bins)
    actual_percents, _ = np.histogram(actual, bins=bin_edges)

    expected_percents = expected_percents / max(1, expected_percents.sum())
    actual_percents = actual_percents / max(1, actual_percents.sum())

    eps = 1e-6
    psi = np.sum(
        (actual_percents - expected_percents)
        * np.log((actual_percents + eps) / (expected_percents + eps))
    )
    return float(psi)


def evaluate_scope(df: pd.DataFrame, scope_name: str, extreme_threshold: int = 30) -> Dict:
    """Calcula a etapa `evaluate scope` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = {"scope": scope_name, "n_samples": len(df)}

    subsets = {
        "annual": np.ones(len(df), dtype=bool),
        "critical_out_nov": df["month"].isin([10, 11]) if "month" in df.columns else np.ones(len(df), dtype=bool),
        "dry_season": df["month"].isin([8, 9, 10, 11, 12]) if "month" in df.columns else np.ones(len(df), dtype=bool),
    }

    for subset_name, mask in subsets.items():
        d = df.loc[mask].copy()
        if len(d) == 0:
            continue

        yt = d["y_true"].values if "y_true" in d.columns else d["fire_count"].values
        yp = d["y_pred"].values
        
        out[f"wape_{subset_name}"] = wape(yt, yp)
        out[f"mape_{subset_name}"] = mape(yt, yp)
        out[f"rmse_{subset_name}"] = rmse(yt, yp)
        out[f"mae_{subset_name}"] = mae(yt, yp)
        out[f"r2_{subset_name}"] = r2_score(yt, yp)

        if "p_occurrence" in d.columns:
            out[f"brier_occ_{subset_name}"] = brier_score(
                (yt > 0).astype(int), d["p_occurrence"].values
            )
        
        if "p_extreme" in d.columns:
            out[f"brier_ext_{subset_name}"] = brier_score(
                (yt >= extreme_threshold).astype(int), d["p_extreme"].values
            )

        if all(c in d.columns for c in ["ic80_lower", "ic80_upper"]):
            out[f"ic80_{subset_name}"] = interval_coverage(
                yt, d["ic80_lower"].values, d["ic80_upper"].values
            )
            out[f"ic80_width_{subset_name}"] = interval_width(
                yp, d["ic80_lower"].values, d["ic80_upper"].values
            )
        
        if all(c in d.columns for c in ["ic95_lower", "ic95_upper"]):
            out[f"ic95_{subset_name}"] = interval_coverage(
                yt, d["ic95_lower"].values, d["ic95_upper"].values
            )
            out[f"ic95_width_{subset_name}"] = interval_width(
                yp, d["ic95_lower"].values, d["ic95_upper"].values
            )

        if "hist_positive" in d.columns:
            out[f"zero_indevido_{subset_name}"] = zero_indevido(yp, d["hist_positive"].values)

        if "municipio_id" in d.columns:
            out[f"recall10_{subset_name}"] = recall_at_k(d, k=10)

    return out


def acceptance_gate(results_df: pd.DataFrame, config: Dict) -> pd.DataFrame:
    """Executa a etapa `acceptance gate` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    decisions = []

    for _, r in results_df.iterrows():
        scope = r["scope"]
        if scope not in config:
            continue
            
        g = config[scope]
        passed = True
        reasons = []

        required_metrics = [
            "wape_critical_out_nov", "ic95_critical_out_nov",
            "zero_indevido_critical_out_nov", "recall10_critical_out_nov",
            "best_baseline_wape",
        ]
        for metric in required_metrics:
            if metric not in r.index or not np.isfinite(r[metric]):
                passed = False
                reasons.append(f"metrica obrigatoria ausente/invalida: {metric}")

        # WAPE crítico
        wape_key = "wape_critical_out_nov"
        if wape_key in r:
            if r[wape_key] > g["wape_critical_threshold"]:
                passed = False
                reasons.append(f"WAPE critico {r[wape_key]:.3f} > limite {g['wape_critical_threshold']}")

        # IC95
        ic95_key = "ic95_critical_out_nov"
        if ic95_key in r:
            if not (g["ic95_min"] <= r[ic95_key] <= g["ic95_max"]):
                passed = False
                reasons.append(f"IC95 {r[ic95_key]:.3f} fora da faixa [{g['ic95_min']}, {g['ic95_max']}]")

        # Zero indevido
        zi_key = "zero_indevido_critical_out_nov"
        if zi_key in r:
            if r[zi_key] > g["zero_indevido_threshold"]:
                passed = False
                reasons.append(f"Zero indevido {r[zi_key]:.4f} > {g['zero_indevido_threshold']}")

        # Recall@10
        r10_key = "recall10_critical_out_nov"
        if r10_key in r:
            if r[r10_key] < g["recall10_threshold"]:
                passed = False
                reasons.append(f"Recall@10 {r[r10_key]:.3f} < {g['recall10_threshold']}")

        if np.isfinite(r.get("best_baseline_wape", np.nan)) and np.isfinite(r.get(wape_key, np.nan)):
            if r[wape_key] >= r["best_baseline_wape"]:
                passed = False
                reasons.append(
                    f"modelo nao supera baseline: {r[wape_key]:.3f} >= {r['best_baseline_wape']:.3f}"
                )

        row = dict(r)
        row["passed"] = passed
        row["pass_reasons"] = "; ".join(reasons) if reasons else "PASS"
        decisions.append(row)

    return pd.DataFrame(decisions)


def compare_to_baseline(
    model_results: pd.DataFrame,
    baseline_results: pd.DataFrame,
    metric: str = "wape_critical_out_nov",
) -> pd.DataFrame:
    """Executa a etapa `compare to baseline` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    comparison = []
    for scope in model_results["scope"].unique():
        m_val = model_results[model_results["scope"] == scope][metric].values
        b_val = baseline_results[baseline_results["scope"] == scope][metric].values
        
        if len(m_val) > 0 and len(b_val) > 0:
            improvement = (b_val[0] - m_val[0]) / b_val[0] * 100
            comparison.append({
                "scope": scope,
                "metric": metric,
                "model_value": m_val[0],
                "baseline_value": b_val[0],
                "improvement_pct": improvement,
                "better": improvement > 0,
            })
    
    return pd.DataFrame(comparison)


def trigger_retrain(report: Dict) -> bool:
    """Executa a etapa `trigger retrain` do fluxo FireCast.
    
    A funcao faz parte de `src/utils/metrics.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return (
        report.get("wape_recent", 0) > report.get("wape_limit", 0.35)
        or report.get("brier_extreme_recent", 0) > report.get("brier_limit", 0.15)
        or report.get("ic95_coverage_recent", 1.0) < 0.88
        or report.get("feature_drift_max", 0) > 0.25
        or report.get("regime_probability", 0) > 0.70
    )
