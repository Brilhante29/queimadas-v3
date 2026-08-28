"""Testa o champion contra baselines que tambem corrigem nivel.

O achado que motivou
--------------------
O G2 compara o champion contra `climatology_municipal`: media historica de
longo prazo, sem tendencia e sem janela recente. O champion e essa mesma
climatologia multiplicada por um escalar de nivel regional. Como a serie tem
degrau em 2012 e tendencia, boa parte do ganho pode ser simplesmente correcao
de nivel -- que **qualquer** baseline com janela recente tambem faria.

"Bate a climatologia municipal de longo prazo" e afirmacao mais fraca do que
"bate um baseline competente", e so a primeira estava demonstrada.

O que este script faz
---------------------
Roda, no mesmo protocolo walk-forward de 120 cortes, baselines que corrigem
nivel de formas diferentes:

- `climatology_municipal`      media de longo prazo (o baseline do G2)
- `climatology_recent_60`      mesma climatologia, so os 60 meses anteriores
- `seasonal_naive_12`          valor do mesmo mes do ano anterior
- `climatology_x_municipal_r12` climatologia x razao dos ultimos 12 meses **do
                               proprio municipio** (correcao de nivel local, em
                               vez da regional que o champion usa)

Todos estritamente causais: para o corte (Y, M) so entra periodo < (Y, M).

**Isto e diagnostico, nao selecao.** O EXP-10 esta congelado. O objetivo e
medir o quanto da afirmacao se sustenta, inclusive se o resultado for
desfavoravel -- especialmente se for.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1" / "municipality_month.csv"
SCOPE = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
CHAMPION_PREDS = PROJECT_ROOT / "outputs" / "apa_araripe" / "exp10" / "predictions_2015_2024.csv"
OUT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "competent_baselines.json"

FIRST_CUT = (2015, 1)
LAST_CUT = (2024, 12)
TRAILING = 12
RECENT_MONTHS = 60
CRITICAL_MONTHS = (10, 11)
SHRINK = 100.0
RATIO_CLIP = (0.5, 2.0)
N_BOOT = 2000
SEED = 20260828


def period(ano: int, mes: int) -> int:
    """Converte (ano, mes) num inteiro ordenavel."""
    return ano * 12 + (mes - 1)


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    """WAPE. Indefinido quando o denominador e zero."""
    denom = np.abs(y).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(y - yhat).sum() / denom)


def build_predictions(df: pd.DataFrame) -> pd.DataFrame:
    """Gera todas as previsoes baseline para os 120 cortes."""
    df = df.copy()
    df["p"] = df.apply(lambda r: period(int(r["ano"]), int(r["mes"])), axis=1)

    cuts = [
        (y, m)
        for y in range(FIRST_CUT[0], LAST_CUT[0] + 1)
        for m in range(1, 13)
        if period(FIRST_CUT[0], FIRST_CUT[1]) <= period(y, m) <= period(LAST_CUT[0], LAST_CUT[1])
    ]

    rows = []
    for ano, mes in cuts:
        cut_p = period(ano, mes)
        past = df[df["p"] < cut_p]           # estritamente passado
        target = df[df["p"] == cut_p]
        if past.empty or target.empty:
            continue

        # 1. climatologia de longo prazo: media do municipio naquele mes
        long_run = (
            past[past["mes"] == mes].groupby("geocodigo")["fire_count"].mean()
        )

        # 2. climatologia recente: so os RECENT_MONTHS meses anteriores
        recent = past[past["p"] >= cut_p - RECENT_MONTHS]
        recent_clim = (
            recent[recent["mes"] == mes].groupby("geocodigo")["fire_count"].mean()
        )

        # 3. naive sazonal: mesmo mes do ano anterior
        last_year = past[past["p"] == cut_p - 12].set_index("geocodigo")["fire_count"]

        # 4. razao de nivel do PROPRIO municipio nos ultimos 12 meses
        window = past[past["p"] >= cut_p - TRAILING]
        obs_by_muni = window.groupby("geocodigo")["fire_count"].sum()
        exp_by_muni = (
            window.assign(
                clim=window["geocodigo"].map(
                    past.groupby(["geocodigo", "mes"])["fire_count"].mean().groupby("geocodigo").mean()
                )
            )
            .groupby("geocodigo")["clim"]
            .sum()
        )
        muni_ratio = (obs_by_muni + 0.0) / exp_by_muni.replace(0, np.nan)
        # Mesmo encolhimento e mesmo clip do champion, para que a comparacao
        # meça a escolha regional-x-local e nao a ausencia de regularizacao.
        shrink_w = obs_by_muni / (obs_by_muni + SHRINK)
        muni_ratio = 1.0 + (muni_ratio - 1.0) * shrink_w
        muni_ratio = muni_ratio.clip(*RATIO_CLIP).fillna(1.0)

        for r in target.itertuples():
            g = int(r.geocodigo)
            base = float(long_run.get(g, np.nan))
            if not np.isfinite(base):
                continue
            rows.append(
                {
                    "cut": f"{ano}-{mes:02d}",
                    "ano": ano,
                    "mes": mes,
                    "geocodigo": g,
                    "uf": r.uf,
                    "fire_count": float(r.fire_count),
                    "climatology_municipal": base,
                    "climatology_recent_60": float(recent_clim.get(g, base)),
                    "seasonal_naive_12": float(last_year.get(g, base)),
                    "climatology_x_municipal_r12": base * float(muni_ratio.get(g, 1.0)),
                }
            )
    return pd.DataFrame(rows)


def bootstrap_delta(
    preds: pd.DataFrame, champion_col: str, other_col: str, rng: np.random.Generator
) -> tuple[float, float, float]:
    """IC95 do delta de WAPE global, reamostrando CORTES.

    Mesmo estimando do EXP-10: reamostra cortes, concatena e recalcula o WAPE
    global sobre a concatenacao."""
    by_cut = {c: g for c, g in preds.groupby("cut")}
    cuts = list(by_cut)
    deltas = []
    for _ in range(N_BOOT):
        sample = rng.choice(cuts, size=len(cuts), replace=True)
        block = pd.concat([by_cut[c] for c in sample], ignore_index=True)
        y = block["fire_count"].to_numpy(float)
        if np.abs(y).sum() == 0:
            continue
        deltas.append(
            wape(y, block[champion_col].to_numpy(float))
            - wape(y, block[other_col].to_numpy(float))
        )
    arr = np.asarray(deltas, dtype=float)
    return (
        float(np.percentile(arr, 2.5)),
        float(np.percentile(arr, 97.5)),
        float((arr < 0).mean()),
    )


def main() -> int:
    """Compara o champion com cada baseline e grava o relatorio."""
    df = pd.read_csv(TARGET)
    scope = set(pd.read_csv(SCOPE)["geocodigo"].astype(int))
    df = df[df["geocodigo"].isin(scope)]

    preds = build_predictions(df)

    champ = pd.read_csv(CHAMPION_PREDS)
    champ = champ[champ["model"] != "climatology_municipal"][
        ["cut", "geocodigo", "y_pred"]
    ].rename(columns={"y_pred": "champion"})
    preds = preds.merge(champ, on=["cut", "geocodigo"], how="inner")
    if preds.empty:
        raise ValueError("juncao com as previsoes do champion ficou vazia")

    y = preds["fire_count"].to_numpy(float)
    crit = preds["mes"].isin(CRITICAL_MONTHS).to_numpy()

    models = [
        "champion",
        "climatology_municipal",
        "climatology_recent_60",
        "seasonal_naive_12",
        "climatology_x_municipal_r12",
    ]
    rng = np.random.default_rng(SEED)

    results = {}
    for m in models:
        yhat = preds[m].to_numpy(float)
        results[m] = {
            "wape_all": round(wape(y, yhat), 4),
            "wape_critical_out_nov": round(wape(y[crit], yhat[crit]), 4),
        }

    comparisons = {}
    for m in models:
        if m == "champion":
            continue
        lo, hi, p_neg = bootstrap_delta(preds, "champion", m, rng)
        beats = hi < 0
        comparisons[m] = {
            "delta_wape_champion_minus_baseline": round(
                results["champion"]["wape_all"] - results[m]["wape_all"], 4
            ),
            "bootstrap_delta_ci95": [round(lo, 4), round(hi, 4)],
            "prob_champion_better": round(p_neg, 4),
            "champion_significantly_better": bool(beats),
        }

    still_wins = [m for m, c in comparisons.items() if c["champion_significantly_better"]]
    loses_or_ties = [m for m in comparisons if m not in still_wins]

    report = {
        "check": "champion contra baselines que tambem corrigem nivel",
        "why": (
            "O G2 so comparou contra climatologia de longo prazo. Como a serie "
            "tem degrau em 2012 e tendencia, parte do ganho poderia ser correcao "
            "de nivel que qualquer baseline com janela recente tambem faria."
        ),
        "status": "DIAGNOSTICO -- nao altera o EXP-10, que esta congelado",
        "protocol": "walk-forward 2015-2024, 120 cortes, treino estritamente no passado",
        "scope": "apa_chapada_araripe (36 municipios)",
        "n_predictions": int(len(preds)),
        "bootstrap_n": N_BOOT,
        "bootstrap_estimand": "WAPE global recalculado por reamostra de cortes",
        "metrics": results,
        "comparisons": comparisons,
        "champion_beats_significantly": sorted(still_wins),
        "champion_does_not_beat_significantly": sorted(loses_or_ties),
        "verdict": (
            "O champion supera TODOS os baselines testados com IC95 do delta "
            "inteiramente negativo, inclusive os que corrigem nivel. A afirmacao "
            "do G2 sobrevive a um teste mais duro do que o que ela mesma fazia."
            if not loses_or_ties
            else "O champion NAO supera com significancia: "
            + ", ".join(sorted(loses_or_ties))
            + ". A afirmacao do G2 e mais fraca do que parecia -- parte do ganho "
            "sobre a climatologia de longo prazo e correcao de nivel que outro "
            "baseline tambem entrega."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"n = {len(preds)} previsoes\n")
    print(f"{'modelo':32s} {'WAPE':>8s} {'out-nov':>8s}")
    for m in models:
        print(f"{m:32s} {results[m]['wape_all']:8.4f} {results[m]['wape_critical_out_nov']:8.4f}")
    print("\nchampion contra cada baseline (IC95 do delta de WAPE global):")
    for m, c in comparisons.items():
        mark = "VENCE" if c["champion_significantly_better"] else "NAO VENCE"
        print(f"  {m:32s} {c['bootstrap_delta_ci95']}  P={c['prob_champion_better']:.4f}  {mark}")
    print(f"\n{report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
