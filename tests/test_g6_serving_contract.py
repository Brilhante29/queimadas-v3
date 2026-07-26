"""Testes publicos do FireCast para tests/test_g6_serving_contract.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""

import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from src.production.champion_climatology import (
    ChampionClimatologyModel,
    build_climatology_table,
    load_training_frame,
    package,
)
from src.production.serving_api import create_app


def test_train_serve_identity(tmp_path):
    """Verifica o comportamento `test train serve identity`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    model = ChampionClimatologyModel.load(tmp_path / "model.json")

    train = load_training_frame()
    fresh_table = {(row["geocodigo"], row["mes"]): row["prediction"] for row in build_climatology_table(train)}

    sample = model.artifact["climatology"][::40]  # amostra espalhada da tabela
    assert len(sample) >= 10
    for row in sample:
        served = model.predict_one(row["geocodigo"], 2026, row["mes"])
        ratio, _ = model.regional_intensity_ratio(2026, row["mes"])
        expected = fresh_table[(row["geocodigo"], row["mes"])] * ratio
        assert served["y_pred"] == expected


def test_deterministic_response(tmp_path):
    """Verifica o comportamento `test deterministic response`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    client = TestClient(create_app(tmp_path / "model.json"))
    payload = {"geocodigo": 2300101, "ano": 2026, "mes": 10}

    bodies = []
    for _ in range(3):
        resp = client.post("/v1/predict", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        body.pop("served_at")  # único campo legitimamente variável
        bodies.append(body)

    assert bodies[0] == bodies[1] == bodies[2]


def test_predict_latency(tmp_path):
    """Verifica o comportamento `test predict latency`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    client = TestClient(create_app(tmp_path / "model.json"))
    payload = {"geocodigo": 2300101, "ano": 2026, "mes": 10}
    client.post("/v1/predict", json=payload)  # warm-up

    latencies = []
    for _ in range(30):
        start = time.perf_counter()
        resp = client.post("/v1/predict", json=payload)
        latencies.append(time.perf_counter() - start)
        assert resp.status_code == 200

    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1]
    assert p95 < 1.0, f"p95 de latência local {p95:.3f}s — regressão grosseira no caminho de predição"


def test_concurrent_load_smoke(tmp_path):
    """Verifica o comportamento `test concurrent load smoke`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    client = TestClient(create_app(tmp_path / "model.json"))
    payload = {"geocodigo": 2300101, "ano": 2026, "mes": 10}

    def call(_):
        """Executa a etapa `call` do fluxo FireCast.
        
        A funcao faz parte de `tests/test_g6_serving_contract.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        resp = client.post("/v1/predict", json=payload)
        return resp.status_code, resp.json().get("y_pred")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(50)))

    statuses = {status for status, _ in results}
    preds = {pred for _, pred in results}
    assert statuses == {200}, f"status sob concorrência: {statuses}"
    assert len(preds) == 1, f"previsões divergentes sob concorrência: {preds}"
