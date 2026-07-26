# Política de Segurança

## Reportar vulnerabilidade

Não abra uma issue pública para vulnerabilidades. Use os
[Security Advisories](../../security/advisories/new) do GitHub (relatório
privado) ou entre em contato diretamente com o mantenedor.

Descreva: componente afetado, passos para reproduzir, impacto e, se possível,
uma correção sugerida. Resposta esperada em até 7 dias.

## Escopo

- Vazamento de credenciais (ex.: `FIRMS_MAP_KEY`), tokens ou chaves.
- Falhas na API de serving (`src/production/serving_api.py`).
- Execução de código via entradas não validadas (ingestores, XAI, LLM).
- Configuração insegura de container (`Dockerfile`, `docker-compose.yml`).

## Boas práticas do projeto

- Segredos vivem apenas no ambiente / `.env` (git-ignored), nunca no código.
- A API é *fail-closed*: sem artefato válido, ela recusa em vez de inventar
  previsão.
- A camada LLM não pode criar números novos — `numeric_fact_guard_v1` rejeita
  qualquer valor fora do pacote XAI verificado.
