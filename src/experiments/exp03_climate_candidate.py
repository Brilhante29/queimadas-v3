"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp03_climate_candidate.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import hashlib
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_inpe_local import load_ibge_lookup, normalize_name  # noqa: E402
from src.experiments.backtest_real_baselines import (  # noqa: E402
    FEATURE_COLS, MIN_TRAIN_MONTHS, TEST_MONTHS, build_features, load_merged_target,
)
from src.models.baselines import get_all_baselines  # noqa: E402
from src.utils.metrics import mae, wape  # noqa: E402

ERA5_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "era5_openmeteo_v1"
NDVI_CSV = REPO_ROOT / "NDVI_Ceara_Municipios_Mensal_FINAL.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "exp03_climate_candidate"

CLIMATE_BASE_VARS = [
    "precipitation_sum", "vapour_pressure_deficit_max",
    "soil_moisture_0_to_7cm_mean", "soil_moisture_7_to_28cm_mean",
    "dry_days", "dry_spell_max", "et0_fao_evapotranspiration",
    "temperature_2m_max", "relative_humidity_2m_mean",
]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp03_climate_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_climate() -> pd.DataFrame:
    """Carrega a etapa `load climate` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp03_climate_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    path = ERA5_SNAPSHOT / "era5_monthly.csv"
    if not path.exists():
        raise FileNotFoundError(f"Snapshot ERA5 ausente: {path} (fail closed)")
    return pd.read_csv(path)


def load_ndvi() -> pd.DataFrame:
    """Carrega a etapa `load ndvi` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp03_climate_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    lookup = load_ibge_lookup()
    df = pd.read_csv(NDVI_CSV)
    df = df.rename(columns={"city": "cidade", "month": "mes", "year": "ano"})
    df["mes"] = df["mes"].astype(int)
    df["ano"] = df["ano"].astype(int)
    df.loc[df["ndvi"] <= 0, "ndvi"] = np.nan  # zeros são meses sem composição válida
    df["key"] = df["cidade"].map(normalize_name)
    geo = {k[0]: v[0] for k, v in lookup.items() if k[1] == "CE"}
    df["geocodigo"] = df["key"].map(geo)
    unmapped = df.loc[df["geocodigo"].isna(), "cidade"].unique().tolist()
    df = df.dropna(subset=["geocodigo"])
    df["geocodigo"] = df["geocodigo"].astype(int)
    ndvi = df.groupby(["geocodigo", "ano", "mes"], as_index=False)["ndvi"].mean()
    return ndvi, unmapped


def add_exog_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list, list]:
    """Executa a etapa `add exog features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp03_climate_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    climate = load_climate()
    ndvi, ndvi_unmapped = load_ndvi()

    df = df.merge(climate, on=["geocodigo", "ano", "mes"], how="left")
    df = df.merge(ndvi, on=["geocodigo", "ano", "mes"], how="left")
    df = df.sort_values(["geocodigo", "period"]).reset_index(drop=True)

    climate_feats = []
    for var in CLIMATE_BASE_VARS:
        g = df.groupby("geocodigo")[var]
        for lag in (1, 2, 3):
            col = f"{var}_lag{lag}"
            df[col] = g.shift(lag)
            climate_feats.append(col)
        col = f"{var}_roll3"
        df[col] = g.transform(lambda x: x.shift(1).rolling(3, min_periods=3).mean())
        climate_feats.append(col)
    for var in ["precipitation_sum", "soil_moisture_28_to_100cm_mean"]:
        g = df.groupby("geocodigo")[var]
        col = f"{var}_roll6"
        df[col] = g.transform(lambda x: x.shift(1).rolling(6, min_periods=6).mean())
        climate_feats.append(col)

    ndvi_feats = []
    g = df.groupby("geocodigo")["ndvi"]
    for lag in (1, 2):
        col = f"ndvi_lag{lag}"
        df[col] = g.shift(lag)
        ndvi_feats.append(col)
    df["ndvi_roll3"] = g.transform(lambda x: x.shift(1).rolling(3, min_periods=3).mean())
    ndvi_feats.append("ndvi_roll3")

    # AUDITORIA AS-OF estrutural: nenhuma coluna de feature exógena pode ser
    # idêntica ao valor bruto do próprio mês (verificação amostral).
    sample = df.dropna(subset=["precipitation_sum", "precipitation_sum_lag1"]).sample(
        n=min(500, len(df)), random_state=0
    )
    if np.allclose(sample["precipitation_sum_lag1"], sample["precipitation_sum"]):
        raise AssertionError("Violação as-of: lag1 igual ao mês corrente")
    return df, climate_feats, ndvi_feats, ndvi_unmapped


def fit_predict_gbm(train, test, cols):
    """Executa a etapa `fit predict gbm` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp03_climate_candidate.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=200, random_state=42)
    model.fit(train[cols], train["fire_count"])
    return np.maximum(model.predict(test[cols]), 0)


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp03_climate_candidate.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, _ = load_merged_target()
    df = build_features(df)
    df, climate_feats, ndvi_feats, ndvi_unmapped = add_exog_features(df)

    candidates = {
        "gbm_target_only": FEATURE_COLS,
        "gbm_climate": FEATURE_COLS + climate_feats,
        "gbm_climate_ndvi": FEATURE_COLS + climate_feats + ndvi_feats,
    }

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

        # baselines no mesmo protocolo
        for model in get_all_baselines():
            model.fit(train, FEATURE_COLS, "fire_count")
            y_pred = np.asarray(model.predict(test), dtype=float)
            pr = test[["geocodigo", "ano", "mes", "fire_count"]].copy()
            pr["model"] = model.name
            pr["y_pred"] = y_pred
            predictions.append(pr)

        # candidatos
        for name, cols in candidates.items():
            y_pred = fit_predict_gbm(train, test, cols)
            pr = test[["geocodigo", "ano", "mes", "fire_count"]].copy()
            pr["model"] = name
            pr["y_pred"] = y_pred
            predictions.append(pr)

    preds = pd.concat(predictions, ignore_index=True)
    preds["cut"] = preds["ano"].astype(str) + "-" + preds["mes"].astype(str).str.zfill(2)

    # resumo
    rows = []
    for model, p in preds.groupby("model"):
        crit = p[p["mes"].isin([10, 11])]
        rows.append({
            "model": model,
            "all_wape": wape(p["fire_count"].values, p["y_pred"].values),
            "all_mae": mae(p["fire_count"].values, p["y_pred"].values),
            "outnov_wape": wape(crit["fire_count"].values, crit["y_pred"].values),
            "n": len(p),
        })
    summary = pd.DataFrame(rows).sort_values("all_wape").reset_index(drop=True)

    baseline_names = [m.name for m in get_all_baselines()]
    best_baseline = summary[summary["model"].isin(baseline_names)].iloc[0]
    best_candidate = summary[summary["model"].isin(candidates.keys())].iloc[0]

    # vitórias por corte
    bb = preds[preds["model"] == best_baseline["model"]]
    bc = preds[preds["model"] == best_candidate["model"]]
    per_cut = []
    for cut in sorted(preds["cut"].unique()):
        a = bb[bb["cut"] == cut]
        b = bc[bc["cut"] == cut]
        per_cut.append({
            "cut": cut,
            "wape_baseline": wape(a["fire_count"].values, a["y_pred"].values),
            "wape_candidate": wape(b["fire_count"].values, b["y_pred"].values),
        })
    per_cut = pd.DataFrame(per_cut)
    per_cut["candidate_wins"] = per_cut["wape_candidate"] < per_cut["wape_baseline"]
    wins = int(per_cut["candidate_wins"].sum())

    # bootstrap por corte (1000 réplicas): delta WAPE = candidato - baseline
    rng = np.random.default_rng(42)
    cuts = per_cut["cut"].values
    deltas = []
    bb_by_cut = {c: g for c, g in bb.groupby("cut")}
    bc_by_cut = {c: g for c, g in bc.groupby("cut")}
    for _ in range(1000):
        sample = rng.choice(cuts, size=len(cuts), replace=True)
        a = pd.concat([bb_by_cut[c] for c in sample])
        b = pd.concat([bc_by_cut[c] for c in sample])
        deltas.append(
            wape(b["fire_count"].values, b["y_pred"].values)
            - wape(a["fire_count"].values, a["y_pred"].values)
        )
    deltas = np.array(deltas)
    ci = np.percentile(deltas, [2.5, 97.5])
    p_better = float((deltas < 0).mean())

    decision_reject = (
        best_candidate["all_wape"] >= best_baseline["all_wape"] or wins < 13
    )
    decision = "REJECT" if decision_reject else "PROMOTE_CANDIDATE_STAGE"

    summary.to_csv(OUT_DIR / "summary.csv", index=False)
    per_cut.to_csv(OUT_DIR / "per_cut_comparison.csv", index=False)
    preds.to_csv(OUT_DIR / "predictions.csv", index=False)

    manifest = {
        "experiment_id": "EXP-2026-07-02-03",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "target_snapshot_sha256": sha256_file(
            PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
        ),
        "climate_snapshot_sha256": sha256_file(ERA5_SNAPSHOT / "era5_monthly.csv"),
        "ndvi_source": str(NDVI_CSV.name),
        "ndvi_unmapped_cities": ndvi_unmapped,
        "test_months": [f"{y}-{m:02d}" for y, m in TEST_MONTHS],
        "candidates": {k: len(v) for k, v in candidates.items()},
        "best_baseline": {"model": best_baseline["model"], "wape": float(best_baseline["all_wape"])},
        "best_candidate": {"model": best_candidate["model"], "wape": float(best_candidate["all_wape"])},
        "candidate_wins_of_24": wins,
        "bootstrap_delta_wape_ci95": [float(ci[0]), float(ci[1])],
        "p_candidate_better": p_better,
        "decision": decision,
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("=== EXP-03: candidato clima/NDVI vs baselines (dados reais, 24 cortes) ===")
    print(summary.to_string(index=False))
    print(f"\nMelhor baseline : {best_baseline['model']} WAPE={best_baseline['all_wape']:.4f}")
    print(f"Melhor candidato: {best_candidate['model']} WAPE={best_candidate['all_wape']:.4f}")
    print(f"Vitórias do candidato: {wins}/24")
    print(f"Bootstrap delta WAPE CI95: [{ci[0]:+.4f}, {ci[1]:+.4f}]  P(candidato melhor)={p_better:.3f}")
    print(f"DECISÃO: {decision}")


if __name__ == "__main__":
    main()
