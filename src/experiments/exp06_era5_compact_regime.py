"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp06_era5_compact_regime.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

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
OUT_DIR = PROJECT_ROOT / "outputs" / "exp06_era5_compact_regime"
BASELINE = "climatology_municipal"
CANDIDATE = "climatology_ridge_era5_compact_regime"
DRY_MONTHS = {8, 9, 10, 11, 12}

CANDIDATE_COLS = [
    "precip_anom_lag1",
    "precip_anom_roll3",
    "dry_spell_change_lag1",
    "vpd_max_lag1",
    "precip_anom_lag1_x_dry",
    "dry_spell_change_lag1_x_dry",
]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp06_era5_compact_regime.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_zonal(zonal_path: Path) -> pd.DataFrame:
    """Carrega a etapa `load zonal` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp06_era5_compact_regime.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not zonal_path.exists():
        raise FileNotFoundError(f"Snapshot ERA5 zonal ausente: {zonal_path} (fail closed)")
    zonal = pd.read_csv(zonal_path)
    required = {
        "geocodigo", "ano", "mes", "era5_weight_covered",
        "precipitation_sum_zonal", "dry_spell_max_zonal",
        "vapour_pressure_deficit_max_zonal",
    }
    missing = required - set(zonal.columns)
    if missing:
        raise ValueError(f"Snapshot ERA5 zonal sem colunas obrigatórias: {sorted(missing)}")
    if float(zonal["era5_weight_covered"].min()) < 0.99:
        raise ValueError("Cobertura zonal insuficiente: peso coberto mínimo < 0.99")
    return zonal


def add_raw_zonal(df: pd.DataFrame, zonal_path: Path) -> pd.DataFrame:
    """Executa a etapa `add raw zonal` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp06_era5_compact_regime.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    zonal = load_zonal(zonal_path)
    keep = [
        "geocodigo", "ano", "mes",
        "precipitation_sum_zonal", "dry_spell_max_zonal", "vapour_pressure_deficit_max_zonal",
        "era5_cells_used", "era5_weight_covered",
    ]
    df = df.merge(zonal[keep], on=["geocodigo", "ano", "mes"], how="left")
    df = df.sort_values(["geocodigo", "period"]).reset_index(drop=True)

    g = df.groupby("geocodigo")["precipitation_sum_zonal"]
    df["precipitation_sum_zonal_lag1"] = g.shift(1)
    df["precipitation_sum_zonal_roll3"] = g.transform(lambda x: x.shift(1).rolling(3, min_periods=3).mean())
    g2 = df.groupby("geocodigo")["dry_spell_max_zonal"]
    df["dry_spell_max_zonal_lag1"] = g2.shift(1)
    g3 = df.groupby("geocodigo")["vapour_pressure_deficit_max_zonal"]
    df["vapour_pressure_deficit_max_zonal_lag1"] = g3.shift(1)

    sample = df.dropna(subset=["precipitation_sum_zonal", "precipitation_sum_zonal_lag1"])
    if len(sample) and np.allclose(sample["precipitation_sum_zonal_lag1"], sample["precipitation_sum_zonal"]):
        raise AssertionError("Violação as-of: precipitation lag1 igual ao mês corrente")

    df["mes_lag1"] = ((df["mes"] - 2) % 12) + 1
    df["is_dry_month"] = df["mes"].isin(DRY_MONTHS).astype(float)
    return df


def add_regime_features(train: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `add regime features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp06_era5_compact_regime.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    clim_precip = train.groupby(["geocodigo", "mes"])["precipitation_sum_zonal"].mean()
    clim_precip_roll3 = train.groupby(["geocodigo", "mes"])["precipitation_sum_zonal_roll3"].mean()
    clim_dry_spell = train.groupby(["geocodigo", "mes"])["dry_spell_max_zonal"].mean()

    frame = frame.copy()
    key_lag1 = list(zip(frame["geocodigo"], frame["mes_lag1"]))
    frame["_clim_precip_lag1"] = pd.Series(key_lag1, index=frame.index).map(clim_precip.to_dict())
    frame["_clim_precip_roll3_lag1"] = pd.Series(key_lag1, index=frame.index).map(clim_precip_roll3.to_dict())
    frame["_clim_dry_spell_lag1"] = pd.Series(key_lag1, index=frame.index).map(clim_dry_spell.to_dict())

    frame["precip_anom_lag1"] = frame["precipitation_sum_zonal_lag1"] - frame["_clim_precip_lag1"]
    frame["precip_anom_roll3"] = frame["precipitation_sum_zonal_roll3"] - frame["_clim_precip_roll3_lag1"]
    frame["dry_spell_change_lag1"] = frame["dry_spell_max_zonal_lag1"] - frame["_clim_dry_spell_lag1"]
    frame["vpd_max_lag1"] = frame["vapour_pressure_deficit_max_zonal_lag1"]
    frame["precip_anom_lag1_x_dry"] = frame["precip_anom_lag1"] * frame["is_dry_month"]
    frame["dry_spell_change_lag1_x_dry"] = frame["dry_spell_change_lag1"] * frame["is_dry_month"]

    frame = frame.drop(columns=["_clim_precip_lag1", "_clim_precip_roll3_lag1", "_clim_dry_spell_lag1"])
    return frame


def fit_residual_predict(train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Executa a etapa `fit residual predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp06_era5_compact_regime.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    baseline = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
    train_base = np.asarray(baseline.predict(train), dtype=float)
    test_base = np.asarray(baseline.predict(test), dtype=float)
    residual = train["fire_count"].to_numpy(dtype=float) - train_base

    med = train[CANDIDATE_COLS].median(numeric_only=True).fillna(0)
    train_x = train[CANDIDATE_COLS].fillna(med)
    test_x = test[CANDIDATE_COLS].fillna(med)

    scaler = StandardScaler()
    train_xs = scaler.fit_transform(train_x)
    test_xs = scaler.transform(test_x)

    model = Ridge(alpha=50.0, random_state=42)
    model.fit(train_xs, residual)
    correction = model.predict(test_xs)
    return np.maximum(test_base + correction, 0), test_base


def run(zonal_path: Path = DEFAULT_ZONAL_PATH, out_dir: Path = OUT_DIR) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp06_era5_compact_regime.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    df, _ = load_merged_target()
    df = build_features(df)
    df = add_raw_zonal(df, zonal_path)

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

        train_r = add_regime_features(train, train)
        test_r = add_regime_features(train, test)

        cand_pred, base_pred = fit_residual_predict(train_r, test_r)
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
    )
    decision = "REJECT" if reject else "PROMOTE"

    summary.to_csv(out_dir / "summary.csv", index=False)
    per_cut.to_csv(out_dir / "per_cut_comparison.csv", index=False)
    preds.to_csv(out_dir / "predictions.csv", index=False)
    manifest = {
        "experiment_id": "EXP-2026-07-08-06",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "zonal_snapshot": str(zonal_path),
        "zonal_snapshot_sha256": sha256_file(zonal_path),
        "target_snapshot_sha256": sha256_file(PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"),
        "test_months": [f"{y}-{m:02d}" for y, m in TEST_MONTHS],
        "candidate_feature_count": len(CANDIDATE_COLS),
        "candidate_features": CANDIDATE_COLS,
        "corrector_model": "Ridge(alpha=50.0) on standardized compact regime features",
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
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== EXP-06: ERA5 zonal compacto por regime seco (Ridge) vs climatology champion ===")
    print(summary.to_string(index=False))
    print(f"Vitorias do candidato: {wins}/{len(per_cut)} (diagnostico, nao decide promocao)")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidato melhor)={p_better:.3f}")
    print(f"DECISAO: {decision}")
    return manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp06_era5_compact_regime.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--zonal-path", type=Path, default=DEFAULT_ZONAL_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    run(args.zonal_path, args.out_dir)


if __name__ == "__main__":
    main()
