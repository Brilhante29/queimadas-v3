"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/realidade_vs_previsto_diagnostico.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.metrics import wape  # noqa: E402

DEFAULT_PRED_PATH = PROJECT_ROOT / "outputs" / "real_backtest_v2" / "predictions.csv"
DEFAULT_OUT_DIR = PROJECT_ROOT / "outputs" / "realidade_vs_previsto"
DEFAULT_CHAMPION = "climatology_municipal"
VOLUME_BINS = [-0.1, 0, 3, 10, 30, 100000]
VOLUME_LABELS = ["0", "1-3", "4-10", "11-30", "30+"]


def run(pred_path: Path = DEFAULT_PRED_PATH, champion: str = DEFAULT_CHAMPION, out_dir: Path = DEFAULT_OUT_DIR) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/realidade_vs_previsto_diagnostico.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    preds = pd.read_csv(pred_path)
    c = preds[preds["model"] == champion].copy()
    if c.empty:
        raise ValueError(f"Nenhuma predição do modelo '{champion}' encontrada em {pred_path}")

    c["resid"] = c["fire_count"] - c["y_pred"]
    c["abs_err"] = c["resid"].abs()
    c["band"] = pd.cut(c["fire_count"], bins=VOLUME_BINS, labels=VOLUME_LABELS)

    pearson = float(c["fire_count"].corr(c["y_pred"], method="pearson"))
    spearman = float(c["fire_count"].corr(c["y_pred"], method="spearman"))

    total_abs_err = float(c["abs_err"].sum())
    total_actual = float(c["fire_count"].sum())
    overall_wape = total_abs_err / total_actual if total_actual else float("nan")

    by_band = c.groupby("band", observed=True).agg(
        n=("fire_count", "size"),
        actual_sum=("fire_count", "sum"),
        pred_sum=("y_pred", "sum"),
        mean_bias=("resid", "mean"),
        abs_err_sum=("abs_err", "sum"),
    ).reset_index()
    by_band["wape_share_of_total_error"] = by_band["abs_err_sum"] / total_abs_err
    by_band["pred_vs_actual_ratio"] = by_band["pred_sum"] / by_band["actual_sum"].replace(0, np.nan)
    by_band.to_csv(out_dir / "by_volume_band.csv", index=False)

    high_bands = by_band[by_band["band"].isin(["11-30", "30+"])]
    high_share_of_predictions = float(high_bands["n"].sum() / len(c))
    high_share_of_error = float(high_bands["abs_err_sum"].sum() / total_abs_err)

    manifest = {
        "source": str(pred_path),
        "champion": champion,
        "n_predictions": int(len(c)),
        "overall_wape": overall_wape,
        "pearson_correlation_real_vs_previsto": pearson,
        "spearman_rank_correlation_real_vs_previsto": spearman,
        "mean_bias_previsto_minus_real": float(c["resid"].mean()) * -1,
        "high_volume_predictions_share": high_share_of_predictions,
        "high_volume_error_share": high_share_of_error,
        "by_volume_band": by_band.assign(band=by_band["band"].astype(str)).to_dict("records"),
        "interpretation": (
            f"Correlacao de Pearson {pearson:.3f} e Spearman {spearman:.3f} indicam que o "
            f"modelo captura o padrao/ranking real de risco relativamente bem, mesmo com "
            f"WAPE de {overall_wape:.3f}. Isso acontece porque {high_share_of_predictions*100:.1f}% "
            f"das previsoes (meses de volume alto/extremo) respondem por "
            f"{high_share_of_error*100:.1f}% do erro absoluto total do WAPE. O WAPE penaliza "
            f"fortemente a magnitude absoluta do erro nesses poucos meses extremos, mesmo "
            f"quando a maioria das previsoes (meses de baixo/medio volume) tem vies pequeno."
        ),
    }
    (out_dir / "diagnostico.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"=== Realidade vs previsto — {champion} ===")
    print(f"Pearson: {pearson:.4f} | Spearman: {spearman:.4f}")
    print(by_band.to_string(index=False))
    print(f"\n{high_share_of_predictions*100:.1f}% das previsões (volume >=11) explicam {high_share_of_error*100:.1f}% do erro total.")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-path", type=Path, default=DEFAULT_PRED_PATH)
    parser.add_argument("--champion", type=str, default=DEFAULT_CHAMPION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    run(pred_path=args.pred_path, champion=args.champion, out_dir=args.out_dir)
