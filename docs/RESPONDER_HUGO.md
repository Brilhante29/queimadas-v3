# Respostas prontas

## Sobre Vercel/deploy

Fechei um pacote limpo em uma pasta unica `firecast`, sem arquivos internos de trabalho. Ele tem backend/API, app Streamlit, Docker, testes, todas as bases, champion, resultados, grafo XAI e demo com Ollama local. Para deploy: o frontend pode ir na Vercel; a API Python precisa rodar em um servico separado ou container. O README ja explica os comandos de teste, API, Docker e como atualizar os meses.

## Sobre INPE e INMET

Boa noite! Mando sim. So para alinhar: o dado de queimadas/focos que usamos como alvo e do INPE, principalmente o recorte `AQUA_M-T` para manter comparabilidade historica. O INMET nao e o dado de queimadas; ele entra como dado meteorologico/estacoes para contexto e validacao, porque as estacoes ficam relativamente distantes das cidades alvo.

No pacote estao os principais arquivos:
- INPE historico de treino: `data/snapshots/inpe_local_v2/inpe_monthly_merged.csv`
- INPE publico 2025/2026 para pontuar realidade: `data/snapshots/inpe_monthly_public_v3/events_target_region.csv` filtrando `satelite == "AQUA_M-T"`
- INMET: `data/snapshots/inmet_automatic_station_observed_v1/municipal_monthly_station_features.csv`

A comparacao correta do modelo e sempre com INPE `AQUA_M-T`, nao com todos os sensores somados.


## Sobre demonstracao visual

Tambem deixei uma demo Streamlit para apresentar o resultado: ela mostra real vs predito, ranking municipal, mapa, metricas do champion e um grafo XAI. A parte LLM roda local via Ollama em Docker e so narra fatos verificados; ela nao muda previsao nem inventa numero. Para abrir tudo automatico: `docker compose up --build`. Isso sobe API, Ollama, baixa/confere o modelo local e abre o Streamlit.
