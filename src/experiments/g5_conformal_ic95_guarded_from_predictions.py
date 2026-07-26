"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DRY_MONTHS = {8, 9, 10, 11, 12}
EVAL_START = pd.Period("2020-01", freq="M")
VALIDATION_YEAR = 2022
TEST_START = pd.Period("2023-01", freq="M")
IC_MIN, IC_MAX = 0.90, 0.98
SELECTION_MIN, SELECTION_MAX = 0.94, 0.98
ALPHA_GRID = [0.05, 0.04, 0.03, 0.02]


def load_predictions(pred_path: Path, champion: str) -> pd.DataFrame:
    """Carrega a etapa `load predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    preds = pd.read_csv(pred_path)
    champ = preds[preds["model"] == champion].copy()
    if champ.empty:
        raise ValueError(f"No predictions for model {champion!r} in {pred_path}")
    champ["period"] = pd.PeriodIndex(
        pd.to_datetime(champ["ano"].astype(str) + "-" + champ["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    champ["abs_error"] = (champ["fire_count"] - champ["y_pred"]).abs()
    champ["is_dry"] = champ["mes"].isin(DRY_MONTHS)
    return champ.sort_values(["period", "geocodigo"]).reset_index(drop=True)


def conformal_band(errors: pd.Series, alpha: float) -> float:
    """Executa a etapa `conformal band` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    vals = np.sort(errors.dropna().to_numpy(dtype=float))
    if len(vals) == 0:
        raise ValueError("empty calibration residuals")
    rank = math.ceil((len(vals) + 1) * (1.0 - alpha))
    rank = min(max(rank, 1), len(vals))
    return float(vals[rank - 1])


def run_candidate(residuals: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """Executa a etapa `run candidate` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for cut, test in residuals[residuals["period"] >= EVAL_START].groupby("period"):
        calib = residuals[residuals["period"] < cut]
        dry_calib = calib[calib["is_dry"]]["abs_error"]
        wet_calib = calib[~calib["is_dry"]]["abs_error"]
        if dry_calib.empty or wet_calib.empty:
            continue

        band_dry = conformal_band(dry_calib, alpha)
        band_wet = conformal_band(wet_calib, alpha)

        t = test.copy()
        band = np.where(t["is_dry"].to_numpy(dtype=bool), band_dry, band_wet)
        low = np.clip(t["y_pred"].to_numpy(dtype=float) - band, 0.0, None)
        high = t["y_pred"].to_numpy(dtype=float) + band
        t["interval_low"] = low
        t["interval_high"] = high
        t["interval_width"] = high - low
        t["covered"] = (t["fire_count"].to_numpy(dtype=float) >= low) & (
            t["fire_count"].to_numpy(dtype=float) <= high
        )
        t["alpha"] = alpha
        t["nominal_coverage"] = 1.0 - alpha
        t["band_dry"] = band_dry
        t["band_wet"] = band_wet
        rows.append(t)
    return pd.concat(rows, ignore_index=True)


def coverage_slices(df: pd.DataFrame) -> dict[str, float]:
    """Executa a etapa `coverage slices` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return {
        "overall": float(df["covered"].mean()),
        "dry": float(df[df["is_dry"]]["covered"].mean()),
        "wet": float(df[~df["is_dry"]]["covered"].mean()),
    }


def mean_width_slices(df: pd.DataFrame) -> dict[str, float]:
    """Executa a etapa `mean width slices` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return {
        "overall": float(df["interval_width"].mean()),
        "dry": float(df[df["is_dry"]]["interval_width"].mean()),
        "wet": float(df[~df["is_dry"]]["interval_width"].mean()),
    }


def selection_pass(cov: dict[str, float]) -> bool:
    """Executa a etapa `selection pass` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return all(SELECTION_MIN <= cov[key] <= SELECTION_MAX for key in ("overall", "dry", "wet"))


def gate_pass(cov: dict[str, float]) -> bool:
    """Executa a etapa `gate pass` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return all(IC_MIN <= cov[key] <= IC_MAX for key in ("overall", "dry", "wet"))


def run(pred_path: Path, champion: str, out_dir: Path) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    residuals = load_predictions(pred_path, champion)

    candidates = {}
    selection_rows = []
    for alpha in ALPHA_GRID:
        candidate = run_candidate(residuals, alpha)
        candidates[alpha] = candidate
        validation = candidate[candidate["ano"] == VALIDATION_YEAR].copy()
        cov = coverage_slices(validation)
        widths = mean_width_slices(validation)
        selection_rows.append(
            {
                "alpha": alpha,
                "nominal_coverage": 1.0 - alpha,
                "selection_pass": selection_pass(cov),
                **{f"validation_coverage_{k}": v for k, v in cov.items()},
                **{f"validation_width_{k}": v for k, v in widths.items()},
            }
        )

    selection_df = pd.DataFrame(selection_rows)
    viable = selection_df[selection_df["selection_pass"]].sort_values("alpha", ascending=False)
    if viable.empty:
        selected_alpha = float(selection_df.sort_values("validation_coverage_overall").iloc[-1]["alpha"])
        selection_decision = "NO_VALID_ALPHA_FELL_BACK_TO_HIGHEST_VALIDATION_COVERAGE"
    else:
        selected_alpha = float(viable.iloc[0]["alpha"])
        selection_decision = "SELECTED_NARROWEST_ALPHA_PASSING_2022_GUARDRAIL"

    eval_df = candidates[selected_alpha].copy()
    test_df = eval_df[eval_df["period"] >= TEST_START].copy()
    if test_df.empty:
        raise ValueError("empty 2023-2024 test window")

    test_cov = coverage_slices(test_df)
    test_width = mean_width_slices(test_df)
    validation_df = eval_df[eval_df["ano"] == VALIDATION_YEAR].copy()
    validation_cov = coverage_slices(validation_df)
    validation_width = mean_width_slices(validation_df)
    gate = "PASS" if gate_pass(test_cov) else "FAIL"

    by_year = (
        eval_df.groupby("ano")
        .agg(
            coverage=("covered", "mean"),
            interval_width=("interval_width", "mean"),
            n=("covered", "size"),
        )
        .reset_index()
    )
    by_year_regime = (
        eval_df.groupby(["ano", "is_dry"])
        .agg(
            coverage=("covered", "mean"),
            interval_width=("interval_width", "mean"),
            n=("covered", "size"),
        )
        .reset_index()
    )
    by_year_regime["regime"] = by_year_regime["is_dry"].map({True: "dry", False: "wet"})
    by_year_regime = by_year_regime.drop(columns=["is_dry"])

    eval_df.to_csv(out_dir / "interval_predictions.csv", index=False)
    selection_df.to_csv(out_dir / "selection_grid.csv", index=False)
    by_year.to_csv(out_dir / "coverage_by_year.csv", index=False)
    by_year_regime.to_csv(out_dir / "coverage_by_year_regime.csv", index=False)

    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "source_predictions": str(pred_path),
        "champion": champion,
        "protocol": (
            "Finite-sample conformal IC95 guardrail from existing out-of-sample predictions. "
            "Nominal alpha selected on validation year 2022 only; gate measured on 2023-2024 only."
        ),
        "method_for_gate": "finite_sample_stratified_conformal_guarded_ic95",
        "alpha_grid": ALPHA_GRID,
        "selection_year": VALIDATION_YEAR,
        "selection_coverage_required": [SELECTION_MIN, SELECTION_MAX],
        "selection_decision": selection_decision,
        "alpha_selected": selected_alpha,
        "nominal_coverage_selected": 1.0 - selected_alpha,
        "validation_coverage": validation_cov,
        "validation_width": validation_width,
        "ic_acceptable_range": [IC_MIN, IC_MAX],
        "n_test_predictions": int(len(test_df)),
        "test_coverage_2023_2024": test_cov,
        "test_interval_width_2023_2024": test_width,
        "overall_coverage_test_2023_2024": test_cov["overall"],
        "dry_season_coverage_test": test_cov["dry"],
        "wet_season_coverage_test": test_cov["wet"],
        "gate_G5": gate,
    }
    (out_dir / "g5_report.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== G5 guarded IC95 conformal ===")
    print(f"model={champion}")
    print(f"alpha selected={selected_alpha} nominal={1.0 - selected_alpha:.3f} ({selection_decision})")
    print(f"validation 2022 coverage: {validation_cov}")
    print(f"TEST 2023-24 coverage: {test_cov}")
    print(f"GATE G5: {gate}")
    return manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/g5_conformal_ic95_guarded_from_predictions.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-path", type=Path, required=True)
    parser.add_argument("--champion", type=str, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.pred_path, args.champion, args.out_dir)


if __name__ == "__main__":
    main()
