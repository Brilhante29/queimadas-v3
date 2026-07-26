"""Testes publicos do FireCast para tests/test_llm_xai.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import math

import pytest
from fastapi.testclient import TestClient

from src.production.champion_climatology import ChampionClimatologyModel, package
from src.production.llm_xai import (
    NarrativeValidationError,
    build_verified_xai_response,
    build_xai_graph,
    build_xai_packet,
    verify_narrative_against_packet,
)
from src.production.serving_api import create_app


def test_xai_packet_matches_served_prediction_exactly(tmp_path):
    """Verifica o comportamento `test xai packet matches served prediction exactly`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    model = ChampionClimatologyModel.load(tmp_path / "model.json")

    packet = build_xai_packet(model, geocodigo=2300101, ano=2026, mes=10)
    served = model.predict_one(2300101, 2026, 10)

    assert packet["llm_xai_contract"]["llm_may_change_prediction"] is False
    assert packet["llm_xai_contract"]["llm_may_introduce_numbers"] is False
    assert math.isclose(packet["prediction"]["y_pred"], served["y_pred"], abs_tol=1e-6)
    assert math.isclose(
        packet["exact_attribution"]["base_climatology"]
        * packet["exact_attribution"]["regional_intensity_ratio"],
        packet["prediction"]["y_pred"],
        abs_tol=1e-6,
    )



def test_xai_graph_encodes_exact_attribution_path(tmp_path):
    """Verifica o comportamento `test xai graph encodes exact attribution path`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    model = ChampionClimatologyModel.load(tmp_path / "model.json")

    packet = build_xai_packet(model, geocodigo=2300101, ano=2026, mes=10)
    graph = build_xai_graph(packet)

    node_ids = {node["id"] for node in graph["nodes"]}
    assert {
        "request",
        "artifact",
        "target_history",
        "municipal_climatology",
        "regional_intensity_window",
        "exact_equation",
        "prediction",
        "interval",
        "numeric_guard",
    } <= node_ids
    edges = {(edge["source"], edge["target"], edge["label"]) for edge in graph["edges"]}
    assert ("municipal_climatology", "exact_equation", "base_climatology") in edges
    assert ("regional_intensity_window", "exact_equation", "regional_intensity_ratio") in edges
    assert any(edge["source"] == "exact_equation" and edge["target"] == "prediction" for edge in graph["edges"])
    assert graph["packet_sha256"] == packet["packet_sha256"]
    assert graph["graph_sha256"]
    assert "flowchart LR" in graph["mermaid"]


def test_verified_llm_response_contains_prompt_and_valid_narrative(tmp_path):
    """Verifica o comportamento `test verified llm response contains prompt and valid narrative`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    model = ChampionClimatologyModel.load(tmp_path / "model.json")

    response = build_verified_xai_response(model, geocodigo=2300101, ano=2026, mes=10)

    assert response["llm_narrative"]["llm_touched_prediction"] is False
    assert response["verification"]["status"] == "verified"
    assert response["verification"]["checked_numeric_tokens"] > 0
    assert "FATOS_VERIFICADOS_JSON" in response["llm_contract"]["grounding_prompt"]
    assert response["xai_packet"]["packet_sha256"]


def test_llm_narrative_rejects_hallucinated_number(tmp_path):
    """Verifica o comportamento `test llm narrative rejects hallucinated number`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    model = ChampionClimatologyModel.load(tmp_path / "model.json")
    packet = build_xai_packet(model, geocodigo=2300101, ano=2026, mes=10)

    with pytest.raises(NarrativeValidationError):
        verify_narrative_against_packet(packet, "A previsao verificada e 999 focos.")


def test_explain_endpoint_returns_verified_xai(tmp_path):
    """Verifica o comportamento `test explain endpoint returns verified xai`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    client = TestClient(create_app(tmp_path / "model.json"))

    response = client.post("/v1/explain", json={"geocodigo": 2300101, "ano": 2026, "mes": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["production_status"] == "producao_interna_aprovada_g3v2"
    assert body["xai_packet"]["schema_version"] == "firecast_xai_packet_v1"
    assert body["xai_graph"]["schema_version"] == "firecast_xai_graph_v1"
    assert body["xai_graph"]["packet_sha256"] == body["xai_packet"]["packet_sha256"]
    assert body["xai_packet"]["exact_attribution"]["base_times_ratio_equals_prediction"] is True
    assert body["llm_narrative"]["engine"] == "verified_template"
    assert body["verification"]["status"] == "verified"


def test_explain_endpoint_fails_closed_when_artifact_missing(tmp_path):
    """Verifica o comportamento `test explain endpoint fails closed when artifact missing`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app(tmp_path / "missing_model.json"))

    response = client.post("/v1/explain", json={"geocodigo": 2300101, "ano": 2026, "mes": 10})

    assert response.status_code == 503
    assert "Modelo indispon" in response.json()["detail"]



def test_explain_graph_endpoint_returns_renderable_graph(tmp_path):
    """Verifica o comportamento `test explain graph endpoint returns renderable graph`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    client = TestClient(create_app(tmp_path / "model.json"))

    response = client.post("/v1/explain/graph", json={"geocodigo": 2300101, "ano": 2026, "mes": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "firecast_xai_graph_v1"
    assert body["production_status"] == "producao_interna_aprovada_g3v2"
    assert len(body["nodes"]) >= 9
    assert len(body["edges"]) >= 10
    assert "flowchart LR" in body["mermaid"]
