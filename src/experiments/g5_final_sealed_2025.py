"""G5 FINAL -- teste selado em 2025. Execucao unica.

Contrato desta execucao
-----------------------
1. A configuracao conformal foi **congelada antes** de qualquer acesso a 2025,
   em `outputs/apa_araripe/g5_drift/frozen_config.json`. Este modulo LE aquele
   arquivo; nao escolhe nada, nao varre grade, nao tem alternativa.
2. O modelo pontual permanece congelado: mesmos hiperparametros do EXP-10
   promovido. 2025 e pontuado aplicando o modelo para frente, nunca
   retreinando-o com 2025.
3. Se reprovar, G5 permanece FAIL. **Nao havera segunda tentativa usando 2025
   para ajuste** -- o resultado desta execucao e final por construcao, porque
   qualquer reexecucao depois de ver o numero seria ajuste no holdout.

O modulo se recusa a rodar se a configuracao congelada nao existir ou se o
hash das previsoes de desenvolvimento nao bater.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import MIN_TRAIN_MONTHS  # noqa: E402
from src.models.baselines import ClimatologyMunicipal  # noqa: E402
from src.scopes import apa_geocodes  # noqa: E402
from src.utils.metrics import mae, wape  # noqa: E402

FROZEN = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_drift" / "frozen_config.json"
DEV_PRED = PROJECT_ROOT / "outputs" / "apa_araripe" / "exp10" / "predictions_2015_2024.csv"
TRAIN_SNAP = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1" / "municipality_month.csv"
SCORE_SNAP = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_2025_scoring" / "municipality_month.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_final_2025"
GATES_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates"

CHAMPION = "climatology_apa_intensity12"
BASELINE = "climatology_municipal"
DRY_MONTHS = {8, 9, 10, 11, 12}
CRITICAL_MONTHS = {10, 11}

# Hiperparametros do EXP-10 promovido -- congelados, nao reajustados.
TRAILING_MONTHS = 12
SHRINK_FIRE_COUNT = 100.0
RATIO_CLIP = (0.5, 2.0)
FEATURE_COLS = ["mes", "municipio_id"]
MIN_STRATUM_CALIB = 30
IC_MIN, IC_MAX = 0.90, 0.98


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen() -> dict:
    """Carrega a etapa `load frozen` do fluxo FireCast.

    Falha fechada se o congelamento nao existir ou se o hash das previsoes de
    desenvolvimento tiver mudado -- nesse caso a config nao corresponde mais ao
    que foi congelado."""
    if not FROZEN.exists():
        raise FileNotFoundError(
            f"configuracao congelada ausente: {FROZEN}. Rode "
            "`python -m src.experiments.g5_conformal_drift_family` antes."
        )
    cfg = json.loads(FROZEN.read_text(encoding="utf-8"))
    actual = sha256_file(DEV_PRED)
    if cfg["predictions_sha256"] != actual:
        raise ValueError(
            "hash das previsoes de desenvolvimento nao bate com o congelamento.\n"
            f"  congelado: {cfg['predictions_sha256']}\n"
            f"  atual    : {actual}\n"
            "A configuracao congelada nao corresponde mais a este backtest."
        )
    return cfg


def load_full_target() -> pd.DataFrame:
    """Carrega a etapa `load full target` do fluxo FireCast.

    Concatena treino (2003-2024) e scoring (2025), recortando pelo escopo da
    APA. 2025 entra SOMENTE como periodo a pontuar."""
    scope = apa_geocodes()
    train = pd.read_csv(TRAIN_SNAP)
    score = pd.read_csv(SCORE_SNAP)

    if train["ano"].max() >= 2025:
        raise ValueError("snapshot de treino contaminado com 2025")
    if set(score["ano"].unique()) != {2025}:
        raise ValueError(f"snapshot de scoring deveria conter so 2025, tem {sorted(score['ano'].unique())}")

    cols = ["geocodigo", "uf", "municipio", "ano", "mes", "fire_count", "observed"]
    df = pd.concat([train[cols], score[cols]], ignore_index=True)
    df = df[df["geocodigo"].astype(int).isin(scope)].copy()
    df.loc[~df["observed"].astype(bool), "fire_count"] = np.nan
    df["period"] = pd.PeriodIndex(
        pd.to_datetime(df["ano"].astype(str) + "-" + df["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    df = df.sort_values(["geocodigo", "period"]).reset_index(drop=True)
    df["municipio_id"] = df["geocodigo"].astype("category").cat.codes
    df["fire_count_lag12"] = df.groupby("geocodigo")["fire_count"].shift(12)
    return df


def score_period(df: pd.DataFrame, cut: pd.Period) -> pd.DataFrame | None:
    """Gera a etapa `score period` do fluxo FireCast.

    Aplica o modelo congelado ao mes `cut`, treinando somente com o passado."""
    train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()]
    test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
    if train.empty or test.empty:
        return None

    hist = train.groupby("geocodigo")["fire_count"].count()
    eligible = hist[hist >= MIN_TRAIN_MONTHS].index
    test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
    if test.empty:
        return None

    model = ClimatologyMunicipal().fit(train, FEATURE_COLS, "fire_count")
    base_pred = np.asarray(model.predict(test), dtype=float)

    prior_periods = pd.period_range(cut - TRAILING_MONTHS, cut - 1, freq="M")
    prior = df[
        df["period"].isin(prior_periods)
        & df["geocodigo"].isin(eligible)
        & df["fire_count"].notna()
    ]
    if len(prior):
        expected = float(np.asarray(model.predict(prior), dtype=float).sum())
        observed = float(prior["fire_count"].sum())
        raw = (observed + SHRINK_FIRE_COUNT) / (expected + SHRINK_FIRE_COUNT)
    else:
        raw = 1.0
    ratio = float(np.clip(raw, RATIO_CLIP[0], RATIO_CLIP[1]))

    rows = []
    for model_name, pred in ((BASELINE, base_pred), (CHAMPION, np.maximum(base_pred * ratio, 0.0))):
        out = test[["geocodigo", "municipio", "uf", "ano", "mes", "fire_count"]].copy()
        out["model"] = model_name
        out["y_pred"] = pred
        out["cut"] = str(cut)
        out["applied_ratio"] = ratio
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """Calcula a etapa `conformal quantile` do fluxo FireCast."""
    vals = np.sort(np.asarray(scores, dtype=float))
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return float("nan")
    rank = min(max(math.ceil((len(vals) + 1) * (1.0 - alpha)), 1), len(vals))
    return float(vals[rank - 1])


def assign_volume_strata(calib: pd.DataFrame) -> dict:
    """Calcula a etapa `assign volume strata` do fluxo FireCast."""
    volume = calib.groupby("geocodigo")["fire_count"].sum()
    if len(volume) < 3:
        return {int(g): "all" for g in volume.index}
    q1, q2 = volume.quantile([1 / 3, 2 / 3])
    return {
        int(g): ("low" if v <= q1 else ("mid" if v <= q2 else "high"))
        for g, v in volume.items()
    }


def main() -> None:
    """Executa a etapa `main` do fluxo FireCast."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = load_frozen()
    chosen = cfg["chosen"]
    alpha = float(chosen["alpha"])
    window = chosen["window"]
    window = None if window is None or (isinstance(window, float) and math.isnan(window)) else int(window)
    method = chosen["method"]

    df = load_full_target()

    # --- 1. pontuar 2025 com o modelo congelado --------------------------
    scored = []
    for m in range(1, 13):
        cut = pd.Period(f"2025-{m:02d}", freq="M")
        out = score_period(df, cut)
        if out is not None:
            scored.append(out)
    if not scored:
        raise ValueError("nenhum mes de 2025 pontuavel")
    preds_2025 = pd.concat(scored, ignore_index=True)
    preds_2025.to_csv(OUT_DIR / "predictions_2025.csv", index=False)

    # --- 2. serie de residuos: desenvolvimento + 2025 --------------------
    dev = pd.read_csv(DEV_PRED)
    dev = dev[dev["model"] == CHAMPION][["geocodigo", "municipio", "uf", "ano", "mes", "fire_count", "y_pred"]]
    new = preds_2025[preds_2025["model"] == CHAMPION][
        ["geocodigo", "municipio", "uf", "ano", "mes", "fire_count", "y_pred"]
    ]
    res = pd.concat([dev, new], ignore_index=True)
    res["period"] = pd.PeriodIndex(
        pd.to_datetime(res["ano"].astype(str) + "-" + res["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    res["abs_error"] = (res["fire_count"] - res["y_pred"]).abs()
    res["is_dry"] = res["mes"].isin(DRY_MONTHS)
    res["is_critical"] = res["mes"].isin(CRITICAL_MONTHS)

    # --- 3. conformal congelado aplicado a 2025 --------------------------
    rows = []
    for m in range(1, 13):
        cut = pd.Period(f"2025-{m:02d}", freq="M")
        test = res[res["period"] == cut]
        if test.empty:
            continue
        if window is None:
            calib = res[res["period"] < cut]
            win_start = calib["period"].min() if len(calib) else None
        else:
            lo = cut - window
            calib = res[(res["period"] >= lo) & (res["period"] < cut)]
            win_start = lo
        if calib.empty:
            continue

        strata = assign_volume_strata(calib)
        calib = calib.copy()
        calib["vol"] = calib["geocodigo"].astype(int).map(strata)
        t = test.copy()
        t["vol"] = t["geocodigo"].astype(int).map(strata).fillna("high")
        t["stratum"] = t["vol"].astype(str) + "_" + np.where(t["is_dry"].to_numpy(bool), "dry", "wet")
        calib["stratum"] = calib["vol"].astype(str) + "_" + np.where(
            calib["is_dry"].to_numpy(bool), "dry", "wet"
        )
        calib["score"] = calib["abs_error"]

        bands = np.empty(len(t), dtype=float)
        n_eff = np.empty(len(t), dtype=int)
        fb = np.empty(len(t), dtype=object)
        for i, s in enumerate(t["stratum"].to_numpy()):
            pool = calib[calib["stratum"] == s]["score"]
            level = "stratum"
            if len(pool) < MIN_STRATUM_CALIB:
                season = "dry" if str(s).endswith("_dry") else "wet"
                pool = calib[calib["stratum"].str.endswith("_" + season)]["score"]
                level = "season"
            if len(pool) < MIN_STRATUM_CALIB:
                pool = calib["score"]
                level = "global"
            bands[i] = conformal_quantile(pool.to_numpy(float), alpha)
            n_eff[i] = int(len(pool))
            fb[i] = level

        y = t["fire_count"].to_numpy(float)
        p = t["y_pred"].to_numpy(float)
        low = np.clip(p - bands, 0.0, None)
        high = p + bands
        t["band"] = bands
        t["n_calib_effective"] = n_eff
        t["fallback_level"] = fb
        t["alpha_effective"] = alpha
        t["calibration_window_start"] = str(win_start) if win_start is not None else ""
        t["calibration_window_end"] = str(cut - 1)
        t["interval_low"] = low
        t["interval_high"] = high
        t["interval_width"] = high - low
        t["covered"] = (y >= low) & (y <= high)
        rows.append(t)

    final = pd.concat(rows, ignore_index=True)
    final.to_csv(OUT_DIR / "interval_predictions_2025.csv", index=False)

    cov = {
        "overall": float(final["covered"].mean()),
        "dry": float(final[final["is_dry"]]["covered"].mean()),
        "wet": float(final[~final["is_dry"]]["covered"].mean()),
        "critical_out_nov": float(final[final["is_critical"]]["covered"].mean()),
        "n_rows": int(len(final)),
    }
    for uf, g in final.groupby("uf"):
        cov[f"uf_{uf}"] = float(g["covered"].mean())
        cov[f"n_uf_{uf}"] = int(len(g))
    for vol, g in final.groupby("vol"):
        cov[f"volume_{vol}"] = float(g["covered"].mean())
        cov[f"n_volume_{vol}"] = int(len(g))
    cov["volume_strata_source"] = "causal_from_calibration_window"

    failures = []
    if not np.isfinite(cov["overall"]):
        failures.append("cobertura geral nao finita")
    elif not (IC_MIN <= cov["overall"] <= IC_MAX):
        failures.append(f"cobertura geral {cov['overall']:.4f} fora de [{IC_MIN}, {IC_MAX}]")
    for uf in ("CE", "PE", "PI"):
        k = f"uf_{uf}"
        if k in cov and not (IC_MIN <= cov[k] <= IC_MAX):
            failures.append(f"cobertura {uf} {cov[k]:.4f} fora de [{IC_MIN}, {IC_MAX}]")

    # acuracia pontual em 2025, para registro (nao e criterio do G5)
    b = preds_2025[preds_2025["model"] == BASELINE]
    c = preds_2025[preds_2025["model"] == CHAMPION]
    point = {
        "wape_baseline": float(wape(b["fire_count"].to_numpy(float), b["y_pred"].to_numpy(float))),
        "wape_champion": float(wape(c["fire_count"].to_numpy(float), c["y_pred"].to_numpy(float))),
        "mae_champion": float(mae(c["fire_count"].to_numpy(float), c["y_pred"].to_numpy(float))),
        "observed_total_2025": int(c["fire_count"].sum()),
        "predicted_total_2025": float(c["y_pred"].sum()),
    }

    gate = {
        "gate": "G5_conformal_final_sealed_2025",
        "scope": "apa_chapada_araripe",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "execution_contract": (
            "execucao unica em holdout selado; configuracao congelada antes de "
            "qualquer acesso a 2025; nenhuma segunda tentativa e permitida"
        ),
        "frozen_config": chosen,
        "frozen_selection_rule": cfg["selection_rule"],
        "frozen_at": cfg["frozen_at"],
        "frozen_dev_metrics": cfg["chosen_dev_metrics"],
        "dev_predictions_sha256": cfg["predictions_sha256"],
        "scoring_snapshot_sha256": sha256_file(SCORE_SNAP),
        "coverage_2025": cov,
        "interval_width_2025": {
            "mean": float(final["interval_width"].mean()),
            "median": float(final["interval_width"].median()),
        },
        "point_accuracy_2025": point,
        "ic_bounds": [IC_MIN, IC_MAX],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / "g5_final_report.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (GATES_DIR / "G5_final_sealed_2025.json").write_text(
        json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(json.dumps(
        {
            "status": gate["status"],
            "frozen_config": chosen,
            "coverage_2025": cov,
            "mean_width": gate["interval_width_2025"]["mean"],
            "point_accuracy_2025": point,
            "failures": failures,
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
