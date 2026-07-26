"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp04_climatology_residual_candidate.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import (  # noqa: E402
    FEATURE_COLS,
    MIN_TRAIN_MONTHS,
    TEST_MONTHS,
    build_features,
    load_merged_target,
)
from src.experiments.exp03_climate_candidate import (  # noqa: E402
    ERA5_SNAPSHOT,
    NDVI_CSV,
    add_exog_features,
)
from src.models.baselines import ClimatologyMunicipal  # noqa: E402
from src.utils.metrics import mae, wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp04_climatology_residual"
CANDIDATE = "climatology_residual_gbm"
BASELINE = "climatology_municipal"


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp04_climatology_residual_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def fit_residual_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Executa a etapa `fit residual predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp04_climatology_residual_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    baseline = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
    train_base = np.asarray(baseline.predict(train), dtype=float)
    test_base = np.asarray(baseline.predict(test), dtype=float)

    residual = train["fire_count"].to_numpy(dtype=float) - train_base
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=80,
        learning_rate=0.04,
        l2_regularization=1.0,
        min_samples_leaf=20,
        random_state=42,
    )
    med = train[cols].median(numeric_only=True).fillna(0)
    model.fit(train[cols].fillna(med), residual)
    residual_pred = model.predict(test[cols].fillna(med))
    return np.maximum(test_base + residual_pred, 0), test_base


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp04_climatology_residual_candidate.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, _ = load_merged_target()
    df = build_features(df)
    df, climate_feats, ndvi_feats, ndvi_unmapped = add_exog_features(df)
    residual_cols = FEATURE_COLS + climate_feats + ndvi_feats

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

        cand_pred, base_pred = fit_residual_predict(train, test, residual_cols)
        base = test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]].copy()
        base["model"] = BASELINE
        base["y_pred"] = base_pred
        predictions.append(base)

        cand = test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]].copy()
        cand["model"] = CANDIDATE
        cand["y_pred"] = cand_pred
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
    deltas = np.array(deltas)
    ci = np.percentile(deltas, [2.5, 97.5])
    p_better = float((deltas < 0).mean())

    baseline_row = summary[summary["model"] == BASELINE].iloc[0]
    candidate_row = summary[summary["model"] == CANDIDATE].iloc[0]
    reject = (
        candidate_row["all_wape"] >= baseline_row["all_wape"]
        or candidate_row["outnov_wape"] > baseline_row["outnov_wape"]
        or wins < 13
    )
    decision = "REJECT" if reject else "ITERATE"

    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    per_cut.to_csv(OUT_DIR / "per_cut_comparison.csv", index=False)
    preds.to_csv(OUT_DIR / "predictions.csv", index=False)
    manifest = {
        "experiment_id": "EXP-2026-07-03-04",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "target_snapshot_sha256": sha256_file(PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"),
        "climate_snapshot_sha256": sha256_file(ERA5_SNAPSHOT / "era5_monthly.csv"),
        "ndvi_source": NDVI_CSV.name,
        "ndvi_unmapped_cities": ndvi_unmapped,
        "residual_feature_count": len(residual_cols),
        "baseline": {"model": BASELINE, "wape": float(baseline_row["all_wape"]), "outnov_wape": float(baseline_row["outnov_wape"])},
        "candidate": {"model": CANDIDATE, "wape": float(candidate_row["all_wape"]), "outnov_wape": float(candidate_row["outnov_wape"])},
        "candidate_wins_of_24": wins,
        "bootstrap_delta_wape_ci95": [float(ci[0]), float(ci[1])],
        "p_candidate_better": p_better,
        "decision": decision,
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("=== EXP-04: residual ancorado na climatologia ===")
    print(summary.to_string(index=False))
    print(f"Vitórias do candidato: {wins}/24")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidato melhor)={p_better:.3f}")
    print(f"DECISÃO: {decision}")


if __name__ == "__main__":
    main()
