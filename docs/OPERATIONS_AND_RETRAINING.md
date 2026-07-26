# FireCast operations and retraining runbook

Updated: 2026-07-13.

This is the operator runbook for keeping FireCast fed with new months while
protecting the frozen validation protocol.  It assumes commands are executed
from `firecast/`.

## Current status

- Internal champion: `climatology_regional_intensity12`.
- Artifact: `outputs/champion_climatology_regional_intensity12/model.json`.
- Internal production: approved under G3 contract v2.
- External production: not approved yet; requires scored live shadow window and
  separate human authorization.
- Reality target for 2025/2026 scoring: public INPE event-level snapshot filtered
  to `AQUA_M-T`, not the all-sensor monthly aggregate.

## Start the API

```bash
./firecast serve
```

Equivalent explicit command:

```bash
PYTHONPATH=. python src/production/serving_api.py \
  --model-path outputs/champion_climatology_regional_intensity12/model.json \
  --host 0.0.0.0 \
  --port 8000
```

Health and core endpoints:

- `GET /health`: returns 200 only when the approved artifact is present and its
  hash is valid; otherwise returns 503.
- `POST /v1/predict`: prediction for `geocodigo`, `ano`, `mes`.
- `GET /v1/champion/summary`: champion metrics, gates and production status.
- `GET /v1/champion/monthly_series`: 24-month gate-window series for plots.
- `GET /v1/champion/municipio_ranking`: municipalities sorted by WAPE risk.
- `GET /v1/climate/enso`: ENSO context series used for interpretation.
- `POST /v1/explain`: exact XAI packet plus verified LLM-safe narrative.

Smoke test:

```bash
python -m pytest tests/test_serving_api.py tests/test_g6_serving_contract.py -q
```

## Verified LLM XAI

Use this when an operator needs a readable explanation without giving an LLM authority over the forecast:

```bash
./firecast explain
```

Equivalent API call:

```bash
curl -X POST http://localhost:8000/v1/explain \
  -H 'Content-Type: application/json' \
  -d '{"geocodigo":2300101,"ano":2026,"mes":10}'
```

The endpoint returns `xai_packet`, `llm_narrative`, `llm_contract` and `verification`. The packet is exact arithmetic from the hash-verified champion artifact. The verifier rejects any narrative that introduces a number not present in the packet. Details: `docs/LLM_XAI_CONTRACT.md`.

## Monthly feeding loop

Create the monthly plan first.  This records what will run and keeps the process
reproducible:

```bash
MONTHS="202608 202609" ./firecast monthly-plan
```

The plan is written to `outputs/monthly_operations_plan.json` and contains:

1. ingest the public INPE month(s);
2. validate data contracts;
3. rerun the reality scoring protocol;
4. score delayed shadow predictions against the sensor-aligned public target;
5. write the monitoring report;
6. smoke-test the API contract;
7. validate the checkpoint files.

## Ingest new public INPE months

Use the additive public snapshot only for scoring/monitoring unless a later
human decision formally promotes it into training.  The historical `inpe_local_v2`
remains frozen for comparable experiments.

```bash
python src/data/ingest_inpe_monthly_public_v3.py --months 202608 202609
python scripts/check_data_ingestors.py
```

Important target rule:

- Do use `data/snapshots/inpe_monthly_public_v3/events_target_region.csv` with
  `--target-satellite AQUA_M-T` for comparable 2025/2026 scoring.
- Do not compare all-sensor public counts with the AQUA_M-T historical target.
- Do not compare predictions for 31 served municipalities against partial v2
  observed rows without labeling it as partial coverage.

## Score reality and shadow

Reality scoring for the owner aggregate target:

```bash
python src/experiments/exp27_reality_volume_2025_2026.py
```

Shadow delayed score and report:

```bash
./firecast shadow-score
./firecast shadow-report
```

Equivalent explicit commands:

```bash
python -m src.production.shadow_monitor score \
  --target-path data/snapshots/inpe_monthly_public_v3/events_target_region.csv \
  --target-satellite AQUA_M-T

python -m src.production.shadow_monitor report \
  --target-path data/snapshots/inpe_monthly_public_v3/events_target_region.csv \
  --target-satellite AQUA_M-T
```

Artifacts:

- `outputs/shadow_monitor/shadow_log.jsonl`: append-only committed predictions.
- `outputs/shadow_monitor/shadow_scores.jsonl`: delayed scores keyed by model
  hash, target hash and target satellite.
- `outputs/shadow_monitor/monitoring_report.md`: freshness, WAPE, MAE, alerts
  and rollback notes.

## Retaining vs retraining

Do not retrain simply because a new month arrived.  New months first go through
scoring and monitoring.  Retraining is triggered only when at least one of these
conditions is documented:

- scored live shadow window shows degradation or target coverage drift;
- source schema/checksum changes in a way that affects training or serving;
- a new as-of causal feature block is available with source contract and
  manifest;
- annual refresh review is due;
- human owner approves a contract revision.

If retraining is triggered, the safe order is:

1. ingest immutable snapshots;
2. validate source contracts and manifests;
3. build as-of feature table;
4. run mandatory baselines;
5. run candidate search on training windows only;
6. evaluate frozen G0-G7 gates;
7. package only if promoted;
8. shadow/canary only with human authorization.

A challenger cannot use 2025/2026 to select parameters.  Those years are reality
checks until a new protocol is explicitly approved.

## Repackage current champion

Only repackage the current champion when source code changed but the model
contract is unchanged:

```bash
./firecast package
./firecast predict
python -m pytest tests/test_serving_api.py tests/test_g6_serving_contract.py -q
```

The package target is `outputs/champion_climatology_regional_intensity12/`.

## Export governance plans

```bash
./firecast plan
./firecast monthly-plan
python python src/mlops/contracts.py --out outputs/production_ml_plan.json
```

The production plan is written to `outputs/production_ml_plan.json`.  It is a
machine-checkable summary of sources, feature blocks, model families, evaluation
protocol, gates and retraining policy.

## Container workflow

The same API and operations can be run in containers:

```bash
docker compose build
docker compose up api
```

Run validation and monthly tasks with the `ops` profile:

```bash
docker compose --profile ops run --rm serving-test
docker compose --profile ops run --rm data-check
MONTHS=202608 docker compose --profile ops run --rm monthly-plan
docker compose --profile ops run --rm shadow-score
docker compose --profile ops run --rm shadow-report
```

Compose mounts `data/`, `outputs/` and `cache/` into `/app`, so delayed shadow
scores and reports are written back to the repository.  Full details are in
`docs/CONTAINERIZATION.md`.

## External release rule

External release remains blocked until all three are true:

1. at least three live shadow months are scored against the correct target;
2. no degradation alert is unresolved under the G3 v2/G7 monitoring contract;
3. a separate human authorization for external release is recorded in the ledger.

The internal approval from 2026-07-11 does not authorize external deployment.

