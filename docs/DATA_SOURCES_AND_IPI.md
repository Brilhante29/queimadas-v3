# Fontes de dados e estratégia espacial do FireCast

Pesquisa e revisão: 2026-07-02.

## Conclusão executiva

O FireCast deve separar claramente quatro papéis:

1. **Alvo observado:** focos de fogo ativo do INPE, mantendo sensor e regra de agregação consistentes no tempo.
2. **Campo meteorológico espacial:** ERA5-Land, acessado diretamente pelo Copernicus CDS ou pelo Open-Meteo com o modelo fixado, cobrindo inclusive municípios sem estação próxima.
3. **Observações de superfície:** INMET e, no Ceará, FUNCEME, usadas para controle de qualidade, validação e correção de viés da reanálise — não como única fonte espacial.
4. **Contexto físico e humano:** MODIS NDVI/EVI, MapBiomas, relevo, malhas do IBGE, vias e hidrografia.

NASA POWER é uma fonte climática complementar e de redundância. NASA FIRMS é uma fonte independente de focos para auditoria do INPE, não deve ser somada ao alvo sem deduplicação por sensor, tempo e localização.

## O que as conversas acrescentam ao projeto

As imagens mostram três decisões em discussão:

- uso de ERA5/ERA5-Land em consultas ponto a ponto;
- tentativa de adaptar o Índice de Perigo de Incêndio (IPI) do artigo de Pereira et al. (2020);
- baixa proximidade entre estações INMET e cidades-alvo no Ceará/Chapada do Araripe.

A preocupação com o INMET procede. Interpolação de poucas estações distantes pode criar superfícies artificiais e esconder efeitos de altitude, litoral e relevo. Reanálise não elimina incerteza, mas fornece uma grade espacial fisicamente consistente. O desenho recomendado é:

```text
ERA5-Land/Open-Meteo por grade dentro do município
                 +
INMET/FUNCEME para viés e validação local
                 +
MODIS/MapBiomas/relevo/pressão humana
                 ↓
estatísticas zonais por município e mês
                 ↓
features disponíveis no instante da previsão
```

“Ponto a ponto” não significa medição exata naquele ponto: ERA5-Land seleciona uma célula de grade próxima, e o Open-Meteo pode selecionar uma célula terrestre com elevação semelhante. Para municípios grandes, consultar somente o centroide é insuficiente. Deve-se amostrar todas as células que intersectam o polígono municipal e calcular média, mediana, percentis 10/90, máximo e fração de área crítica.

## Matriz de fontes

| Fonte | Uso no FireCast | Cobertura/resolução | Acesso oficial | Regra operacional |
|---|---|---|---|---|
| INPE Programa Queimadas | alvo principal, risco de fogo e área queimada | focos em quase tempo real; CSV/KML; produtos observados e previstos | [Dados Abertos INPE](https://data.inpe.br/queimadas/portal/dados-abertos/) | baixar arquivos anuais/mensais imutáveis; registrar satélite, versão e data de coleta |
| Open-Meteo Historical | acesso simples a reanálise | ERA5 0,25°; ERA5-Land 0,1°; horário | [Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) | fixar explicitamente ERA5/ERA5-Land; nunca deixar o provedor misturar modelos ao longo da série |
| Copernicus ERA5-Land | fonte climática histórica canônica | 0,1° (~9–11 km), horário, 1950–presente | [ERA5-Land time series](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-timeseries?tab=overview) | preferível para snapshot reprodutível e estatística zonal em lote |
| NASA POWER | redundância, radiação e agroclima | dados diários desde 1981; ponto e região; grade de origem preservada | [POWER Daily API](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) | definir `time-standard=UTC` ou `LST`; cachear por célula, não repetir coordenadas equivalentes |
| INMET | observação de superfície e validação | estações automáticas/convencionais; históricos desde 2000 no portal | [Históricos](https://portal.inmet.gov.br/dadoshistoricos), [catálogo de estações](https://portal.inmet.gov.br/paginas/catalogoaut), [BDMEP](https://portal.inmet.gov.br/servicos/bdmep-dados-hist%C3%B3ricos) | guardar distância, altitude, cobertura e percentual de faltantes; rejeitar interpolação sem suporte espacial |
| FUNCEME | validação regional e precipitação no Ceará | rede estadual mais densa e produtos locais | [FUNCEME](https://www.funceme.br/) | priorizar como validação regional quando houver série e licença de acesso documentadas |
| NASA FIRMS | auditoria independente de focos | MODIS/VIIRS NRT e processamento padrão | [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | usar chave em variável de ambiente; para histórico, preferir produtos `SP`, não misturar com `NRT` |
| MODIS MOD13Q1 V6.1 | NDVI/EVI e estresse da vegetação | 250 m, composição de 16 dias | [Catálogo MOD13Q1](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MOD13Q1) | aplicar escala 0,0001 e máscaras `DetailedQA`/`SummaryQA`; respeitar data real de publicação |
| MapBiomas | combustível e uso/cobertura da terra | mapas anuais de cobertura | [MapBiomas Brasil](https://brasil.mapbiomas.org/) | versionar coleção e ano; usar somente mapas publicados antes do corte da previsão |
| IBGE | malha municipal, população e densidade | polígonos municipais SIRGAS 2000 | [Malhas municipais](https://www.ibge.gov.br/geociencias/organizacao-do-territorio/malhas-territoriais/15774-malhas.html) | usar geocódigo IBGE como chave, nunca nome normalizado como chave principal |

## Endpoints e exemplos

### Open-Meteo / ERA5-Land

Endpoint usado no projeto:

```text
https://archive-api.open-meteo.com/v1/archive
```

Parâmetros mínimos: `latitude`, `longitude`, `start_date`, `end_date`, variáveis `hourly` ou `daily`, `timezone` para agregações diárias e seleção explícita do modelo ERA5-Land. Variáveis prioritárias: temperatura a 2 m, umidade relativa, ponto de orvalho, precipitação, VPD, vento, radiação, evapotranspiração e umidade do solo.

Para treinamento de longo prazo, a série precisa usar um único produto consistente. Para previsão operacional, é necessário arquivar previsões emitidas no passado com horizonte fixo; usar reanálise como feature histórica e previsão meteorológica atual na produção cria *train-serving skew*.

### NASA POWER

Endpoint usado no projeto:

```text
https://power.larc.nasa.gov/api/temporal/daily/point
```

Exemplo de parâmetros: `parameters=T2M,T2M_MAX,PRECTOTCORR,RH2M,WS10M,ALLSKY_SFC_SW_DWN`, `community=AG`, coordenadas, datas `YYYYMMDD`, formato JSON e padrão temporal explícito. A API limita uma requisição pontual a 20 parâmetros e pode responder `429`; implementar retry exponencial e cache por célula.

### INPE

O acesso canônico deve partir da página de Dados Abertos. Ela oferece focos em CSV/KML, arquivos diários, mensais, anuais e atualização quase em tempo real, além de risco de fogo, meteorologia e área queimada. O endereço atualmente codificado em `ingest_inpe.py` deve ser tratado como adaptador sujeito a mudança e validado por teste de contrato; o pipeline deve ter fallback para os arquivos oficiais, não para dados sintéticos.

Campos mínimos a preservar no nível de evento: `data_hora_gmt`, latitude, longitude, satélite, instrumento, município/geocódigo, bioma, FRP, risco de fogo, precipitação e dias sem chuva quando disponíveis. O alvo mensal deve ser criado por *spatial join* com a malha IBGE da versão registrada.

### INMET

Não foi localizada documentação oficial de uma API pública estável equivalente às APIs NASA/Open-Meteo. Os canais oficiais documentados são catálogo CSV, downloads históricos anuais e BDMEP. Portanto, o ingestor deve usar arquivos versionados e checksums, e não endpoints internos descobertos por engenharia reversa.

Cada valor interpolado precisa carregar `station_count`, `nearest_station_km`, `max_station_km`, `elevation_delta_m`, `observed_fraction` e método. Se houver menos de três estações com dados válidos, ou geometria espacial ruim, a interpolação deve ser marcada como indisponível. Para este projeto, INMET é melhor como referência para avaliar e corrigir ERA5-Land do que como grade meteorológica principal.

## Adaptação do IPI

O artigo [“Desenvolvimento do Índice de Perigo de Incêndio (IPI)”](https://periodicos.ufsm.br/cienciaenatura/article/view/37624) combina o “triângulo do fogo” em três blocos com pesos de um terço:

- combustível: NDVI, material combustível/uso do solo, FMI e FMA;
- condições físicas: declividade, altitude e orientação das vertentes;
- ignição/pressão humana: densidade demográfica, vias e hidrografia.

As variáveis dinâmicas são temperatura, umidade, chuva/dias sem chuva, FMI, FMA e NDVI. As estáticas são cobertura da terra, relevo, densidade, vias e hidrografia. O estudo usou MODIS em composições de 16 dias, estações INMET e focos INPE para validação histórica.

No FireCast, o IPI deve entrar primeiro como **feature candidata**, não como verdade nem como substituto do modelo:

- `fmi_available_lag1`, `fmi_mean_lag1`, `fmi_p90_lag1`;
- `fma_available_lag1`, `fma_last_lag1`, `fma_max_lag1`;
- `ndvi_median_available`, `ndvi_p10_available`, `ndvi_anomaly_available`;
- `fuel_landcover_share`, `slope_p90`, `north_facing_share`;
- `road_density`, `distance_to_road_p10`, `population_density`, `distance_to_water_p10`;
- `ipi_proxy_lag1` e componentes separados por bloco.

O sufixo `available` significa “publicado e disponível no instante do corte”. A equação completa do artigo está incorporada como imagem no HTML; ela deve ser transcrita e testada contra um exemplo do artigo antes de qualquer implementação. Os coeficientes foram ajustados empiricamente em outra região, então precisam ser recalibrados no Ceará sem usar o período de teste.

## Protocolo espacial recomendado

1. Baixar e versionar a malha IBGE; usar geocódigo como chave.
2. Criar uma grade ERA5-Land de 0,1° cobrindo Ceará, Pernambuco e Piauí uma única vez.
3. Fazer interseção grade–município e armazenar pesos por área; não repetir chamadas para centroides que caem na mesma célula.
4. Agregar diariamente e mensalmente com estatísticas zonais e cobertura observada.
5. Associar estações INMET/FUNCEME à grade e medir o erro da reanálise por estação, mês e regime climático.
6. Aplicar correção de viés treinada apenas no passado de cada corte temporal.
7. Agregar MODIS/MapBiomas/relevo no polígono municipal com máscaras de qualidade.
8. Registrar `source`, `dataset_version`, `retrieved_at`, `available_at`, unidade, timezone, método e checksum para toda feature.

## Problemas encontrados no código atual

- `load_municipality_coords("brazil")` usa apenas uma amostra e capitais; isso não representa o Brasil.
- Open-Meteo consulta um centroide por município e não fixa claramente o produto de reanálise na requisição.
- NASA POWER repete chamadas por município mesmo quando vários centroides pertencem à mesma célula de origem.
- A chave municipal é baseada parcialmente em nomes; deve migrar para geocódigo IBGE.
- O ingestor FIRMS contém `demo_key` no código; a chave deve vir de `FIRMS_MAP_KEY` e a execução deve falhar sem credencial.
- Não existe ingestor INMET/FUNCEME nem relatório de distância/cobertura das estações.
- Climatologias e anomalias ainda precisam ser calculadas dentro de cada janela de treino do backtest.
- Não há registro sistemático de `available_at`, o que impede provar ausência de leakage para fontes com atraso de publicação.

## Ordem de implementação

1. Corrigir identidade municipal e ingestão completa da malha IBGE.
2. Criar snapshot ERA5-Land por grade e estatística zonal municipal.
3. Criar ingestor de arquivos INMET e relatório de cobertura espacial; avaliar FUNCEME no Ceará.
4. Versionar o alvo INPE por sensor e produto; adicionar auditoria FIRMS.
5. Implementar MOD13Q1 com QA e datas de disponibilidade.
6. Implementar os componentes do IPI e executar ablação walk-forward.
7. Somente promover as features que melhorarem o modelo em múltiplas janelas e mantiverem calibração e estabilidade espacial.

