"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp09_enso_conditional_climatology.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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
    MIN_TRAIN_MONTHS,
    build_features,
    load_merged_target,
)
from src.utils.metrics import mae, wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp09_enso_conditional_climatology"
ENSO_PATH = PROJECT_ROOT / "data" / "snapshots" / "enso_cpc_v1" / "enso_monthly.csv"
BASELINE = "climatology_municipal"
CANDIDATE = "climatology_enso_conditional"
EXTENDED_TEST_MONTHS = [(y, m) for y in range(2015, 2025) for m in range(1, 13)]
FROZEN_YEARS = (2025, 2026)
# Fator limitado a uma faixa sã: grupos ENSO pequenos no início do treino não
# podem produzir amplificações absurdas.
RATIO_CLIP = (0.5, 2.0)


def load_enso_lagged() -> pd.DataFrame:
    """Carrega a etapa `load enso lagged` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp09_enso_conditional_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    enso = pd.read_csv(ENSO_PATH)[["ano", "mes", "enso_regime"]]
    period = pd.PeriodIndex(
        pd.to_datetime(enso["ano"].astype(str) + "-" + enso["mes"].astype(str).str.zfill(2)), freq="M"
    )
    lagged = enso.copy()
    lagged["period"] = period + 1  # o regime de m fica disponível para prever m+1
    return lagged[["period", "enso_regime"]].rename(columns={"enso_regime": "enso_state_lag1"})


def climatology_mean_predict(train: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
    """Executa a etapa `climatology mean predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp09_enso_conditional_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    table = train.groupby(["municipio_id", "mes"])["fire_count"].mean()
    keys = list(zip(frame["municipio_id"], frame["mes"]))
    return np.array([table.get(k, 0.0) for k in keys], dtype=float)


def enso_ratios(train: pd.DataFrame) -> dict[str, float]:
    """Executa a etapa `enso ratios` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp09_enso_conditional_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    clim_pred = climatology_mean_predict(train, train)
    grouped = pd.DataFrame(
        {"state": train["enso_state_lag1"].values, "actual": train["fire_count"].values, "pred": clim_pred}
    ).groupby("state").sum()
    ratios: dict[str, float] = {}
    for state, row in grouped.iterrows():
        if row["pred"] > 0:
            ratios[state] = float(np.clip(row["actual"] / row["pred"], *RATIO_CLIP))
        else:
            ratios[state] = 1.0
    return ratios


def run() -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp09_enso_conditional_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    assert not any(y in FROZEN_YEARS for y, _ in EXTENDED_TEST_MONTHS), "2025+ deve continuar congelado"

    df, _ = load_merged_target()
    df = build_features(df)
    df = df.merge(load_enso_lagged(), on="period", how="left")

    predictions = []
    ratio_log = []
    for (ty, tm) in EXTENDED_TEST_MONTHS:
        cut = pd.Period(f"{ty}-{tm:02d}", freq="M")
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna() & df["enso_state_lag1"].notna()]
        test = df[(df["period"] == cut) & df["fire_count"].notna()]
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()]
        if len(test) == 0 or len(train) == 0:
            continue

        base_pred = climatology_mean_predict(train, test)
        ratios = enso_ratios(train)
        state = test["enso_state_lag1"].iloc[0] if test["enso_state_lag1"].notna().any() else "neutral"
        factor = ratios.get(state, 1.0)
        cand_pred = base_pred * factor
        ratio_log.append({"cut": str(cut), "enso_state_lag1": state, "factor": factor, **{f"r_{k}": v for k, v in ratios.items()}})

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
        rows.append(
            {
                "model": model,
                "all_wape": wape(p["fire_count"].values, p["y_pred"].values),
                "all_mae": mae(p["fire_count"].values, p["y_pred"].values),
                "outnov_wape": wape(crit["fire_count"].values, crit["y_pred"].values),
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
    pd.DataFrame(ratio_log).to_csv(OUT_DIR / "enso_factors_by_cut.csv", index=False)

    manifest = {
        "experiment_id": "EXP-2026-07-09-09",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Fator multiplicativo por estado ENSO (lag 1, as-of), aprendido no treino de cada corte, melhora a climatologia media no protocolo ESTENDIDO — correcao condicional ao regime, nao estatica (licao do EXP-08)",
        "protocol": "walk-forward estendido 2015-2024 (120 cortes), 2025+ congelado",
        "ratio_clip": list(RATIO_CLIP),
        "baseline": {"model": BASELINE, "wape": float(baseline_row["all_wape"]), "outnov_wape": float(baseline_row["outnov_wape"])},
        "candidate": {"model": CANDIDATE, "wape": float(candidate_row["all_wape"]), "outnov_wape": float(candidate_row["outnov_wape"])},
        "delta_wape_candidate_minus_baseline": float(candidate_row["all_wape"] - baseline_row["all_wape"]),
        "candidate_wins_of_n_cuts": wins,
        "n_cuts": int(len(per_cut)),
        "bootstrap_delta_wape_ci95": [float(ci[0]), float(ci[1])],
        "p_candidate_better": p_better,
        "rejection_condition": "all_wape >= baseline.all_wape OR outnov_wape > baseline.outnov_wape (no protocolo estendido)",
        "decision": decision,
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== EXP-09: climatologia condicional ao ENSO vs media (protocolo estendido 2015-2024) ===")
    print(summary.to_string(index=False))
    print(f"Vitorias do candidato: {wins}/{len(per_cut)}")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidato melhor)={p_better:.3f}")
    print(f"DECISAO: {decision}")
    return manifest


if __name__ == "__main__":
    run()
