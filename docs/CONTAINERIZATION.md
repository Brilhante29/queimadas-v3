# Containerizacao do FireCast

Atualizado: 2026-07-15.

A entrega foi configurada para subir a demonstracao completa com um unico comando. O stack padrao inicia a API, o Ollama, o preparo do modelo local e o dashboard Streamlit. Os servicos de teste, operacao mensal e shell continuam separados em profiles `ops` e `debug`.

## Arquivos

- `Dockerfile`: constroi a imagem Python `firecast:local` e compila os modulos criticos.
- `.dockerignore`: evita levar ambiente virtual, caches e segredos acidentais para a imagem.
- `docker/entrypoint.sh`: despacha comandos de API, dashboard, testes, shadow e XAI.
- `docker-compose.yml`: orquestra API, Ollama, pull automatico do modelo e Streamlit.

## Subir tudo automaticamente

```bash
docker compose up --build
```

Esse comando executa a sequencia operacional:

1. constroi a imagem da aplicacao;
2. sobe a API em `http://localhost:8000`;
3. espera o endpoint `/health` responder;
4. sobe o Ollama em `http://localhost:11434`;
5. baixa ou confere o modelo definido em `OLLAMA_MODEL`;
6. inicia o Streamlit em `http://localhost:8501` somente depois que a API esta saudavel e o modelo local foi preparado.

URLs finais:

```text
API:       http://localhost:8000
Ollama:    http://localhost:11434
Dashboard: http://localhost:8501
```

Modelo padrao:

```text
OLLAMA_MODEL=llama3.2:3b
```

Para trocar o modelo:

```bash
OLLAMA_MODEL=llama3.1:8b docker compose up --build
```

## Rodar somente a API

```bash
docker compose up api
```

Health check:

```bash
curl http://localhost:8000/health
```

Exemplo XAI pela API:

```bash
curl -X POST http://localhost:8000/v1/explain   -H 'Content-Type: application/json'   -d '{"geocodigo":2300101,"ano":2026,"mes":10}'
```

A resposta contem pacote XAI glass-box, grafo dirigido e narrativa verificada. O LLM local nao prediz, nao altera `y_pred` e nao pode introduzir numero novo.

## Checagens em container

```bash
docker compose --profile ops run --rm test
docker compose --profile ops run --rm serving-test
docker compose --profile ops run --rm data-check
docker compose --profile ops run --rm explain
docker compose --profile ops run --rm xai-graph
```

`serving-test` cobre contrato da API, G6, XAI verificado e comportamento fail-closed.

## Operacao mensal

Criar plano para novos meses INPE publicos:

```bash
MONTHS=202608 docker compose --profile ops run --rm monthly-plan
```

Pontuar e relatar shadow predictions contra o alvo publico AQUA-MT:

```bash
docker compose --profile ops run --rm shadow-score
docker compose --profile ops run --rm shadow-report
```

Os volumes `./data`, `./outputs` e `./cache` sao montados no container. Assim, dados ficam fora da imagem e os relatorios voltam para a pasta auditavel.

## Shell de debug

```bash
docker compose --profile debug run --rm shell
```

## Limite de producao

A containerizacao automatiza a demonstracao e o serving local. Ela nao autoriza deploy externo, nao retreina automaticamente e nao permite que o LLM mude previsoes. Release externo ainda exige shadow vivo pontuado e aprovacao humana separada.
