# FireCast production release audit

Data: 2026-07-13

## Verdict

**APROVADO PARA PRODUCAO INTERNA.**

**NAO APROVADO PARA PRODUCAO EXTERNA.**

O sistema esta apto para uso interno fail-closed sob o contrato G3 v2 aprovado em 2026-07-11. O release externo permanece bloqueado porque o shadow publico AQUA-MT de 2026-05..07 tem alertas de WAPE em meses de denominador baixo e ainda falta autorizacao humana externa especifica.

## Gates atuais

| Gate | Status | Evidencia |
| --- | --- | --- |
| G0 | PASS | Suite completa 56/56 no host; container `serving-test` 16/16; `scripts/check_data_ingestors.py` OK com 20 snapshots / 26 ingestores; checkpoint, sync de checklist e Compose config validos. |
| G1 | PASS | INPE v2 congelado para treino/validacao, INPE publico v3 para scoring aditivo, eventos INPE, ERA5, ENSO, FIRMS, IBGE e INMET versionados. |
| G2 | PASS | EXP-10: WAPE 0.6430 vs baseline 0.7906; out-nov 0.5419 vs 0.6923; CI95 bootstrap do delta WAPE totalmente negativo. |
| G3 | PASS (v2) | EXP-26: CE mensal escopo 0.2245 <= 0.25; CE sazonal 0.1794 <= 0.20; Chapada sazonal 0.3723 <= 0.40; zero indevido 0.0; Recall@10 CE/Chapada 0.775/0.900. |
| G4 | PASS | Robustez espacial/sazonal do EXP-10 passa na janela 2023-2024; riscos residuais de baixo volume documentados. |
| G5 | PASS | `g5_conformal_ic95_guarded_exp10`: cobertura 0.9170 geral, 0.9000 seca, 0.9274 chuva. |
| G6 | PASS | API fail-closed, hash do artefato, identidade treino-serving, smoke concorrente e LLM-XAI verificado em `/v1/explain` cobertos por testes. |
| G7 | PASS interno / externo bloqueado | Aprovacao humana interna, model/data card, rollback, shadow harness e containerizacao existem. Release externo exige shadow sem alerta e autorizacao humana separada. |

## Auditoria G3

O contrato v1 municipal-mes foi mantido como metrica informacional porque a auditoria EXP-25 mostrou ruido pratico alto nesse nivel de granularidade. O G3 de producao atual e o contrato v2, focado em escopos agregados e ranking operacional.

Evidencia principal do G3 v2:

| Metrica | Valor |
| --- | ---: |
| CE mensal por escopo | 0.2245 |
| CE sazonal | 0.1794 |
| Chapada sazonal | 0.3723 |
| Recall@10 CE | 0.775 |
| Recall@10 Chapada | 0.900 |
| Zero indevido | 0.0 |

As linhas negativas continuam documentadas e nao foram apagadas: regressao, classificacao/hurdle, clusterizacao, kernels espaciais, FIRMS, IBGE, NDVI local e INMET observado nao bateram o champion sem leakage. Essa evidencia justifica nao trocar o modelo por um candidato mais complexo apenas porque ele parece bom em uma janela curta.

## Realidade 2025/2026

O score de realidade usa INPE publico event-level filtrado em `AQUA_M-T`:

| Janela | Observado | Predito | Erro absoluto |
| --- | ---: | ---: | ---: |
| 2025 | 1571 | 1491.984 | 79.016 |
| 2026 Jan-Jun | 131 | 87.436 | 43.564 |

A comparacao anterior `686 observado vs 1492 predito` misturava alvo parcial v2 com cobertura completa de predicao e nao deve ser usada como decisao de promocao.

## LLM-XAI verificado

A camada LLM nao tem autoridade preditiva. A API monta primeiro o pacote exato `y_pred = municipal_month_climatology * regional_intensity_ratio`, derivado do artefato com hash verificado. A narrativa so e retornada se todos os tokens numericos forem aprovados pelo pacote; numero novo causa falha fechada.

Evidencia: `src/production/llm_xai.py`, `tests/test_llm_xai.py`, `docs/LLM_XAI_CONTRACT.md`, `POST /v1/explain`, `./firecast explain` e `docker compose --profile ops run --rm explain`.

## Decisao operacional

Pode rodar internamente via host ou container:

- `./firecast serve`
- `docker compose up api`
- `docker compose --profile ops run --rm test`
- `docker compose --profile ops run --rm shadow-score`
- `./firecast explain`
- `docker compose --profile ops run --rm explain`

Nao publicar externamente ate:

1. shadow live contra AQUA-MT estar pontuado sem alerta irresolvido;
2. a janela observada ser revisada com denominadores baixos explicitamente tratados;
3. autorizacao humana externa ser registrada no ledger.

## Evidencia final conhecida

- `docker compose build`: imagem `firecast:local` criada.
- `.venv/Scripts/python.exe -m pytest tests -q`: 56/56 passando.
- `docker compose --profile ops run --rm serving-test`: 16/16 passando.
- `docker compose --profile ops run --rm data-check`: 20 snapshots / 26 ingestores OK.
- `docker compose --profile ops run --rm checkpoint`: checkpoint valido.
- `docker compose --profile ops run --rm explain`: explicacao XAI verificada emitida no container.
- `docker compose up -d api` + `GET /health`: API ok com champion `climatology_regional_intensity12`.
