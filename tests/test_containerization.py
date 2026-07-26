"""Testes publicos do FireCast para tests/test_containerization.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_current_champion_and_entrypoint():
    """Verifica o comportamento `test dockerfile uses current champion and entrypoint`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "python:3.10-slim" in dockerfile
    assert "outputs/champion_climatology_regional_intensity12" in dockerfile
    assert "docker/entrypoint.sh" in dockerfile
    assert "src/production/serving_api.py" in dockerfile
    assert "src/production/llm_xai.py" in dockerfile
    assert "streamlit_app/firecast_dashboard.py" in dockerfile
    assert "EXPOSE 8000 8501" in dockerfile
    assert ".venv" not in dockerfile


def test_compose_defines_api_and_ops_services():
    """Verifica o comportamento `test compose defines api and ops services`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    expected = {
        "api",
        "test",
        "serving-test",
        "data-check",
        "plan",
        "monthly-plan",
        "shadow-score",
        "shadow-report",
        "explain",
        "xai-graph",
        "streamlit",
        "ollama",
        "ollama-pull",
        "shell",
    }
    assert expected <= set(services)
    assert services["api"]["command"] == ["api"]
    assert "8000:8000" in services["api"]["ports"]
    assert services["shadow-score"]["command"] == ["shadow-score"]
    assert services["shadow-report"]["command"] == ["shadow-report"]
    assert services["explain"]["command"] == ["explain"]
    assert services["streamlit"]["command"] == ["streamlit"]
    assert "profiles" not in services["streamlit"]
    assert "8501:8501" in services["streamlit"]["ports"]
    assert services["streamlit"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["streamlit"]["depends_on"]["ollama-pull"]["condition"] == "service_completed_successfully"
    assert services["ollama"]["image"] == "ollama/ollama:latest"
    assert "profiles" not in services["ollama"]
    assert "11434:11434" in services["ollama"]["ports"]
    assert services["ollama"]["healthcheck"]["test"] == ["CMD", "ollama", "list"]
    assert services["ollama-pull"]["depends_on"]["ollama"]["condition"] == "service_healthy"
    pull_command = "\n".join(services["ollama-pull"]["command"])
    assert "ollama pull" in pull_command
    assert services["ollama-pull"]["entrypoint"] == ["/bin/sh", "-c"]
    assert "ollama_models" in compose["volumes"]


def test_entrypoint_exposes_operational_commands():
    """Verifica o comportamento `test entrypoint exposes operational commands`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    entrypoint = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")

    for command in [
        "api|serve)",
        "test)",
        "serving-test)",
        "data-check)",
        "monthly-plan)",
        "shadow-score)",
        "shadow-report)",
        "explain)",
        "xai-graph)",
        "streamlit|dashboard)",
    ]:
        assert command in entrypoint
    assert "--target-satellite" in entrypoint
    assert "AQUA_M-T" in entrypoint

def test_dockerignore_keeps_mutable_state_out_of_image():
    """Verifica o comportamento `test dockerignore keeps mutable state out of image`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for pattern in ["data/**", "outputs/**", "cache/**", ".venv", ".env.*"]:
        assert pattern in dockerignore

