"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g4_chapada_spatial_slice_report.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.metrics import mae, wape  # noqa: E402

PRED_PATH = PROJECT_ROOT / "outputs" / "real_backtest_v2" / "predictions.csv"
WEIGHTS_PATH = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "g4_chapada_spatial_slice"
CHAMPION = "climatology_municipal"
DRY_MONTHS = {8, 9, 10, 11, 12}
ABS_WAPE_MARGIN = 0.10


def _metric_row(label: str, frame: pd.DataFrame) -> dict:
    """Executa a etapa `metric row` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g4_chapada_spatial_slice_report.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if frame.empty:
        return {
            "slice": label,
            "n": 0,
            "n_municipios": 0,
            "volume_real": 0.0,
            "volume_predito": 0.0,
            "wape": float("nan"),
            "mae": float("nan"),
            "bias_total": float("nan"),
        }
    return {
        "slice": label,
        "n": int(len(frame)),
        "n_municipios": int(frame["geocodigo"].nunique()),
        "volume_real": float(frame["fire_count"].sum()),
        "volume_predito": float(frame["y_pred"].sum()),
        "wape": float(wape(frame["fire_count"].values, frame["y_pred"].values)),
        "mae": float(mae(frame["fire_count"].values, frame["y_pred"].values)),
        "bias_total": float(np.sum(frame["y_pred"].values - frame["fire_count"].values)),
    }


def run(
    pred_path: Path = PRED_PATH,
    weights_path: Path = WEIGHTS_PATH,
    champion: str = CHAMPION,
    out_dir: Path = OUT_DIR,
) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g4_chapada_spatial_slice_report.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)

    preds = pd.read_csv(pred_path)
    weights = pd.read_csv(weights_path)
    chapada_geocodigos = set(weights["geocodigo"].astype(int).unique())

    champ = preds[preds["model"] == champion].copy()
    if champ.empty:
        raise ValueError(f"No predictions for champion '{champion}' in {pred_path}")

    champ["geocodigo"] = champ["geocodigo"].astype(int)
    champ["spatial_slice"] = np.where(
        champ["geocodigo"].isin(chapada_geocodigos),
        "chapada_araripe_cariri",
        "fora_chapada_universo",
    )
    champ["regime"] = np.where(champ["mes"].isin(DRY_MONTHS), "dry_aug_dec", "other_months")

    overall = _metric_row("overall", champ)
    overall_dry = _metric_row("overall_dry_aug_dec", champ[champ["regime"] == "dry_aug_dec"])

    by_region = pd.DataFrame(
        [_metric_row(region, group) for region, group in champ.groupby("spatial_slice", sort=True)]
    ).sort_values("slice")
    by_region_regime = pd.DataFrame(
        [
            _metric_row(f"{region}__{regime}", group)
            | {"spatial_slice": region, "regime": regime}
            for (region, regime), group in champ.groupby(["spatial_slice", "regime"], sort=True)
        ]
    ).sort_values(["spatial_slice", "regime"])

    chapada = by_region[by_region["slice"] == "chapada_araripe_cariri"]
    if chapada.empty:
        raise ValueError("No champion predictions overlap the Chapada/Cariri geocodigo set")
    chapada_row = chapada.iloc[0].to_dict()

    chapada_dry = by_region_regime[
        (by_region_regime["spatial_slice"] == "chapada_araripe_cariri")
        & (by_region_regime["regime"] == "dry_aug_dec")
    ]
    chapada_dry_row = chapada_dry.iloc[0].to_dict() if not chapada_dry.empty else _metric_row("chapada_dry_aug_dec", champ.iloc[0:0])

    regional_wape_delta = float(chapada_row["wape"] - overall["wape"])
    dry_wape_delta = float(chapada_dry_row["wape"] - overall_dry["wape"])
    regional_violation = bool(regional_wape_delta > ABS_WAPE_MARGIN)
    dry_violation = bool(dry_wape_delta > ABS_WAPE_MARGIN)
    gate = "PASS" if not regional_violation and not dry_violation else "FAIL"

    by_region.to_csv(out_dir / "by_region.csv", index=False)
    by_region_regime.to_csv(out_dir / "by_region_regime.csv", index=False)

    manifest = {
        "source_predictions": str(pred_path),
        "source_chapada_weights": str(weights_path),
        "champion": champion,
        "chapada_geocodigos_in_weights": len(chapada_geocodigos),
        "chapada_geocodigos_in_predictions": int(
            champ[champ["spatial_slice"] == "chapada_araripe_cariri"]["geocodigo"].nunique()
        ),
        "non_chapada_geocodigos_in_predictions": int(
            champ[champ["spatial_slice"] == "fora_chapada_universo"]["geocodigo"].nunique()
        ),
        "overall": overall,
        "overall_dry_aug_dec": overall_dry,
        "chapada_araripe_cariri": chapada_row,
        "chapada_araripe_cariri_dry_aug_dec": chapada_dry_row,
        "regional_wape_delta_vs_overall": regional_wape_delta,
        "dry_wape_delta_vs_overall_dry": dry_wape_delta,
        "absolute_wape_margin": ABS_WAPE_MARGIN,
        "regional_violation": regional_violation,
        "dry_violation": dry_violation,
        "gate_G4_chapada_slice": gate,
        "limitation": (
            "Slice audit over existing walk-forward predictions; not a leave-region-out retraining protocol "
            "because the current champion is municipality-specific."
        ),
    }
    (out_dir / "g4_chapada_report.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=== G4 Chapada/Cariri spatial slice audit ===")
    print(f"Overall WAPE: {overall['wape']:.4f}")
    print(f"Chapada/Cariri WAPE: {chapada_row['wape']:.4f} | delta vs overall: {regional_wape_delta:+.4f}")
    print(
        "Chapada/Cariri dry WAPE: "
        f"{chapada_dry_row['wape']:.4f} | delta vs overall dry: {dry_wape_delta:+.4f}"
    )
    print(f"GATE G4 CHAPADA SLICE: {gate}")
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-path", type=Path, default=PRED_PATH)
    parser.add_argument("--weights-path", type=Path, default=WEIGHTS_PATH)
    parser.add_argument("--champion", type=str, default=CHAMPION)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    run(
        pred_path=args.pred_path,
        weights_path=args.weights_path,
        champion=args.champion,
        out_dir=args.out_dir,
    )
