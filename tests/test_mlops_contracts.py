"""Testes publicos do FireCast para tests/test_mlops_contracts.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
from src.mlops.contracts import REQUIRED_GATES, build_chapada_plan, write_plan


def test_chapada_plan_matches_current_internal_production_state():
    """Verifica o comportamento `test chapada plan matches current internal production state`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    plan = build_chapada_plan()

    assert plan.scope == "chapada_araripe_internal_ce_pe_pi"
    assert plan.validate() == []
    assert "climatology_regional_intensity12" in plan.current_champion
    assert plan.status == "APPROVED_INTERNAL_PRODUCTION_G3V2_EXTERNAL_PENDING_SHADOW_AND_HUMAN_AUTHORIZATION"
    assert {gate.gate for gate in plan.gates} == REQUIRED_GATES
    assert all(gate.status == "PASS" for gate in plan.gates)
    assert any(gate.gate == "G3_scope_contract_v2" for gate in plan.gates)
    assert any(source.name == "inpe_monthly_public_v3" and source.role == "target" for source in plan.data_sources)
    assert any(source.name == "nasa_firms_multi_sensor" and source.role == "audit" for source in plan.data_sources)
    assert any(block.name == "climate_physical" and "era5_zonal_chapada" in block.sources for block in plan.feature_blocks)
    assert any(block.name == "llm_xai_explanation" for block in plan.feature_blocks)
    assert any("tests/test_llm_xai.py" in gate.evidence for gate in plan.gates)
    assert any("docs/RELATED_WORK_COMPETITIVE_POSITION.md" in gate.evidence for gate in plan.gates)
    assert "WAPE" in plan.evaluation.primary_metrics
    assert "Recall@K" in plan.evaluation.primary_metrics
    assert any("shadow" in action.lower() for action in plan.next_actions)


def test_write_plan_exports_current_status(tmp_path):
    """Verifica o comportamento `test write plan exports current status`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    out = tmp_path / "production_ml_plan.json"
    plan = write_plan(out)

    text = out.read_text(encoding="utf-8")
    assert '"scope": "chapada_araripe_internal_ce_pe_pi"' in text
    assert '"G5_uncertainty_calibration"' in text
    assert plan.status.endswith("HUMAN_AUTHORIZATION")
