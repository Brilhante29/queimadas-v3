# FireCast LLM-safe XAI contract

Updated: 2026-07-13.

## Claim

FireCast now uses an LLM-compatible XAI layer with a hard production boundary:

the LLM never predicts, never changes a prediction and never introduces a number.

The champion is already a glass-box model:

```text
y_pred = municipal_month_climatology * regional_intensity_ratio
```

The XAI layer exposes that exact multiplication as a machine-readable packet and
then validates any natural-language narrative against the packet. If a narrative
contains a numeric token that is not present in the packet, the verifier rejects
it. This makes the LLM useful for communication while preserving the integrity of
serving.

## Implementation

| Layer | File / endpoint | Role |
|---|---|---|
| Exact attribution | `src/production/llm_xai.py::build_xai_packet` | Reads the hash-verified champion artifact and reconstructs base climatology, regional multiplier, prediction and p90 interval. |
| LLM prompt contract | `build_llm_grounding_prompt` | Gives an external LLM only verified JSON facts and forbids new numbers. |
| Narrative verifier | `verify_narrative_against_packet` | Fails closed if the text contains an unapproved number. |
| API | `POST /v1/explain` | Returns the exact packet, verified narrative, prompt contract and verifier result. |
| CLI/container | `./firecast explain`, `docker compose --profile ops run --rm explain` | Local reproducible sample explanation. |

## Why this is XAI gain

Classical model explanation often estimates attribution after the fact. FireCast
can do better because the champion is interpretable by construction. The XAI
packet is not a surrogate explanation; it is the same arithmetic used for
serving:

1. load `model.json` and verify `artifact_sha256`;
2. find the municipal-month climatology row;
3. find the regional trailing-12-month intensity row, or the documented latest
   training ratio for future periods;
4. compute `base * ratio`;
5. assert that the result equals `predict_one` and that the p90 interval matches;
6. only then render/validate a narrative.

The LLM adds value only after this proof: it turns an exact attribution packet
into readable operational language. The verifier prevents hallucinated counts,
wrong intervals, wrong years and invented percentages from reaching the user.

## Failure policy

- Missing or tampered model artifact: fail closed.
- Unknown municipality/month: fail closed.
- XAI arithmetic differs from served prediction: fail closed.
- LLM narrative contains any unapproved number: fail closed.
- External release remains blocked by the existing G7 external rules; XAI does
  not authorize deployment.

## Example

```bash
./firecast explain
```

API:

```bash
curl -X POST http://localhost:8000/v1/explain \
  -H 'Content-Type: application/json' \
  -d '{"geocodigo":2300101,"ano":2026,"mes":10}'
```

The response contains:

- `xai_packet.prediction.y_pred`;
- `xai_packet.exact_attribution.base_climatology`;
- `xai_packet.exact_attribution.regional_intensity_ratio`;
- `llm_narrative.text`;
- `llm_contract.grounding_prompt_sha256`;
- `verification.status = verified`.

## Tests

`tests/test_llm_xai.py` proves:

- exact packet equals served prediction;
- verified response contains the LLM prompt and narrative;
- hallucinated numeric text is rejected;
- `/v1/explain` returns verified XAI;
- missing artifacts fail closed.

## Directed XAI Graph

`POST /v1/explain` now includes `xai_graph`, and `POST /v1/explain/graph` returns the graph only. The graph is generated from the verified packet and contains the exact attribution path: request + historical INPE target -> municipal climatology + trailing regional intensity -> exact equation -> prediction -> interval -> numeric guard.
