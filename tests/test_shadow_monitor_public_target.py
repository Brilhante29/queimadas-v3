"""Testes publicos do FireCast para tests/test_shadow_monitor_public_target.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import pandas as pd
import pytest

from src.production.shadow_monitor import load_observed


def test_public_event_target_requires_satellite_filter(tmp_path):
    """Verifica o comportamento `test public event target requires satellite filter`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    target = tmp_path / "events_target_region.csv"
    pd.DataFrame(
        [
            {"geocodigo": 2300101, "ano": 2026, "mes": 5, "satelite": "AQUA_M-T"},
            {"geocodigo": 2300101, "ano": 2026, "mes": 5, "satelite": "NOAA-20"},
        ]
    ).to_csv(target, index=False)

    with pytest.raises(ValueError, match="target-satellite"):
        load_observed(target_path=target)


def test_public_event_target_aggregates_only_selected_satellite(tmp_path):
    """Verifica o comportamento `test public event target aggregates only selected satellite`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    target = tmp_path / "events_target_region.csv"
    pd.DataFrame(
        [
            {"geocodigo": 2300101, "ano": 2026, "mes": 5, "satelite": "AQUA_M-T"},
            {"geocodigo": 2300101, "ano": 2026, "mes": 5, "satelite": "AQUA_M-T"},
            {"geocodigo": 2300101, "ano": 2026, "mes": 5, "satelite": "NOAA-20"},
            {"geocodigo": 2300200, "ano": 2026, "mes": 5, "satelite": "AQUA_M-T"},
        ]
    ).to_csv(target, index=False)

    observed = load_observed(target_path=target, target_satellite="AQUA_M-T")

    rows = observed.sort_values("geocodigo").to_dict("records")
    assert rows == [
        {"geocodigo": 2300101, "ano": 2026, "mes": 5, "fire_count": 2.0},
        {"geocodigo": 2300200, "ano": 2026, "mes": 5, "fire_count": 1.0},
    ]


def test_monthly_target_rejects_satellite_filter_without_sensor_column(tmp_path):
    """Verifica o comportamento `test monthly target rejects satellite filter without sensor column`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    target = tmp_path / "monthly.csv"
    pd.DataFrame([{"geocodigo": 2300101, "ano": 2026, "mes": 5, "fire_count": 4}]).to_csv(target, index=False)

    with pytest.raises(ValueError, match="event-level"):
        load_observed(target_path=target, target_satellite="AQUA_M-T")


def test_score_treats_event_absence_as_zero_for_public_target(tmp_path, monkeypatch):
    """Verifica o comportamento `test score treats event absence as zero for public target`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.production import shadow_monitor

    target = tmp_path / "events_target_region.csv"
    pd.DataFrame(
        [
            {"geocodigo": 2300101, "ano": 2026, "mes": 5, "satelite": "AQUA_M-T"},
        ]
    ).to_csv(target, index=False)

    out_dir = tmp_path / "shadow"
    shadow_log = out_dir / "shadow_log.jsonl"
    score_log = out_dir / "shadow_scores.jsonl"
    out_dir.mkdir()
    shadow_log.write_text(
        '{"ano":2026,"mes":5,"mode":"live_shadow","model_sha256":"abc",'
        '"predictions":[{"geocodigo":2300101,"y_pred":0.25},{"geocodigo":2300200,"y_pred":0.75}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(shadow_monitor, "OUT_DIR", out_dir)
    monkeypatch.setattr(shadow_monitor, "SHADOW_LOG", shadow_log)
    monkeypatch.setattr(shadow_monitor, "SCORE_LOG", score_log)

    result = shadow_monitor.score(target_path=target, target_satellite="AQUA_M-T")

    assert len(result) == 1
    row = result[0]
    assert row["score_schema_version"] == shadow_monitor.SCORE_SCHEMA_VERSION
    assert row["event_absence_is_zero"] is True
    assert row["n_scored"] == 2
    assert row["n_missing_observed"] == 0
    assert row["observed_total"] == 1.0
    assert row["predicted_total"] == 1.0
