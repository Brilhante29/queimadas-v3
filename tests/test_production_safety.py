"""Testes publicos do FireCast para tests/test_production_safety.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import numpy as np
import pandas as pd

from src.features.build_feature_store import build_feature_store
from src.features.leakage_audit import audit_feature_store
from src.models.baselines import ClimatologyMunicipal, NaiveLag12
from src.models.rast_fire_x import RASTFireX
from src.utils.metrics import acceptance_gate


def test_fire_memory_features_only_use_prior_months(tmp_path):
    """Verifica o comportamento `test fire memory features only use prior months`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    inpe = pd.DataFrame(
        {
            "municipio_id": [1, 1, 1],
            "municipio_nome": ["A", "A", "A"],
            "estado": ["CE", "CE", "CE"],
            "ano": [2024, 2024, 2024],
            "mes": [1, 2, 3],
            "fire_count": [10, 20, 30],
        }
    )
    weather = inpe[["municipio_id", "municipio_nome", "estado", "ano", "mes"]].copy()
    weather["temperature"] = [25.0, 26.0, 27.0]
    enso = pd.DataFrame(
        {
            "ano": [2024, 2024, 2024],
            "mes": [1, 2, 3],
            "nino34_anomaly": [0.0, 0.1, 0.2],
            "enso_prob_el_nino": [30, 35, 40],
            "enso_regime": ["neutral", "neutral", "neutral"],
        }
    )

    result = build_feature_store(inpe, weather, enso_df=enso, output_dir=str(tmp_path))

    assert np.isnan(result.iloc[0]["fire_roll3"])
    assert result.iloc[1]["fire_roll3"] == 10
    assert result.iloc[2]["fire_roll3"] == 15
    assert result["fire_ytd"].tolist() == [0, 10, 30]


def test_direct_target_derivatives_are_never_model_features():
    """Verifica o comportamento `test direct target derivatives are never model features`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    frame = pd.DataFrame(
        {
            "fire_count": [0, 5, 40],
            "occurrence": [0, 1, 1],
            "extreme_event": [0, 0, 1],
            "FRP_sum": [0.0, 10.0, 80.0],
            "temperature": [25.0, 26.0, 27.0],
        }
    )

    selected = RASTFireX()._select_features(frame, "count")

    assert selected == ["temperature"]
    audit = audit_feature_store(frame)
    unsafe = set(audit.loc[~audit["safe_to_use"], "feature"])
    assert {"fire_count", "occurrence", "extreme_event", "FRP_sum"} <= unsafe


def test_baselines_fit_and_predict_instead_of_all_failing():
    """Verifica o comportamento `test baselines fit and predict instead of all failing`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    train = pd.DataFrame(
        {
            "municipio_id": [1, 1, 1],
            "mes": [1, 1, 2],
            "fire_count": [2, 4, 8],
            "fire_count_lag12": [1, 2, 3],
            "temperature": [25.0, 26.0, 27.0],
        }
    )
    test = train.iloc[[0, 2]].copy()

    climatology = ClimatologyMunicipal().fit(train, ["temperature"])
    naive = NaiveLag12().fit(train, ["temperature"])

    assert climatology.predict(test).tolist() == [3.0, 8.0]
    assert naive.predict(test).tolist() == [1, 3]


def test_acceptance_gate_fails_closed_without_valid_baseline():
    """Verifica o comportamento `test acceptance gate fails closed without valid baseline`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    results = pd.DataFrame(
        [
            {
                "scope": "ceara",
                "wape_critical_out_nov": 0.10,
                "ic95_critical_out_nov": 0.95,
                "zero_indevido_critical_out_nov": 0.0,
                "recall10_critical_out_nov": 0.8,
                "best_baseline_wape": np.nan,
            }
        ]
    )
    config = {
        "ceara": {
            "wape_critical_threshold": 0.20,
            "ic95_min": 0.90,
            "ic95_max": 0.98,
            "zero_indevido_threshold": 0.0,
            "recall10_threshold": 0.70,
        }
    }

    decision = acceptance_gate(results, config).iloc[0]

    assert not decision["passed"]
    assert "best_baseline_wape" in decision["pass_reasons"]
