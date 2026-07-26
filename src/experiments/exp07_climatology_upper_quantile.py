"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp07_climatology_upper_quantile.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import (  # noqa: E402
    FEATURE_COLS,
    MIN_TRAIN_MONTHS,
    TEST_MONTHS,
    build_features,
    load_merged_target,
)
from src.utils.metrics import mae, wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp07_climatology_upper_quantile"
BASELINE = "climatology_municipal"
CANDIDATE = "climatology_municipal_p65"
QUANTILE = 0.65


def climatology_predict(train: pd.DataFrame, test: pd.DataFrame, quantile: float | None) -> np.ndarray:
    """Executa a etapa `climatology predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp07_climatology_upper_quantile.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if quantile is None:
        table = train.groupby(["municipio_id", "mes"])["fire_count"].mean()
    else:
        table = train.groupby(["municipio_id", "mes"])["fire_count"].quantile(quantile)
    keys = list(zip(test["municipio_id"], test["mes"]))
    return np.array([table.get(k, 0.0) for k in keys], dtype=float)


def run() -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp07_climatology_upper_quantile.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, _ = load_merged_target()
    df = build_features(df)

    predictions = []
    for (ty, tm) in TEST_MONTHS:
        cut = pd.Period(f"{ty}-{tm:02d}", freq="M")
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
        test = df[(df["period"] == cut) & df["fire_count"].notna()]
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()]
        if len(test) == 0 or len(train) == 0:
            continue

        base_pred = climatology_predict(train, test, None)
        cand_pred = climatology_predict(train, test, QUANTILE)

        cols = ["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]
        base = test[cols].copy()
        base["model"] = BASELINE
        base["y_pred"] = base_pred
        predictions.append(base)

        cand = test[cols].copy()
        cand["model"] = CANDIDATE
        cand["y_pred"] = np.maximum(cand_pred, 0)
        predictions.append(cand)

    preds = pd.concat(predictions, ignore_index=True)
    preds["cut"] = preds["ano"].astype(str) + "-" + preds["mes"].astype(str).str.zfill(2)

    rows = []
    for model, p in preds.groupby("model"):
        crit = p[p["mes"].isin([10, 11])]
        high = p[p["fire_count"] > 10]
        rows.append(
            {
                "model": model,
                "all_wape": wape(p["fire_count"].values, p["y_pred"].values),
                "all_mae": mae(p["fire_count"].values, p["y_pred"].values),
                "outnov_wape": wape(crit["fire_count"].values, crit["y_pred"].values),
                "outnov_mae": mae(crit["fire_count"].values, crit["y_pred"].values),
                "high_volume_wape": wape(high["fire_count"].values, high["y_pred"].values),
                "n": len(p),
            }
        )
    summary = pd.DataFrame(rows).sort_values("all_wape").reset_index(drop=True)

    bb = preds[preds["model"] == BASELINE]
    bc = preds[preds["model"] == CANDIDATE]
    per_cut = []
    for cut in sorted(preds["cut"].unique()):
        a = bb[bb["cut"] == cut]
        b = bc[bc["cut"] == cut]
        per_cut.append(
            {
                "cut": cut,
                "wape_baseline": wape(a["fire_count"].values, a["y_pred"].values),
                "wape_candidate": wape(b["fire_count"].values, b["y_pred"].values),
            }
        )
    per_cut = pd.DataFrame(per_cut)
    per_cut["candidate_wins"] = per_cut["wape_candidate"] < per_cut["wape_baseline"]
    wins = int(per_cut["candidate_wins"].sum())

    rng = np.random.default_rng(42)
    cuts = per_cut["cut"].values
    bb_by_cut = {c: g for c, g in bb.groupby("cut")}
    bc_by_cut = {c: g for c, g in bc.groupby("cut")}
    deltas = []
    for _ in range(1000):
        sample = rng.choice(cuts, size=len(cuts), replace=True)
        a = pd.concat([bb_by_cut[c] for c in sample])
        b = pd.concat([bc_by_cut[c] for c in sample])
        deltas.append(wape(b["fire_count"].values, b["y_pred"].values) - wape(a["fire_count"].values, a["y_pred"].values))
    deltas = np.asarray(deltas)
    ci = np.percentile(deltas, [2.5, 97.5])
    p_better = float((deltas < 0).mean())

    baseline_row = summary[summary["model"] == BASELINE].iloc[0]
    candidate_row = summary[summary["model"] == CANDIDATE].iloc[0]
    reject = (
        candidate_row["all_wape"] >= baseline_row["all_wape"]
        or candidate_row["outnov_wape"] > baseline_row["outnov_wape"]
    )
    decision = "REJECT" if reject else "PROMOTE"

    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    per_cut.to_csv(OUT_DIR / "per_cut_comparison.csv", index=False)
    preds.to_csv(OUT_DIR / "predictions.csv", index=False)

    manifest = {
        "experiment_id": "EXP-2026-07-09-07",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Quantil p65 por (municipio,mes) corrige subprevisao sistematica em meses de volume alto (diagnosticada: 62% do erro em 9.9% das previsoes, meses fire_count>=11 subprevistos em 37-39%)",
        "quantile": QUANTILE,
        "test_months": [f"{y}-{m:02d}" for y, m in TEST_MONTHS],
        "baseline": {"model": BASELINE, "wape": float(baseline_row["all_wape"]), "outnov_wape": float(baseline_row["outnov_wape"])},
        "candidate": {"model": CANDIDATE, "wape": float(candidate_row["all_wape"]), "outnov_wape": float(candidate_row["outnov_wape"])},
        "delta_wape_candidate_minus_baseline": float(candidate_row["all_wape"] - baseline_row["all_wape"]),
        "candidate_wins_of_n_cuts": wins,
        "n_cuts": int(len(per_cut)),
        "bootstrap_delta_wape_ci95": [float(ci[0]), float(ci[1])],
        "p_candidate_better": p_better,
        "rejection_condition": "all_wape >= baseline.all_wape OR outnov_wape > baseline.outnov_wape",
        "decision": decision,
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== EXP-07: climatologia p65 vs media (champion) ===")
    print(summary.to_string(index=False))
    print(f"Vitorias do candidato: {wins}/{len(per_cut)}")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidato melhor)={p_better:.3f}")
    print(f"DECISAO: {decision}")
    return manifest


if __name__ == "__main__":
    run()
