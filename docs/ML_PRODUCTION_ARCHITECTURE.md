# ML production architecture - FireCast Chapada do Araripe

Updated: 2026-07-13.

Status: **approved for internal production under G3 contract v2**.  External
release is still blocked until a scored live shadow window and a separate human
authorization are recorded.

For the current scientific stack and references, also read
`docs/SCIENTIFIC_MLOPS_STACK.md`.  For operator commands, read
`docs/OPERATIONS_AND_RETRAINING.md`.

## Operational objective

Forecast monthly fire-focus counts by municipality (`geocodigo` IBGE).  The
first production scope is Chapada do Araripe / CE-PE-PI plus CE aggregate gate
slices.  A model can serve internally only when data identity, leakage controls,
baseline superiority, scope metrics, uncertainty, serving and governance all
pass.

## Current champion

`climatology_regional_intensity12` is the internal champion:

```text
pred = municipal_month_climatology * clip((observed_last_12m + 100) / (expected_last_12m + 100), 0.5, 2.0)
```

The target month is excluded from the regional-intensity factor.  The artifact is
`outputs/champion_climatology_regional_intensity12/model.json`.

Primary evidence:

| Evidence | Result |
|---|---:|
| EXP-10 WAPE | `0.6430` vs baseline `0.7906` |
| EXP-10 out-nov WAPE | `0.5419` vs baseline `0.6923` |
| EXP-10 won cuts | `85/120` |
| EXP-26 CE monthly scope WAPE | `0.2245 <= 0.25` |
| EXP-26 CE seasonal WAPE | `0.1794 <= 0.20` |
| EXP-26 Chapada seasonal WAPE | `0.3723 <= 0.40` |
| EXP-26 Recall@10 | CE `0.775`, Chapada `0.900` |
| G5 coverage | overall `0.9170`, dry `0.9000`, wet `0.9274` |
| EXP-27 2025 public AQUA-MT | observed `1571`, predicted `1491.984`, abs error `79.016` |
| EXP-27 2026 Jan-Jun public AQUA-MT | observed `131`, predicted `87.436`, abs error `43.564` |

## Architecture

```text
Source contracts
  -> immutable/additive snapshots + checksums
  -> point-in-time feature logic by geocodigo/ano/mes
  -> mandatory baselines + challengers
  -> frozen evaluation protocols
  -> G0-G7 gatekeeper
  -> versioned artifact + model/data cards
  -> fail-closed API + verified LLM XAI
  -> shadow monitor + delayed score + retraining decision
```

The code contract is `src/mlops/contracts.py`.  Export it with:

```bash
./firecast plan
```

## Data source roles

| Role | Source | Status | Correct use |
|---|---|---|---|
| Historical target | `inpe_local_v2` | PASS | Frozen training/evaluation target. Suspect gaps stay missing, never zero-filled. |
| Additive public target | `inpe_monthly_public_v3` | PASS | Scoring-only reality/shadow target; use event-level rows filtered to `AQUA_M-T`. |
| Event audit | `inpe_event_points_v1` | PASS | Event-level FRP/risk/location features and audits with strict lags. |
| Geometry | IBGE municipal/geocodigo snapshots | PASS | Entity identity and zonal operations. |
| Weather | ERA5/INMET/ENSO snapshots | PASS as sources | Candidate features only when lagged/as-of; tested variants did not beat the champion. |
| Fire audit | NASA FIRMS snapshots | PASS as audit | Independent audit/feature source; do not silently sum with INPE. |
| Human pressure | IBGE population/PAM | PASS as source | Static/annual features with publication-year rules; tested variants did not promote. |

## Gate contract

| Gate | Status | Evidence |
|---|---|---|
| G0 integrity | PASS | tests, data-check, checkpoint and checklist sync. |
| G1 real data/as-of | PASS | real snapshots, manifests, sensor-aligned public target. |
| G2 baseline superiority | PASS | EXP-10 improves WAPE and out-nov with CI95 delta below zero. |
| G3 scope contract v2 | PASS | EXP-26 aggregate scope and Recall@10 limits pass. |
| G4 spatial/slice robustness | PASS | 2023-2024 gate slices pass; residual risks documented. |
| G5 uncertainty calibration | PASS | conformal IC95 coverage in [0.90, 0.98]. |
| G6 serving contract | PASS | fail-closed API, artifact hash, train-serving identity tests. |
| G7 internal governance | PASS | human internal approval, cards, rollback, shadow harness. |

External production is not implied by these PASS states.  G7 is scoped to
internal production until live shadow evidence and human external authorization
are recorded.

## Serving

```bash
./firecast serve
```

The API must fail closed when the artifact is absent or its hash is invalid.
Relevant tests:

```bash
python -m pytest tests/test_serving_api.py tests/test_g6_serving_contract.py -q
```

## Monitoring and retraining

Monthly data arrival does not automatically retrain the model.  The correct
monthly loop is:

```bash
MONTHS="202608 202609" ./firecast monthly-plan
python src/data/ingest_inpe_monthly_public_v3.py --months 202608 202609
./firecast data-check
./firecast shadow-score
./firecast shadow-report
python python src/mlops/contracts.py --out outputs/production_ml_plan.json
```

Retraining requires a documented trigger: shadow degradation, source/schema
change, annual review, new as-of feature block or human-approved contract
revision.  A challenger must pass all internal gates before packaging and cannot
use 2025/2026 scoring windows to choose parameters.

## Current research frontier

The evidence from EXP-12 through EXP-24 shows that simple municipal allocation
variants are exhausted.  The next publishable improvement should enter as a new
source/architecture line, not as hidden tuning:

- grid/cell model with official vegetation/fuel and land-use layers;
- measurement-error-aware count model using INPE/FIRMS disagreement;
- hierarchical sparse-count model with audited uncertainty.

Each line must start with source contracts and end at the same G0-G7 gatekeeper.
