# FireCast: production readiness

Updated on 2026-07-13.

O veredito por escopo esta no bloco gerado abaixo, produzido por
`scripts/build_public_results_summary.py` a partir dos artefatos. Nao edite
aquele bloco a mao: ele e reescrito e verificado no CI.

## Current verdict

<!-- FIRECAST:METRICS:START -->
> Bloco gerado por `scripts/build_public_results_summary.py`. Nao edite a mao.
> Todo numero e lido de artefato; o CI falha se este bloco divergir.

### Escopo vigente: APA Chapada do Araripe (36 municipios -- CE 18, PE 8, PI 10)

Status de producao: **NAO APROVADO PARA PRODUCAO**

Incerteza: `not_validated` -- G5 reprovado: G5_final_sealed_2025.json=FAIL ['cobertura PE 0.9896 fora de [0.9, 0.98]']; G5_conformal.json=FAIL ['cobertura geral 0.8762 fora de [0.9, 0.98]', 'cobertura CE 0.8819 fora de [0.9, 0.98]', 'cobertura PE 0.8490 fora de [0.9, 0.98]', 'cobertura PI 0.8875 fora de [0.9, 0.98]']

| Bloco | Metrica | Valor |
|---|---|---:|
| Walk-forward 120 cortes | WAPE baseline | `0.7850` |
| Walk-forward 120 cortes | WAPE champion | `0.7074` |
| Walk-forward 120 cortes | Delta WAPE | `-0.0775` |
| Estacao critica Out-Nov | WAPE baseline | `0.6710` |
| Estacao critica Out-Nov | WAPE champion | `0.5761` |
| Selecao | Bootstrap delta WAPE IC95 | `[-0.1315, -0.0307]` |
| Selecao | P(delta < 0) | `0.9995` |
| Selecao | Cortes vencidos | `0.7383` |
| Holdout selado 2025 | WAPE baseline | `0.6485` |
| Holdout selado 2025 | WAPE champion | `0.5611` |
| Holdout selado 2025 | Cobertura geral | `0.9537` |
| Holdout selado 2025 | Largura media | `10.1074` |

#### Gates

| Gate | Status |
|---|---|
| G0_data | **PASS** |
| G1_training | **PASS** |
| G2_selection | **PASS** |
| G5_conformal_incumbent_method | **FAIL** |
| G5_conformal_final_sealed_2025 | **FAIL** |

G5 reprovou. Motivo registrado: `['cobertura PE 0.9896 fora de [0.9, 0.98]']`.

#### Limitacoes conhecidas do G5

Duas ressalvas medidas, nao opinadas. Ambas saem de auditoria independente e
ficam aqui porque mudam a leitura do resultado de 2025.

1. **O intervalo e unilateral na pratica.** 420 de 432 intervalos (97.2%) tem limite inferior <= 0, que praticamente nao pode ser violado. Nas 12 linhas com piso testavel a cobertura cai para `0.5833`. Das violacoes, 17 sao por cima e 3 por baixo. A cobertura global de `0.9537` mede sobretudo o teto do intervalo.

2. **O teto do gate coincide com o nivel nominal.** Nominal `0.98`, teto aceitavel `0.98`. Um metodo perfeitamente calibrado estoura esse teto so por acaso amostral com a probabilidade abaixo:

| UF | n | Cobertura | Erros observados | Erros minimos p/ passar o teto | P(metodo perfeito reprova) |
|---|---:|---:|---:|---:|---:|
| CE | 216 | 0.9444 | 12 | 5 | 0.5660 |
| PE | 96 | 0.9896 | 1 | 2 | 0.4255 |
| PI | 120 | 0.9417 | 7 | 3 | 0.5687 |

   PE reprovou com 1 erro em 96. Precisaria de pelo menos 2 para passar: o gate
   penalizou acerto. O FAIL **permanece** -- reespecificar o criterio depois de ver
   o holdout seria ajuste no holdout, que o contrato proibe. O registro correto e
   que o metodo nao foi validado **e** que o gate, como especificado, tambem nao
   serve. Nova tentativa exige gate reescrito e pre-registrado antes de tocar em
   outro ano.

### Escopo legado: Cariri/CE -- NAO SE APLICA A APA

Preservado para rastreabilidade historica do projeto. Foi produzido sobre outro escopo, outro snapshot e outro recorte de avaliacao. Escopo: municipios do Ceara apenas; recorte 'chapada' interno de 50 celulas avaliadas; 31 municipios no artefato de treino.

**Qualquer afirmacao sobre desempenho na APA Chapada do Araripe. O escopo APA tem WAPE mais alto e G5 reprovado; usar estes numeros no lugar daqueles inverteria a conclusao.**

| Metrica legada (Cariri/CE) | Valor |
|---|---:|
| WAPE walk-forward estendido | `0.6430` |
| WAPE Out-Nov | `0.5419` |
| G3 v2 CE mensal | `0.2245` |
| G3 v2 CE sazonal | `0.1794` |
| G3 v2 'chapada' sazonal (recorte de 50 celulas) | `0.3723` |
| G5 legado cobertura geral (nominal 0.96) | `0.9170` |
| G5 legado gate | `PASS` |

O G5 legado passou com nominal 0,96 contra teto 0,98 -- tinha folga. O G5 da APA
usou nominal 0,98 contra o mesmo teto 0,98, sem folga nenhuma. Os dois numeros
nao sao comparaveis, e o PASS legado nao sustenta nada sobre a APA.
<!-- FIRECAST:METRICS:END -->

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
