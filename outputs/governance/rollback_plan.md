# FireCast - Plano de Rollback

Atualizado em 2026-07-13.

## Principio

O serving e fail-closed por construcao: o artefato e um JSON versionado com hash sha256 verificado no load. Qualquer estado invalido resulta em erro explicito, nunca em previsao fabricada. O rollback e uma troca controlada de artefato/configuracao, seguida de verificacao de API e registro no checkpoint.

## Artefato atual

Champion interno atual: `climatology_regional_intensity12`.

Artefato servido: `outputs/champion_climatology_regional_intensity12/model.json`.

Status: aprovado para producao interna sob G3 v2. Release externo segue bloqueado por alertas de shadow publico AQUA-MT e falta de autorizacao humana externa especifica.

## Procedimento de rollback

1. Identificar o artefato bom anterior. Cada `model.json` carrega `artifact_sha256`, `created_at`, `model_name` e hashes de entrada. O hash atualmente servido aparece em `/health`.
2. Substituir o artefato apontado pelo servico. Para o champion atual, repor `outputs/champion_climatology_regional_intensity12/model.json` ou apontar explicitamente o servico para outro `model.json` aprovado.
3. Reiniciar o servico (`./firecast serve` ou `docker compose up api`). O load reverifica o hash; artefato adulterado ou incompativel deve falhar fechado.
4. Verificar `GET /health` e um `POST /v1/predict` com caso conhecido. A resposta deve mostrar o `model_name` e o `artifact_sha256` esperados.
5. Registrar a reversao em `outputs/public_results_summary.json`, `outputs/production_ml_plan.json`, `outputs/monthly_operations_plan.json` e `outputs/public_results_summary.json` quando aplicavel.
6. Rodar `./firecast checkpoint` e pelo menos os testes de serving antes de considerar o rollback concluido.

## Regeneracao deterministica

Se o artefato EXP-10 atual nao estiver disponivel, ele deve ser regenerado a partir dos snapshots versionados e das predicoes `outputs/exp10_dynamic_regional_intensity/`, seguindo o codigo em `src/production/champion_climatology.py` e validando os hashes resultantes antes de servir.

## Precedentes reais

- 2026-07-09: `climatology_municipal_p65` foi promovido em janela curta e revertido apos EXP-08 reprovar no protocolo estendido. A reversao cobriu artefato, API, testes e model card.
- 2026-07-11: `climatology_regional_intensity12` foi mantido como champion interno sob contrato G3 v2; release externo continuou bloqueado apesar de G0-G7 internos PASS.
- 2026-07-11: containerizacao validou empacotamento local, mas nao alterou o limite de release externo.

## Gatilhos de rollback em producao externa futura

- WAPE mensal realizado > champion + 0.05 por 2 meses consecutivos, apos revisao de denominador baixo;
- cobertura do intervalo abaixo de 0.88;
- drift material de schema, sensor-alvo ou cobertura do INPE;
- erro sistematico de dados de entrada;
- qualquer gate G0-G7 interno voltar para FAIL/UNKNOWN sem mitigacao documentada.

Qualquer gatilho dispara: congelar promocao em curso, reverter para o ultimo artefato aprovado, abrir investigacao e registrar no journal/ledger.
