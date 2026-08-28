# FireCast

[![CI](https://github.com/Brilhante29/queimadas-v3/actions/workflows/ci.yml/badge.svg)](https://github.com/Brilhante29/queimadas-v3/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/Brilhante29/queimadas-v3?include_prereleases)](https://github.com/Brilhante29/queimadas-v3/releases)

FireCast e um pacote de pesquisa e producao para prever focos mensais de queimadas por municipio na regiao operacional Chapada do Araripe / CE-PE-PI. A entrega contem codigo, dados, testes, API, container, artefato champion, resultados e documentacao suficiente para um colega auditar, executar e continuar o trabalho sem depender do historico privado de desenvolvimento.

## Estado da Entrega

- Codigo, testes, API, container e artefato champion versionados no git.
- Subconjunto minimo de dados no repo (`data/snapshots/inpe_local_v2/`, `data/reference/`) — suficiente para a suite de testes passar sem download.
- Bases completas (~1.2 GB, `20` snapshots + bases brutas externas) entregues via [GitHub Releases](../../releases) — veja [Bases de Dados](#bases-de-dados).
- Modelo atual: `climatology_regional_intensity12`.
- Status: aprovado para uso interno sob contrato G3 v2; deploy externo ainda depende de janela shadow pontuada e autorizacao separada.
- Testes esperados: `python -m pytest tests -q`.

## Ideia Cientifica

O problema nao e tratado como classificacao binaria simples. O alvo principal e uma contagem mensal de focos ativos do INPE por municipio, com chave IBGE (`geocodigo`). O desenho foi construido para evitar tres erros comuns: misturar sensores sem controle, usar informacao do futuro em features historicas, e comparar metricas de tarefas diferentes como se fossem equivalentes.

A previsao atual usa um modelo glass-box porque, neste recorte, ele venceu a combinacao entre qualidade, estabilidade, interpretabilidade e operacionalizacao. Modelos candidatos com mais fontes foram testados, mas o champion mantido foi o que entregou melhor compromisso fora da amostra sem overfitting em 2025/2026.

## Modelo Vencedor

O champion e:

```text
climatology_regional_intensity12
```

A formula operacional e:

```text
predicao = climatologia_municipal_do_mes * fator_regional_de_intensidade_12m
```

Onde:

- `climatologia_municipal_do_mes`: media historica do municipio naquele mes do calendario.
- `fator_regional_de_intensidade_12m`: razao entre observado e esperado nos ultimos 12 meses regionais ja conhecidos.
- O mes alvo nunca entra no fator regional.
- O artefato empacotado fica em `outputs/champion_climatology_regional_intensity12/model.json`.

A escolha e proposital: o modelo e simples o bastante para explicar exatamente cada previsao, mas forte o bastante para superar o baseline climatologico no protocolo congelado.

## Metricas Principais da IA

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

## Bases de Dados

As bases completas (~1.2 GB) nao ficam no git. Elas sao entregues como assets
de um [GitHub Release](../../releases). Baixe e extraia na raiz do projeto:

```bash
# baixe os assets do release mais recente (data-v3-*.tar.gz) e extraia:
tar -xzf firecast-data-snapshots.tar.gz     # -> data/snapshots/
tar -xzf firecast-data-external-bases.tar.gz # -> data/raw_external_bases/ + reference/
```

O repositorio ja inclui o subconjunto minimo (`data/snapshots/inpe_local_v2/`,
`data/reference/`, `data/ALL_BASES_MANIFEST.json`) para rodar os testes sem
download. Para reproduzir realidade/scoring 2025-2026 e os experimentos
completos, baixe o release.

As bases estao organizadas em:

```text
data/snapshots/          snapshots versionados e com manifestos
data/raw_external_bases/ arquivos brutos recebidos ou preservados para auditoria
data/ALL_BASES_MANIFEST.json inventario estruturado de todas as bases
```

Principais papeis:

- INPE: alvo de focos de queimadas.
- INMET: contexto meteorologico/estacoes e validacao, nao alvo de queimadas.
- FIRMS: auditoria independente e comparacao de sensores.
- ERA5/Open-Meteo: campo meteorologico espacial e features candidatas.
- ENSO: regime climatico mensal.
- IBGE: identidade municipal, malha, populacao, grafo espacial e contexto humano.
- PAM/NDVI/NASA: bases auxiliares ou exploratorias, conforme contrato de fonte.

Veja `docs/ALL_BASES.md` para a lista completa.

## Estrutura do Projeto

```text
app/                    frontend fonte para dashboard/API
streamlit_app/          vitrine executiva com real vs predito e XAI Ollama
docker/                 entrypoint do container
configs/                configuracoes de escopo, gates e fontes
data/snapshots/         todas as bases versionadas
data/raw_external_bases/ bases brutas preservadas
docs/                   metodologia, operacao, XAI e inventario
outputs/                champion, metricas, gates, relatorios e evidencias
scripts/                checagens operacionais de dados
src/data/               ingestores e construtores de snapshots
src/experiments/        experimentos, auditorias e reality checks
src/features/           feature store e controles de leakage
src/mlops/              contratos G0-G7 e plano mensal
src/models/             baselines e familias candidatas
src/production/         API, champion, shadow monitor e XAI
tests/                  testes de contrato, regressao e producao
```

## XAI e Grafo Explicavel

O FireCast tem XAI exato porque o champion e glass-box. Para cada previsao, o sistema retorna:

- pacote de fatos verificaveis (`xai_packet`);
- narrativa numericamente conferida;
- grafo dirigido de atribuicao (`xai_graph`);
- string Mermaid para renderizacao rapida;
- hashes `packet_sha256` e `graph_sha256`.

Endpoints:

```text
POST /v1/explain
POST /v1/explain/graph
```

Comando local:

```bash
./firecast explain
./firecast xai-graph
```

O grafo mostra o caminho:

```text
requisicao + alvo historico INPE
        -> climatologia municipal + intensidade regional 12m
        -> equacao exata
        -> predicao
        -> intervalo
        -> guarda numerica
```

A camada LLM, quando usada, fica apenas depois da predicao. Ela nao pode alterar `y_pred`, nao pode criar numero novo e falha se a narrativa sair do pacote verificado.

## Como Rodar Localmente

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests -q
python src\production\serving_api.py --model-path outputs\champion_climatology_regional_intensity12\model.json
```

Linux/macOS/Git Bash:

```bash
./firecast test
./firecast serve
./firecast predict
./firecast explain
./firecast xai-graph
```


## Dashboard Streamlit + Ollama

A entrega inclui uma vitrine visual em `streamlit_app/firecast_dashboard.py`. Ela foi desenhada para demonstrar o modelo para banca, orientador ou parceiro tecnico sem misturar interface com treino:

- mostra `observado vs predito` em 2025/2026 e no backtest 2023-2024;
- exibe os maiores erros por municipio e o mapa pontual de robustez;
- abre uma previsao individual por municipio/ano/mes;
- renderiza o grafo XAI dirigido do pacote `xai_graph`;
- chama um LLM local via Ollama somente para narrar fatos ja congelados;
- valida a narrativa contra o pacote XAI antes de exibir como verificada.

Rodar localmente:

```bash
streamlit run streamlit_app/firecast_dashboard.py
```

Rodar com Docker de forma automatica:

```bash
docker compose up --build
```

Esse comando constroi a imagem da aplicacao, sobe a API em `http://localhost:8000`, sobe o Ollama em `http://localhost:11434`, baixa/confere o modelo local e abre o Streamlit em `http://localhost:8501`.

Modelo padrao do Ollama: `llama3.2:3b`. Para trocar:

```bash
OLLAMA_MODEL=llama3.1:8b docker compose up --build
```

Importante: o Ollama nao calcula previsao, nao calibra parametro e nao decide gate. Ele recebe um prompt aterrado em JSON verificado, gera texto, e o `numeric_fact_guard_v1` rejeita a resposta se aparecer numero fora do pacote.

## API

Exemplo:

```bash
curl -X POST http://localhost:8000/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"geocodigo":2300101,"ano":2026,"mes":10}'
```

Endpoints principais:

- `GET /health`
- `POST /v1/predict`
- `POST /v1/explain`
- `POST /v1/explain/graph`
- `GET /v1/champion/summary`
- `GET /v1/champion/monthly_series`
- `GET /v1/champion/municipio_ranking`
- `GET /v1/champion/municipio_monthly_series?geocodigo=<int>&ano=<int?>`
  (cada linha traz `cobertura_completa: bool`, indicando se o `ano` daquela
  linha tem os 12 meses no backtest; `y_sum` e sempre inteiro (contagem
  historica bruta), `pred_sum` e um valor real (previsao de climatologia) e
  nao deve ser arredondado por esta API — arredondamento, se necessario, e
  responsabilidade da camada de persistencia do consumidor)
- `GET /v1/climate/enso`

## Docker

```bash
docker compose up --build
```

Para subir somente a API, use `docker compose up api`.

Checagens operacionais:

```bash
docker compose --profile ops run --rm test
docker compose --profile ops run --rm serving-test
docker compose --profile ops run --rm data-check
docker compose --profile ops run --rm explain
docker compose --profile ops run --rm xai-graph
```

## Atualizacao Mensal

Novos meses devem ser ingeridos, validados e pontuados antes de qualquer retreinamento:

```bash
python src/data/ingest_inpe_monthly_public_v3.py --months 202608 202609
python scripts/check_data_ingestors.py
python src/experiments/exp27_reality_volume_2025_2026.py
python -m src.production.shadow_monitor score --target-path data/snapshots/inpe_monthly_public_v3/events_target_region.csv --target-satellite AQUA_M-T
python -m src.production.shadow_monitor report --target-path data/snapshots/inpe_monthly_public_v3/events_target_region.csv --target-satellite AQUA_M-T
```

Regra: nao ajustar parametro usando 2025/2026 como busca escondida. Esses anos sao realidade atrasada/scoring, salvo revisao conjunta de protocolo.

## Limites e Cuidados

- INMET nao substitui INPE; ele ajuda a interpretar condicoes meteorologicas.
- Bases `unverified` estao incluidas para transparencia, mas nao provam qualidade de producao sozinhas.
- WAPE municipal-mes e ruidoso; o contrato operacional usa agregados, sazonalidade critica, ranking e incerteza.
- Deploy externo exige janela shadow e autorizacao especifica.
- Decisoes finas de threshold, ablacao e promocao de novo modelo devem ser revisadas com os autores do projeto.
