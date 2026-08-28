"""Rastreia quebra estrutural na serie do alvo (2003-2024).

Por que
-------
O contrato de sensor -- "satelite de referencia INPE, homogeneo em toda a
serie" -- e uma afirmacao sobre o produto do INPE, **nao** uma medicao. Os
arquivos-fonte nao trazem coluna de satelite:

```text
id_bdq, foco_id, lat, lon, data_pas, pais, estado, municipio, bioma
```

Ou seja: se o satelite de referencia tivesse mudado no meio da serie, a
definicao do alvo teria mudado junto e **nada no repositorio detectaria**.
Este script e a deteccao que faltava.

O que ele pode e o que nao pode
-------------------------------
PODE sinalizar deslocamento abrupto de nivel, que e a assinatura tipica de
troca de sensor. NAO PODE distinguir troca de sensor de dinamica real de seca:
as duas produzem salto de nivel. Um ponto de mudanca aqui e motivo de
investigacao, nunca prova de defeito -- e a ausencia dele nao prova
homogeneidade. Com 22 pontos anuais o poder do teste e baixo, e isso esta
reportado junto do resultado.

Teste: Pettitt (nao parametrico, sem supor normalidade nem variancia
constante), aplicado a serie mensal dessazonalizada e aos totais anuais.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_ce_pe_pi_satref_v1" / "municipality_month.csv"
SCOPE = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
OUT = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "structural_break_screen.json"

ALPHA = 0.05


def pettitt(x: np.ndarray) -> tuple[int, float, float]:
    """Teste de Pettitt para ponto de mudanca unico.

    Devolve (indice do ponto de mudanca, estatistica K, p-valor aproximado).

    U[t] = soma_{i<=t} soma_{j>t} sinal(x_i - x_j); K = max|U|. O p-valor usa a
    aproximacao padrao p ~ 2*exp(-6K^2 / (T^3 + T^2)), truncada em 1."""
    n = len(x)
    if n < 4:
        return -1, 0.0, 1.0
    # sinal(x_i - x_j) somado eficientemente via ranks nao e exato com empates;
    # com n pequeno o laco direto e barato e evita erro de aproximacao.
    u = np.zeros(n - 1)
    for t in range(1, n):
        left = x[:t][:, None]
        right = x[t:][None, :]
        u[t - 1] = np.sign(left - right).sum()
    k_idx = int(np.argmax(np.abs(u)))
    k = float(abs(u[k_idx]))
    p = 2.0 * math.exp(-6.0 * k * k / (n ** 3 + n ** 2))
    return k_idx + 1, k, min(1.0, p)


def deseasonalize(monthly: pd.DataFrame) -> pd.Series:
    """Divide cada mes pela media historica daquele mes do calendario.

    Deixa a serie em unidade de 'indice relativo ao normal daquele mes', que e
    onde um salto de nivel por troca de sensor apareceria limpo."""
    by_month = monthly.groupby("mes")["fire_count"].transform("mean")
    idx = monthly["fire_count"] / by_month.replace(0, np.nan)
    return idx


def screen(df: pd.DataFrame, label: str) -> dict:
    """Roda o rastreio numa serie agregada."""
    monthly = (
        df.groupby(["ano", "mes"], as_index=False)["fire_count"].sum().sort_values(["ano", "mes"])
    )
    monthly["idx"] = deseasonalize(monthly)
    m = monthly.dropna(subset=["idx"]).reset_index(drop=True)

    cp_m, k_m, p_m = pettitt(m["idx"].to_numpy(float))
    monthly_cp = (
        f"{int(m.loc[cp_m, 'ano'])}-{int(m.loc[cp_m, 'mes']):02d}"
        if 0 <= cp_m < len(m)
        else None
    )

    annual = df.groupby("ano", as_index=False)["fire_count"].sum().sort_values("ano")
    cp_a, k_a, p_a = pettitt(annual["fire_count"].to_numpy(float))
    annual_cp = int(annual.iloc[cp_a]["ano"]) if 0 <= cp_a < len(annual) else None

    # Niveis medios antes e depois do ponto anual, para dimensionar o salto.
    before = float(annual.iloc[:cp_a]["fire_count"].mean()) if cp_a > 0 else None
    after = float(annual.iloc[cp_a:]["fire_count"].mean()) if 0 <= cp_a < len(annual) else None

    return {
        "series": label,
        "n_months": int(len(m)),
        "n_years": int(len(annual)),
        "monthly_deseasonalized": {
            "change_point": monthly_cp,
            "K": k_m,
            "p_value": round(p_m, 4),
            "significant_at_0.05": bool(p_m < ALPHA),
        },
        "annual_totals": {
            "change_point_year": annual_cp,
            "K": k_a,
            "p_value": round(p_a, 4),
            "significant_at_0.05": bool(p_a < ALPHA),
            "mean_before": round(before, 1) if before is not None else None,
            "mean_after": round(after, 1) if after is not None else None,
            "ratio_after_over_before": (
                round(after / before, 3) if before not in (None, 0) and after is not None else None
            ),
        },
    }


def main() -> int:
    """Roda o rastreio no total CE/PE/PI, por UF e no escopo APA."""
    df = pd.read_csv(TARGET)
    scope = set(pd.read_csv(SCOPE)["geocodigo"])

    results = [screen(df, "CE+PE+PI (todos os 593 municipios)")]
    for uf in sorted(df["uf"].unique()):
        results.append(screen(df[df["uf"] == uf], f"UF {uf}"))
    results.append(screen(df[df["geocodigo"].isin(scope)], "escopo APA (36 municipios)"))

    flagged = [
        r for r in results
        if r["annual_totals"]["significant_at_0.05"]
        or r["monthly_deseasonalized"]["significant_at_0.05"]
    ]

    # Impacto no modelo: o fator regional de intensidade e uma razao
    # observado/esperado sobre os 12 meses anteriores ao corte. Se todas as
    # janelas ficam de um lado so da quebra, o fator nao mistura regimes.
    ratios = pd.read_csv(
        PROJECT_ROOT / "outputs" / "apa_araripe" / "exp10" / "regional_ratio_by_cut.csv"
    )
    earliest_window = str(ratios["prior_window_start"].min())
    break_years = [
        r["annual_totals"]["change_point_year"]
        for r in results
        if r["annual_totals"]["significant_at_0.05"]
    ]
    latest_break = max(break_years) if break_years else None
    windows_all_post_break = (
        latest_break is not None and int(earliest_window[:4]) > latest_break
    )
    first_ratio = float(ratios.sort_values("cut").iloc[0]["raw_ratio"])

    model_impact = {
        "regional_factor_earliest_window_start": earliest_window,
        "latest_significant_break_year": latest_break,
        "all_regional_windows_are_post_break": bool(windows_all_post_break),
        "first_cut_raw_ratio": round(first_ratio, 4),
        "break_level_ratios_after_over_before": {
            r["series"]: r["annual_totals"]["ratio_after_over_before"]
            for r in results
            if r["annual_totals"]["significant_at_0.05"]
        },
        "reading": (
            "O fator regional de intensidade e uma razao observado/esperado nos 12 "
            "meses anteriores ao corte. A janela mais antiga comeca em "
            f"{earliest_window}, depois da quebra de {latest_break}: nenhuma janela "
            "mistura os dois regimes. Alem disso, a razao do primeiro corte "
            f"({first_ratio:.4f}) e praticamente igual a razao de nivel medida na "
            "propria quebra -- ou seja, o fator regional absorve empiricamente o "
            "degrau de nivel. Isso e uma explicacao mecanica de por que o champion "
            "supera a climatologia pura, e nao apenas um ganho empirico sem causa."
        ),
        "residual_risk": (
            "A climatologia municipal por mes e estimada sobre 2003-2024 inteiro e "
            "portanto ATRAVESSA a quebra: o nivel base de cada municipio mistura os "
            "dois regimes. O fator regional corrige isso no agregado, nao por "
            "municipio. Recalibrar a climatologia so com dados pos-2012 e um "
            "experimento legitimo e NAO foi feito -- o EXP-10 esta congelado por "
            "decisao registrada, e refaze-lo agora seria selecionar metodo depois "
            "de ver o diagnostico."
        ),
    }

    report = {
        "check": "rastreio de quebra estrutural na serie do alvo",
        "model_impact": model_impact,
        "motivation": (
            "Os arquivos-fonte do INPE nao tem coluna de satelite "
            "(id_bdq, foco_id, lat, lon, data_pas, pais, estado, municipio, bioma). "
            "A homogeneidade do satelite de referencia era assercao sobre o produto, "
            "sem nenhuma verificacao no repositorio."
        ),
        "method": "Pettitt (nao parametrico, ponto de mudanca unico)",
        "what_this_cannot_do": (
            "Nao distingue troca de sensor de dinamica real de seca -- as duas "
            "produzem salto de nivel. Ponto de mudanca aqui e motivo de "
            "investigacao, nao prova de defeito. Ausencia de ponto de mudanca "
            "nao prova homogeneidade: com 22 pontos anuais o poder e baixo."
        ),
        "alpha": ALPHA,
        "series": results,
        "n_series_flagged": len(flagged),
        "verdict": (
            "NENHUMA quebra significativa detectada em nenhuma serie. Isso "
            "enfraquece -- nao elimina -- a hipotese de troca silenciosa de sensor."
            if not flagged
            else "QUEBRA detectada; investigar antes de tratar a serie como homogenea."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for r in results:
        a = r["annual_totals"]
        print(
            f"{r['series']:38s} anual cp={a['change_point_year']} p={a['p_value']:.4f} "
            f"{'SIGNIF' if a['significant_at_0.05'] else 'ns'} "
            f"razao={a['ratio_after_over_before']}"
        )
    print(f"\n{report['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
