"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g4_spatial_robustness_report.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

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
OUT_DIR = PROJECT_ROOT / "outputs" / "g4_spatial_robustness"
CHAMPION = "climatology_municipal"
DRY_MONTHS = {8, 9, 10, 11, 12}
MIN_VOLUME_FOR_FLAG = 10
MUNICIPIO_WAPE_MULTIPLE = 2.0
REGIME_WAPE_ABS_MARGIN = 0.10


def run(pred_path: Path = PRED_PATH, champion: str = CHAMPION, out_dir: Path = OUT_DIR) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g4_spatial_robustness_report.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    preds = pd.read_csv(pred_path)
    champ = preds[preds["model"] == champion].copy()
    if champ.empty:
        raise ValueError(f"Nenhuma predição do champion '{champion}' encontrada em {pred_path}")

    overall_wape = wape(champ["fire_count"].values, champ["y_pred"].values)
    overall_mae = mae(champ["fire_count"].values, champ["y_pred"].values)

    # Por município
    rows = []
    for geo, g in champ.groupby("geocodigo"):
        rows.append(
            {
                "geocodigo": int(geo),
                "municipio_ibge": g["municipio_ibge"].iloc[0],
                "n": len(g),
                "volume_real": float(g["fire_count"].sum()),
                "wape": wape(g["fire_count"].values, g["y_pred"].values),
                "mae": mae(g["fire_count"].values, g["y_pred"].values),
            }
        )
    by_muni = pd.DataFrame(rows).sort_values("wape", ascending=False).reset_index(drop=True)
    by_muni["flag_regressao"] = (
        (by_muni["wape"] > MUNICIPIO_WAPE_MULTIPLE * overall_wape) & (by_muni["volume_real"] >= MIN_VOLUME_FOR_FLAG)
    )

    # Por regime (seco vs demais) usando o próprio mês previsto
    champ["is_dry"] = champ["mes"].isin(DRY_MONTHS)
    dry = champ[champ["is_dry"]]
    wet = champ[~champ["is_dry"]]
    dry_wape = wape(dry["fire_count"].values, dry["y_pred"].values) if len(dry) else float("nan")
    wet_wape = wape(wet["fire_count"].values, wet["y_pred"].values) if len(wet) else float("nan")
    regime_violation = bool(dry_wape - overall_wape > REGIME_WAPE_ABS_MARGIN)

    # Por faixa de volume (baixo/médio/alto), já usada no relatório atual (>10 = alto)
    low = champ[champ["fire_count"] <= 5]
    mid = champ[(champ["fire_count"] > 5) & (champ["fire_count"] <= 10)]
    high = champ[champ["fire_count"] > 10]
    by_volume = pd.DataFrame(
        [
            {"faixa": "baixo (<=5)", "n": len(low), "wape": wape(low["fire_count"].values, low["y_pred"].values) if len(low) else float("nan")},
            {"faixa": "medio (6-10)", "n": len(mid), "wape": wape(mid["fire_count"].values, mid["y_pred"].values) if len(mid) else float("nan")},
            {"faixa": "alto (>10)", "n": len(high), "wape": wape(high["fire_count"].values, high["y_pred"].values) if len(high) else float("nan")},
        ]
    )

    n_flagged = int(by_muni["flag_regressao"].sum())
    n_muni = len(by_muni)
    flagged_share = n_flagged / n_muni if n_muni else 0.0

    if n_flagged == 0 and not regime_violation:
        gate = "PASS"
    elif flagged_share <= 0.15 and not regime_violation:
        gate = "PARTIAL"
    else:
        gate = "FAIL"

    by_muni.to_csv(out_dir / "by_municipio.csv", index=False)
    by_volume.to_csv(out_dir / "by_volume_band.csv", index=False)

    failure_cases = by_muni[by_muni["flag_regressao"]].to_dict("records")

    manifest = {
        "source": str(pred_path),
        "champion": champion,
        "overall_wape": float(overall_wape),
        "overall_mae": float(overall_mae),
        "n_municipios": n_muni,
        "n_municipios_flagged": n_flagged,
        "municipio_flag_criteria": f"wape > {MUNICIPIO_WAPE_MULTIPLE}x overall AND volume_real >= {MIN_VOLUME_FOR_FLAG}",
        "dry_season_wape": float(dry_wape),
        "wet_season_wape": float(wet_wape),
        "regime_violation": regime_violation,
        "regime_criteria": f"dry_wape - overall_wape > {REGIME_WAPE_ABS_MARGIN}",
        "by_volume_band": by_volume.to_dict("records"),
        "failure_cases": failure_cases,
        "gate_G4": gate,
    }
    (out_dir / "g4_report.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== G4 — Robustez espacial/regime do champion (dados reais) ===")
    print(f"WAPE geral: {overall_wape:.4f} | município mais frágil: {by_muni.iloc[0]['municipio_ibge']} (WAPE {by_muni.iloc[0]['wape']:.4f}, volume {by_muni.iloc[0]['volume_real']:.0f})")
    print(f"Municípios flagados por regressão material: {n_flagged}/{n_muni}")
    print(f"WAPE regime seco (ago-dez): {dry_wape:.4f} | WAPE demais meses: {wet_wape:.4f} | violação: {regime_violation}")
    print(by_volume.to_string(index=False))
    print(f"GATE G4: {gate}")
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-path", type=Path, default=PRED_PATH)
    parser.add_argument("--champion", type=str, default=CHAMPION)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    run(pred_path=args.pred_path, champion=args.champion, out_dir=args.out_dir)
