"""Testes publicos do FireCast para tests/test_champion_climatology.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import json

import pytest

from src.production.champion_climatology import ChampionClimatologyModel, package


def test_champion_artifact_predicts_and_fails_closed(tmp_path):
    """Verifica o comportamento `test champion artifact predicts and fails closed`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    artifact = package(tmp_path)
    model = ChampionClimatologyModel.load(tmp_path / "model.json")

    row = artifact["climatology"][0]
    pred = model.predict_one(row["geocodigo"], 2026, row["mes"])

    assert pred["y_pred"] >= 0
    assert pred["interval_p90_high"] >= pred["y_pred"]
    assert pred["artifact_sha256"] == artifact["artifact_sha256"]

    with pytest.raises(ValueError, match="fail-closed"):
        model.predict_one(9999999, 2026, 1)


def test_champion_artifact_hash_detects_tampering(tmp_path):
    """Verifica o comportamento `test champion artifact hash detects tampering`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    package(tmp_path)
    path = tmp_path / "model.json"
    payload = json.loads(path.read_text())
    payload["climatology"][0]["prediction"] += 1
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="Hash do artefato invalido"):
        ChampionClimatologyModel.load(path)
