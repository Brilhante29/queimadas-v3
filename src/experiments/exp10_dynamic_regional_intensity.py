"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp10_dynamic_regional_intensity.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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
    FEATURE_COLS,
    MIN_TRAIN_MONTHS,
    build_features,
    load_merged_target,
)
from src.models.baselines import ClimatologyMunicipal  # noqa: E402
from src.utils.metrics import mae, wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity"
BASELINE = "climatology_municipal"
CANDIDATE = "climatology_regional_intensity12"
TEST_MONTHS = [(y, m) for y in range(2015, 2025) for m in range(1, 13)]
FROZEN_YEARS_UNTOUCHED = [2025, 2026]
TRAILING_MONTHS = 12
SHRINK_FIRE_COUNT = 100.0
RATIO_CLIP = (0.5, 2.0)


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp10_dynamic_regional_intensity.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def aggregate_metrics(preds: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `aggregate metrics` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp10_dynamic_regional_intensity.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for model, p in preds.groupby("model"):
        crit = p[p["mes"].isin([10, 11])]
        dry = p[p["mes"].isin([8, 9, 10, 11, 12])]
        high = p[p["fire_count"] > 10]
        rows.append(
            {
                "model": model,
                "all_wape": wape(p["fire_count"].values, p["y_pred"].values),
                "all_mae": mae(p["fire_count"].values, p["y_pred"].values),
                "all_n": int(len(p)),
                "all_y_total": float(p["fire_count"].sum()),
                "outnov_wape": wape(crit["fire_count"].values, crit["y_pred"].values),
                "outnov_mae": mae(crit["fire_count"].values, crit["y_pred"].values),
                "outnov_n": int(len(crit)),
                "outnov_y_total": float(crit["fire_count"].sum()),
                "dry_wape": wape(dry["fire_count"].values, dry["y_pred"].values),
                "high_volume_wape": wape(high["fire_count"].values, high["y_pred"].values),
            }
        )
    return pd.DataFrame(rows).sort_values("all_wape").reset_index(drop=True)


def compute_cut_predictions(df: pd.DataFrame, cut: pd.Period) -> tuple[pd.DataFrame | None, dict | None]:
    """Calcula a etapa `compute cut predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp10_dynamic_regional_intensity.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
    test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()

    hist = train.groupby("geocodigo")["fire_count"].count()
    eligible = hist[hist >= MIN_TRAIN_MONTHS].index
    test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
    if len(train) == 0 or len(test) == 0:
        return None, None

    baseline = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
    base_pred = np.asarray(baseline.predict(test), dtype=float)

    prior_periods = pd.period_range(cut - TRAILING_MONTHS, cut - 1, freq="M")
    prior = df[
        df["period"].isin(prior_periods)
        & df["geocodigo"].isin(eligible)
        & df["fire_count"].notna()
    ].copy()

    if len(prior):
        expected_12m = float(np.asarray(baseline.predict(prior), dtype=float).sum())
        observed_12m = float(prior["fire_count"].sum())
        raw_ratio = (observed_12m + SHRINK_FIRE_COUNT) / (expected_12m + SHRINK_FIRE_COUNT)
    else:
        expected_12m = 0.0
        observed_12m = 0.0
        raw_ratio = 1.0
    ratio = float(np.clip(raw_ratio, RATIO_CLIP[0], RATIO_CLIP[1]))
    cand_pred = np.maximum(base_pred * ratio, 0.0)

    rows = []
    for model, pred in [(BASELINE, base_pred), (CANDIDATE, cand_pred)]:
        out = test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "target_source"]].copy()
        out["model"] = model
        out["y_pred"] = pred
        out["cut"] = str(cut)
        rows.append(out)

    ratio_row = {
        "cut": str(cut),
        "ano": int(cut.year),
        "mes": int(cut.month),
        "observed_trailing_12m": observed_12m,
        "expected_trailing_12m": expected_12m,
        "raw_ratio": float(raw_ratio),
        "applied_ratio": ratio,
        "n_prior_rows": int(len(prior)),
        "n_test_rows": int(len(test)),
    }
    return pd.concat(rows, ignore_index=True), ratio_row


def bootstrap_delta_by_cut(base: pd.DataFrame, cand: pd.DataFrame, n: int = 2000) -> tuple[list[float], float]:
    """Executa a etapa `bootstrap delta by cut` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp10_dynamic_regional_intensity.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rng = np.random.default_rng(42)
    cuts = sorted(base["cut"].unique())
    base_by_cut = {c: g for c, g in base.groupby("cut")}
    cand_by_cut = {c: g for c, g in cand.groupby("cut")}
    deltas = []
    for _ in range(n):
        sample = rng.choice(cuts, size=len(cuts), replace=True)
        b = pd.concat([base_by_cut[c] for c in sample], ignore_index=True)
        c = pd.concat([cand_by_cut[c] for c in sample], ignore_index=True)
        deltas.append(wape(c["fire_count"].values, c["y_pred"].values) - wape(b["fire_count"].values, b["y_pred"].values))
    arr = np.asarray(deltas, dtype=float)
    ci = np.percentile(arr, [2.5, 97.5])
    return [float(ci[0]), float(ci[1])], float((arr < 0).mean())


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp10_dynamic_regional_intensity.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    df = build_features(df)

    prediction_blocks = []
    ratio_log = []
    skipped = []
    for year, month in TEST_MONTHS:
        cut = pd.Period(f"{year}-{month:02d}", freq="M")
        pred, ratio_row = compute_cut_predictions(df, cut)
        if pred is None:
            skipped.append(str(cut))
            continue
        prediction_blocks.append(pred)
        ratio_log.append(ratio_row)

    preds = pd.concat(prediction_blocks, ignore_index=True)
    ratios = pd.DataFrame(ratio_log)
    summary = aggregate_metrics(preds)

    base = preds[preds["model"] == BASELINE].copy()
    cand = preds[preds["model"] == CANDIDATE].copy()

    per_cut = []
    for cut in sorted(preds["cut"].unique()):
        b = base[base["cut"] == cut]
        c = cand[cand["cut"] == cut]
        per_cut.append(
            {
                "cut": cut,
                "ano": int(cut[:4]),
                "mes": int(cut[5:7]),
                "wape_baseline": wape(b["fire_count"].values, b["y_pred"].values),
                "wape_candidate": wape(c["fire_count"].values, c["y_pred"].values),
                "y_total": float(b["fire_count"].sum()),
            }
        )
    per_cut = pd.DataFrame(per_cut)
    per_cut["candidate_wins"] = per_cut["wape_candidate"] < per_cut["wape_baseline"]
    wins = int(per_cut["candidate_wins"].sum())

    by_year = []
    for model, p_model in preds.groupby("model"):
        for year, p_year in p_model.groupby("ano"):
            by_year.append(
                {
                    "model": model,
                    "ano": int(year),
                    "wape": wape(p_year["fire_count"].values, p_year["y_pred"].values),
                    "y_total": float(p_year["fire_count"].sum()),
                    "pred_total": float(p_year["y_pred"].sum()),
                }
            )
    by_year = pd.DataFrame(by_year)

    ci, p_better = bootstrap_delta_by_cut(base, cand)
    baseline_row = summary[summary["model"] == BASELINE].iloc[0]
    candidate_row = summary[summary["model"] == CANDIDATE].iloc[0]
    delta_wape = float(candidate_row["all_wape"] - baseline_row["all_wape"])
    delta_outnov = float(candidate_row["outnov_wape"] - baseline_row["outnov_wape"])

    reject = (
        candidate_row["all_wape"] >= baseline_row["all_wape"]
        or candidate_row["outnov_wape"] > baseline_row["outnov_wape"]
        or wins <= len(per_cut) / 2
        or ci[1] >= 0
    )
    decision = "REJECT" if reject else "PROMOTE"

    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    per_cut.to_csv(OUT_DIR / "per_cut_comparison.csv", index=False)
    by_year.to_csv(OUT_DIR / "by_year.csv", index=False)
    ratios.to_csv(OUT_DIR / "ratio_log.csv", index=False)
    preds.to_csv(OUT_DIR / "predictions.csv", index=False)

    manifest = {
        "experiment_id": "EXP-2026-07-09-10",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": (
            "Trailing-12-month regional fire-memory intensity corrects interannual activity level "
            "while preserving municipal-month climatology shape."
        ),
        "change": "candidate = climatology_municipal * clipped regional trailing-12m observed/expected ratio",
        "protocol": "walk-forward estendido 2015-2024 (120 cortes), 2025+ congelado",
        "target_snapshot_sha256": sha256_file(PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"),
        "frozen_years_untouched": FROZEN_YEARS_UNTOUCHED,
        "parameters": {
            "trailing_months": TRAILING_MONTHS,
            "shrink_fire_count": SHRINK_FIRE_COUNT,
            "ratio_clip": list(RATIO_CLIP),
            "min_train_months": MIN_TRAIN_MONTHS,
        },
        "baseline": {
            "model": BASELINE,
            "wape": float(baseline_row["all_wape"]),
            "outnov_wape": float(baseline_row["outnov_wape"]),
            "dry_wape": float(baseline_row["dry_wape"]),
        },
        "candidate": {
            "model": CANDIDATE,
            "wape": float(candidate_row["all_wape"]),
            "outnov_wape": float(candidate_row["outnov_wape"]),
            "dry_wape": float(candidate_row["dry_wape"]),
        },
        "delta_wape_candidate_minus_baseline": delta_wape,
        "delta_outnov_wape_candidate_minus_baseline": delta_outnov,
        "candidate_wins_of_n_cuts": wins,
        "n_cuts": int(len(per_cut)),
        "bootstrap_delta_wape_ci95": ci,
        "p_candidate_better": p_better,
        "rejection_condition": (
            "all_wape >= baseline OR outnov_wape > baseline OR wins <= 60/120 "
            "OR bootstrap delta WAPE CI95 upper >= 0"
        ),
        "decision": decision,
        "series_gaps_reindexed": [{"geocodigo": int(g), "missing_months": int(n)} for g, n in gaps],
        "skipped_cuts": skipped,
        "artifacts": [
            "summary.csv",
            "per_cut_comparison.csv",
            "by_year.csv",
            "ratio_log.csv",
            "predictions.csv",
        ],
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("=== EXP-10: dynamic regional fire-memory intensity ===")
    print(summary.to_string(index=False))
    print(f"Delta WAPE candidate-baseline: {delta_wape:+.4f}")
    print(f"Delta out-nov WAPE candidate-baseline: {delta_outnov:+.4f}")
    print(f"Candidate wins: {wins}/{len(per_cut)}")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidate better)={p_better:.3f}")
    print(f"DECISION: {decision}")


if __name__ == "__main__":
    main()
