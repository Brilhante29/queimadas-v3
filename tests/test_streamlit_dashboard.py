"""Testes publicos do dashboard Streamlit do FireCast.

As verificacoes garantem que a vitrine preserve o contrato: o LLM local so narra fatos, o grafo XAI continua disponivel e o Docker Compose expoe Streamlit com Ollama.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_dashboard_exposes_model_reality_and_xai_graph():
    """Confere se o painel apresenta modelo, realidade, grafo XAI e guard numerico."""
    app = (ROOT / "streamlit_app" / "firecast_dashboard.py").read_text(encoding="utf-8")

    for expected in [
        "streamlit",
        "plotly",
        "build_verified_xai_response",
        "verify_narrative_against_packet",
        "plot_real_vs_pred",
        "plot_xai_graph",
        "xai_graph",
        "monthly_reality_comparison.csv",
        "by_municipio.csv",
    ]:
        assert expected in app


def test_streamlit_ollama_contract_is_fail_closed():
    """Confere se o Ollama usa streaming desativado e validacao antes de exibir narrativa."""
    app = (ROOT / "streamlit_app" / "firecast_dashboard.py").read_text(encoding="utf-8")

    assert "/api/generate" in app
    assert '"stream": False' in app
    assert "temperature" in app
    assert "NarrativeValidationError" in app
    assert "LLM so narrou fatos verificados" in app


def test_compose_default_stack_exposes_streamlit_and_ollama():
    """Confere se o Docker padrao sobe API, Streamlit e Ollama automaticamente."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "profiles" not in services["streamlit"]
    assert "profiles" not in services["ollama"]
    assert services["streamlit"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert services["streamlit"]["depends_on"]["ollama-pull"]["condition"] == "service_completed_successfully"
    assert services["ollama-pull"]["environment"]["OLLAMA_MODEL"] == "${OLLAMA_MODEL:-llama3.2:3b}"
    assert services["ollama-pull"]["depends_on"]["ollama"]["condition"] == "service_healthy"
    assert compose["x-firecast-base"]["environment"]["OLLAMA_BASE_URL"] == "http://ollama:11434"
