# Dashboard Streamlit com XAI e Ollama

Este documento descreve a vitrine visual do FireCast. A aplicacao fica em `streamlit_app/firecast_dashboard.py` e serve para demonstrar o modelo champion sem alterar qualquer artefato de treino.

## Papel da interface

A interface mostra cinco blocos:

1. `Resumo`: metricas principais, contrato G3 v2 e grafico de realidade 2025/2026.
2. `Real vs predito`: comparacao mensal por cenario e backtest congelado 2023-2024.
3. `Municipios`: ranking de WAPE, volume real e mapa de centroides quando disponivel.
4. `XAI + Ollama`: predicao individual, grafo de atribuicao, pacote XAI e narracao local.
5. `Bases e operacao`: manifesto de snapshots, bases brutas e comandos de execucao.

## Contrato de XAI

O champion e glass-box. A atribuicao exata e:

```text
predicao = climatologia_municipal_do_mes * fator_regional_de_intensidade_12m
```

O grafo XAI explicita o caminho:

```text
requisicao -> climatologia municipal -> equacao exata -> predicao -> intervalo -> guarda numerica
       alvo historico INPE -> intensidade regional 12m ------^
       artefato hash-verificado -----------------------------^
```

O LLM local entra somente depois desse pacote existir. Ele recebe o `grounding_prompt`, escreve uma narrativa e passa por `verify_narrative_against_packet`. Se o texto contiver numero nao presente no pacote, a aplicacao rejeita a narrativa e mostra falha operacional.

## Ollama em Docker

O stack padrao sobe tudo de forma automatica:

```bash
docker compose up --build
```

O Compose executa esta sequencia:

1. constroi a imagem `firecast:local`;
2. sobe a API e aguarda `/health`;
3. sobe o servidor Ollama;
4. baixa ou confere o modelo definido em `OLLAMA_MODEL`;
5. inicia o Streamlit somente depois que a API esta saudavel e o modelo foi preparado.

URLs:

```text
API:       http://localhost:8000
Ollama:    http://localhost:11434
Dashboard: http://localhost:8501
```

Variaveis relevantes:

```text
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:3b
STREAMLIT_PORT=8501
```

Para modelos maiores, trocar `OLLAMA_MODEL` antes do `docker compose up --build`. A escolha do modelo afeta apenas fluidez da narracao, nao a predicao nem as metricas.

## Evidencia operacional

A demo usa arquivos congelados:

- `outputs/public_results_summary.json`
- `outputs/exp27_reality_volume_2025_2026/monthly_reality_comparison.csv`
- `outputs/exp10_dynamic_regional_intensity/predictions_2023_2024.csv`
- `outputs/g4_spatial_robustness_exp10_2023_2024/by_municipio.csv`
- `outputs/champion_climatology_regional_intensity12/model.json`
- `data/ALL_BASES_MANIFEST.json`

Nenhum desses arquivos e reescrito pela interface.
