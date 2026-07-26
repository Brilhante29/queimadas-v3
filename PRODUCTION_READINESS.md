# FireCast: production readiness

Updated on 2026-07-13.

Status: **APPROVED FOR INTERNAL PRODUCTION under G3 contract v2**.  External
release remains **blocked** until live shadow scores show no unresolved
monitoring alert and a separate human authorization is recorded.

## Current verdict

| Gate | Status | Evidence |
|---|---|---|
| G0 | PASS | `.venv/Scripts/python.exe -m pytest tests -q` => 56/56 passing, 1 known Starlette/httpx warning; container `docker compose --profile ops run --rm serving-test` => 16/16 passing after image rebuild; `scripts/check_data_ingestors.py` => 20 snapshots / 26 ingestors OK; checklist sync OK; JSONL/checkpoint OK; Compose config OK. |
| G1 | PASS | Real versioned data sources are in the path: INPE v2 target, public INPE v3 scoring target, INPE event points, ERA5/ENSO, FIRMS, IBGE and INMET snapshots. Public 2025/2026 scoring uses event-level `AQUA_M-T`, not all-sensor mixing. |
| G2 | PASS | EXP-10 `climatology_regional_intensity12` beats the previous climatology baseline: WAPE 0.6430 vs 0.7906, out-nov 0.5419 vs 0.6923, 85/120 cuts won, bootstrap delta WAPE CI95 [-0.2195, -0.0852]. |
| G3 | PASS (v2) | EXP-26 frozen gate: CE monthly scope WAPE 0.2245 <= 0.25; CE seasonal WAPE 0.1794 <= 0.20; Chapada seasonal WAPE 0.3723 <= 0.40; Recall@10 0.775/0.90; zero indevido 0.0. v1 municipal-month limits remain historical/informational because EXP-25 measured practical irreducible noise around that granularity. |
| G4 | PASS | EXP-10 spatial/slice gate passed on the 2023-2024 window; residual low-volume risks are documented. |
| G5 | PASS | `g5_conformal_ic95_guarded_exp10`: 2023-2024 coverage 0.9170 overall, 0.9000 dry, 0.9274 wet, inside [0.90, 0.98]. |
| G6 | PASS | Fail-closed serving, artifact hash validation, train-serving identity, concurrent load smoke and verified LLM-safe XAI are covered by tests. `POST /v1/explain` returns exact attribution and rejects unverified numbers. CLI/Makefile point to `outputs/champion_climatology_regional_intensity12/model.json`. |
| G7 | PASS (internal only) | Human internal approval, model/data card, rollback and shadow harness exist. Public AQUA-MT shadow scoring now uses `score_schema_version=v2_event_absence_is_zero`, treating absent event rows as zero fires. 2026-05..07 are scored and 2026-08 is pending observed data. External release is blocked by unresolved WAPE alerts on the scored low-denominator live months. |

## Current champion

| Metric | Value |
|---|---:|
| Model | `climatology_regional_intensity12` |
| Artifact | `outputs/champion_climatology_regional_intensity12/model.json` |
| Extended WAPE | `0.6430` |
| Extended out-nov WAPE | `0.5419` |
| Dry-season WAPE | `0.5983` |
| G5 coverage overall/dry/wet | `0.9170 / 0.9000 / 0.9274` |
| 2025 public AQUA-MT actual/pred/error | `1571 / 1491.984 / 79.016` |
| 2026 Jan-Jun public AQUA-MT actual/pred/error | `131 / 87.436 / 43.564` |

## What is operational locally

- API: `./firecast serve` starts the internal fail-closed API with the current champion. Container equivalent: `docker compose up api`. Verified explanation: `./firecast explain` or `docker compose --profile ops run --rm explain`.
- Production plan: `./firecast plan` exports `outputs/production_ml_plan.json` with G0-G7, data sources, feature blocks, model families and retraining rules.
- Monthly operations: `./firecast monthly-plan` exports `outputs/monthly_operations_plan.json` with the ingest/score/report/checkpoint loop. Container equivalent: `MONTHS=YYYYMM docker compose --profile ops run --rm monthly-plan`.
- Shadow scoring: `./firecast shadow-score` and `./firecast shadow-report` score committed predictions against `data/snapshots/inpe_monthly_public_v3/events_target_region.csv --target-satellite AQUA_M-T`.
- Documentation: `docs/SCIENTIFIC_MLOPS_STACK.md`, `docs/OPERATIONS_AND_RETRAINING.md` and `docs/LLM_XAI_CONTRACT.md` explain the scientific stack, operating loop and verified LLM-safe XAI boundary.

## Why external release is still blocked

The internal model is usable for internal ranking, aggregate planning and audit,
but external release requires stronger live evidence.  The newly corrected
shadow score shows:

| Month | Mode | Observed | Predicted | WAPE | Status |
|---|---|---:|---:|---:|---|
| 2026-05 | live_shadow | 1 | 3.10 | 3.9757 | ALERT |
| 2026-06 | live_shadow | 10 | 6.27 | 1.1330 | ALERT |
| 2026-07 | live_shadow | 9 | 15.30 | 2.2805 | ALERT |
| 2026-08 | live_shadow | pending | 47.12 | n/a | awaiting observed data |

The alerts are dominated by very low monthly denominators, but they are still
real monitoring alerts.  They do not invalidate internal approval under the G3
v2 aggregate contract; they do block external release until reviewed/resolved.

## Release rules

Allowed now:

- internal dashboard/API use under status `producao_interna_aprovada_g3v2`;
- municipal risk ranking and aggregate scope magnitude with the documented G3 v2
  limits;
- monthly shadow scoring and research/audit continuation.

Not allowed now:

- external operational publication;
- claiming precise municipal-month magnitude;
- tuning or selecting parameters on 2025/2026 reality windows;
- mixing all-sensor public target with the historical AQUA-MT target.

External release requires all of the following:

1. at least three live shadow months scored against the correct public AQUA-MT target;
2. no unresolved degradation/freshness/schema alert;
3. separate human authorization recorded in `outputs/experiment_ledger.jsonl`;
4. checkpoint state, journal and next actions updated coherently.

## Primary evidence artifacts

- EXP-10 champion: `outputs/exp10_dynamic_regional_intensity/`.
- G3 v2: `outputs/exp26_g3_contract_v2_evaluation/contract_v2_report.json`.
- Reality scoring: `outputs/exp27_reality_volume_2025_2026/run_manifest.json`.
- Refresh rejection: `outputs/exp28_operational_refresh_reality_holdout/`.
- G5 conformal: `outputs/g5_conformal_ic95_guarded_exp10/g5_report.json`.
- Shadow monitor: `outputs/shadow_monitor/shadow_scores.jsonl` and `outputs/shadow_monitor/monitoring_report.md`.
- Production contract: `outputs/production_ml_plan.json`.
- Verified LLM XAI: `src/production/llm_xai.py`, `tests/test_llm_xai.py`, `docs/LLM_XAI_CONTRACT.md` and `POST /v1/explain`.
- Containerization: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `docker/entrypoint.sh`, `docs/CONTAINERIZATION.md`.
- Monthly runbook plan: `outputs/monthly_operations_plan.json`.
- internal additions audit: `outputs/maintainer_additions_audit.md`.
