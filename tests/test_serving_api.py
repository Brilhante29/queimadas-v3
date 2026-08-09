"""Testes publicos do FireCast para tests/test_serving_api.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import json

from fastapi.testclient import TestClient

from src.production.champion_climatology import package
from src.production.serving_api import PRODUCTION_STATUS_SERVING, PRODUCTION_STATUS_SUMMARY, create_app


def test_serving_api_predicts_with_packaged_artifact(tmp_path):
    """Verifica o comportamento `test serving api predicts with packaged artifact`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    client = TestClient(create_app(tmp_path / "model.json"))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["production_status"] == PRODUCTION_STATUS_SERVING

    response = client.post(
        "/v1/predict",
        json={"geocodigo": 2300101, "ano": 2026, "mes": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["geocodigo"] == 2300101
    assert body["mes"] == 10
    assert body["y_pred"] >= 0
    assert body["model_name"] == "climatology_regional_intensity12"
    assert body["regional_intensity_ratio"] > 0
    assert body["regional_intensity_ratio_period"]
    assert body["interval_p90_high"] >= body["interval_p90_low"]
    assert body["production_status"] == PRODUCTION_STATUS_SERVING


def test_serving_api_fails_closed_when_artifact_missing(tmp_path):
    """Verifica o comportamento `test serving api fails closed when artifact missing`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app(tmp_path / "missing_model.json"))

    health = client.get("/health")
    assert health.status_code == 503

    response = client.post(
        "/v1/predict",
        json={"geocodigo": 2300101, "ano": 2026, "mes": 10},
    )

    assert response.status_code == 503
    assert "Modelo indispon" in response.json()["detail"]


def test_serving_api_champion_summary_uses_real_backtest_evidence():
    """Verifica o comportamento `test serving api champion summary uses real backtest evidence`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["model_name"] == "climatology_regional_intensity12"
    assert 0 < body["all_wape"] < 2
    assert body["g5_coverage_overall"] == body["coverage_test_2024_overall"]
    assert body["g5_coverage_overall"] >= 0.90
    assert body["production_status"] == PRODUCTION_STATUS_SUMMARY
    assert any(key.startswith("G5") for key in body["gates"])


def test_serving_api_champion_monthly_series_has_24_real_cuts():
    """Verifica o comportamento `test serving api champion monthly series has 24 real cuts`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/monthly_series")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 24
    assert {"cut", "ano", "mes", "y_sum", "pred_sum", "wape"} <= body[0].keys()


def test_serving_api_champion_municipio_monthly_series_returns_24_real_cuts_for_abaiara():
    """Verifica o comportamento `test serving api champion municipio monthly series returns 24 real cuts for abaiara`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/municipio_monthly_series", params={"geocodigo": 2300101})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 24
    assert {"mes", "ano", "y_sum", "pred_sum", "cobertura_completa"} <= body[0].keys()
    assert all(row["ano"] in (2023, 2024) for row in body)
    assert all(row["cobertura_completa"] is True for row in body)


def test_serving_api_champion_municipio_monthly_series_filters_by_year():
    """Verifica o comportamento `test serving api champion municipio monthly series filters by year`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get(
        "/v1/champion/municipio_monthly_series",
        params={"geocodigo": 2300101, "ano": 2024},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 12
    assert {row["mes"] for row in body} == set(range(1, 13))
    assert all(row["cobertura_completa"] is True for row in body)


def test_serving_api_champion_municipio_monthly_series_fails_closed_for_unknown_geocodigo():
    """Verifica o comportamento `test serving api champion municipio monthly series fails closed for unknown geocodigo`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/municipio_monthly_series", params={"geocodigo": 9999999})

    assert response.status_code == 404
    assert "9999999" in response.json()["detail"]


def test_serving_api_champion_municipio_monthly_series_returns_404_for_valid_geocodigo_without_backtest_rows():
    """Verifica o comportamento `test serving api champion municipio monthly series returns 404 for valid geocodigo without backtest rows`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    # 2308104 = Mauriti, municipio real do Cariri (geocode IBGE valido) mas
    # sem nenhuma linha no backtest do champion (predictions_2023_2024.csv).
    response = client.get("/v1/champion/municipio_monthly_series", params={"geocodigo": 2308104})

    assert response.status_code == 404
    assert response.json()["detail"]


def test_serving_api_champion_municipio_monthly_series_flags_partial_2024_coverage_for_crato():
    """Verifica o comportamento `test serving api champion municipio monthly series flags partial 2024 coverage for crato`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    # 2304202 = Crato: 2024 so tem meses 1-7 no backtest (falta a temporada
    # de incendio ago-dez), enquanto 2023 tem os 12 meses completos.
    partial = client.get(
        "/v1/champion/municipio_monthly_series",
        params={"geocodigo": 2304202, "ano": 2024},
    )
    complete = client.get(
        "/v1/champion/municipio_monthly_series",
        params={"geocodigo": 2304202, "ano": 2023},
    )

    assert partial.status_code == 200
    partial_body = partial.json()
    assert len(partial_body) == 7
    assert all(row["cobertura_completa"] is False for row in partial_body)

    assert complete.status_code == 200
    complete_body = complete.json()
    assert len(complete_body) == 12
    assert all(row["cobertura_completa"] is True for row in complete_body)


def test_serving_api_champion_municipio_ranking_is_sorted_by_wape_desc():
    """Verifica o comportamento `test serving api champion municipio ranking is sorted by wape desc`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/municipio_ranking")

    assert response.status_code == 200
    body = response.json()
    assert len(body) > 0
    wapes = [row["wape"] for row in body]
    assert wapes == sorted(wapes, reverse=True)


def test_serving_api_climate_enso_matches_known_2015_16_el_nino():
    """Verifica o comportamento `test serving api climate enso matches known 2015 16 el nino`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/climate/enso")

    assert response.status_code == 200
    body = {(row["ano"], row["mes"]): row for row in response.json()}
    assert body[(2015, 11)]["enso_regime"] == "el_nino"
    assert body[(2015, 11)]["nino34_anomaly"] > 1.5


def test_serving_api_fails_closed_when_artifact_tampered(tmp_path):
    """Verifica o comportamento `test serving api fails closed when artifact tampered`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    artifact = package(tmp_path)
    artifact["climatology"][0]["prediction"] = 999999
    (tmp_path / "model.json").write_text(json.dumps(artifact), encoding="utf-8")
    client = TestClient(create_app(tmp_path / "model.json"))

    response = client.post(
        "/v1/predict",
        json={"geocodigo": 2300101, "ano": 2026, "mes": 10},
    )

    assert response.status_code == 503
    assert "Hash do artefato invalido" in response.json()["detail"]
