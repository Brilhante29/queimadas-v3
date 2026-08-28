"""Coloca intervalo no ganho pontual de 2025, que foi reportado como numero seco.

O achado que motivou
--------------------
O registro do teste selado dizia "ganho de -13,5%" e "a previsao pontual e
robusta" a partir de **um ano**: 432 linhas, 36 series correlacionadas, 12
meses. Numero pontual sem intervalo, e adjetivo mais forte do que n = 1 ano
sustenta.

O que este script faz
---------------------
Bootstrap por **mes** -- o cluster natural, ja que municipios do mesmo mes
compartilham o regime climatico daquele mes e nao sao independentes. Reamostra
os 12 meses de 2025 com reposicao, concatena e recalcula o WAPE global, do
mesmo jeito que o EXP-10 faz com cortes.

Tambem mede o vies do total: o champion subestimou 2025.

**Nao e tuning.** Nada e selecionado aqui; o numero ja estava publicado. Isto
so mede a incerteza que faltava nele.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREDS = PROJECT_ROOT / "outputs" / "apa_araripe" / "g5_final_2025" / "predictions_2025.csv"
OUT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "point_gain_2025_uncertainty.json"

CHAMPION = "climatology_apa_intensity12"
BASELINE = "climatology_municipal"
N_BOOT = 5000
SEED = 20260828


def wape(y: np.ndarray, yhat: np.ndarray) -> float:
    """WAPE. Indefinido com denominador zero."""
    denom = np.abs(y).sum()
    if denom == 0:
        return float("nan")
    return float(np.abs(y - yhat).sum() / denom)


def main() -> int:
    """Calcula o IC do ganho de 2025 e o vies do total."""
    df = pd.read_csv(PREDS)
    wide = df.pivot_table(
        index=["geocodigo", "uf", "ano", "mes"], columns="model", values="y_pred"
    ).reset_index()
    obs = (
        df[df["model"] == CHAMPION][["geocodigo", "ano", "mes", "fire_count"]]
        .drop_duplicates()
    )
    wide = wide.merge(obs, on=["geocodigo", "ano", "mes"], how="inner")

    y = wide["fire_count"].to_numpy(float)
    champ = wide[CHAMPION].to_numpy(float)
    base = wide[BASELINE].to_numpy(float)

    point_champ = wape(y, champ)
    point_base = wape(y, base)
    point_delta = point_champ - point_base
    relative = point_delta / point_base

    # Bootstrap por mes: municipios do mesmo mes compartilham regime e nao sao
    # independentes, entao o mes e a unidade de reamostragem honesta.
    rng = np.random.default_rng(SEED)
    by_month = {m: g for m, g in wide.groupby("mes")}
    months = list(by_month)
    deltas, relatives = [], []
    for _ in range(N_BOOT):
        sample = rng.choice(months, size=len(months), replace=True)
        block = pd.concat([by_month[m] for m in sample], ignore_index=True)
        yy = block["fire_count"].to_numpy(float)
        if np.abs(yy).sum() == 0:
            continue
        wc = wape(yy, block[CHAMPION].to_numpy(float))
        wb = wape(yy, block[BASELINE].to_numpy(float))
        deltas.append(wc - wb)
        relatives.append((wc - wb) / wb if wb else np.nan)

    d = np.asarray(deltas, float)
    r = np.asarray([x for x in relatives if np.isfinite(x)], float)
    lo, hi = float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))
    rlo, rhi = float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))
    p_better = float((d < 0).mean())
    significant = hi < 0

    total_obs = float(y.sum())
    total_champ = float(champ.sum())
    bias = (total_champ - total_obs) / total_obs

    report = {
        "check": "incerteza do ganho pontual de 2025",
        "why": (
            "O ganho de -13,5% foi publicado como numero seco, a partir de um "
            "unico ano com 36 series correlacionadas, e acompanhado de 'a previsao "
            "pontual e robusta' -- adjetivo mais forte do que n = 1 ano sustenta."
        ),
        "resampling_unit": "mes (municipios do mesmo mes nao sao independentes)",
        "n_rows": int(len(wide)),
        "n_months": len(months),
        "bootstrap_n": N_BOOT,
        "wape_baseline": round(point_base, 4),
        "wape_champion": round(point_champ, 4),
        "delta_wape": round(point_delta, 4),
        "relative_gain": round(relative, 4),
        "delta_wape_ci95": [round(lo, 4), round(hi, 4)],
        "relative_gain_ci95": [round(rlo, 4), round(rhi, 4)],
        "prob_champion_better": round(p_better, 4),
        "significant_at_95": bool(significant),
        "total_bias": {
            "observed": round(total_obs, 1),
            "predicted": round(total_champ, 1),
            "relative_bias": round(bias, 4),
            "reading": (
                f"O champion subestimou o total de 2025 em {abs(bias):.1%}. "
                "Subestimar em contexto de risco de fogo e o lado errado do erro."
                if bias < 0
                else f"O champion superestimou o total de 2025 em {bias:.1%}."
            ),
        },
        "verdict": (
            f"O ganho e significativo ao nivel de 95% (IC95 do delta "
            f"[{lo:.4f}, {hi:.4f}])."
            if significant
            else f"O ganho NAO e significativo ao nivel de 95%: o IC95 do delta "
            f"[{lo:.4f}, {hi:.4f}] cruza o zero. Um ano nao sustenta a afirmacao "
            "de que 'a previsao pontual e robusta'."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"WAPE 2025: baseline {point_base:.4f} -> champion {point_champ:.4f}")
    print(f"delta {point_delta:+.4f}  IC95 [{lo:.4f}, {hi:.4f}]  P(melhor)={p_better:.4f}")
    print(f"ganho relativo {relative:+.1%}  IC95 [{rlo:+.1%}, {rhi:+.1%}]")
    print(f"vies do total: {bias:+.1%}")
    print(f"\n{report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
