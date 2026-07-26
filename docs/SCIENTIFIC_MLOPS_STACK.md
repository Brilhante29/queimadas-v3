# Scientific MLOps stack for FireCast

Updated: 2026-07-13.

This document records the production/research structure used by FireCast after
Iteration 45.  It is not a generic architecture wishlist: every layer below is
mapped to code, artifacts or gates in this repository.  For the paper-facing
literature comparison, read `docs/RELATED_WORK_COMPETITIVE_POSITION.md`.

## External references used

- Google TFX User Guide: production ML pipelines are organized as common
  components for ingestion, validation, transform, training, evaluation,
  infra validation and pushing.
  https://www.tensorflow.org/tfx/guide
- Google Rules of Machine Learning: first get robust infrastructure and simple
  models right, test train/serve identity, monitor freshness and silent failures,
  and add new sources only when the current approach plateaus.
  https://developers.google.com/machine-learning/guides/rules-of-ml
- Kubeflow Pipelines: ML workflows are DAGs of reusable components with
  artifacts, run tracking and caching.
  https://www.kubeflow.org/docs/components/pipelines/overview/
- MLflow Tracking: experiments must log parameters, code versions, metrics and
  output artifacts as runs.
  https://mlflow.org/docs/latest/ml/tracking/
- DVC data/model versioning: data, source and model versions need to be tracked
  together to reproduce experiments.
  https://doc.dvc.org/example-scenarios/versioning-data-and-models
- Feast feature store: point-in-time-correct offline feature sets avoid leakage;
  online/offline parity is a separate serving concern.
  https://docs.feast.dev/
- Model Cards for Model Reporting: model documentation must state intended use,
  evaluation procedure, performance across conditions and limitations.
  https://arxiv.org/abs/1810.03993
- Hidden Technical Debt in ML Systems: the major risk factors are entanglement,
  undeclared consumers, data dependencies, configuration debt and external world
  changes; the remedy is explicit APIs, tests, refactoring and documentation.
  https://proceedings.neurips.cc/paper_files/paper/2015/file/86df7dcfd896fcaf2674f757a2463eba-Paper.pdf

## FireCast component map

| Scientific stack layer | FireCast implementation | Gate |
|---|---|---|
| Source contracts | `src/data/*`, `data/snapshots/*/manifest.json`, `outputs/research_log.md` | G0/G1 |
| Immutable target snapshots | `inpe_local_v2` for training/evaluation, `inpe_monthly_public_v3` for additive reality scoring | G1 |
| Point-in-time feature logic | experiment scripts enforce lagged/as-of features; `src/mlops/contracts.py` records leakage controls | G1/G2 |
| Experiment tracking | `outputs/exp*/run_manifest.json`, `outputs/experiment_ledger.jsonl`, `outputs/model_progress_report.md` | G2/G3 |
| Frozen evaluation protocol | EXP-10 extended walk-forward, EXP-26 G3 v2, EXP-27/28 scoring-only reality checks | G2/G3 |
| Uncertainty | `outputs/g5_conformal_ic95_guarded_exp10/g5_report.json` | G5 |
| Production artifact | `outputs/champion_climatology_regional_intensity12/model.json` and model card | G6/G7 |
| Serving API | `src/production/serving_api.py`, `tests/test_serving_api.py`, `tests/test_g6_serving_contract.py` | G6 |
| Verified LLM XAI | `src/production/llm_xai.py`, `POST /v1/explain`, `tests/test_llm_xai.py` | G6/G7 |
| Monitoring and rollback | `src/production/shadow_monitor.py`, `outputs/shadow_monitor/`, `rollback_plan.md` | G7 |
| Monthly continuation loop | `src/mlops/monthly_ops.py`, `./firecast monthly-plan`, this document | G0/G7 |

## Gate separation

The gates are now explicit in `src/mlops/contracts.py` and exported by
`./firecast plan`:

- G0 integrity: tests, data-check, checkpoint harness, checklist sync and append-only
  governance files.
- G1 real data/as-of: source manifests, no synthetic production evidence,
  target sensor alignment, no current-month leakage.
- G2 baseline superiority: a candidate must beat the best valid baseline on the
  same frozen protocol.
- G3 scope contract v2: aggregate CE/Chapada limits, Recall@10 and zero-indevido
  limits; municipal-month WAPE remains informational because EXP-25 measured it
  near the irreducible-noise zone.
- G4 spatial/slice robustness: critical spatial and seasonal slices checked and
  residual risks named.
- G5 uncertainty calibration: finite-sample conformal intervals selected outside
  the gate years and measured on 2023-2024.
- G6 serving contract: artifact hash, fail-closed API, train-serving identity,
  concurrent smoke tests and verified LLM-XAI narration.
- G7 governance/monitoring: human internal approval, model/data cards, rollback,
  shadow log, delayed scoring and external-release hold.

Internal production is approved under G3 v2.  External production is still
blocked until live shadow months are scored without degradation and a separate
human authorization is recorded.

## Current model and scientific claim

The current champion is `climatology_regional_intensity12`.  It is deliberately
simple and interpretable:

```text
pred = municipal_month_climatology * clip((observed_last_12m + 100) / (expected_last_12m + 100), 0.5, 2.0)
```

The target month never enters the regional intensity factor.  The promoted
claim is not that this is the most complex possible model; the claim is that it
is the best supported model under the current data contracts.

Primary evidence:

- EXP-10 extended protocol 2015-2024, 120 cuts: WAPE 0.6430 vs baseline 0.7906;
  out-nov WAPE 0.5419 vs baseline 0.6923; 85/120 cuts won; bootstrap CI95 for
  delta WAPE [-0.2195, -0.0852].
- EXP-26 G3 v2: CE scope-month WAPE 0.2245 <= 0.25; CE seasonal WAPE 0.1794 <=
  0.20; Chapada seasonal WAPE 0.3723 <= 0.40; Recall@10 0.775/0.90; zero
  indevido 0.0.
- G5 guarded conformal: 2023-2024 coverage 0.9170 overall, 0.9000 dry season,
  0.9274 wet season, inside [0.90, 0.98].
- EXP-27 reality scoring: with complete public AQUA_M-T target, 2025 observed
  1571 vs predicted 1491.984, absolute error 79.016; 2026 Jan-Jun observed 131
  vs predicted 87.436, absolute error 43.564.  The previous 686 vs 1492 mismatch
  mixed a partial v2 target with full prediction coverage.
- EXP-28 operational refresh was rejected: it improved short 2026 by only about
  3.7 fires but worsened complete 2025 error from 79 to 140.

## Verified LLM XAI

The LLM contribution is intentionally bounded: FireCast does not ask an LLM to predict, rank, calibrate or invent explanations. The champion is a glass-box formula, so the XAI packet exposes the exact base climatology, exact regional multiplier, exact product and exact p90 interval. An optional LLM may only narrate those facts; `numeric_fact_guard_v1` rejects any narrative with numbers outside the packet.

This is an XAI improvement because the explanation is not a surrogate model. It is the same arithmetic used by serving, with a mechanical guard against hallucinated quantities. See `docs/LLM_XAI_CONTRACT.md`.

## Why the stack keeps the simple champion

The repository has already tested regression, classification/hurdle,
clustering, spatial graph, event kernels, FIRMS lines, IBGE population/PAM,
local NDVI triage and INMET observed weather.  The negative results are useful
scientific evidence, not failures to hide.  The current rule is:

1. A new source must have an as-of contract and manifest.
2. A new model must beat the champion on the frozen protocol before touching
   serving.
3. Reality windows 2025/2026 are scoring-only and cannot choose parameters.
4. Monthly data arrival triggers scoring and monitoring first, not automatic
   retraining.

That is the core anti-overfitting rule for the project.

## Directory responsibilities

```text
configs/                 Source and gate configuration.
data/snapshots/          Immutable or append-only source snapshots and manifests.
docs/                    Scientific architecture, source contracts and operations.
outputs/exp*/            Experiment manifests, metrics and diagnostics.
outputs/champion_*/      Approved artifacts and model cards.
outputs/shadow_monitor/  Append-only shadow predictions, delayed scores and report.
src/data/                Ingestion and snapshot builders.
src/experiments/         Frozen-protocol experiments and audits.
src/mlops/               Gates, contracts and monthly operations abstraction.
src/production/          Champion package, API and shadow monitor.
tests/                   Regression tests for serving, gates and data contracts.
```

## Article-readiness checklist

A scientific article can now cite the repository artifacts directly:

- Problem formulation: monthly municipal count forecasting by `geocodigo`.
- Data provenance: source manifests in `data/snapshots` and research log.
- Leakage control: source contracts and as-of feature statements in
  `src/mlops/contracts.py`.
- Baselines/champion: EXP-10 and model card.
- Negative results: EXP-12 through EXP-24 plus EXP-25 feasibility audit.
- Revised production contract: EXP-26, with a transparent note that G3 v2 was a
  human product decision informed by prior evidence.
- Reality validation: EXP-27/28, explicitly scoring-only.
- Uncertainty: G5 conformal report.
- Serving/monitoring: G6 tests and G7 shadow monitor.
- Related-work positioning: `docs/RELATED_WORK_COMPETITIVE_POSITION.md` and `outputs/research_frontier_benchmark.json`.

## Open research frontier

The next publishable model improvement is unlikely to come from another simple
municipal total-preserving allocator.  The evidence points to three honest
frontiers:

- cell/grid modeling with high-quality vegetation/fuel and land-use layers,
  then aggregating to municipality after validation;
- measurement-error-aware count models that use INPE and FIRMS disagreement as
  a noise signal rather than treating the target as exact;
- hierarchical/partial-pooling count models for sparse municipalities, with
  conformal or Bayesian uncertainty audited on frozen slices.

None of these should use 2025/2026 to pick parameters.  They must enter through
new source contracts, new experiment manifests and the same G0-G7 gatekeeper.
