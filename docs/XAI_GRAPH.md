# Grafo de Atribuicao XAI

O FireCast expoe um grafo dirigido de XAI para cada previsao. O grafo e gerado a partir do mesmo pacote verificado usado por `POST /v1/explain`; ele nao chama o modelo novamente, nao permite que uma camada LLM altere numeros e carrega hashes que ligam o grafo ao pacote factual.

## Endpoints e Comandos

```bash
curl -X POST http://localhost:8000/v1/explain/graph \
  -H "Content-Type: application/json" \
  -d '{"geocodigo":2300101,"ano":2026,"mes":10}'

./firecast xai-graph
docker compose --profile ops run --rm xai-graph
```

## Estrutura do Grafo

O grafo usa `schema_version = firecast_xai_graph_v1` e contem:

- `nodes`: requisicao, artefato, alvo historico, climatologia municipal, janela de intensidade regional, equacao exata, predicao, intervalo e guarda numerica.
- `edges`: caminho operacional de dados e requisicao ate `base_climatology * regional_intensity_ratio = prediction`.
- `mermaid`: string `flowchart LR` para renderizacao simples.
- `packet_sha256` e `graph_sha256`: hashes para revisao, cache e validacao de interface.

Este grafo explica o champion servido. Ele nao e feature importance de modelo black-box e nao deve ser usado para alegar que features candidatas nao promovidas causaram a predicao.
