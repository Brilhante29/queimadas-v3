"""G5 conformal do escopo APA Chapada do Araripe, calibrado do zero.

Regra inegociavel (SDD 21): **zero reaproveitamento da calibracao do Ceara**.
Todo residuo usado aqui nasce das previsoes produzidas pelo backtest APA
(`outputs/apa_araripe/exp10/predictions_2015_2024.csv`). Nenhum residuo, banda
ou quantil do experimento CE entra neste arquivo.

Metodo (mesmo do G5 vigente, reaplicado ao escopo novo):
- conformal split estratificado por estacao (seca vs. umida);
- janela de calibracao expansiva: para o corte t, calibra em tudo < t;
- banda = estatistica de ordem ``ceil((n+1)(1-alpha))`` dos |residuos|;
- grade de alpha, selecionando a banda mais estreita que passa a guarda no
  ano de validacao;
- cobertura final avaliada em periodo POSTERIOR ao usado na selecao, para nao
  escolher alpha olhando o proprio holdout.

Novidade em relacao ao G5 do CE: cobertura reportada tambem por UF (CE/PE/PI)
e por estrato de volume municipal, porque o escopo agora e triestadual e uma
cobertura agregada boa poderia esconder um estado descalibrado.
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

PRED_PATH = PROJECT_ROOT / "outputs" / "apa_araripe" / "exp10" / "predictions_2015_2024.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5"
GATES_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates"

CHAMPION = "climatology_apa_intensity12"

DRY_MONTHS = {8, 9, 10, 11, 12}
CRITICAL_MONTHS = {10, 11}

# Selecao de alpha olha ate VALIDATION_END; a cobertura reportada como
# resultado do gate e medida so a partir de TEST_START. Sem sobreposicao.
CALIB_START = pd.Period("2015-01", freq="M")
VALIDATION_START = pd.Period("2020-01", freq="M")
VALIDATION_END = pd.Period("2022-12", freq="M")
TEST_START = pd.Period("2023-01", freq="M")

IC_MIN, IC_MAX = 0.90, 0.98
ALPHA_GRID = [0.05, 0.04, 0.03, 0.02]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_apa_residuals() -> pd.DataFrame:
    """Carrega a etapa `load apa residuals` do fluxo FireCast.

    Le SOMENTE as previsoes do backtest APA. Falha fechada se o arquivo do
    escopo antigo for apontado por engano."""
    preds = pd.read_csv(PRED_PATH)
    champ = preds[preds["model"] == CHAMPION].copy()
    if champ.empty:
        raise ValueError(f"nenhuma previsao do modelo {CHAMPION!r} em {PRED_PATH}")

    champ["period"] = pd.PeriodIndex(
        pd.to_datetime(champ["ano"].astype(str) + "-" + champ["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    champ["abs_error"] = (champ["fire_count"] - champ["y_pred"]).abs()
    champ["is_dry"] = champ["mes"].isin(DRY_MONTHS)
    champ["is_critical"] = champ["mes"].isin(CRITICAL_MONTHS)
    return champ.sort_values(["period", "geocodigo"]).reset_index(drop=True)


def conformal_band(errors: pd.Series, alpha: float) -> float:
    """Executa a etapa `conformal band` do fluxo FireCast.

    Quantil conforme de amostra finita: ``ceil((n+1)(1-alpha))``-esima
    estatistica de ordem."""
    vals = np.sort(errors.dropna().to_numpy(dtype=float))
    if len(vals) == 0:
        raise ValueError("residuos de calibracao vazios")
    rank = min(max(math.ceil((len(vals) + 1) * (1.0 - alpha)), 1), len(vals))
    return float(vals[rank - 1])


MIN_STRATUM_CALIB = 30  # residuos minimos para bancar um quantil conforme


def _volume_strata_from_calib(calib: pd.DataFrame) -> dict[int, str]:
    """Calcula a etapa `volume strata from calib` do fluxo FireCast.

    Atribui cada municipio a um tercil de volume usando SOMENTE a janela de
    calibracao (passado do corte). Usar o volume do conjunto avaliado seria
    vazamento: a faixa do municipio no teste nao pode ser definida pelo
    proprio teste."""
    volume = calib.groupby("geocodigo")["fire_count"].sum()
    if len(volume) < 3:
        return {int(g): "all" for g in volume.index}
    q1, q2 = volume.quantile([1 / 3, 2 / 3])
    out = {}
    for geo, v in volume.items():
        out[int(geo)] = "low" if v <= q1 else ("mid" if v <= q2 else "high")
    return out


def run_alpha(
    residuals: pd.DataFrame,
    alpha: float,
    eval_start: pd.Period,
    stratify_volume: bool = False,
) -> pd.DataFrame:
    """Executa a etapa `run alpha` do fluxo FireCast.

    Aplica conformal com janela expansiva. A calibracao de cada corte usa
    exclusivamente periodos ANTERIORES ao corte -- nenhuma informacao do mes
    avaliado entra na banda.

    Com ``stratify_volume=True`` aplica conformal de Mondrian: a banda e
    calibrada dentro do grupo (estacao x tercil de volume) a que a linha
    pertence. Isso existe porque uma banda unica por estacao mistura
    municipios de escalas muito diferentes -- num escopo com Bodoco (milhares
    de focos) ao lado de municipios com quase nenhum, a banda agregada fica
    estreita demais para os grandes e larga demais para os pequenos. A
    validade conforme vale por estrato quando a calibracao e feita por
    estrato."""
    rows = []
    for cut, test in residuals[residuals["period"] >= eval_start].groupby("period"):
        calib = residuals[residuals["period"] < cut]
        if calib.empty:
            continue

        t = test.copy()
        if not stratify_volume:
            dry = calib[calib["is_dry"]]["abs_error"]
            wet = calib[~calib["is_dry"]]["abs_error"]
            if dry.empty or wet.empty:
                continue
            band_dry = conformal_band(dry, alpha)
            band_wet = conformal_band(wet, alpha)
            band = np.where(t["is_dry"].to_numpy(dtype=bool), band_dry, band_wet)
            t["stratum"] = np.where(t["is_dry"].to_numpy(dtype=bool), "dry", "wet")
            t["n_calib_effective"] = np.where(
                t["is_dry"].to_numpy(dtype=bool), len(dry), len(wet)
            )
            t["fallback_level"] = "season"
        else:
            strata = _volume_strata_from_calib(calib)
            calib = calib.copy()
            calib["vol"] = calib["geocodigo"].astype(int).map(strata)
            t["vol"] = t["geocodigo"].astype(int).map(strata)
            # municipio nunca visto na calibracao cai no estrato mais largo
            t["vol"] = t["vol"].fillna("high")
            t["stratum"] = t["vol"] + "_" + np.where(t["is_dry"].to_numpy(dtype=bool), "dry", "wet")
            calib["stratum"] = calib["vol"] + "_" + np.where(
                calib["is_dry"].to_numpy(dtype=bool), "dry", "wet"
            )

            band = np.empty(len(t), dtype=float)
            n_eff = np.empty(len(t), dtype=int)
            fb = np.empty(len(t), dtype=object)
            ok = True
            for i, s in enumerate(t["stratum"].to_numpy()):
                errs = calib[calib["stratum"] == s]["abs_error"]
                level = "stratum"
                if len(errs) < MIN_STRATUM_CALIB:
                    # estrato sem residuos suficientes: recua para a estacao
                    # inteira em vez de inventar quantil com amostra minuscula
                    season = "dry" if s.endswith("_dry") else "wet"
                    errs = calib[calib["is_dry"] == (season == "dry")]["abs_error"]
                    level = "season"
                if errs.empty:
                    ok = False
                    break
                band[i] = conformal_band(errs, alpha)
                n_eff[i] = int(len(errs))
                fb[i] = level
            if not ok:
                continue
            t["n_calib_effective"] = n_eff
            t["fallback_level"] = fb

        y = t["fire_count"].to_numpy(dtype=float)
        p = t["y_pred"].to_numpy(dtype=float)
        low = np.clip(p - band, 0.0, None)
        high = p + band
        t["interval_low"] = low
        t["interval_high"] = high
        t["interval_width"] = high - low
        t["covered"] = (y >= low) & (y <= high)
        t["alpha"] = alpha
        t["nominal_coverage"] = 1.0 - alpha
        t["calibration_window_start"] = str(calib["period"].min())
        t["calibration_window_end"] = str(cut - 1)
        t["alpha_effective"] = alpha
        t["band"] = band
        rows.append(t)
    if not rows:
        raise ValueError(f"nenhum corte avaliavel para alpha={alpha}")
    return pd.concat(rows, ignore_index=True)


def coverage_report(df: pd.DataFrame) -> dict:
    """Calcula a etapa `coverage report` do fluxo FireCast.

    Cobertura fatiada. Estrato de volume usa o total historico de focos do
    municipio dentro do proprio conjunto avaliado."""
    out: dict[str, float | int] = {
        "overall": float(df["covered"].mean()),
        "dry": float(df[df["is_dry"]]["covered"].mean()),
        "wet": float(df[~df["is_dry"]]["covered"].mean()),
        "critical_out_nov": float(df[df["is_critical"]]["covered"].mean()),
        "n_rows": int(len(df)),
    }
    for uf, g in df.groupby("uf"):
        out[f"uf_{uf}"] = float(g["covered"].mean())
        out[f"n_uf_{uf}"] = int(len(g))

    # Estrato de volume CAUSAL: usa o `vol` atribuido durante a calibracao
    # (informacao disponivel ANTES da previsao). Recalcular tercis com o
    # `fire_count` do proprio conjunto avaliado seria estratificacao ex-post
    # do holdout -- os numeros por volume descreveriam grupos definidos pelo
    # resultado que se quer medir.
    if "vol" in df.columns:
        for name, sub in df.groupby("vol"):
            out[f"volume_{name}"] = float(sub["covered"].mean())
            out[f"n_volume_{name}"] = int(len(sub))
        out["volume_strata_source"] = "causal_from_calibration_window"
    else:
        out["volume_strata_source"] = "unavailable_method_without_volume_strata"
    return out


def width_report(df: pd.DataFrame) -> dict:
    """Calcula a etapa `width report` do fluxo FireCast."""
    return {
        "overall": float(df["interval_width"].mean()),
        "dry": float(df[df["is_dry"]]["interval_width"].mean()),
        "wet": float(df[~df["is_dry"]]["interval_width"].mean()),
        "median": float(df["interval_width"].median()),
    }


def main() -> None:
    """Executa a etapa `main` do fluxo FireCast."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GATES_DIR.mkdir(parents=True, exist_ok=True)

    residuals = load_apa_residuals()

    # --- selecao de metodo + alpha: olha SO ate VALIDATION_END ---------------
    # Ambos os metodos competem na janela de validacao. O criterio de aceite
    # (IC_MIN/IC_MAX) NAO e afrouxado; o que muda e o estimador.
    selection = []
    for stratify in (False, True):
        for alpha in ALPHA_GRID:
            try:
                cand = run_alpha(residuals, alpha, VALIDATION_START, stratify_volume=stratify)
            except ValueError:
                continue
            val = cand[(cand["period"] >= VALIDATION_START) & (cand["period"] <= VALIDATION_END)]
            if val.empty:
                continue
            cov = float(val["covered"].mean())
            # cobertura por UF tambem entra na guarda: um agregado bom nao pode
            # mascarar um estado descalibrado
            by_uf = val.groupby("uf")["covered"].mean()
            worst_uf = float(by_uf.min())
            selection.append(
                {
                    "method": "mondrian_season_x_volume" if stratify else "season_only",
                    "stratify_volume": stratify,
                    "alpha": alpha,
                    "nominal": 1.0 - alpha,
                    "validation_coverage": cov,
                    "validation_worst_uf_coverage": worst_uf,
                    "validation_mean_width": float(val["interval_width"].mean()),
                    "passes_guardrail": bool(
                        IC_MIN <= cov <= IC_MAX and worst_uf >= IC_MIN
                    ),
                }
            )
    sel_df = pd.DataFrame(selection)
    sel_df.to_csv(OUT_DIR / "alpha_selection.csv", index=False)

    passing = sel_df[sel_df["passes_guardrail"]]
    if len(passing):
        # banda mais estreita entre as que passam a guarda
        chosen = passing.sort_values("validation_mean_width").iloc[0]
        selection_decision = "SELECTED_NARROWEST_PASSING_VALIDATION_GUARDRAIL_INCL_PER_UF"
    else:
        chosen = sel_df.sort_values("validation_worst_uf_coverage", ascending=False).iloc[0]
        selection_decision = "NO_CONFIG_PASSED_GUARDRAIL_FELL_BACK_TO_BEST_WORST_UF_COVERAGE"
    chosen_alpha = float(chosen["alpha"])
    chosen_stratify = bool(chosen["stratify_volume"])

    # --- avaliacao final: SOMENTE periodo posterior a selecao ---------------
    final = run_alpha(residuals, chosen_alpha, TEST_START, stratify_volume=chosen_stratify)
    final = final[final["period"] >= TEST_START].copy()
    final.to_csv(OUT_DIR / "interval_predictions.csv", index=False)

    cov = coverage_report(final)
    wid = width_report(final)

    failures = []
    if not (IC_MIN <= cov["overall"] <= IC_MAX):
        failures.append(f"cobertura geral {cov['overall']:.4f} fora de [{IC_MIN}, {IC_MAX}]")
    for uf in ("CE", "PE", "PI"):
        key = f"uf_{uf}"
        if key in cov and not (IC_MIN <= cov[key] <= IC_MAX):
            failures.append(f"cobertura {uf} {cov[key]:.4f} fora de [{IC_MIN}, {IC_MAX}]")
    if not np.isfinite(cov["overall"]):
        failures.append("cobertura geral nao finita")

    gate = {
        "gate": "G5_conformal",
        "scope": "apa_chapada_araripe",
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "calibration_provenance": (
            "calibrado do zero a partir de outputs/apa_araripe/exp10/"
            "predictions_2015_2024.csv; nenhum residuo do escopo CE reutilizado"
        ),
        "predictions_sha256": sha256_file(PRED_PATH),
        "champion": CHAMPION,
        "method": (
            "conformal Mondrian (estacao x tercil de volume), janela expansiva"
            if chosen_stratify
            else "conformal split por estacao, janela expansiva"
        ),
        "stratify_volume": chosen_stratify,
        "alpha_grid": ALPHA_GRID,
        "alpha_selected": chosen_alpha,
        "nominal_coverage": 1.0 - chosen_alpha,
        "selection_decision": selection_decision,
        "selection_window": [str(VALIDATION_START), str(VALIDATION_END)],
        "evaluation_window": [str(TEST_START), str(final["period"].max())],
        "coverage": cov,
        "interval_width": wid,
        "ic_bounds": [IC_MIN, IC_MAX],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (OUT_DIR / "g5_report.json").write_text(json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8")
    (GATES_DIR / "G5_conformal.json").write_text(json.dumps(gate, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(
        {
            "status": gate["status"],
            "alpha_selected": chosen_alpha,
            "nominal_coverage": 1.0 - chosen_alpha,
            "coverage": cov,
            "mean_width": wid["overall"],
            "failures": failures,
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
