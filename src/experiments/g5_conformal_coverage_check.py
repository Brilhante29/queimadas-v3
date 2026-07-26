"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g5_conformal_coverage_check.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

PRED_PATH = PROJECT_ROOT / "outputs" / "real_backtest_v2" / "predictions.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "g5_conformal_coverage"
CHAMPION = "climatology_municipal"
DRY_MONTHS = {8, 9, 10, 11, 12}
CALIB_YEAR = 2023
TEST_YEAR = 2024
IC_MIN, IC_MAX = 0.90, 0.98


def run(pred_path: Path = PRED_PATH, champion: str = CHAMPION, out_dir: Path = OUT_DIR) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_coverage_check.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    preds = pd.read_csv(pred_path)
    champ = preds[preds["model"] == champion].copy()
    champ["abs_error"] = (champ["fire_count"] - champ["y_pred"]).abs()

    calib = champ[champ["ano"] == CALIB_YEAR]
    test = champ[champ["ano"] == TEST_YEAR].copy()
    if calib.empty or test.empty:
        raise ValueError("Calibração ou teste vazio — verificar anos disponíveis em predictions.csv")

    p90_calib = float(calib["abs_error"].quantile(0.90))
    test["interval_low"] = (test["y_pred"] - p90_calib).clip(lower=0.0)
    test["interval_high"] = test["y_pred"] + p90_calib
    test["covered"] = (test["fire_count"] >= test["interval_low"]) & (test["fire_count"] <= test["interval_high"])

    overall_coverage = float(test["covered"].mean())

    test["is_dry"] = test["mes"].isin(DRY_MONTHS)
    dry_cov = float(test[test["is_dry"]]["covered"].mean())
    wet_cov = float(test[~test["is_dry"]]["covered"].mean())

    overall_in_range = IC_MIN <= overall_coverage <= IC_MAX
    dry_in_range = IC_MIN <= dry_cov <= IC_MAX
    wet_in_range = IC_MIN <= wet_cov <= IC_MAX

    if overall_in_range and dry_in_range and wet_in_range:
        gate = "PASS"
    elif overall_in_range:
        gate = "PARTIAL"
    else:
        gate = "FAIL"

    per_muni = (
        test.groupby("municipio_ibge")["covered"]
        .agg(["mean", "count"])
        .rename(columns={"mean": "coverage", "count": "n"})
        .sort_values("coverage")
        .reset_index()
    )
    per_muni.to_csv(out_dir / "coverage_by_municipio.csv", index=False)

    manifest = {
        "source": str(pred_path),
        "champion": champion,
        "protocol": f"calibração em {CALIB_YEAR} (12 cortes), teste congelado em {TEST_YEAR} (12 cortes)",
        "p90_abs_error_calibrated": p90_calib,
        "nominal_coverage_target": 0.90,
        "ic_acceptable_range": [IC_MIN, IC_MAX],
        "overall_coverage_test": overall_coverage,
        "dry_season_coverage_test": dry_cov,
        "wet_season_coverage_test": wet_cov,
        "overall_in_range": overall_in_range,
        "dry_in_range": dry_in_range,
        "wet_in_range": wet_in_range,
        "gate_G5": gate,
    }
    (out_dir / "g5_report.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== G5 — Cobertura fora da amostra (calibração 2023 -> teste 2024) ===")
    print(f"p90 erro absoluto calibrado em 2023: {p90_calib:.4f}")
    print(f"Cobertura em 2024 (nunca visto na calibração): geral={overall_coverage:.4f} seco={dry_cov:.4f} demais={wet_cov:.4f}")
    print(f"Faixa aceitável: [{IC_MIN}, {IC_MAX}]")
    print(f"GATE G5: {gate}")
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-path", type=Path, default=PRED_PATH)
    parser.add_argument("--champion", type=str, default=CHAMPION)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    run(pred_path=args.pred_path, champion=args.champion, out_dir=args.out_dir)
