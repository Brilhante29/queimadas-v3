"""Testes publicos do FireCast para tests/test_ingest_inpe_local.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.ingest_inpe_local import (
    fill_zero_months,
    flag_legacy_gaps,
    merge_sources,
    normalize_name,
)


def test_normalize_name_strips_state_suffixes_and_accents():
    """Verifica o comportamento `test normalize name strips state suffixes and accents`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    assert normalize_name("Aurora CE") == "aurora"
    assert normalize_name("Jati ceara") == "jati"
    assert normalize_name("Missão_Velha") == "missao velha"
    assert normalize_name("Campo_Sales") == "campos sales"  # alias
    assert normalize_name("ACARAÚ") == "acarau"


def _grid(geo, months, counts):
    """Executa a etapa `grid` do fluxo FireCast.
    
    A funcao faz parte de `tests/test_ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return pd.DataFrame(
        {
            "geocodigo": geo,
            "municipio_ibge": "X",
            "uf": "CE",
            "ano": [m[0] for m in months],
            "mes": [m[1] for m in months],
            "fire_count": counts,
            "assumed_zero": False,
            "source_name": "test",
        }
    )


def test_flag_legacy_gaps_quarantines_zero_fire_season_between_active_years():
    """Verifica o comportamento `test flag legacy gaps quarantines zero fire season between active years`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    months = [(y, m) for y in (2022, 2023, 2024) for m in range(1, 13)]
    counts = []
    for (y, m) in months:
        if m in (8, 9, 10, 11, 12):
            counts.append(0 if y == 2023 else 5)  # 2023 zerado entre anos ativos
        else:
            counts.append(0)
    out = flag_legacy_gaps(_grid(1, months, counts))
    gap = out[out["suspect_gap"]]
    assert set(gap["ano"]) == {2023}
    assert set(gap["mes"]) == {8, 9, 10, 11, 12}
    assert gap["fire_count"].isna().all()
    # anos vizinhos intactos
    assert out[(out["ano"] == 2022) & (out["mes"] == 10)]["fire_count"].iloc[0] == 5


def test_flag_legacy_gaps_keeps_genuine_zero_when_neighbors_also_low():
    """Verifica o comportamento `test flag legacy gaps keeps genuine zero when neighbors also low`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    months = [(y, m) for y in (2022, 2023, 2024) for m in range(1, 13)]
    counts = [0] * len(months)  # município sem fogo em nenhum ano
    out = flag_legacy_gaps(_grid(2, months, counts))
    assert not out["suspect_gap"].any()
    assert out["fire_count"].notna().all()


def test_fill_zero_months_respects_coverage_window():
    """Verifica o comportamento `test fill zero months respects coverage window`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    monthly = pd.DataFrame(
        {
            "geocodigo": [1],
            "municipio_ibge": ["X"],
            "uf": ["CE"],
            "ano": [2024],
            "mes": [3],
            "fire_count": [7],
            "frp_sum": [10.0],
            "frp_mean": [10.0],
            "frp_max": [10.0],
            "risco_fogo_mean": [np.nan],
            "dias_sem_chuva_mean": [np.nan],
            "source_name": ["test"],
        }
    )
    cov = pd.DataFrame(
        {
            "geocodigo": [1],
            "municipio_ibge": ["X"],
            "uf": ["CE"],
            "coverage_start": [pd.Period("2024-01", freq="M")],
            "coverage_end": [pd.Period("2024-06", freq="M")],
        }
    )
    out = fill_zero_months(monthly, cov, "test")
    assert len(out) == 6  # jan..jun apenas — nada além da janela
    assert out.loc[out["mes"] == 3, "fire_count"].iloc[0] == 7
    assert out.loc[out["mes"] == 1, "fire_count"].iloc[0] == 0
    assert out.loc[out["mes"] == 1, "assumed_zero"].iloc[0]
    assert not out.loc[out["mes"] == 3, "assumed_zero"].iloc[0]


def test_fill_zero_months_excludes_window_after_export_cutoff():
    """Verifica o comportamento `test fill zero months excludes window after export cutoff`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    monthly = pd.DataFrame(
        {
            "geocodigo": [1], "municipio_ibge": ["X"], "uf": ["CE"],
            "ano": [2025], "mes": [11], "fire_count": [2],
            "frp_sum": [10.0], "frp_mean": [5.0], "frp_max": [6.0],
            "risco_fogo_mean": [np.nan], "dias_sem_chuva_mean": [np.nan],
            "source_name": ["test"],
        }
    )
    # Export dated October cannot prove coverage for an observation in November.
    cov = pd.DataFrame(
        {
            "geocodigo": [1], "municipio_ibge": ["X"], "uf": ["CE"],
            "coverage_start": [pd.Period("2025-11", freq="M")],
            "coverage_end": [pd.Period("2025-10", freq="M")],
        }
    )
    out = fill_zero_months(monthly, cov, "test")
    assert out.empty


def test_merge_sources_prefers_ref_early_and_legacy_late():
    """Verifica o comportamento `test merge sources prefers ref early and legacy late`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    cols = ["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count",
            "assumed_zero", "source_name"]
    ref = pd.DataFrame(
        [[1, "X", "CE", 2024, 10, 3, False, "inpe_bdq_aqua_ref"],
         [1, "X", "CE", 2025, 2, 0, True, "inpe_bdq_aqua_ref"]],
        columns=cols,
    )
    leg = pd.DataFrame(
        [[1, "X", "CE", 2024, 10, 0, True, "inpe_bdq_legacy"],
         [1, "X", "CE", 2025, 2, 8, False, "inpe_bdq_legacy"],
         [1, "X", "CE", 2023, 5, 2, False, "inpe_bdq_legacy"]],
        columns=cols,
    )
    out = merge_sources(ref, leg)
    r2410 = out[(out["ano"] == 2024) & (out["mes"] == 10)].iloc[0]
    r2502 = out[(out["ano"] == 2025) & (out["mes"] == 2)].iloc[0]
    r2305 = out[(out["ano"] == 2023) & (out["mes"] == 5)].iloc[0]
    assert r2410["target_source"] == "inpe_bdq_aqua_ref" and r2410["fire_count"] == 3
    assert r2502["target_source"] == "inpe_bdq_legacy" and r2502["fire_count"] == 8
    assert r2305["target_source"] == "inpe_bdq_legacy"  # fallback onde ref não cobre
    # sem duplicatas de chave
    assert not out.duplicated(subset=["geocodigo", "ano", "mes"]).any()
