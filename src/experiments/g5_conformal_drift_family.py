"""Familia de conformal robusta a deslocamento temporal -- desenvolvimento e congelamento.

Contexto
--------
O G5 anterior (`g5_conformal_apa_araripe.py`) REPROVOU: cobertura caiu de
0,9228 na validacao (2020-2022) para 0,8762 no holdout (2023-2024). Ver
`outputs/apa_araripe/audit/g5_finding.md`.

Disciplina desta etapa (decisao do usuario: opcao 3 + 1)
-------------------------------------------------------
- 2023-2024 **deixou de ser holdout**. Seus resultados ja foram observados e
  motivaram a mudanca de metodo, entao a partir daqui integram o conjunto de
  DESENVOLVIMENTO. Continuam validos como evidencia historica do fracasso do
  metodo antigo.
- 2025 permanece **LACRADO**. Nenhuma metrica de 2025 e acessada por este
  modulo; ele se recusa a carregar qualquer periodo >= 2025.
- A familia de candidatos e **pre-definida** aqui. Nao se cria candidato novo
  depois de ver 2025.
- Selecao por **robustez temporal**: cobertura minima entre folds e entre UFs,
  com largura apenas como desempate. Nunca mais "intervalo mais estreito que
  mal passou".

Ao final, a configuracao vencedora e congelada em `frozen_config.json` com
hash. So depois disso 2025 pode ser ingerido e avaliado, uma unica vez.
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
OUT_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_drift"

CHAMPION = "climatology_apa_intensity12"
DRY_MONTHS = {8, 9, 10, 11, 12}
CRITICAL_MONTHS = {10, 11}

SEALED_FROM = 2025  # nada deste ano ou depois entra aqui
IC_MIN, IC_MAX = 0.90, 0.98
# Margem exigida ACIMA do piso durante o desenvolvimento. Existe porque uma
# configuracao que encosta em 0,90 no fold mais dificil nao tem folga nenhuma
# para o deslocamento temporal que derrubou o G5 anterior (0,9228 -> 0,8762).
# Robustez primeiro; largura so desempata entre as que ja tem folga.
DEV_MARGIN = 0.02
ALPHA_GRID = [0.05, 0.04, 0.03, 0.02]
MIN_STRATUM_CALIB = 30
ACI_GAMMA = 0.01

# Folds temporais de desenvolvimento: cada ano avaliado com calibracao
# estritamente anterior.
FOLDS = [2021, 2022, 2023, 2024]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dev_residuals() -> pd.DataFrame:
    """Carrega a etapa `load dev residuals` do fluxo FireCast.

    Le as previsoes do backtest APA e **recusa** qualquer periodo do ano
    lacrado em diante. A trava e explicita para que o lacre nao dependa de
    disciplina humana."""
    preds = pd.read_csv(PRED_PATH)
    champ = preds[preds["model"] == CHAMPION].copy()
    if champ.empty:
        raise ValueError(f"nenhuma previsao de {CHAMPION!r} em {PRED_PATH}")

    leaked = champ[champ["ano"] >= SEALED_FROM]
    if len(leaked):
        raise ValueError(
            f"LACRE VIOLADO: {len(leaked)} linhas com ano >= {SEALED_FROM} no "
            "conjunto de desenvolvimento. 2025+ nao pode ser usado aqui."
        )

    champ["period"] = pd.PeriodIndex(
        pd.to_datetime(champ["ano"].astype(str) + "-" + champ["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    champ["abs_error"] = (champ["fire_count"] - champ["y_pred"]).abs()
    champ["is_dry"] = champ["mes"].isin(DRY_MONTHS)
    champ["is_critical"] = champ["mes"].isin(CRITICAL_MONTHS)
    return champ.sort_values(["period", "geocodigo"]).reset_index(drop=True)


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """Calcula a etapa `conformal quantile` do fluxo FireCast.

    Quantil conforme de amostra finita: ceil((n+1)(1-alpha))-esima estatistica
    de ordem."""
    vals = np.sort(np.asarray(scores, dtype=float))
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return float("nan")
    rank = min(max(math.ceil((len(vals) + 1) * (1.0 - alpha)), 1), len(vals))
    return float(vals[rank - 1])


def assign_volume_strata(calib: pd.DataFrame) -> dict:
    """Calcula a etapa `assign volume strata` do fluxo FireCast.

    Tercis de volume derivados SOMENTE da janela de calibracao (passado do
    corte). Usar volume do conjunto avaliado seria vazamento."""
    volume = calib.groupby("geocodigo")["fire_count"].sum()
    if len(volume) < 3:
        return {int(g): "all" for g in volume.index}
    q1, q2 = volume.quantile([1 / 3, 2 / 3])
    return {
        int(g): ("low" if v <= q1 else ("mid" if v <= q2 else "high"))
        for g, v in volume.items()
    }


def municipal_scale(df: pd.DataFrame, cut) -> dict:
    """Calcula a etapa `municipal scale` do fluxo FireCast.

    Escala por municipio conhecida em t-1: media dos ultimos 12 meses
    observados antes do corte. Usada pelo conformal normalizado para atacar a
    dependencia erro-escala diretamente."""
    window = df[(df["period"] >= cut - 12) & (df["period"] < cut)]
    if window.empty:
        return {}
    m = window.groupby("geocodigo")["fire_count"].mean()
    return {int(g): max(1.0, float(v)) for g, v in m.items()}


def run_config(residuals, alpha, eval_periods, method, window_months):
    """Executa a etapa `run config` do fluxo FireCast.

    Aplica uma configuracao conformal e devolve os intervalos com
    proveniencia completa por linha: estrato causal, tamanho EFETIVO da
    amostra de calibracao usada naquele quantil, nivel de fallback, banda,
    alpha efetivo e janela de calibracao realmente empregada."""
    rows = []
    alpha_t = alpha  # usado pelo metodo adaptativo

    for cut in sorted(eval_periods):
        test = residuals[residuals["period"] == cut]
        if test.empty:
            continue

        if window_months is None:
            calib = residuals[residuals["period"] < cut]
            win_start = calib["period"].min() if len(calib) else None
        else:
            lo = cut - window_months
            calib = residuals[(residuals["period"] >= lo) & (residuals["period"] < cut)]
            win_start = lo
        if calib.empty:
            continue

        strata = assign_volume_strata(calib)
        calib = calib.copy()
        calib["vol"] = calib["geocodigo"].astype(int).map(strata)
        t = test.copy()
        t["vol"] = t["geocodigo"].astype(int).map(strata).fillna("high")

        season = np.where(t["is_dry"].to_numpy(dtype=bool), "dry", "wet")
        calib_season = np.where(calib["is_dry"].to_numpy(dtype=bool), "dry", "wet")
        t["stratum"] = t["vol"].astype(str) + "_" + season
        calib["stratum"] = calib["vol"].astype(str) + "_" + calib_season

        alpha_eff = alpha_t if method == "adaptive_aci" else alpha
        alpha_eff = float(np.clip(alpha_eff, 0.001, 0.30))

        if method == "normalized":
            scale = municipal_scale(residuals, cut)
            calib["scale"] = calib["geocodigo"].astype(int).map(scale).fillna(1.0)
            t["scale"] = t["geocodigo"].astype(int).map(scale).fillna(1.0)
            calib["score"] = calib["abs_error"] / calib["scale"]
        else:
            calib["score"] = calib["abs_error"]
            t["scale"] = 1.0

        bands = np.empty(len(t), dtype=float)
        n_eff = np.empty(len(t), dtype=int)
        fallback = np.empty(len(t), dtype=object)

        for i, (stratum, sc) in enumerate(zip(t["stratum"].to_numpy(), t["scale"].to_numpy())):
            pool = calib[calib["stratum"] == stratum]["score"]
            level = "stratum"
            if len(pool) < MIN_STRATUM_CALIB:
                season_i = "dry" if str(stratum).endswith("_dry") else "wet"
                pool = calib[calib["stratum"].str.endswith("_" + season_i)]["score"]
                level = "season"
            if len(pool) < MIN_STRATUM_CALIB:
                pool = calib["score"]
                level = "global"
            q = conformal_quantile(pool.to_numpy(dtype=float), alpha_eff)
            bands[i] = q * float(sc) if method == "normalized" else q
            n_eff[i] = int(len(pool))
            fallback[i] = level

        y = t["fire_count"].to_numpy(dtype=float)
        p = t["y_pred"].to_numpy(dtype=float)
        low = np.clip(p - bands, 0.0, None)
        high = p + bands
        t["band"] = bands
        t["n_calib_effective"] = n_eff
        t["fallback_level"] = fallback
        t["alpha_effective"] = alpha_eff
        t["calibration_window_start"] = str(win_start) if win_start is not None else ""
        t["calibration_window_end"] = str(cut - 1)
        t["interval_low"] = low
        t["interval_high"] = high
        t["interval_width"] = high - low
        t["covered"] = (y >= low) & (y <= high)
        rows.append(t)

        if method == "adaptive_aci":
            # ACI: corrige alpha com o erro de cobertura JA OBSERVADO neste
            # corte. Nenhuma informacao futura entra.
            err = 1.0 - float(t["covered"].mean())
            alpha_t = alpha_t + ACI_GAMMA * (alpha - err)

    if not rows:
        raise ValueError("nenhum corte avaliavel para a configuracao pedida")
    return pd.concat(rows, ignore_index=True)


def candidate_grid():
    """Carrega a etapa `candidate grid` do fluxo FireCast.

    Familia PRE-DEFINIDA. Congelada antes de qualquer acesso a 2025."""
    cands = []
    for alpha in ALPHA_GRID:
        cands.append({"name": "expanding_mondrian", "method": "mondrian", "window": None, "alpha": alpha})
        for w in (24, 36, 48):
            cands.append({"name": "rolling_mondrian_" + str(w), "method": "mondrian", "window": w, "alpha": alpha})
        cands.append({"name": "normalized_expanding", "method": "normalized", "window": None, "alpha": alpha})
        cands.append({"name": "normalized_rolling_36", "method": "normalized", "window": 36, "alpha": alpha})
        cands.append({"name": "adaptive_aci_expanding", "method": "adaptive_aci", "window": None, "alpha": alpha})
    return cands


def evaluate_candidate(residuals, cand):
    """Calcula a etapa `evaluate candidate` do fluxo FireCast.

    Avalia a configuracao em multiplos folds temporais. A metrica de selecao e
    a cobertura MINIMA entre (fold x UF) -- robustez, nao media."""
    per_fold = []
    widths = []
    for year in FOLDS:
        periods = pd.period_range(str(year) + "-01", str(year) + "-12", freq="M")
        try:
            out = run_config(residuals, cand["alpha"], periods, cand["method"], cand["window"])
        except ValueError:
            continue
        out = out[out["ano"] == year]
        if out.empty:
            continue
        cov = float(out["covered"].mean())
        by_uf = out.groupby("uf")["covered"].mean()
        per_fold.append(
            {
                "fold": year,
                "coverage": cov,
                "worst_uf": float(by_uf.min()),
                "mean_width": float(out["interval_width"].mean()),
            }
        )
        widths.append(float(out["interval_width"].mean()))

    if not per_fold:
        return dict(cand, usable=False)

    covs = [f["coverage"] for f in per_fold]
    worst_ufs = [f["worst_uf"] for f in per_fold]
    out = dict(cand)
    out.update(
        {
            "usable": True,
            "n_folds": len(per_fold),
            "min_fold_coverage": float(np.min(covs)),
            "mean_fold_coverage": float(np.mean(covs)),
            "max_fold_coverage": float(np.max(covs)),
            "min_fold_uf_coverage": float(np.min(worst_ufs)),
            "mean_width": float(np.mean(widths)),
            "folds": per_fold,
        }
    )
    return out


def main() -> None:
    """Executa a etapa `main` do fluxo FireCast."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    residuals = load_dev_residuals()

    results = [evaluate_candidate(residuals, c) for c in candidate_grid()]
    usable = [r for r in results if r.get("usable")]
    table = pd.DataFrame(
        [{k: v for k, v in r.items() if k != "folds"} for r in usable]
    ).sort_values(["min_fold_uf_coverage", "min_fold_coverage"], ascending=False)
    table.to_csv(OUT_DIR / "candidate_selection.csv", index=False)

    # Selecao por ROBUSTEZ. Exige piso MAIS margem em TODOS os folds e em
    # TODAS as UFs, nao estoura o teto, e so entao usa largura como desempate.
    # A margem e o que impede de reeleger "o mais estreito que mal passou":
    # uma config com 0,9167 na pior UF nao compete com uma de 0,9375, mesmo
    # sendo mais estreita.
    floor = IC_MIN + DEV_MARGIN
    eligible = table[
        (table["min_fold_coverage"] >= floor)
        & (table["min_fold_uf_coverage"] >= floor)
        & (table["max_fold_coverage"] <= IC_MAX)
    ]
    if len(eligible):
        chosen = eligible.sort_values("mean_width").iloc[0].to_dict()
        decision = "SELECTED_NARROWEST_AMONG_THOSE_WITH_MARGIN_IN_EVERY_FOLD_AND_UF"
    else:
        chosen = table.sort_values(
            ["min_fold_uf_coverage", "min_fold_coverage"], ascending=False
        ).iloc[0].to_dict()
        decision = "NO_CANDIDATE_MET_FLOOR_IN_EVERY_FOLD_AND_UF_PICKED_MOST_ROBUST"

    frozen = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "configuracao conformal congelada ANTES de qualquer acesso a 2025",
        "sealed_year": SEALED_FROM,
        "development_window": "2015-2024 (2023-2024 rebaixado de holdout para desenvolvimento)",
        "selection_rule": (
            "cobertura minima entre folds E entre UFs deve atingir piso + margem "
            "de desenvolvimento; teto nao pode ser estourado; largura apenas "
            "como desempate entre as que ja tem folga"
        ),
        "dev_margin": DEV_MARGIN,
        "effective_dev_floor": IC_MIN + DEV_MARGIN,
        "selection_decision": decision,
        "folds": FOLDS,
        "ic_bounds": [IC_MIN, IC_MAX],
        "candidate_family": sorted({c["name"] for c in candidate_grid()}),
        "chosen": {
            "name": chosen["name"],
            "method": chosen["method"],
            "window": chosen["window"],
            "alpha": chosen["alpha"],
        },
        "chosen_dev_metrics": {
            "min_fold_coverage": chosen["min_fold_coverage"],
            "mean_fold_coverage": chosen["mean_fold_coverage"],
            "max_fold_coverage": chosen["max_fold_coverage"],
            "min_fold_uf_coverage": chosen["min_fold_uf_coverage"],
            "mean_width": chosen["mean_width"],
        },
        "predictions_sha256": sha256_file(PRED_PATH),
        "eligible_count": int(len(eligible)),
        "n_candidates_evaluated": int(len(usable)),
    }
    (OUT_DIR / "frozen_config.json").write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    per_fold_rows = []
    for r in usable:
        for f in r["folds"]:
            per_fold_rows.append(
                {"name": r["name"], "alpha": r["alpha"], "window": r["window"], **f}
            )
    pd.DataFrame(per_fold_rows).to_csv(OUT_DIR / "per_fold_detail.csv", index=False)

    print(json.dumps(
        {
            "n_candidates": len(usable),
            "eligible": int(len(eligible)),
            "decision": decision,
            "chosen": frozen["chosen"],
            "dev_metrics": frozen["chosen_dev_metrics"],
        },
        indent=2,
        ensure_ascii=False,
    ))
    print("")
    print("top 10 por robustez:")
    cols = [
        "name", "alpha", "window", "min_fold_coverage",
        "min_fold_uf_coverage", "max_fold_coverage", "mean_width",
    ]
    print(table[cols].head(10).to_string(index=False))


if __name__ == "__main__":
    main()
