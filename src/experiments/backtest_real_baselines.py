"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/backtest_real_baselines.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.models.baselines import get_all_baselines  # noqa: E402
from src.utils.metrics import wape, mae, rmse  # noqa: E402

SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2"
OUT_DIR = PROJECT_ROOT / "outputs" / "real_backtest_v2"

TEST_MONTHS = [(y, m) for y in (2023, 2024) for m in range(1, 13)]
MIN_TRAIN_MONTHS = 60  # município precisa de >=5 anos de histórico no treino


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/backtest_real_baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_merged_target() -> pd.DataFrame:
    """Carrega a etapa `load merged target` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/backtest_real_baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    merged = pd.read_csv(SNAPSHOT / "inpe_monthly_merged.csv")
    merged = merged.sort_values(["geocodigo", "ano", "mes"]).reset_index(drop=True)

    # série temporal contínua exigida para lags: verificar buracos
    merged["period"] = pd.PeriodIndex(
        pd.to_datetime(merged["ano"].astype(str) + "-" + merged["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    gaps = []
    for geo, g in merged.groupby("geocodigo"):
        expected = pd.period_range(g["period"].min(), g["period"].max(), freq="M")
        missing = set(expected) - set(g["period"])
        if missing:
            gaps.append((geo, len(missing)))
    if gaps:
        # reindexar preenchendo meses faltantes como NaN (não zero!) — fontes
        # diferentes podem deixar buracos; lags sobre NaN viram NaN e o mês
        # não entra no treino/teste.
        full = []
        for geo, g in merged.groupby("geocodigo"):
            expected = pd.period_range(g["period"].min(), g["period"].max(), freq="M")
            g = g.set_index("period").reindex(expected)
            g["geocodigo"] = geo
            g["municipio_ibge"] = g["municipio_ibge"].ffill().bfill()
            g["uf"] = g["uf"].ffill().bfill()
            g.index.name = "period"
            full.append(g.reset_index())
        merged = pd.concat(full, ignore_index=True)
        merged["ano"] = merged["period"].dt.year
        merged["mes"] = merged["period"].dt.month
    return merged, gaps


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Constroi a etapa `build features` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/backtest_real_baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = df.sort_values(["geocodigo", "period"]).reset_index(drop=True)
    g = df.groupby("geocodigo")["fire_count"]
    for lag in (1, 2, 3, 6, 12):
        df[f"fire_count_lag{lag}"] = g.shift(lag)
    df["fire_roll3"] = g.transform(lambda x: x.shift(1).rolling(3, min_periods=3).mean())
    df["fire_roll6"] = g.transform(lambda x: x.shift(1).rolling(6, min_periods=6).mean())
    df["same_month_last_year"] = df["fire_count_lag12"]
    df["mes_sin"] = np.sin(2 * np.pi * df["mes"] / 12)
    df["mes_cos"] = np.cos(2 * np.pi * df["mes"] / 12)
    # identidade compatível com os baselines existentes
    df["municipio_id"] = df["geocodigo"]
    df["estado"] = df["uf"]
    return df


FEATURE_COLS = [
    "fire_count_lag1", "fire_count_lag2", "fire_count_lag3",
    "fire_count_lag6", "fire_count_lag12",
    "fire_roll3", "fire_roll6", "same_month_last_year",
    "mes_sin", "mes_cos", "mes", "municipio_id",
]


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/backtest_real_baselines.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    df = build_features(df)

    monthly_metrics = []
    predictions = []
    failures = []

    for (ty, tm) in TEST_MONTHS:
        cut = pd.Period(f"{ty}-{tm:02d}", freq="M")
        train = df[(df["period"] < cut) & df["fire_count"].notna()]
        test = df[(df["period"] == cut) & df["fire_count"].notna()]
        # exigir histórico mínimo e features completas de lag12 no teste
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()]
        train = train[train["fire_count_lag12"].notna()]
        if len(test) == 0 or len(train) == 0:
            continue

        y_true = test["fire_count"].values
        models = get_all_baselines()
        for model in models:
            try:
                model.fit(train, FEATURE_COLS, "fire_count")
                y_pred = np.asarray(model.predict(test), dtype=float)
            except Exception as e:  # baseline quebrado reprova a execução
                failures.append({"model": model.name, "cut": str(cut), "error": repr(e)})
                continue
            monthly_metrics.append(
                {
                    "cut": str(cut), "ano": ty, "mes": tm, "model": model.name,
                    "n": len(test),
                    "wape": wape(y_true, y_pred),
                    "mae": mae(y_true, y_pred),
                    "rmse": rmse(y_true, y_pred),
                    "y_sum": float(y_true.sum()),
                    "pred_sum": float(y_pred.sum()),
                }
            )
            pr = test[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "target_source"]].copy()
            pr["model"] = model.name
            pr["y_pred"] = y_pred
            predictions.append(pr)

    if failures:
        pd.DataFrame(failures).to_csv(OUT_DIR / "baseline_failures.csv", index=False)
        raise RuntimeError(f"{len(failures)} execuções de baseline falharam — ver baseline_failures.csv")

    mm = pd.DataFrame(monthly_metrics)
    preds = pd.concat(predictions, ignore_index=True)

    # agregado: WAPE agregado (soma dos erros / soma dos observados), geral e out-nov
    def agg_block(p: pd.DataFrame) -> dict:
        """Executa a etapa `agg block` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/backtest_real_baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        return {
            "wape": wape(p["fire_count"].values, p["y_pred"].values),
            "mae": mae(p["fire_count"].values, p["y_pred"].values),
            "n": len(p),
            "y_total": int(p["fire_count"].sum()),
        }

    rows = []
    for model, p in preds.groupby("model"):
        r = {"model": model}
        r.update({f"all_{k}": v for k, v in agg_block(p).items()})
        crit = p[p["mes"].isin([10, 11])]
        r.update({f"outnov_{k}": v for k, v in agg_block(crit).items()})
        rows.append(r)
    summary = pd.DataFrame(rows).sort_values("all_wape")

    mm.to_csv(OUT_DIR / "backtest_monthly_metrics.csv", index=False)
    summary.to_csv(OUT_DIR / "backtest_summary.csv", index=False)
    preds.to_csv(OUT_DIR / "predictions.csv", index=False)

    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "snapshot": SNAPSHOT.name,
        "snapshot_monthly_sha256": sha256_file(SNAPSHOT / "inpe_monthly_merged.csv"),
        "test_months": [f"{y}-{m:02d}" for y, m in TEST_MONTHS],
        "min_train_months": MIN_TRAIN_MONTHS,
        "feature_cols": FEATURE_COLS,
        "series_gaps_reindexed": [{"geocodigo": int(g), "missing_months": int(n)} for g, n in gaps],
        "n_predictions": int(len(preds)),
        "models": sorted(preds["model"].unique().tolist()),
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("=== Backtest walk-forward em DADOS REAIS (2023-2024, h=1) ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
