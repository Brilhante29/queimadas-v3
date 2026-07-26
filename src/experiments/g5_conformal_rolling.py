"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g5_conformal_rolling.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import (  # noqa: E402
    MIN_TRAIN_MONTHS,
    build_features,
    load_merged_target,
)

OUT_DIR = PROJECT_ROOT / "outputs" / "g5_conformal_rolling"
CHAMPION = "climatology_municipal"
DRY_MONTHS = {8, 9, 10, 11, 12}
RESIDUAL_MONTHS = [(y, m) for y in range(2015, 2025) for m in range(1, 13)]
EVAL_START = pd.Period("2020-01", freq="M")
IC_MIN, IC_MAX = 0.90, 0.98
NOMINAL = 0.90


def climatology_mean_predict(train: pd.DataFrame, frame: pd.DataFrame) -> np.ndarray:
    """Executa a etapa `climatology mean predict` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_rolling.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    table = train.groupby(["municipio_id", "mes"])["fire_count"].mean()
    keys = list(zip(frame["municipio_id"], frame["mes"]))
    return np.array([table.get(k, 0.0) for k in keys], dtype=float)


def run() -> dict:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g5_conformal_rolling.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, _ = load_merged_target()
    df = build_features(df)

    # Passo 1: gerar resíduos out-of-sample reais do champion em todos os cortes
    frames = []
    for (ty, tm) in RESIDUAL_MONTHS:
        cut = pd.Period(f"{ty}-{tm:02d}", freq="M")
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
        test = df[(df["period"] == cut) & df["fire_count"].notna()]
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()]
        if len(test) == 0 or len(train) == 0:
            continue
        out = test[["geocodigo", "municipio_ibge", "ano", "mes"]].copy()
        out["period"] = cut
        out["fire_count"] = test["fire_count"].values
        out["y_pred"] = climatology_mean_predict(train, test)
        out["abs_error"] = (out["fire_count"] - out["y_pred"]).abs()
        out["is_dry"] = out["mes"].isin(DRY_MONTHS)
        frames.append(out)
    residuals = pd.concat(frames, ignore_index=True)

    # Passo 2: ACI (Adaptive Conformal Inference, Gibbs & Candès 2021) por
    # regime: o nível do quantil q_t é ajustado online usando SOMENTE erros de
    # cobertura de cortes passados (as-of válido). O hiperparâmetro gamma
    # (velocidade de adaptação) é SELECIONADO em uma janela temporal separada
    # (2020-2022) e o resultado do gate é medido APENAS na janela de teste
    # nunca usada na seleção (2023-2024) — evita ajustar o método olhando o
    # próprio teste. A variante "static" (quantil fixo 0.90 rolling) roda
    # junto como referência.
    SELECT_END = pd.Period("2022-12", freq="M")
    GAMMA_GRID = [0.05, 0.10, 0.20, 0.30]

    def run_aci(gamma: float) -> pd.DataFrame:
        """Executa a etapa `run aci` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/g5_conformal_rolling.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        q_level = {"dry": NOMINAL, "wet": NOMINAL}
        rows = []
        for cut, test in residuals[residuals["period"] >= EVAL_START].groupby("period"):
            calib = residuals[residuals["period"] < cut]
            q_dry = float(np.clip(q_level["dry"], 0.50, 0.999))
            q_wet = float(np.clip(q_level["wet"], 0.50, 0.999))
            band_dry = float(calib[calib["is_dry"]]["abs_error"].quantile(q_dry))
            band_wet = float(calib[~calib["is_dry"]]["abs_error"].quantile(q_wet))
            p90_dry = float(calib[calib["is_dry"]]["abs_error"].quantile(NOMINAL))
            p90_wet = float(calib[~calib["is_dry"]]["abs_error"].quantile(NOMINAL))

            t = test.copy()
            for label, bd, bw in (("static", p90_dry, p90_wet), ("aci", band_dry, band_wet)):
                band = t["is_dry"].map({True: bd, False: bw}).to_numpy()
                low = np.clip(t["y_pred"].to_numpy() - band, 0.0, None)
                high = t["y_pred"].to_numpy() + band
                t[f"covered_{label}"] = (t["fire_count"].to_numpy() >= low) & (t["fire_count"].to_numpy() <= high)
            t["aci_q_dry"] = q_dry
            t["aci_q_wet"] = q_wet
            rows.append(t)

            for regime, mask in (("dry", t["is_dry"]), ("wet", ~t["is_dry"])):
                if mask.any():
                    realized = float(t.loc[mask, "covered_aci"].mean())
                    q_level[regime] += gamma * (NOMINAL - realized)
        return pd.concat(rows, ignore_index=True)

    # Seleção de gamma na janela 2020-2022 (o teste 2023-2024 fica intocado)
    selection_scores = {}
    runs = {}
    for gamma in GAMMA_GRID:
        run_df = run_aci(gamma)
        runs[gamma] = run_df
        sel = run_df[run_df["period"] <= SELECT_END]
        selection_scores[gamma] = abs(float(sel["covered_aci"].mean()) - NOMINAL)
    best_gamma = min(selection_scores, key=selection_scores.get)
    eval_df = runs[best_gamma]

    # Métricas do gate: SOMENTE a janela de teste 2023-2024
    test_df = eval_df[eval_df["period"] > SELECT_END]
    eval_df["covered"] = eval_df["covered_aci"]
    overall = float(test_df["covered_aci"].mean())
    dry_cov = float(test_df[test_df["is_dry"]]["covered_aci"].mean())
    wet_cov = float(test_df[~test_df["is_dry"]]["covered_aci"].mean())
    static_overall = float(test_df["covered_static"].mean())
    static_dry = float(test_df[test_df["is_dry"]]["covered_static"].mean())
    static_wet = float(test_df[~test_df["is_dry"]]["covered_static"].mean())
    selection_coverage = float(eval_df[eval_df["period"] <= SELECT_END]["covered_aci"].mean())
    calib_log = eval_df.groupby(eval_df["period"].astype(str)).agg(
        aci_q_dry=("aci_q_dry", "first"), aci_q_wet=("aci_q_wet", "first")
    ).reset_index()

    overall_ok = IC_MIN <= overall <= IC_MAX
    dry_ok = IC_MIN <= dry_cov <= IC_MAX
    wet_ok = IC_MIN <= wet_cov <= IC_MAX
    gate = "PASS" if (overall_ok and dry_ok and wet_ok) else ("PARTIAL" if overall_ok else "FAIL")

    by_year = eval_df.groupby(eval_df["ano"].astype(int))["covered"].mean().rename("coverage").reset_index()
    by_year.to_csv(OUT_DIR / "coverage_by_year.csv", index=False)
    calib_log.to_csv(OUT_DIR / "calibration_bands_by_cut.csv", index=False)

    manifest = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "champion": CHAMPION,
        "protocol": (
            "ACI estratificado por regime sobre resíduos out-of-sample rolling (2015+). "
            "gamma selecionado na janela 2020-2022; gate medido SOMENTE em 2023-2024 "
            "(24 cortes nunca usados na seleção do método)"
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
        "previous_attempts": {
            "v1_global_2023calib": {"overall": 0.89375, "dry": 0.7182, "gate": "FAIL"},
            "v2_stratified_2023calib": {"overall": 0.8594, "dry": 0.8273, "gate": "FAIL"},
            "v3_rolling_static_full_eval": {"overall": 0.8848, "dry": 0.8915, "gate": "FAIL"},
        },
    }
    (OUT_DIR / "g5_report.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== G5 v4 — ACI estratificado; gamma selecionado em 2020-2022, teste em 2023-2024 ===")
    print(f"gamma selecionado: {best_gamma} (scores seleção: {selection_scores})")
    print(f"TESTE 2023-24 ACI:    geral={overall:.4f} seco={dry_cov:.4f} demais={wet_cov:.4f} (faixa [{IC_MIN}, {IC_MAX}])")
    print(f"TESTE 2023-24 Static: geral={static_overall:.4f} seco={static_dry:.4f} demais={static_wet:.4f}")
    print(by_year.to_string(index=False))
    print(f"GATE G5: {gate}")
    return manifest


if __name__ == "__main__":
    run()
