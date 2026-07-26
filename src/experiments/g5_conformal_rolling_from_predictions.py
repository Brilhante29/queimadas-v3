"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g5_conformal_rolling_from_predictions.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

DRY_MONTHS = {8, 9, 10, 11, 12}
EVAL_START = pd.Period("2020-01", freq="M")
SELECT_END = pd.Period("2022-12", freq="M")
IC_MIN, IC_MAX = 0.90, 0.98
NOMINAL = 0.90
GAMMA_GRID = [0.05, 0.10, 0.20, 0.30]


def load_residuals(pred_path: Path, champion: str) -> pd.DataFrame:
    """Carrega a etapa `load residuals` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_rolling_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
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


def run_aci(residuals: pd.DataFrame, gamma: float) -> pd.DataFrame:
    """Executa a etapa `run aci` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_rolling_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    q_level = {"dry": NOMINAL, "wet": NOMINAL}
    rows = []
    for cut, test in residuals[residuals["period"] >= EVAL_START].groupby("period"):
        calib = residuals[residuals["period"] < cut]
        if calib.empty:
            continue
        q_dry = float(np.clip(q_level["dry"], 0.50, 0.999))
        q_wet = float(np.clip(q_level["wet"], 0.50, 0.999))
        dry_calib = calib[calib["is_dry"]]["abs_error"]
        wet_calib = calib[~calib["is_dry"]]["abs_error"]
        if dry_calib.empty or wet_calib.empty:
            continue

        band_dry = float(dry_calib.quantile(q_dry))
        band_wet = float(wet_calib.quantile(q_wet))
        p90_dry = float(dry_calib.quantile(NOMINAL))
        p90_wet = float(wet_calib.quantile(NOMINAL))

        t = test.copy()
        for label, bd, bw in (("static", p90_dry, p90_wet), ("aci", band_dry, band_wet)):
            band = t["is_dry"].map({True: bd, False: bw}).to_numpy(dtype=float)
            low = np.clip(t["y_pred"].to_numpy(dtype=float) - band, 0.0, None)
            high = t["y_pred"].to_numpy(dtype=float) + band
            t[f"covered_{label}"] = (t["fire_count"].to_numpy(dtype=float) >= low) & (
                t["fire_count"].to_numpy(dtype=float) <= high
            )
        t["aci_q_dry"] = q_dry
        t["aci_q_wet"] = q_wet
        rows.append(t)

        for regime, mask in (("dry", t["is_dry"]), ("wet", ~t["is_dry"])):
            if mask.any():
                realized = float(t.loc[mask, "covered_aci"].mean())
                q_level[regime] += gamma * (NOMINAL - realized)
    return pd.concat(rows, ignore_index=True)


def run(pred_path: Path, champion: str, out_dir: Path) -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_rolling_from_predictions.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    residuals = load_residuals(pred_path, champion)

    selection_scores = {}
    runs = {}
    for gamma in GAMMA_GRID:
        run_df = run_aci(residuals, gamma)
        runs[gamma] = run_df
        sel = run_df[run_df["period"] <= SELECT_END]
        selection_scores[gamma] = abs(float(sel["covered_aci"].mean()) - NOMINAL)

    best_gamma = min(selection_scores, key=selection_scores.get)
    eval_df = runs[best_gamma]
    test_df = eval_df[eval_df["period"] > SELECT_END].copy()
    if test_df.empty:
        raise ValueError("Empty 2023-2024 test window for G5")

    overall = float(test_df["covered_aci"].mean())
    dry_cov = float(test_df[test_df["is_dry"]]["covered_aci"].mean())
    wet_cov = float(test_df[~test_df["is_dry"]]["covered_aci"].mean())
    static_overall = float(test_df["covered_static"].mean())
    static_dry = float(test_df[test_df["is_dry"]]["covered_static"].mean())
    static_wet = float(test_df[~test_df["is_dry"]]["covered_static"].mean())
    selection_coverage = float(eval_df[eval_df["period"] <= SELECT_END]["covered_aci"].mean())

    overall_ok = IC_MIN <= overall <= IC_MAX
    dry_ok = IC_MIN <= dry_cov <= IC_MAX
    wet_ok = IC_MIN <= wet_cov <= IC_MAX
    gate = "PASS" if (overall_ok and dry_ok and wet_ok) else ("PARTIAL" if overall_ok else "FAIL")

    eval_df["covered"] = eval_df["covered_aci"]
    by_year = eval_df.groupby(eval_df["ano"].astype(int))["covered"].mean().rename("coverage").reset_index()
    by_year.to_csv(out_dir / "coverage_by_year.csv", index=False)
    eval_df.groupby(eval_df["period"].astype(str)).agg(
        aci_q_dry=("aci_q_dry", "first"),
        aci_q_wet=("aci_q_wet", "first"),
    ).reset_index().to_csv(out_dir / "calibration_bands_by_cut.csv", index=False)

    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "source_predictions": str(pred_path),
        "champion": champion,
        "protocol": (
            "ACI estratificado por regime sobre predicoes out-of-sample existentes. "
            "gamma selecionado em 2020-2022; gate medido somente em 2023-2024."
        ),
        "method_for_gate": "aci",
        "gamma_grid": GAMMA_GRID,
        "gamma_selected": best_gamma,
        "gamma_selection_scores_abs_dev": {str(k): float(v) for k, v in selection_scores.items()},
        "selection_window_coverage": selection_coverage,
        "nominal_coverage_target": NOMINAL,
        "ic_acceptable_range": [IC_MIN, IC_MAX],
        "n_test_predictions": int(len(test_df)),
        "overall_coverage_test_2023_2024": overall,
        "dry_season_coverage_test": dry_cov,
        "wet_season_coverage_test": wet_cov,
        "static_rolling_variant_test": {"overall": static_overall, "dry": static_dry, "wet": static_wet},
        "coverage_by_year_full_eval": by_year.to_dict("records"),
        "gate_G5": gate,
    }
    (out_dir / "g5_report.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== G5 from predictions: ACI rolling ===")
    print(f"model={champion}")
    print(f"gamma selected: {best_gamma} (selection scores: {selection_scores})")
    print(f"TEST 2023-24 ACI: overall={overall:.4f} dry={dry_cov:.4f} wet={wet_cov:.4f}")
    print(f"TEST 2023-24 static: overall={static_overall:.4f} dry={static_dry:.4f} wet={static_wet:.4f}")
    print(f"GATE G5: {gate}")
    return manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/g5_conformal_rolling_from_predictions.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred-path", type=Path, required=True)
    parser.add_argument("--champion", type=str, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.pred_path, args.champion, args.out_dir)


if __name__ == "__main__":
    main()
