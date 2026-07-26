# FireCast: previsÃ£o mensal de focos de queimadas por municÃ­pio com validaÃ§Ã£o temporal estrita, anÃ¡lise de viabilidade estatÃ­stica e contrato de produÃ§Ã£o auditÃ¡vel

Rascunho de artigo - versao 1.1, 2026-07-13.
Todos os nÃºmeros citados sÃ£o reproduzÃ­veis a partir dos artefatos versionados listados na SeÃ§Ã£o 12.

---

## Resumo

Apresentamos o FireCast, um sistema de previsÃ£o mensal de focos de fogo ativo por municÃ­pio para o CearÃ¡ e a Chapada do Araripe (Brasil), com horizonte de 1 mÃªs. O modelo campeÃ£o Ã© deliberadamente simples â€” uma climatologia municipal por mÃªs modulada por um fator regional de intensidade dos Ãºltimos 12 meses observados â€” e foi selecionado apÃ³s 26 experimentos registrados em ledger imutÃ¡vel, dos quais 10 famÃ­lias de hipÃ³teses mais complexas (memÃ³ria municipal, eventos pontuais, kernels espaciais, dados FIRMS multi-sensor, grafo espacial IBGE, pressÃ£o populacional, NDVI, Ã¡rea agrÃ­cola PAM e meteorologia observada INMET) foram rejeitadas por nÃ£o superarem o campeÃ£o sob protocolo congelado. Em backtest walk-forward com 120 cortes mensais (2015â€“2024), o campeÃ£o reduz o WAPE de 0,7906 (climatologia municipal) para 0,6430 (âˆ’18,7%), com IC95 bootstrap do delta inteiramente negativo [âˆ’0,2195; âˆ’0,0852]. ContribuiÃ§Ã£o metodolÃ³gica central: uma auditoria de viabilidade estatÃ­stica com orÃ¡culo de mÃ©dia perfeita demonstra que o erro municipal-mÃªs do campeÃ£o (WAPE â‰ˆ 0,50 nos meses crÃ­ticos) estÃ¡ prÃ³ximo do piso irredutÃ­vel do alvo â€” a dispersÃ£o histÃ³rica implica piso â‰ˆ 0,38â€“0,53 e dois sistemas satelitais independentes (INPE vs. FIRMS) discordam em WAPE 0,41â€“0,43 ao medir os mesmos fogos. Isso motivou um contrato de produÃ§Ã£o em granularidade compatÃ­vel com o ruÃ­do: totais mensais por escopo (WAPE 0,2245), total sazonal (0,1794), ranking municipal (Recall@10 0,775â€“0,90), zero indevido nulo e intervalos conformes com cobertura empÃ­rica 0,917 para 95% nominal.

**Palavras-chave:** previsÃ£o de queimadas, sÃ©ries temporais de contagem, walk-forward, prediÃ§Ã£o conforme, piso de ruÃ­do aleatÃ³rio, WAPE.

---

## 1. IntroduÃ§Ã£o

A previsÃ£o mensal de focos de queimadas por municÃ­pio apoia alocaÃ§Ã£o preventiva de brigadas, fiscalizaÃ§Ã£o e comunicaÃ§Ã£o de risco. O problema Ã© difÃ­cil por trÃªs razÃµes estruturais: (i) as contagens municipais mensais sÃ£o pequenas e superdispersas; (ii) o alvo Ã© definido por um sistema de detecÃ§Ã£o orbital (INPE), sujeito a ruÃ­do de mediÃ§Ã£o comparÃ¡vel ao prÃ³prio sinal em baixa contagem; (iii) fontes preditoras candidatas (clima, vegetaÃ§Ã£o, pressÃ£o humana) tÃªm resoluÃ§Ã£o temporal ou espacial incompatÃ­vel com o gap que precisariam fechar.

Este trabalho documenta o sistema completo â€” dados, mÃ©todo, protocolo, resultados positivos e negativos, anÃ¡lise de viabilidade e contrato de produÃ§Ã£o â€” sob um princÃ­pio Ãºnico: **nenhuma afirmaÃ§Ã£o de qualidade sem dado real, validaÃ§Ã£o temporal estrita e baseline vÃ¡lido**. Cinco contribuicoes:

1. **Um campeÃ£o simples e auditÃ¡vel** que supera baselines climatolÃ³gicos com significÃ¢ncia em 120 cortes temporais, mantendo interpretabilidade completa (SeÃ§Ã£o 5).
2. **Um registro sistemÃ¡tico de resultados negativos** (SeÃ§Ã£o 9): dez famÃ­lias de features/arquiteturas alternativas avaliadas no mesmo protocolo congelado e rejeitadas â€” evitando o viÃ©s de publicaÃ§Ã£o interna que infla sistemas de ML operacionais.
3. **Uma auditoria de viabilidade estatÃ­stica** (SeÃ§Ã£o 8) que estabelece pisos de erro irredutÃ­vel via orÃ¡culo de mÃ©dia perfeita e desacordo entre sensores independentes, fundamentando a escolha da granularidade do contrato de produÃ§Ã£o â€” em vez de perseguir metas abaixo do ruÃ­do fÃ­sico do alvo.
4. **LLM-XAI verificado**: uma camada de linguagem natural que nunca toca a prediÃ§Ã£o. O sistema primeiro emite um pacote XAI exato da formula do campeao; qualquer narrativa LLM e validada contra esse pacote e falha fechado se introduzir numero nao verificado.

5. **Posicionamento competitivo auditado**: a comparacao com trabalhos recentes separa tarefas incompativeis (perigo diario, deteccao pontual, espalhamento e suscetibilidade) da contribuicao propria do FireCast: previsao prospectiva de contagem municipal-mes, incerteza, piso de ruido, serving fail-closed e XAI verificavel.

### 1.1 Trabalhos relacionados e criterio de comparacao

A literatura recente em ML para fogo cobre tarefas diferentes. Prapas et al. formulam perigo diario como classificacao em grade de 1 km e reportam AUROC 0,926 para ConvLSTM; WISP reformula a previsao diaria como predicao de conjunto de centros de clusters em 375 m, reportando AP 38,2%, cobertura de massa FRP 53,4% e localizacao em 5 km de 54,1%; outros trabalhos recentes focam espalhamento pos-ignicao, modelos de difusao para propagacao, suscetibilidade com RF+SHAP, benchmarks retrospectivos no Cerrado e deteccao Landsat-8.

Esses resultados nao sao diretamente comparaveis ao WAPE municipal-mes do FireCast. O criterio adotado neste artigo e mais conservador: FireCast so reivindica superioridade quando o eixo e compartilhado ou operacionalmente equivalente. Assim, nao afirmamos superar WISP em localizacao de ignicoes nem trabalhos de espalhamento em IoU. A contribuicao competitiva esta em outro eixo: uma previsao de contagem mensal por municipio com semantica prospectiva/as-of, baselines fortes, avaliacao walk-forward, erro de realidade 2025/2026, intervalos conformes, auditoria de piso de ruido, ledger de resultados negativos, API fail-closed e LLM-XAI verificado mecanicamente. A matriz completa esta em `docs/RELATED_WORK_COMPETITIVE_POSITION.md` e o resumo estruturado em `outputs/research_frontier_benchmark.json`.
## 2. Dados

### 2.1 Alvo

- **Fonte:** focos de fogo ativo do Programa Queimadas/INPE (BDQueimadas), snapshot `inpe_local_v2`, imutÃ¡vel e com checksums.
- **Unidade:** contagem de focos por municÃ­pio Ã— mÃªs; 44 municÃ­pios do CearÃ¡ (incluindo os da Chapada do Araripe/Cariri), 2002â€“2026 (8.659 linhas municÃ­pio-mÃªs), chave = geocÃ³digo IBGE.
- **Regra de fusÃ£o:** sÃ©rie de referÃªncia do sensor AQUA (tarde) complementada por histÃ³rico legado validado em janela de sobreposiÃ§Ã£o; meses com suspeita de lacuna de cobertura entram como `NaN` (nunca como zero) e ficam fora de treino e teste.
- **Disponibilidade temporal (`available_at`):** o alvo do mÃªs *t* sÃ³ Ã© usado como feature a partir de *t+1*; toda feature derivada do alvo usa `shift(1)` antes de qualquer agregaÃ§Ã£o.

### 2.2 Fontes auxiliares (features candidatas e auditoria)

| Fonte | Papel | Snapshot |
|---|---|---|
| ERA5 (Open-Meteo, produto fixado) | clima histÃ³rico zonal | `era5_*` |
| ENSO (CPC) | regime interanual | `enso_cpc_v1` |
| NASA FIRMS (MODIS/VIIRS SP) | auditoria independente do alvo; features candidatas | `firms_*_ce_v1` |
| IBGE malha municipal | identidade espacial, grafo de vizinhanÃ§a | `ibge_spatial_graph_v1` |
| IBGE/SIDRA populaÃ§Ã£o e PAM | pressÃ£o humana, Ã¡rea agrÃ­cola | `ibge_population_estimates_v1`, `ibge_pam_crop_area_v1` |
| INMET (zips anuais oficiais) | meteorologia observada de superfÃ­cie | `inmet_automatic_station_observed_v1` |
| INPE eventos pontuais | features de FRP/risco defasadas | `inpe_event_points_v1` |

Toda fonte tem manifesto com URL oficial, licenÃ§a, esquema, checksums e regra as-of. Nenhuma credencial Ã© persistida em cÃ³digo; ingestores falham fechado sem fonte real (proibiÃ§Ã£o de fallback sintÃ©tico).

## 3. FormulaÃ§Ã£o do problema

Seja $y_{i,t}$ a contagem de focos no municÃ­pio $i$ no mÃªs $t$. O sistema prevÃª $\hat{y}_{i,t}$ com horizonte $h=1$, usando exclusivamente informaÃ§Ã£o disponÃ­vel atÃ© $t-1$. Dois escopos de avaliaÃ§Ã£o: **CearÃ¡** (todos os 44 municÃ­pios) e **Chapada do Araripe/Cariri** (subconjunto definido por malha versionada). Meses crÃ­ticos: outubro e novembro (pico da estaÃ§Ã£o seca).

## 4. Baselines

Nove baselines obrigatÃ³rios executam em todo experimento (erro em baseline invalida a execuÃ§Ã£o): lag sazonal de 12 meses; climatologia municipal por mÃªs; climatologia estadual; mÃ©dia histÃ³rica recente; GLM Poisson; binomial negativa; Poisson zero-inflado; Tweedie; e boosting com o conjunto seguro de features. O melhor baseline consistente Ã© a **climatologia municipal por mÃªs**, que serve de referÃªncia principal.

## 5. Modelo campeÃ£o

O campeÃ£o (`climatology_regional_intensity12`, EXP-10) Ã© uma climatologia municipal modulada por intensidade regional:

$$\hat{y}_{i,t} = \underbrace{\bar{y}_{i,m(t)}}_{\text{climatologia municÃ­pio} \times \text{mÃªs}} \cdot \underbrace{\mathrm{clip}\!\left(\frac{O_{12}(t) + 100}{E_{12}(t) + 100},\; 0{,}5,\; 2{,}0\right)}_{\text{fator regional de intensidade}}$$

onde $\bar{y}_{i,m}$ Ã© a mÃ©dia histÃ³rica do municÃ­pio $i$ no mÃªs-calendÃ¡rio $m$ calculada apenas com treino anterior ao corte; $O_{12}(t)$ Ã© o total regional observado nos 12 meses anteriores a $t$; e $E_{12}(t)$ Ã© o total esperado pela climatologia nos mesmos 12 meses. A suavizaÃ§Ã£o (+100) impede que anos de baixa contagem instabilizem o fator; o clip [0,5; 2,0] limita extrapolaÃ§Ã£o. **O mÃªs-alvo nunca entra no fator.**

Mecanismo: a climatologia captura o padrÃ£o sazonal-espacial estÃ¡vel; o fator corrige o nÃ­vel interanual (anos El NiÃ±o/seca vs. anos Ãºmidos) usando apenas memÃ³ria regional observada. A escolha do modelo simples segue o princÃ­pio de parcimÃ´nia do protocolo: candidatos mais complexos sÃ³ substituem o campeÃ£o se o superarem fora da amostra com incerteza favorÃ¡vel â€” nenhum o fez (SeÃ§Ã£o 9).

Incerteza: intervalos IC95 por **prediÃ§Ã£o conforme finita estratificada com guarda** (split-conformal sobre resÃ­duos out-of-sample, Î± selecionado em ano de calibraÃ§Ã£o disjunto do gate; Î±=0,04 â†’ nominal 0,96).

## 6. Protocolo experimental

1. **Walk-forward estendido:** 120 cortes mensais (2015-01 a 2024-12). Em cada corte, treino usa estritamente meses anteriores; municÃ­pio precisa de â‰¥60 meses de histÃ³rico para elegibilidade. Dados de 2025+ permanecem congelados (nÃ£o usados em nenhuma decisÃ£o).
2. **SeparaÃ§Ã£o seleÃ§Ã£o/gate:** hipÃ³teses e hiperparÃ¢metros sÃ£o selecionados em 2015â€“2022; a janela 2023â€“2024 (meses crÃ­ticos) Ã© **gate congelado** â€” nenhuma decisÃ£o de modelagem a consulta. Candidatos que sÃ³ venceriam olhando o gate sÃ£o reportados como *audit-only* e nÃ£o sÃ£o promovÃ­veis.
3. **ValidaÃ§Ã£o espacial (G4):** holdout de municÃ­pios e fatia Chapada/Cariri; regressÃµes materiais por municÃ­pio reprovam.
4. **CalibraÃ§Ã£o (G5):** seleÃ§Ã£o de Î± em 2022, avaliaÃ§Ã£o de cobertura em 2023â€“2024 por regime (seca/chuva).
5. **Auditoria de leakage:** ordenaÃ§Ã£o entidade-tempo antes de lags/rolagens; `shift(1)` obrigatÃ³rio; climatologias e normalizaÃ§Ãµes recalculadas dentro de cada janela de treino; mÃ¡scaras de disponibilidade por fonte.
6. **Ledger imutÃ¡vel:** todo experimento (positivo ou negativo) registra hipÃ³tese falsificÃ¡vel, mudanÃ§a Ãºnica, splits, mÃ©tricas, artefatos e decisÃ£o (`PROMOTE/ITERATE/REJECT/INVALID`) em `outputs/experiment_ledger.jsonl` (32 entradas).
7. **Incerteza da diferenÃ§a:** bootstrap temporal do delta de WAPE contra o campeÃ£o.

### 6.1 MÃ©tricas

- **WAPE** (primÃ¡ria de magnitude): $\sum_i |y_i - \hat{y}_i| / \sum_i y_i$ â€” robusta a zeros, ponderada por volume.
- **MAE** (diagnÃ³stico), em focos/municÃ­pio-mÃªs.
- **Recall@10** (ranking): fraÃ§Ã£o dos 10 municÃ­pios com mais focos observados no mÃªs recuperados entre os 10 primeiros do ranking previsto; mÃ©dia sobre meses do gate.
- **Zero indevido** (seguranÃ§a operacional): fraÃ§Ã£o de previsÃµes nulas para municÃ­pios com histÃ³rico positivo de fogo â€” deve ser 0.
- **Cobertura IC95** (calibraÃ§Ã£o): cobertura empÃ­rica dos intervalos nominais de 95%â€“96% por regime.

## 7. Resultados

### 7.1 CampeÃ£o vs. baseline (walk-forward 2015â€“2024, 120 cortes, n = 3.628 previsÃµes, 8.493 focos)

| MÃ©trica | Climatologia municipal (baseline) | **CampeÃ£o (EXP-10)** | Î” relativo |
|---|---:|---:|---:|
| WAPE geral | 0,7906 | **0,6430** | âˆ’18,7% |
| WAPE outâ€“nov (crÃ­ticos) | 0,6923 | **0,5419** | âˆ’21,7% |
| WAPE estaÃ§Ã£o seca (agoâ€“dez) | 0,7427 | **0,5983** | âˆ’19,4% |
| WAPE alto volume | 0,5301 | **0,4446** | âˆ’16,1% |
| MAE geral (focos) | 1,851 | **1,505** | âˆ’18,7% |
| MAE outâ€“nov (focos) | 5,426 | **4,247** | âˆ’21,7% |

SignificÃ¢ncia: o campeÃ£o vence em 85/120 cortes; IC95 bootstrap do delta de WAPE = **[âˆ’0,2195; âˆ’0,0852]**, inteiramente negativo; P(campeÃ£o melhor) = 1,000.

### 7.2 Contrato de produÃ§Ã£o G3 v2 (gate congelado 2023â€“2024, meses crÃ­ticos)

O contrato v2 (ver SeÃ§Ã£o 8 para a justificativa) avalia magnitude na granularidade agregada e ranking na municipal:

| MÃ©trica | Limite | **Valor** | Resultado |
|---|---:|---:|---|
| WAPE totais mensais â€” CearÃ¡ | â‰¤ 0,25 | **0,2245** | PASS |
| WAPE total sazonal â€” CearÃ¡ | â‰¤ 0,20 | **0,1794** | PASS |
| WAPE total sazonal â€” Chapada | â‰¤ 0,40 | **0,3723** | PASS |
| Recall@10 â€” CearÃ¡ | â‰¥ 0,70 | **0,775** | PASS |
| Recall@10 â€” Chapada | â‰¥ 0,60 | **0,900** | PASS |
| Zero indevido (ambos os escopos) | = 0,0 | **0,0** | PASS |
| WAPE municipal-mÃªs â€” CE / Chapada | *informacional* | 0,4993 / 0,5110 | â€” |

CoerÃªncia com baseline: o campeÃ£o nÃ£o perde para a climatologia municipal em nenhuma mÃ©trica do contrato, em nenhum escopo.

### 7.3 CalibraÃ§Ã£o de intervalos (G5)

Conformal guardado com Î± = 0,04 (nominal 0,96), selecionado em 2022, avaliado em 2023â€“2024: cobertura geral **0,9170**, estaÃ§Ã£o seca **0,9000**, estaÃ§Ã£o chuvosa **0,9274** â€” dentro da faixa aceitÃ¡vel [0,90; 0,98] em todos os regimes.

### 7.4 Robustez espacial (G4)

Na janela de gate 2023â€“2024: zero municÃ­pios com regressÃ£o material; WAPE seco da fatia crÃ­tica 0,5078; fatia Chapada/Cariri aprovada. Fora da janela de gate (avaliaÃ§Ã£o estendida 2015â€“2024), dois municÃ­pios de baixo volume (Jaguaruana, Porteiras) aparecem como alertas e sÃ£o monitorados em produÃ§Ã£o.

## 8. AnÃ¡lise de viabilidade estatÃ­stica: quanto erro Ã© irredutÃ­vel?

Pergunta: *que WAPE municipal-mÃªs qualquer modelo pontual poderia atingir?* MÃ©todo (EXP-25): **orÃ¡culo de mÃ©dia perfeita** â€” assume-se um modelo que conhece exatamente a mÃ©dia condicional de cada cÃ©lula municÃ­pio-mÃªs (aproximada pelo valor realizado, a suposiÃ§Ã£o mais favorÃ¡vel possÃ­vel ao previsor); o erro restante Ã© apenas ruÃ­do de contagem, simulado por Monte Carlo (4.000 rÃ©plicas, semente fixa) sob duas distribuiÃ§Ãµes:

- **Poisson** (dispersÃ£o mÃ­nima â†’ limite inferior duro);
- **Binomial negativa** com dispersÃ£o agrupada estimada dos resÃ­duos histÃ³ricos 2015â€“2022 (referÃªncia realista; enviesada para cima por conter sinal previsÃ­vel â€” caveat documentado).

Complementarmente, mede-se o **desacordo de mediÃ§Ã£o** entre dois sistemas independentes de observaÃ§Ã£o dos mesmos fogos (INPE vs. FIRMS multi-sensor reescalado pelo total) nas mesmas cÃ©lulas do gate.

| Piso (gate 2023â€“2024, meses crÃ­ticos) | CearÃ¡ | Chapada |
|---|---:|---:|
| Poisson, mÃ©dia perfeita (IC 2,5â€“97,5%) | 0,169 [0,138; 0,201] | 0,226 [0,171; 0,286] |
| Binomial negativa, dispersÃ£o histÃ³rica | 0,384 | 0,534 |
| Desacordo INPE vs. FIRMS (reescalado) | 0,412 | 0,427 |
| **CampeÃ£o (municipal-mÃªs)** | **0,499** | **0,511** |

Leitura: (i) o campeÃ£o estÃ¡ a ~0,1 do piso NB realista â€” a maior parte do erro municipal-mÃªs Ã© ruÃ­do, nÃ£o deficiÃªncia de modelo; (ii) o contrato original v1 (WAPE municipal-mÃªs â‰¤ 0,20/0,25) exigiria prever o INPE melhor do que um satÃ©lite independente consegue *medi-lo*, com margem quase nula atÃ© sob Poisson puro; (iii) em agregaÃ§Ãµes compatÃ­veis com o ruÃ­do (totais mensais/sazonais por escopo), os pisos caem para 0,03â€“0,07 e o campeÃ£o entrega 0,18â€“0,37.

Com essa evidÃªncia, o owner do produto aprovou formalmente (2026-07-11, registrado com autoria no ledger: `DECISION-G3-CONTRACT-V2`) a migraÃ§Ã£o do gate de magnitude para a granularidade agregada, mantendo ranking e zero indevido na granularidade municipal. **TransparÃªncia metodolÃ³gica:** os limites v2 foram definidos com conhecimento do desempenho do campeÃ£o; a alegaÃ§Ã£o estatÃ­stica de qualidade deriva dos pisos acima e da superioridade sobre baselines â€” nÃ£o da posiÃ§Ã£o dos limites. Nenhum dado, split ou prediÃ§Ã£o foi re-ajustado: a avaliaÃ§Ã£o v2 (EXP-26) reutiliza as prediÃ§Ãµes congeladas de todos os experimentos anteriores.

## 9. Resultados negativos (registrados no mesmo protocolo)

Dez famÃ­lias de hipÃ³teses foram avaliadas contra o campeÃ£o com seleÃ§Ã£o em 2015â€“2022 e gate congelado 2023â€“2024. Nenhuma melhorou o WAPE crÃ­tico selecionÃ¡vel; vÃ¡rias degradaram o gate:

| EXP | FamÃ­lia | Resultado no gate (CE, selecionÃ¡vel) |
|---|---|---|
| 12 | RegressÃ£o/hurdle/clusterizaÃ§Ã£o/memÃ³ria/lag-blends | melhor vÃ¡lido 0,4660; nada â‰¤ 0,20 |
| 13 | Eventos pontuais INPE defasados (FRP, risco) | REJECT |
| 14 | Kernel espacial de eventos | 0,5028 (pior que campeÃ£o) |
| 15â€“19 | FIRMS MODIS/VIIRS/multi-sensor | seletor manteve campeÃ£o |
| 20 | Grafo espacial IBGE (pressÃ£o de vizinhos) | 0,5043 (pior) |
| 21 | PopulaÃ§Ã£o/densidade/Ã¡rea IBGE | seletor manteve campeÃ£o |
| 22 | NDVI local (sem QA â€” invÃ¡lido para promoÃ§Ã£o) | exploratÃ³rio, manteve campeÃ£o |
| 23 | Ãrea agrÃ­cola PAM/IBGE por cultura | seletor manteve campeÃ£o |
| 24 | Seca observada INMET (dÃ©ficit de chuva, VPD, IDW de 35 estaÃ§Ãµes) | seleÃ§Ã£o Chapada degradou o gate (0,6247 vs. 0,5110) |

ObservaÃ§Ã£o instrutiva do EXP-24: a variante `inmet_tilt_vpd3` obteve o melhor WAPE de gate CE jÃ¡ visto (0,4639 *audit-only*), mas sÃ³ seria escolhida consultando o gate â€” ilustrando por que a separaÃ§Ã£o seleÃ§Ã£o/gate Ã© indispensÃ¡vel: sem ela, o "melhor" resultado publicado seria um artefato de seleÃ§Ã£o a posteriori.

## 10. LLM-XAI verificado e producao

O ganho de XAI via LLM e deliberadamente restrito e verificavel. Como o campeao e uma formula glass-box, o sistema constroi para cada previsao um pacote com: climatologia municipal-mes, fator regional, produto exato, intervalo p90, janela de evidencia e hash do artefato. O LLM recebe apenas esse JSON como fatos aterrados; nao recebe permissao para prever, ranquear ou ajustar qualquer numero. Um verificador (`numeric_fact_guard_v1`) rejeita a narrativa se qualquer token numerico nao estiver no pacote.

Essa arquitetura transforma o LLM em interface de comunicacao auditavel, nao em fonte de verdade. Portanto, a explicacao em linguagem natural e util para operadores e para artigo, mas a garantia vem do pacote deterministico e dos testes: a decomposicao deve bater com `predict_one`, e uma frase com numero alucinado e reprovada.

## 11. ProduÃ§Ã£o e monitoramento

- **Serving fail-closed (G6):** API FastAPI serve exclusivamente o artefato serializado com hash verificado (`model.json`, sha256 verificado no load); modelo ausente ou entrada invÃ¡lida retorna erro explÃ­cito â€” nunca um nÃºmero fabricado. Identidade treino/serving coberta pela suite atual (55 testes, incluindo carga concorrente, determinismo e LLM-XAI verificado).
- **GovernanÃ§a (G7):** model card com limitaÃ§Ãµes explÃ­citas; aprovaÃ§Ã£o humana registrada para operaÃ§Ã£o **interna** (`OPS-G7-APPROVAL-2026-07-11`); release **externo** condicionado a janela de shadow pontuada.
- **Shadow prospectivo:** previsÃµes para 2026-05..08 foram registradas em log append-only **antes** de os desfechos serem conhecidos, com sha256 do artefato e do relatÃ³rio de calibraÃ§Ã£o; quando as observaÃ§Ãµes chegarem, o desempenho atrasado Ã© pontuado com alertas automÃ¡ticos de degradaÃ§Ã£o (WAPE > referÃªncia + 0,05), faltantes e frescor de dados.
- **Rollback:** artefatos versionados por hash; troca de modelo documentada em ledger.

## 12. LimitaÃ§Ãµes e ameaÃ§as Ã  validade

1. **PrecisÃ£o municipal de magnitude:** WAPE municipal-mÃªs â‰ˆ 0,50 estÃ¡ na zona de ruÃ­do irredutÃ­vel; o sistema **nÃ£o deve** ser usado para prometer contagens exatas por municÃ­pio â€” o contrato explicita ranking e agregados.
2. **Limites v2 definidos post-hoc:** mitigado por (i) autoria humana registrada, (ii) ancoragem nos pisos estatÃ­sticos, (iii) reavaliaÃ§Ã£o sem re-ajuste; ainda assim, a validaÃ§Ã£o prospectiva definitiva Ã© a janela de shadow em curso.
3. **DependÃªncia do sensor:** o alvo Ã© uma mediÃ§Ã£o orbital; mudanÃ§as de satÃ©lite/algoritmo do INPE podem deslocar a sÃ©rie (mitigaÃ§Ã£o: versÃ£o de sensor registrada, FIRMS como auditoria independente).
4. **MunicÃ­pios de baixo volume:** dois alertas na avaliaÃ§Ã£o estendida; monitorados em shadow.
5. **Cobertura do artefato:** 31/44 municÃ­pios tÃªm climatologia servÃ­vel (piso de histÃ³rico); os demais falham fechado.
6. **Escopo geogrÃ¡fico:** resultados restritos ao CearÃ¡/Chapada; extrapolaÃ§Ã£o para outros biomas exige novo ciclo completo de validaÃ§Ã£o.

## 13. Reprodutibilidade

Todos os experimentos usam sementes fixas, snapshots imutÃ¡veis com sha256 e protocolo congelado. Artefatos principais:

| Artefato | Caminho |
|---|---|
| Ledger de experimentos (32 entradas) | `outputs/experiment_ledger.jsonl` |
| CampeÃ£o serializado + model card | `outputs/champion_climatology_regional_intensity12/` |
| Backtest estendido (mÃ©tricas/prediÃ§Ãµes) | `outputs/exp10_dynamic_regional_intensity/` |
| AvaliaÃ§Ã£o do contrato v2 | `outputs/exp26_g3_contract_v2_evaluation/` |
| Auditoria de viabilidade (pisos) | `outputs/exp25_g3_feasibility_audit/` |
| CalibraÃ§Ã£o conforme guardada | `outputs/g5_conformal_ic95_guarded_exp10/` |
| Robustez espacial | `outputs/g4_spatial_robustness_exp10_2023_2024/` |
| Shadow log prospectivo | `outputs/shadow_monitor/` |
| LLM-XAI verificado | `src/production/llm_xai.py`, `tests/test_llm_xai.py`, `docs/LLM_XAI_CONTRACT.md` |
| Contrato de gates | `configs/config.yaml` (seÃ§Ã£o `g3_contract`) |
| Alvo e fontes com manifestos | `data/snapshots/*/manifest.json` |

SuÃ­te de verificaÃ§Ã£o: `pytest tests -q` (56 testes), `scripts/check_data_ingestors.py` (20 snapshots, 26 ingestores), `python src/mlops/contracts.py --out outputs/production_ml_plan.json`, `tests/test_llm_xai.py`.

## ReferÃªncias

1. INPE â€” Programa Queimadas, Dados Abertos. https://data.inpe.br/queimadas/portal/dados-abertos/
2. NASA FIRMS â€” Fire Information for Resource Management System. https://firms.modaps.eosdis.nasa.gov/
3. Hersbach, H. et al. (2020). The ERA5 global reanalysis. *QJRMS*, 146(730). (Acesso via Open-Meteo Historical API, produto fixado.)
4. INMET â€” Dados HistÃ³ricos de EstaÃ§Ãµes AutomÃ¡ticas. https://portal.inmet.gov.br/dadoshistoricos
5. IBGE â€” Malhas Territoriais e SIDRA (tabelas 6579, 1612). https://www.ibge.gov.br/
6. Pereira, J. et al. (2020). Desenvolvimento do Ãndice de Perigo de IncÃªndio (IPI). *CiÃªncia e Natura*. (Base conceitual dos blocos combustÃ­vel/fÃ­sico/igniÃ§Ã£o avaliados como features candidatas.)
7. Vovk, V., Gammerman, A., Shafer, G. (2005). *Algorithmic Learning in a Random World*. Springer. (PrediÃ§Ã£o conforme.)
8. Hyndman, R.J., Athanasopoulos, G. (2021). *Forecasting: Principles and Practice*, 3Âª ed. (Protocolo walk-forward e baselines.)
