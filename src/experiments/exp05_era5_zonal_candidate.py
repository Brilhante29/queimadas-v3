"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp05_era5_zonal_candidate.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
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
from src.models.baselines import ClimatologyMunicipal  # noqa: E402
from src.utils.metrics import mae, wape  # noqa: E402

DEFAULT_ZONAL_PATH = PROJECT_ROOT / "cache" / "era5_zonal_fast" / "era5_zonal_monthly.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "exp05_era5_zonal_candidate"
BASELINE = "climatology_municipal"
CANDIDATE = "climatology_residual_era5_zonal"

ZONAL_BASE_VARS = [
    "precipitation_sum_zonal",
    "vapour_pressure_deficit_max_zonal",
    "soil_moisture_0_to_7cm_mean_zonal",
    "soil_moisture_7_to_28cm_mean_zonal",
    "soil_moisture_28_to_100cm_mean_zonal",
    "dry_days_zonal",
    "dry_spell_max_zonal",
    "et0_fao_evapotranspiration_zonal",
    "temperature_2m_max_zonal",
    "relative_humidity_2m_mean_zonal",
    "wind_speed_10m_max_zonal",
]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp05_era5_zonal_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_zonal(zonal_path: Path) -> pd.DataFrame:
    """Carrega a etapa `load zonal` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp05_era5_zonal_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not zonal_path.exists():
        raise FileNotFoundError(f"Snapshot ERA5 zonal ausente: {zonal_path} (fail closed)")
    zonal = pd.read_csv(zonal_path)
    required = {"geocodigo", "ano", "mes", "era5_weight_covered", *ZONAL_BASE_VARS}
    missing = required - set(zonal.columns)
    if missing:
        raise ValueError(f"Snapshot ERA5 zonal sem colunas obrigatórias: {sorted(missing)}")
    if float(zonal["era5_weight_covered"].min()) < 0.99:
        raise ValueError("Cobertura zonal insuficiente: peso coberto mínimo < 0.99")
    return zonal


def add_zonal_features(df: pd.DataFrame, zonal_path: Path) -> tuple[pd.DataFrame, list[str]]:
    """Executa a etapa `add zonal features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp05_era5_zonal_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    zonal = load_zonal(zonal_path)
    keep = ["geocodigo", "ano", "mes", *ZONAL_BASE_VARS, "era5_cells_used", "era5_weight_covered"]
    df = df.merge(zonal[keep], on=["geocodigo", "ano", "mes"], how="left")
    df = df.sort_values(["geocodigo", "period"]).reset_index(drop=True)

    features: list[str] = []
    for var in ZONAL_BASE_VARS:
        g = df.groupby("geocodigo")[var]
        for lag in (1, 2, 3):
            col = f"{var}_lag{lag}"
            df[col] = g.shift(lag)
            features.append(col)
        roll_col = f"{var}_roll3"
        df[roll_col] = g.transform(lambda x: x.shift(1).rolling(3, min_periods=3).mean())
        features.append(roll_col)

    # Structural as-of guard: lag1 cannot be identical to same-month raw value.
    sample = df.dropna(subset=["precipitation_sum_zonal", "precipitation_sum_zonal_lag1"])
    if len(sample) and np.allclose(sample["precipitation_sum_zonal_lag1"], sample["precipitation_sum_zonal"]):
        raise AssertionError("Violação as-of: precipitation lag1 igual ao mês corrente")
    return df, features


def fit_residual_predict(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Executa a etapa `fit residual predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp05_era5_zonal_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    baseline = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
    train_base = np.asarray(baseline.predict(train), dtype=float)
    test_base = np.asarray(baseline.predict(test), dtype=float)
    residual = train["fire_count"].to_numpy(dtype=float) - train_base

    med = train[cols].median(numeric_only=True).fillna(0)
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=80,
        learning_rate=0.04,
        l2_regularization=1.0,
        min_samples_leaf=20,
        random_state=42,
    )
    model.fit(train[cols].fillna(med), residual)
    return np.maximum(test_base + model.predict(test[cols].fillna(med)), 0), test_base


def run(zonal_path: Path = DEFAULT_ZONAL_PATH, out_dir: Path = OUT_DIR) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp05_era5_zonal_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df, _ = load_merged_target()
    df = build_features(df)
    df, zonal_feats = add_zonal_features(df, zonal_path)
    candidate_cols = FEATURE_COLS + zonal_feats

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

        cand_pred, base_pred = fit_residual_predict(train, test, candidate_cols)
        cols = ["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"]
        base = test[cols].copy()
        base["model"] = BASELINE
        base["y_pred"] = base_pred
        predictions.append(base)

        cand = test[cols].copy()
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
    deltas = np.asarray(deltas)
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

    summary.to_csv(out_dir / "summary.csv", index=False)
    per_cut.to_csv(out_dir / "per_cut_comparison.csv", index=False)
    preds.to_csv(out_dir / "predictions.csv", index=False)
    manifest = {
        "experiment_id": "EXP-2026-07-08-05",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "zonal_snapshot": str(zonal_path),
        "zonal_snapshot_sha256": sha256_file(zonal_path),
        "target_snapshot_sha256": sha256_file(PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"),
        "test_months": [f"{y}-{m:02d}" for y, m in TEST_MONTHS],
        "zonal_feature_count": len(zonal_feats),
        "baseline": {"model": BASELINE, "wape": float(baseline_row["all_wape"]), "outnov_wape": float(baseline_row["outnov_wape"])},
        "candidate": {"model": CANDIDATE, "wape": float(candidate_row["all_wape"]), "outnov_wape": float(candidate_row["outnov_wape"])},
        "delta_wape_candidate_minus_baseline": float(candidate_row["all_wape"] - baseline_row["all_wape"]),
        "candidate_wins_of_24": wins,
        "bootstrap_delta_wape_ci95": [float(ci[0]), float(ci[1])],
        "p_candidate_better": p_better,
        "decision": decision,
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== EXP-05: ERA5 zonal residual vs climatology champion ===")
    print(summary.to_string(index=False))
    print(f"Vitórias do candidato: {wins}/24")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidato melhor)={p_better:.3f}")
    print(f"DECISÃO: {decision}")
    return manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp05_era5_zonal_candidate.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--zonal-path", type=Path, default=DEFAULT_ZONAL_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    run(args.zonal_path, args.out_dir)


if __name__ == "__main__":
    main()
