"""Testes publicos do FireCast para tests/test_ingestion_semantic_guards.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import pandas as pd
import pytest


def test_firms_requires_real_municipal_identity():
    """Verifica o comportamento `test firms requires real municipal identity`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.data.ingest_firms import aggregate_firms_monthly

    raw = pd.DataFrame(
        {
            "latitude": [-7.1],
            "longitude": [-39.2],
            "state": ["CE"],
            "year": [2024],
            "month": [10],
            "frp": [12.0],
        }
    )

    with pytest.raises(ValueError, match="no municipality"):
        aggregate_firms_monthly(raw)


def test_firms_requires_real_state_identity():
    """Verifica o comportamento `test firms requires real state identity`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.data.ingest_firms import aggregate_firms_monthly

    raw = pd.DataFrame(
        {
            "municipio": ["Crato"],
            "year": [2024],
            "month": [10],
            "frp": [12.0],
        }
    )

    with pytest.raises(ValueError, match="no estado"):
        aggregate_firms_monthly(raw)


def test_enso_local_fallback_requires_explicit_opt_in(monkeypatch):
    """Verifica o comportamento `test enso local fallback requires explicit opt in`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    import src.data.ingest_enso as enso

    class Response:
        """Representa `Response` dentro do fluxo FireCast.
        
        A classe concentra dados ou comportamento usado por `tests/test_ingestion_semantic_guards.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
        status_code = 503
        text = "service unavailable"

    monkeypatch.setattr(enso.requests, "get", lambda *args, **kwargs: Response())

    with pytest.raises(RuntimeError, match="refusing local fallback"):
        enso.fetch_enso_data(start_year=2024, end_year=2024)

    fallback = enso.fetch_enso_data(start_year=2024, end_year=2024, allow_local_fallback=True)
    assert set(fallback["enso_is_fallback"]) == {True}
    assert set(fallback["enso_source"]) == {"local_enso_database_fallback"}


def test_legacy_simulation_modules_are_marked_synthetic():
    """Verifica o comportamento `test legacy simulation modules are marked synthetic`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.data.ingest_climate_consolidated import generate_climate_data
    from src.data.ingest_fire_consolidated import generate_consolidated_fire_data

    climate = generate_climate_data(scope="ceara", start_year=2024, end_year=2024, seed=1)
    fire = generate_consolidated_fire_data(scope="ceara", start_year=2024, end_year=2024, seed=1)

    assert set(climate["synthetic_flag"]) == {True}
    assert set(fire["synthetic_flag"]) == {True}
