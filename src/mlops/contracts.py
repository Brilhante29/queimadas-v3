"""Modulo publico do FireCast para contratos de producao, gates e operacao mensal.

Arquivo `src/mlops/contracts.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

GateStatus = Literal["PASS", "FAIL", "PARTIAL", "UNKNOWN"]
Decision = Literal["PROMOTE", "ITERATE", "REJECT", "INVALID"]

REQUIRED_GATES = {
    "G0_integrity",
    "G1_real_data_asof",
    "G2_baseline_superiority",
    "G3_scope_contract_v2",
    "G4_spatial_slice_robustness",
    "G5_uncertainty_calibration",
    "G6_serving_contract",
    "G7_governance_monitoring_internal",
}


@dataclass(frozen=True)
class DataSourceContract:
    """Representa `DataSourceContract` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    name: str
    role: Literal["target", "weather", "vegetation", "human_pressure", "geometry", "audit"]
    snapshot: str
    required_for: list[str]
    as_of_rule: str
    production_status: GateStatus
    blocker: str | None = None


@dataclass(frozen=True)
class FeatureBlockContract:
    """Representa `FeatureBlockContract` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    name: str
    sources: list[str]
    availability: str
    leakage_controls: list[str]
    promotion_rule: str


@dataclass(frozen=True)
class ModelFamilyContract:
    """Representa `ModelFamilyContract` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    name: str
    purpose: str
    required_features: list[str]
    search_space: dict[str, list[Any]] = field(default_factory=dict)
    promotion_condition: str = "Must beat the champion on the frozen protocol and not regress critical slices."


@dataclass(frozen=True)
class EvaluationProtocol:
    """Representa `EvaluationProtocol` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    scope: str
    entity_key: str
    target: str
    horizon: str
    temporal_split: str
    spatial_tests: list[str]
    primary_metrics: list[str]
    slice_metrics: list[str]
    uncertainty: str
    final_test_policy: str


@dataclass(frozen=True)
class ReleaseGate:
    """Representa `ReleaseGate` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    gate: str
    status: GateStatus
    must_prove: list[str]
    evidence: list[str]
    current_blocker: str | None = None


@dataclass(frozen=True)
class RetrainingContract:
    """Representa `RetrainingContract` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    cadence: str
    triggers: list[str]
    steps: list[str]
    rollback_rule: str


@dataclass(frozen=True)
class ProductionMLPlan:
    """Representa `ProductionMLPlan` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/contracts.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    created_at: str
    scope: str
    current_champion: str
    status: str
    data_sources: list[DataSourceContract]
    feature_blocks: list[FeatureBlockContract]
    model_families: list[ModelFamilyContract]
    evaluation: EvaluationProtocol
    gates: list[ReleaseGate]
    retraining: RetrainingContract
    next_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Executa a etapa `to dict` do fluxo FireCast.
        
        A funcao faz parte de `src/mlops/contracts.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        return asdict(self)

    def validate(self) -> list[str]:
        """Executa a etapa `validate` do fluxo FireCast.
        
        A funcao faz parte de `src/mlops/contracts.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        errors: list[str] = []
        source_names = {s.name for s in self.data_sources}
        for block in self.feature_blocks:
            missing = [src for src in block.sources if src not in source_names and src != "approved_point_predictions"]
            if missing:
                errors.append(f"feature block {block.name} references missing sources: {missing}")
            if block.name == "fire_memory" and "shift(1)" not in " ".join(block.leakage_controls):
                errors.append("fire_memory block must explicitly require shift(1) leakage control")

        gate_names = {g.gate for g in self.gates}
        missing_gates = sorted(REQUIRED_GATES - gate_names)
        extra_gates = sorted(gate_names - REQUIRED_GATES)
        if missing_gates:
            errors.append(f"missing required gates: {missing_gates}")
        if extra_gates:
            errors.append(f"unknown gates in plan: {extra_gates}")
        for gate in self.gates:
            if gate.status == "PASS" and not gate.evidence:
                errors.append(f"gate {gate.gate} is PASS but has no evidence")

        joined_metrics = " ".join(self.evaluation.primary_metrics)
        if "WAPE" not in joined_metrics:
            errors.append("evaluation must include WAPE as a primary count metric")
        if "Recall@K" not in joined_metrics:
            errors.append("evaluation must include Recall@K/NDCG for operational ranking")
        if "climatology_regional_intensity12" not in self.current_champion:
            errors.append("current champion is stale; expected climatology_regional_intensity12")
        if "EXTERNAL_PENDING" in self.status:
            actions = " ".join(self.next_actions).lower()
            if "shadow" not in actions:
                errors.append("external-pending status must require a scored shadow window")
            if "human" not in actions and "authorization" not in actions:
                errors.append("external-pending status must require human authorization")
        return errors


def build_chapada_plan() -> ProductionMLPlan:
    """Constroi a etapa `build chapada plan` do fluxo FireCast.
    
    A funcao faz parte de `src/mlops/contracts.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""

    return ProductionMLPlan(
        created_at=datetime.now(timezone.utc).isoformat(),
        scope="chapada_araripe_internal_ce_pe_pi",
        current_champion=(
            "climatology_regional_intensity12; EXP-10 promoted; extended WAPE 0.6430 "
            "vs baseline 0.7906; out-nov WAPE 0.5419 vs baseline 0.6923"
        ),
        status="APPROVED_INTERNAL_PRODUCTION_G3V2_EXTERNAL_PENDING_SHADOW_AND_HUMAN_AUTHORIZATION",
        data_sources=[
            DataSourceContract(
                "inpe_local_v2",
                "target",
                "data/snapshots/inpe_local_v2",
                ["training", "evaluation", "internal_monitoring"],
                "Frozen historical target. A target month is usable only after source coverage proves availability; suspect gaps stay missing, never zero-filled.",
                "PASS",
            ),
            DataSourceContract(
                "inpe_monthly_public_v3",
                "target",
                "data/snapshots/inpe_monthly_public_v3",
                ["scoring_only_2025_2026", "shadow_monitoring"],
                "Additive monthly public target. Use event-level rows filtered to AQUA_M-T for comparability with the historical target; do not tune on 2025/2026.",
                "PASS",
            ),
            DataSourceContract(
                "inpe_event_points_v1",
                "target",
                "data/snapshots/inpe_event_points_v1",
                ["audit", "event_feature_experiments"],
                "Event points preserve source time, satellite, FRP, risk and location; any aggregation must be lagged or scoring-only.",
                "PASS",
            ),
            DataSourceContract(
                "ibge_malha_municipal_2024",
                "geometry",
                "data/snapshots/ibge_malha_municipal_2024",
                ["zonal_features", "serving_identity"],
                "Static snapshot versioned by retrieval date and checksum; geocodigo is the canonical entity key.",
                "PASS",
            ),
            DataSourceContract(
                "era5_grid_weights_chapada_v1",
                "geometry",
                "data/snapshots/era5_grid_weights_chapada_v1",
                ["weather_zonal"],
                "Static grid-municipality weights; weights by municipality must sum near 1 before use.",
                "PASS",
            ),
            DataSourceContract(
                "era5_zonal_chapada",
                "weather",
                "cache/era5_zonal_chapada",
                ["candidate_training", "weather_audit"],
                "Historical reanalysis is used only as lagged/as-of evidence; serving must not depend on future reanalysis for the target month.",
                "PASS",
                "weather candidates tested so far did not beat the champion gates",
            ),
            DataSourceContract(
                "enso_cpc_v1",
                "weather",
                "data/snapshots/enso_cpc_v1",
                ["climate_regime_audit", "serving_context"],
                "Monthly climate-regime labels are context features; never select a final model on 2025/2026 scoring windows.",
                "PASS",
            ),
            DataSourceContract(
                "nasa_firms_multi_sensor",
                "audit",
                "data/snapshots/firms_multi_sensor_ce_v1",
                ["target_audit", "frontier_experiments"],
                "FIRMS is an independent audit/feature source. It is not summed with INPE without explicit sensor-time-space rules.",
                "PASS",
            ),
            DataSourceContract(
                "ibge_population_and_pam",
                "human_pressure",
                "data/snapshots/ibge_population_estimates_v1; data/snapshots/ibge_pam_crop_area_v1",
                ["human_pressure_experiments", "audit"],
                "Static or slow-moving snapshots must use the publication year available before the prediction cut.",
                "PASS",
                "tested candidates did not improve G3 enough for promotion",
            ),
            DataSourceContract(
                "inmet_automatic_station_observed_v1",
                "weather",
                "data/snapshots/inmet_automatic_station_observed_v1",
                ["weather_audit", "candidate_training"],
                "Station observations carry distance, altitude and missingness. Only lagged observed months can feed training/serving.",
                "PASS",
                "tested candidates did not improve G3 enough for promotion",
            ),
        ],
        feature_blocks=[
            FeatureBlockContract(
                "fire_memory",
                ["inpe_local_v2"],
                "available after the target month is observed",
                ["sort by geocodigo/time", "shift(1) before lags/rolling", "climatology fit inside each train cut"],
                "baseline block and current champion; every candidate must beat it on the same frozen protocol",
            ),
            FeatureBlockContract(
                "regional_intensity",
                ["inpe_local_v2"],
                "last 12 observed months before the forecast cut",
                ["target month excluded", "rolling totals use only observed past months", "clip ratio to documented range"],
                "current promoted block because it improved WAPE and out-nov without leaking the target month",
            ),
            FeatureBlockContract(
                "climate_physical",
                ["era5_zonal_chapada", "enso_cpc_v1", "inmet_automatic_station_observed_v1"],
                "lagged or published-before-cut values only",
                ["available_at <= prediction_cut", "train-serving source parity", "no future reanalysis for target month"],
                "promote only if it beats the champion and critical slices after ablation",
            ),
            FeatureBlockContract(
                "external_fire_audit",
                ["nasa_firms_multi_sensor", "inpe_event_points_v1"],
                "audit and lagged feature candidates only",
                ["sensor filter documented", "no target mixing without dedup", "event aggregations use past months only"],
                "use to estimate measurement noise and test frontier hypotheses, not to redefine the target silently",
            ),
            FeatureBlockContract(
                "human_pressure",
                ["ibge_population_and_pam", "ibge_malha_municipal_2024"],
                "static or slowly changing snapshots with known publication year",
                ["geocodigo primary key", "published year <= prediction year", "ablate separately from fire memory"],
                "must improve ranking or aggregate error without degrading G3/G5",
            ),
            FeatureBlockContract(
                "conformal_wrapper",
                ["approved_point_predictions"],
                "computed from frozen out-of-sample residuals",
                ["alpha selected on validation year only", "gate measured on held-out 2023-2024", "strata documented"],
                "empirical IC coverage must remain inside the configured G5 range",
            ),
            FeatureBlockContract(
                "llm_xai_explanation",
                ["approved_point_predictions"],
                "computed only after a hash-verified prediction exists",
                [
                    "LLM cannot call predict or change y_pred",
                    "all numeric narrative tokens must be present in the XAI packet",
                    "unverified narrative fails closed",
                ],
                "explanation layer may ship only when exact attribution equals served prediction and numeric_fact_guard_v1 passes",
            ),
        ],
        model_families=[
            ModelFamilyContract(
                "approved_champion",
                "production baseline and current internal champion",
                ["fire_memory", "regional_intensity"],
                {"model": ["municipal_month_climatology_x_regional_intensity12"]},
                "serves internally until a challenger passes all gates and a human authorizes promotion",
            ),
            ModelFamilyContract(
                "mandatory_baselines",
                "valid lower bound and regression guard",
                ["fire_memory"],
                {"models": ["lag12", "municipal_climatology", "state_climatology", "historical_mean"]},
                "all baselines must execute; challengers must beat the best valid baseline",
            ),
            ModelFamilyContract(
                "gbm_count",
                "strong tabular count challenger",
                ["fire_memory", "climate_physical"],
                {"loss": ["poisson", "tweedie", "squared_error"], "learning_rate": [0.03, 0.06]},
                "beat the champion in aggregate, out-nov, G3 v2, G4 and G5 without 2025/2026 tuning",
            ),
            ModelFamilyContract(
                "two_stage_occurrence_count",
                "separate occurrence/risk ranking from count severity",
                ["fire_memory", "climate_physical", "external_fire_audit"],
                {"classifier": ["hist_gbm"], "regressor": ["poisson_gbm", "tweedie"]},
                "improve Recall@K/NDCG and aggregate WAPE without calibration failure",
            ),
            ModelFamilyContract(
                "hierarchical_or_bayesian_count",
                "research candidate for sparse municipalities and measurement noise",
                ["fire_memory", "external_fire_audit", "human_pressure"],
                {"families": ["negative_binomial", "partial_pooling"]},
                "publishable only if it improves noise-aware slices and preserves operational simplicity",
            ),
        ],
        evaluation=EvaluationProtocol(
            scope="Chapada do Araripe CE/PE/PI target municipalities plus CE aggregate gate slices",
            entity_key="geocodigo IBGE",
            target="monthly INPE fire_count; public scoring uses AQUA_M-T event-level aggregation for comparability",
            horizon="h=1 month forecast; future horizons are separate contracts",
            temporal_split="extended walk-forward 2015-2024 for selection; 2023-2024 frozen gate; 2025/2026 scoring-only reality checks",
            spatial_tests=["municipality slices", "Chapada/Cariri critical slice", "state/CE aggregate gate", "dry-season out-nov"],
            primary_metrics=["WAPE", "MAE", "RMSE", "Recall@K", "NDCG", "interval coverage", "absolute aggregate volume error"],
            slice_metrics=["state", "municipality", "month", "dry season", "out-nov", "volume decile", "target coverage regime"],
            uncertainty="finite-sample conformal IC95 with validation-year alpha selection and 2023-2024 gate coverage",
            final_test_policy="No feature, hyperparameter, threshold or model choice may be selected on 2025/2026 scoring windows.",
        ),
        gates=[
            ReleaseGate(
                "G0_integrity",
                "PASS",
                ["tests pass", "ingestors/snapshots accounted for", "release evidence valid", "public package checks pass"],
                ["pytest tests -q", "scripts/check_data_ingestors.py", "python src/mlops/contracts.py --out outputs/production_ml_plan.json", "python -m pytest tests -q"],
            ),
            ReleaseGate(
                "G1_real_data_asof",
                "PASS",
                ["real immutable snapshots", "as-of rules", "no synthetic production evidence", "sensor-aligned public scoring target"],
                ["data/snapshots/* manifests", "EXP-27 public AQUA_M-T overlap validation"],
            ),
            ReleaseGate(
                "G2_baseline_superiority",
                "PASS",
                ["candidate beats best valid baseline", "critical dry-season slice does not regress"],
                ["EXP-10 WAPE 0.6430 vs 0.7906; out-nov 0.5419 vs 0.6923; CI95 delta below zero"],
            ),
            ReleaseGate(
                "G3_scope_contract_v2",
                "PASS",
                ["CE aggregate monthly/seasonal limits", "Chapada seasonal limit", "Recall@10 limits", "zero indevido limit"],
                ["outputs/exp26_g3_contract_v2_evaluation/contract_v2_report.json"],
            ),
            ReleaseGate(
                "G4_spatial_slice_robustness",
                "PASS",
                ["spatial and critical-slice regressions checked", "known residual risks documented"],
                ["outputs/g4_spatial_robustness_exp10_2023_2024/g4_report.json"],
            ),
            ReleaseGate(
                "G5_uncertainty_calibration",
                "PASS",
                ["empirical IC coverage in configured range", "dry/wet slices covered"],
                ["outputs/g5_conformal_ic95_guarded_exp10/g5_report.json"],
            ),
            ReleaseGate(
                "G6_serving_contract",
                "PASS",
                [
                    "artifact hash",
                    "fail-closed API",
                    "training-serving identity",
                    "concurrent load smoke",
                    "verified LLM XAI cannot alter prediction or invent numbers",
                ],
                ["tests/test_serving_api.py", "tests/test_g6_serving_contract.py", "tests/test_llm_xai.py", "POST /v1/explain"],
            ),
            ReleaseGate(
                "G7_governance_monitoring_internal",
                "PASS",
                ["human internal approval", "model/data card", "rollback", "shadow harness", "LLM XAI limitations documented", "related-work claims are bounded and benchmarked"],
                [
                    "OPS-G7-APPROVAL-2026-07-11",
                    "outputs/shadow_monitor/",
                    "rollback_plan.md",
                    "data_card.md",
                    "docs/LLM_XAI_CONTRACT.md",
                    "docs/RELATED_WORK_COMPETITIVE_POSITION.md",
                    "outputs/research_frontier_benchmark.json",
                ],
                "external release still requires scored live shadow months and separate human authorization",
            ),
        ],
        retraining=RetrainingContract(
            cadence="monthly scoring and monitoring; retraining only on scheduled review or a documented trigger",
            triggers=[
                "three scored shadow months with degradation or target coverage drift",
                "schema/source/checksum change that affects training or serving",
                "new causal/as-of feature block with a source contract",
                "annual model refresh review",
                "human-approved contract revision",
            ],
            steps=[
                "ingest immutable snapshots",
                "validate source contracts and manifests",
                "build as-of feature table",
                "run mandatory baselines",
                "run candidate search on training windows only",
                "evaluate frozen G0-G7 gates",
                "package only if promoted",
                "shadow/canary only with human authorization",
            ],
            rollback_rule="serving keeps the last approved artifact; a challenger is rejected if any required internal gate is FAIL/UNKNOWN or if external authorization is absent",
        ),
        next_actions=[
            "Score the committed live shadow window with public AQUA_M-T observations as months arrive.",
            "Keep external release blocked until at least 3 scored shadow months show no degradation alert and a human authorization is recorded.",
            "Use the monthly operations plan to ingest new months, score delayed reality, and decide whether retraining is actually triggered.",
        ],
    )


def write_plan(path: Path) -> ProductionMLPlan:
    """Grava a etapa `write plan` do fluxo FireCast.
    
    A funcao faz parte de `src/mlops/contracts.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    plan = build_chapada_plan()
    errors = plan.validate()
    if errors:
        raise ValueError("invalid FireCast production ML plan: " + "; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/mlops/contracts.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser(description="Validate/export FireCast production ML plan")
    parser.add_argument("--out", type=Path, default=Path("outputs/production_ml_plan.json"))
    args = parser.parse_args()
    plan = write_plan(args.out)
    print(f"wrote {args.out} for {plan.scope}: {plan.status}")


if __name__ == "__main__":
    main()
