# FireCast - relatorio de progresso do modelo

Atualizado em 2026-07-13.

## Resumo executivo

O champion interno continua sendo `climatology_regional_intensity12` (EXP-10). Ele melhorou de forma real contra o baseline no protocolo estendido, e o gate G5 passou com calibracao IC95 guardada.

Em 2026-07-11 o owner humano aprovou o **contrato G3 v2** (DECISION-G3-CONTRACT-V2) apos a auditoria EXP-25 demonstrar que o v1 (WAPE municipal-mes <= 0.20/0.25) estava na zona de ruido irredutivel do alvo. O EXP-26 avaliou o champion no protocolo congelado e **todos os gates G0-G7 estao PASS** â€” G3 no contrato v2 e G7 escopado a **producao interna** (OPS-G7-APPROVAL), com shadow vivo comprometido para 2026-05..08. Release EXTERNO pendente de janela de shadow pontuada + autorizacao especifica. Em 2026-07-13 foi adicionada uma camada LLM-XAI verificada que nao muda o modelo: ela narra somente um pacote de atribuicao exato e falha fechado se tentar introduzir numero nao aprovado.

Historico que sustenta a decisao: as iteracoes 39-41 testaram grafo espacial IBGE, populacao/area IBGE, NDVI local exploratorio, area agricola PAM e meteorologia observada INMET oficial; todos falharam o G3 v1 (dez falhas consecutivas na familia de alocadores total-preserving).

## Champion atual

| Modelo | Protocolo | WAPE geral | WAPE out-nov | WAPE seco | Status |
|---|---|---:|---:|---:|---|
| `climatology_municipal` | 2015-2024, 120 cortes | 0.7906 | 0.6923 | 0.7427 | Baseline anterior |
| `climatology_regional_intensity12` | 2015-2024, 120 cortes | 0.6430 | 0.5419 | 0.5983 | **Champion interno** |

EXP-10 melhora WAPE geral em -0.1476 e out-nov em -0.1505; CI95 bootstrap do delta WAPE = [-0.2195, -0.0852], P(candidato melhor)=1.000.

## G5 fechado

| Metrica | Valor |
|---|---:|
| Selecao | ano 2022 |
| Gate | anos 2023-2024 |
| Alpha selecionado | 0.04 |
| Cobertura geral gate | 0.9170 |
| Cobertura seca gate | 0.9000 |
| Cobertura chuva gate | 0.9274 |
| Faixa aceitavel | [0.90, 0.98] |
| Decisao | G5 PASS |

## G3: fronteira testada

| Familia | Melhor evidencia | WAPE critico gate |
|---|---|---:|
| Memoria municipal | `municipal_recent_ratio_k12_s5_l0.5` | 0.4660 |
| Oracle proibido | `oracle_monthly_total_climatology_shape` | 0.4680 |
| Eventos pontuais | audit-only `event_pressure_allocator` | 0.4916 |
| Classificacao/hurdle | `hurdle_exp10_thr0.4_scale0` | 0.4976 |
| Lag blend | `exp10_0.6_lag12_0.4` | 0.4980 |
| Champion atual | `climatology_regional_intensity12` | 0.4993 |
| Grafo IBGE | selected CE `graph_own_roll12_l0p1` | 0.5043 |
| FIRMS multi-sensor | selected CE `firms_count_roll6_l0p1` | 0.5088 |
| Populacao/area IBGE | seletor manteve champion | 0.4993 |
| NDVI local exploratorio | seletor manteve champion | 0.4993 |
| PAM area agricola temporaria | seletor manteve champion | 0.4993 |
| INMET seca observada | seletor CE manteve champion; audit-only `inmet_tilt_vpd3_p0p15` 0.4639 | 0.4993 |

Alvo G3: <=0.20 para CE e <=0.25 para Chapada/Cariri. Nenhum candidato valido chegou perto.

## Resultado das novas hipoteses

| Experimento | Hipotese | Resultado |
|---|---|---|
| EXP-20 | Grafo espacial IBGE + pressao de fogo defasada melhoraria alocacao. | REJECT: selected CE 0.5043; selected Chapada champion 0.5110; best Chapada audit-only 0.5024 ainda falha. |
| EXP-21 | Populacao, densidade e area IBGE capturariam pressao humana/exposicao. | REJECT: seletor manteve champion; todos os alocadores estaticos pioraram. |
| EXP-22 | NDVI local indicaria valor de priorizar MOD13Q1 oficial. | EXPLORATORY REJECT: CSV local sem QA/available_at e invalido para promocao; mesmo exploratoriamente nao supera champion. |
| EXP-23 | Area plantada PAM/IBGE por cultura funcionaria como fuel/uso do solo anual. | REJECT: seletor manteve champion; best Chapada audit-only mandioca_share = 0.5097. |
| EXP-24 | Seca observada INMET defasada (deficit de chuva, VPD) melhoraria a alocacao por ser mensal-dinamica. | REJECT: selecao CE manteve champion; selecao Chapada piorou o gate congelado (0.6247 vs 0.5110); best CE audit-only 0.4639 nao e selecionavel. |
| EXP-25 | Os limites G3 estao abaixo do piso estatistico irredutivel (nenhum modelo pontual passa). | REJECT na forma forte (piso Poisson 0.169/0.226 < limites), mas inatingibilidade pratica triangulada: piso NB 0.384/0.534 e desacordo INPE-FIRMS 0.412/0.427 acima dos limites; champion ja faz 0.2245/0.1794 em totais CE. |

Conclusao: o fail de G3 nao e resolvido por mais uma redistribuicao municipal mensal simples. Nos melhores candidatos, zero indevido = 0.0 e Recall@10 = 0.775 (Ceara) / 0.900 (Chapada). O fail e WAPE, isto e magnitude/alocacao espacial nos meses criticos.

## Gates atuais

| Gate | Status | Por que |
|---|---|---|
| G0 | PASS | Suite host 56/56; container serving-test 16/16; data-check OK (20 snapshots, 26 ingestores); checkpoint/sync validos. |
| G1 | PASS | Dados reais versionados no caminho champion e nos snapshots novos, incluindo FIRMS, IBGE/PAM e INMET oficial. |
| G2 | PASS | EXP-10 bate baseline de forma consistente no protocolo estendido. |
| G3 | PASS (v2) | EXP-26: CE totais mensais 0.2245<=0.25; CE sazonal 0.1794<=0.20; Chapada sazonal 0.3723<=0.40; Recall@10 0.775/0.90; zero indevido 0.0; coerencia champion>=baseline. v1 encerrado por inviabilidade (EXP-25). |
| G4 | PASS | Gate 2023-2024 e fatia Chapada passam; estendido tem 2 alertas de baixo volume. |
| G5 | PASS | IC95 guardado cobre geral/seca/chuva dentro da faixa [0.90, 0.98]. |
| G6 | PASS | Serving fail-closed, contrato testado e LLM-XAI verificado em `/v1/explain`. |
| G7 | PASS (interno) | Aprovacao humana registrada; shadow vivo 2026-05..08 comprometido antes dos desfechos; rollback por sha256. Release EXTERNO pendente de janela de shadow pontuada. |

## Proxima linha de trabalho

1. Ingerir `inpe_local_v3` aditivo do canal oficial mensal do INPE (verificado 2026-07-11) para pontuar o shadow 2026-05..08; o v2 permanece congelado para experimentos.
2. Janela de release externo: sugerido 3 meses de shadow pontuado sem alerta de degradacao no contrato v2, seguido de autorizacao humana especifica.
3. WAPE municipal-mes (~0.50) segue como metrica informacional monitorada; linha grid/cell com MapBiomas/MOD13Q1 e opcional e so inicia com decisao explicita de investimento.
4. Nao reabrir a familia de alocadores total-preserving nem o contrato v1 sem informacao causal nova e decisao humana.

## Validacao da iteracao 43

- `py_compile` de EXP-26 e mudancas de serving: OK.
- `scripts/check_data_ingestors.py`: OK, 20 snapshots e 26 ingestores.
- `pytest tests -q`: 46/46 passando com asserts de status atualizados, 1 warning conhecido Starlette/httpx.
- `python src/mlops/contracts.py --out outputs/production_ml_plan.json`: valido.
- `python -m pytest tests -q`: valido.
- YAML/ledger: integros (32 entradas).
- Shadow log: 2026-05..08 em live_shadow + drill 2025-03, todos com sha256 do artefato.





## Validacao da iteracao 45

- Stack MLOps cientifico formalizado em `docs/SCIENTIFIC_MLOPS_STACK.md` e `src/mlops/contracts.py`.
- Runbook operacional/mensal formalizado em `docs/OPERATIONS_AND_RETRAINING.md` e `src/mlops/monthly_ops.py`.
- CLI/Makefile apontam para `outputs/champion_climatology_regional_intensity12`.
- Shadow publico AQUA-MT pontuado com `score_schema_version=v2_event_absence_is_zero`: ausencia de evento em alvo event-level e tratada como zero, nao como observado ausente.
- `pytest tests -q`: 46/46 passando, 1 warning conhecido Starlette/httpx.
- `scripts/check_data_ingestors.py`: OK, 20 snapshots e 26 ingestores.
- `python -m pytest tests -q`: OK.

## Validacao da iteracao 46

- Containerizacao criada: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker/entrypoint.sh` e `docs/CONTAINERIZATION.md`.
- Imagem `firecast:local` construida com sucesso via `docker compose build`.
- `docker compose --profile ops run --rm serving-test`: 11/11 passando.
- `docker compose --profile ops run --rm data-check`: OK, 20 snapshots e 26 ingestores.
- `docker compose --profile ops run --rm checkpoint`: valido.
- `docker compose --profile ops run --rm test`: 50/50 passando, 1 warning conhecido Starlette/httpx.
- `docker compose up -d api` + `GET /health`: status ok, champion `climatology_regional_intensity12`, production_status `producao_interna_aprovada_g3v2`; servico removido em seguida com `docker compose down`.

## Validacao da iteracao 48

- LLM-XAI verificado criado em `src/production/llm_xai.py`: pacote exato, prompt aterrado e guarda numerica `numeric_fact_guard_v1`.
- API exposta em `POST /v1/explain`; CLI `./firecast explain`; Compose `docker compose --profile ops run --rm explain`.
- `pytest tests -q`: 56/56 passando, 1 warning conhecido Starlette/httpx.
- `pytest tests/test_llm_xai.py tests/test_serving_api.py tests/test_containerization.py tests/test_mlops_contracts.py`: 18/18 passando.
- `docker compose build`: imagem `firecast:local` reconstruida sem BOM no entrypoint.
- `docker compose --profile ops run --rm serving-test`: 16/16 passando.
- `docker compose --profile ops run --rm explain`: explicacao verificada emitida dentro do container.
- Decisao: NO_MODEL_CHANGE. O champion permanece `climatology_regional_intensity12`; a melhoria e de XAI/governanca G6/G7, sem overfitting em 2025/2026.
