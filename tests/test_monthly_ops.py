"""Testes publicos do FireCast para tests/test_monthly_ops.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import pytest

from src.mlops.monthly_ops import DEFAULT_TARGET_SATELLITE, build_monthly_plan


def test_monthly_plan_orders_ingest_score_report_before_registry_update():
    """Verifica o comportamento `test monthly plan orders ingest score report before registry update`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    plan = build_monthly_plan(["202609", "202608", "202608"])

    assert plan.months == ["202608", "202609"]
    assert plan.target_satellite == DEFAULT_TARGET_SATELLITE
    steps = [command.step for command in plan.commands]
    assert steps == [
        "01_ingest_public_target",
        "02_validate_data_contracts",
        "03_reality_score_holdout",
        "04_shadow_score",
        "05_shadow_report",
        "06_api_contract_smoke",
        "07_publish_results_registry",
    ]
    assert "shadow_monitor score" in plan.commands[3].command
    assert "AQUA_M-T" in plan.commands[3].command
    assert "Do not retrain" in plan.retraining_policy


def test_monthly_plan_validates_yyyymm():
    """Verifica o comportamento `test monthly plan validates yyyymm`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    with pytest.raises(ValueError, match="YYYYMM"):
        build_monthly_plan(["2026-08"])

    with pytest.raises(ValueError, match="01..12"):
        build_monthly_plan(["202613"])
