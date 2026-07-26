# FireCast - Changelog tecnico do modelo

Registro das decisoes de modelo. Detalhe completo por iteracao em `outputs/public_results_summary.json`; experimentos em `outputs/public_results_summary.json` e nos `run_manifest.json` de cada `outputs/exp*/`.

## 2026-07-13

- **Auditoria de continuidade**: documentos vivos de release/governanca foram reconciliados com o estado atual. `outputs/production_release_audit.md` e `outputs/governance/*` agora refletem G0-G7 PASS no escopo interno e release externo bloqueado por shadow/autorizacao, nao por G3 antigo.
- **Inventario das adicoes internal**: criado `outputs/maintainer_additions_audit.md` para separar dados, experimentos, producao, containerizacao, frontend e proximas acoes.
- **LLM-XAI verificado**: `src/production/llm_xai.py`, `POST /v1/explain`, `./firecast explain` e `docs/LLM_XAI_CONTRACT.md` adicionados. O LLM nao prediz nem altera numeros; a narrativa e validada por guarda numerica e falha fechado se introduzir valor fora do pacote XAI.

## 2026-07-11

- **Contrato G3 v2 aprovado para producao interna**: EXP-26 formalizou o contrato agregado/ranking. Resultado: CE mensal escopo 0.2245 <= 0.25; CE sazonal 0.1794 <= 0.20; Chapada sazonal 0.3723 <= 0.40; zero indevido 0.0; Recall@10 CE/Chapada 0.775/0.900.
- **G7 interno PASS**: aprovacao humana interna registrada, model/data card, rollback, shadow harness e API fail-closed presentes. Release externo continua pendente de shadow sem alerta e autorizacao humana separada.
- **Reality scoring corrigido**: EXP-27 usa INPE publico event-level filtrado em `AQUA_M-T`. 2025: observado 1571, predito 1491.984, erro 79.016. 2026 Jan-Jun: observado 131, predito 87.436, erro 43.564.
- **Refresh operacional rejeitado**: EXP-28 melhorou pouco 2026 curto e piorou 2025 completo; nao promove para evitar overfitting na janela de realidade.
- **Shadow publico v2_event_absence_is_zero**: 2026-05..07 pontuados contra AQUA-MT; alertas de WAPE em denominadores baixos bloqueiam release externo.
- **MLOps e runbook**: `src/mlops/contracts.py`, `src/mlops/monthly_ops.py`, `docs/SCIENTIFIC_MLOPS_STACK.md` e `docs/OPERATIONS_AND_RETRAINING.md` separam gates, dados, serving, shadow e retreino.
- **Containerizacao**: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker/entrypoint.sh` e `docs/CONTAINERIZATION.md` criados; suite container 50/50 na criacao, serving-test depois ampliado para 16/16 com LLM-XAI, data-check e checkpoint OK.

## 2026-07-09

- **EXP-10 PROMOTE interno**: `climatology_regional_intensity12` substitui a climatologia municipal simples. WAPE 0.7906 -> 0.6430, out-nov 0.6923 -> 0.5419, seco 0.7427 -> 0.5983, 85/120 cortes, CI95 delta WAPE [-0.2195, -0.0852]. G2 PASS.
- **G5 PASS**: conformal IC95 guardado selecionou alpha somente em 2022 e mediu 2023-2024: cobertura geral 0.9170, seca 0.9000, chuva 0.9274, dentro da faixa [0.90, 0.98].
- **EXP-12 G3 frontier sweep FAIL v1**: historicos, regressao, memoria municipal, clusterizacao, hurdle, lag blends e oracle proibido nao passam o antigo contrato municipal-mes. Melhor valido = `municipal_recent_ratio_k12_s5_l0.5`, WAPE critico 0.4660 contra alvo 0.20-0.25.
- **EXP-13/14 G3 FAIL v1**: eventos pontuais e kernel espaco-temporal total-preserving melhoraram apenas audit-only ou falharam selecao temporal; rejeitados por risco de selection leakage.
- **G6 fechado**: identidade treino/serving, determinismo, latencia local e carga concorrente cobertos por testes.
- **EXP-09 ENSO condicional REJECT**: fator multiplicativo por estado ENSO piorou o protocolo estendido.
- **EXP-07/EXP-08 promocao revertida**: percentil 65 pareceu bom em 24 cortes, mas falhou em 120 cortes; promocao exige protocolo estendido.

## 2026-07-08

- **EXP-06 ERA5 zonal compacto + Ridge REJECT**: WAPE 0.5529 vs 0.5501 no protocolo curto.
- **EXP-05 ERA5 zonal residual GBM REJECT**: WAPE 0.5779 vs 0.5501.
- **G4 robustez espacial/regime PASS**: 0/31 municipios com regressao material na janela auditada; regime seco melhor que o geral.
- **G5 v1/v2 FAIL**: bandas global e estratificada calibradas em 2023 nao cobriram 2024.

## 2026-07-03

- **EXP-04 residual ancorado REJECT**: WAPE 0.5521 vs 0.5501.
- **EXP-03 clima+NDVI REJECT**: melhor candidato 0.5754 vs 0.5501.

## 2026-07-02

- **Baseline real estabelecido**: `climatology_municipal`, snapshot `inpe_local_v2`, nove baselines executados.
- **Alvo corrigido para v2**: falsos zeros de borda de cobertura em quarentena; correlacao entre fontes corrigida em Campos Sales.
