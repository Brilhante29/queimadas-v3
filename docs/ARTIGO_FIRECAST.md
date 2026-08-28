# FireCast: previsão mensal de focos de queimadas por município com validação temporal estrita, análise de viabilidade estatística e contrato de produção auditável

> ## Aviso de escopo -- leia antes de citar qualquer numero
>
> **Este artigo descreve o escopo LEGADO do FireCast: municipios do Ceara,
> com um subconjunto interno chamado "Chapada do Araripe/Cariri" definido por
> malha versionada de nomes de municipio.**
>
> Ele **nao** descreve a APA Chapada do Araripe -- a unidade de conservacao
> federal de 36 municipios em CE, PE e PI, derivada por intersecao espacial
> com o poligono do ICMBio. Os dois escopos compartilham o nome "Chapada do
> Araripe" e nada mais: alvo diferente, snapshot diferente, recorte de
> avaliacao diferente.
>
> Nenhuma metrica deste artigo sustenta afirmacao sobre a APA. No escopo APA o
> WAPE e mais alto e o gate de incerteza G5 **reprovou** -- inclusive em teste
> selado de 2025. Os resultados da APA estao em `outputs/public_results_summary.json`
> (bloco `current_scope`) e no bloco gerado do `README.md`.
>
> Este aviso existe porque a versao anterior deste documento permitia ler
> numeros do Ceara como se fossem da APA.

Rascunho de artigo - versao 1.1, 2026-07-13.
Todos os números citados são reproduzíveis a partir dos artefatos versionados listados na Seção 12.

---

## Resumo

Apresentamos o FireCast, um sistema de previsão mensal de focos de fogo ativo por município para o Ceará e a Chapada do Araripe (Brasil), com horizonte de 1 mês. O modelo campeão é deliberadamente simples — uma climatologia municipal por mês modulada por um fator regional de intensidade dos últimos 12 meses observados — e foi selecionado após 26 experimentos registrados em ledger imutável, dos quais 10 famílias de hipóteses mais complexas (memória municipal, eventos pontuais, kernels espaciais, dados FIRMS multi-sensor, grafo espacial IBGE, pressão populacional, NDVI, área agrícola PAM e meteorologia observada INMET) foram rejeitadas por não superarem o campeão sob protocolo congelado. Em backtest walk-forward com 120 cortes mensais (2015–2024), o campeão reduz o WAPE de 0,7906 (climatologia municipal) para 0,6430 (−18,7%), com IC95 bootstrap do delta inteiramente negativo [−0,2195; −0,0852]. Contribuição metodológica central: uma auditoria de viabilidade estatística com oráculo de média perfeita demonstra que o erro municipal-mês do campeão (WAPE ≈ 0,50 nos meses críticos) está próximo do piso irredutível do alvo — a dispersão histórica implica piso ≈ 0,38–0,53 e dois sistemas satelitais independentes (INPE vs. FIRMS) discordam em WAPE 0,41–0,43 ao medir os mesmos fogos. Isso motivou um contrato de produção em granularidade compatível com o ruído: totais mensais por escopo (WAPE 0,2245), total sazonal (0,1794), ranking municipal (Recall@10 0,775–0,90), zero indevido nulo e intervalos conformes com cobertura empírica 0,917 para 95% nominal.

**Palavras-chave:** previsão de queimadas, séries temporais de contagem, walk-forward, predição conforme, piso de ruído aleatório, WAPE.

---

## 1. Introdução

A previsão mensal de focos de queimadas por município apoia alocação preventiva de brigadas, fiscalização e comunicação de risco. O problema é difícil por três razões estruturais: (i) as contagens municipais mensais são pequenas e superdispersas; (ii) o alvo é definido por um sistema de detecção orbital (INPE), sujeito a ruído de medição comparável ao próprio sinal em baixa contagem; (iii) fontes preditoras candidatas (clima, vegetação, pressão humana) têm resolução temporal ou espacial incompatível com o gap que precisariam fechar.

Este trabalho documenta o sistema completo — dados, método, protocolo, resultados positivos e negativos, análise de viabilidade e contrato de produção — sob um princípio único: **nenhuma afirmação de qualidade sem dado real, validação temporal estrita e baseline válido**. Cinco contribuicoes:

1. **Um campeão simples e auditável** que supera baselines climatológicos com significância em 120 cortes temporais, mantendo interpretabilidade completa (Seção 5).
2. **Um registro sistemático de resultados negativos** (Seção 9): dez famílias de features/arquiteturas alternativas avaliadas no mesmo protocolo congelado e rejeitadas — evitando o viés de publicação interna que infla sistemas de ML operacionais.
3. **Uma auditoria de viabilidade estatística** (Seção 8) que estabelece pisos de erro irredutível via oráculo de média perfeita e desacordo entre sensores independentes, fundamentando a escolha da granularidade do contrato de produção — em vez de perseguir metas abaixo do ruído físico do alvo.
4. **LLM-XAI verificado**: uma camada de linguagem natural que nunca toca a predição. O sistema primeiro emite um pacote XAI exato da formula do campeao; qualquer narrativa LLM e validada contra esse pacote e falha fechado se introduzir numero nao verificado.

5. **Posicionamento competitivo auditado**: a comparacao com trabalhos recentes separa tarefas incompativeis (perigo diario, deteccao pontual, espalhamento e suscetibilidade) da contribuicao propria do FireCast: previsao prospectiva de contagem municipal-mes, incerteza, piso de ruido, serving fail-closed e XAI verificavel.

### 1.1 Trabalhos relacionados e criterio de comparacao

A literatura recente em ML para fogo cobre tarefas diferentes. Prapas et al. formulam perigo diario como classificacao em grade de 1 km e reportam AUROC 0,926 para ConvLSTM; WISP reformula a previsao diaria como predicao de conjunto de centros de clusters em 375 m, reportando AP 38,2%, cobertura de massa FRP 53,4% e localizacao em 5 km de 54,1%; outros trabalhos recentes focam espalhamento pos-ignicao, modelos de difusao para propagacao, suscetibilidade com RF+SHAP, benchmarks retrospectivos no Cerrado e deteccao Landsat-8.

Esses resultados nao sao diretamente comparaveis ao WAPE municipal-mes do FireCast. O criterio adotado neste artigo e mais conservador: FireCast so reivindica superioridade quando o eixo e compartilhado ou operacionalmente equivalente. Assim, nao afirmamos superar WISP em localizacao de ignicoes nem trabalhos de espalhamento em IoU. A contribuicao competitiva esta em outro eixo: uma previsao de contagem mensal por municipio com semantica prospectiva/as-of, baselines fortes, avaliacao walk-forward, erro de realidade 2025/2026, intervalos conformes, auditoria de piso de ruido, ledger de resultados negativos, API fail-closed e LLM-XAI verificado mecanicamente. A matriz completa esta em `docs/RELATED_WORK_COMPETITIVE_POSITION.md` e o resumo estruturado em `outputs/research_frontier_benchmark.json`.
## 2. Dados

### 2.1 Alvo

- **Fonte:** focos de fogo ativo do Programa Queimadas/INPE (BDQueimadas), snapshot `inpe_local_v2`, imutável e com checksums.
- **Unidade:** contagem de focos por município × mês; 44 municípios do Ceará (incluindo os da Chapada do Araripe/Cariri), 2002–2026 (8.659 linhas município-mês), chave = geocódigo IBGE.
- **Regra de fusão:** série de referência do sensor AQUA (tarde) complementada por histórico legado validado em janela de sobreposição; meses com suspeita de lacuna de cobertura entram como `NaN` (nunca como zero) e ficam fora de treino e teste.
- **Disponibilidade temporal (`available_at`):** o alvo do mês *t* só é usado como feature a partir de *t+1*; toda feature derivada do alvo usa `shift(1)` antes de qualquer agregação.

### 2.2 Fontes auxiliares (features candidatas e auditoria)

| Fonte | Papel | Snapshot |
|---|---|---|
| ERA5 (Open-Meteo, produto fixado) | clima histórico zonal | `era5_*` |
| ENSO (CPC) | regime interanual | `enso_cpc_v1` |
| NASA FIRMS (MODIS/VIIRS SP) | auditoria independente do alvo; features candidatas | `firms_*_ce_v1` |
| IBGE malha municipal | identidade espacial, grafo de vizinhança | `ibge_spatial_graph_v1` |
| IBGE/SIDRA população e PAM | pressão humana, área agrícola | `ibge_population_estimates_v1`, `ibge_pam_crop_area_v1` |
| INMET (zips anuais oficiais) | meteorologia observada de superfície | `inmet_automatic_station_observed_v1` |
| INPE eventos pontuais | features de FRP/risco defasadas | `inpe_event_points_v1` |

Toda fonte tem manifesto com URL oficial, licença, esquema, checksums e regra as-of. Nenhuma credencial é persistida em código; ingestores falham fechado sem fonte real (proibição de fallback sintético).

## 3. Formulação do problema

Seja $y_{i,t}$ a contagem de focos no município $i$ no mês $t$. O sistema prevê $\hat{y}_{i,t}$ com horizonte $h=1$, usando exclusivamente informação disponível até $t-1$. Dois escopos de avaliação: **Ceará** (todos os 44 municípios) e **Chapada do Araripe/Cariri** (subconjunto definido por malha versionada). Meses críticos: outubro e novembro (pico da estação seca).

## 4. Baselines

Nove baselines obrigatórios executam em todo experimento (erro em baseline invalida a execução): lag sazonal de 12 meses; climatologia municipal por mês; climatologia estadual; média histórica recente; GLM Poisson; binomial negativa; Poisson zero-inflado; Tweedie; e boosting com o conjunto seguro de features. O melhor baseline consistente é a **climatologia municipal por mês**, que serve de referência principal.

## 5. Modelo campeão

O campeão (`climatology_regional_intensity12`, EXP-10) é uma climatologia municipal modulada por intensidade regional:

$$\hat{y}_{i,t} = \underbrace{\bar{y}_{i,m(t)}}_{\text{climatologia município} \times \text{mês}} \cdot \underbrace{\mathrm{clip}\!\left(\frac{O_{12}(t) + 100}{E_{12}(t) + 100},\; 0{,}5,\; 2{,}0\right)}_{\text{fator regional de intensidade}}$$

onde $\bar{y}_{i,m}$ é a média histórica do município $i$ no mês-calendário $m$ calculada apenas com treino anterior ao corte; $O_{12}(t)$ é o total regional observado nos 12 meses anteriores a $t$; e $E_{12}(t)$ é o total esperado pela climatologia nos mesmos 12 meses. A suavização (+100) impede que anos de baixa contagem instabilizem o fator; o clip [0,5; 2,0] limita extrapolação. **O mês-alvo nunca entra no fator.**

Mecanismo: a climatologia captura o padrão sazonal-espacial estável; o fator corrige o nível interanual (anos El Niño/seca vs. anos úmidos) usando apenas memória regional observada. A escolha do modelo simples segue o princípio de parcimônia do protocolo: candidatos mais complexos só substituem o campeão se o superarem fora da amostra com incerteza favorável — nenhum o fez (Seção 9).

Incerteza: intervalos IC95 por **predição conforme finita estratificada com guarda** (split-conformal sobre resíduos out-of-sample, α selecionado em ano de calibração disjunto do gate; α=0,04 → nominal 0,96).

## 6. Protocolo experimental

1. **Walk-forward estendido:** 120 cortes mensais (2015-01 a 2024-12). Em cada corte, treino usa estritamente meses anteriores; município precisa de ≥60 meses de histórico para elegibilidade. Dados de 2025+ permanecem congelados (não usados em nenhuma decisão).
2. **Separação seleção/gate:** hipóteses e hiperparâmetros são selecionados em 2015–2022; a janela 2023–2024 (meses críticos) é **gate congelado** — nenhuma decisão de modelagem a consulta. Candidatos que só venceriam olhando o gate são reportados como *audit-only* e não são promovíveis.
3. **Validação espacial (G4):** holdout de municípios e fatia Chapada/Cariri; regressões materiais por município reprovam.
4. **Calibração (G5):** seleção de α em 2022, avaliação de cobertura em 2023–2024 por regime (seca/chuva).
5. **Auditoria de leakage:** ordenação entidade-tempo antes de lags/rolagens; `shift(1)` obrigatório; climatologias e normalizações recalculadas dentro de cada janela de treino; máscaras de disponibilidade por fonte.
6. **Ledger imutável:** todo experimento (positivo ou negativo) registra hipótese falsificável, mudança única, splits, métricas, artefatos e decisão (`PROMOTE/ITERATE/REJECT/INVALID`) em `outputs/experiment_ledger.jsonl` (32 entradas).
7. **Incerteza da diferença:** bootstrap temporal do delta de WAPE contra o campeão.

### 6.1 Métricas

- **WAPE** (primária de magnitude): $\sum_i |y_i - \hat{y}_i| / \sum_i y_i$ — robusta a zeros, ponderada por volume.
- **MAE** (diagnóstico), em focos/município-mês.
- **Recall@10** (ranking): fração dos 10 municípios com mais focos observados no mês recuperados entre os 10 primeiros do ranking previsto; média sobre meses do gate.
- **Zero indevido** (segurança operacional): fração de previsões nulas para municípios com histórico positivo de fogo — deve ser 0.
- **Cobertura IC95** (calibração): cobertura empírica dos intervalos nominais de 95%–96% por regime.

## 7. Resultados

### 7.1 Campeão vs. baseline (walk-forward 2015–2024, 120 cortes, n = 3.628 previsões, 8.493 focos)

| Métrica | Climatologia municipal (baseline) | **Campeão (EXP-10)** | Δ relativo |
|---|---:|---:|---:|
| WAPE geral | 0,7906 | **0,6430** | −18,7% |
| WAPE out–nov (críticos) | 0,6923 | **0,5419** | −21,7% |
| WAPE estação seca (ago–dez) | 0,7427 | **0,5983** | −19,4% |
| WAPE alto volume | 0,5301 | **0,4446** | −16,1% |
| MAE geral (focos) | 1,851 | **1,505** | −18,7% |
| MAE out–nov (focos) | 5,426 | **4,247** | −21,7% |

Significância: o campeão vence em 85/120 cortes; IC95 bootstrap do delta de WAPE = **[−0,2195; −0,0852]**, inteiramente negativo; P(campeão melhor) = 1,000.

### 7.2 Contrato de produção G3 v2 (gate congelado 2023–2024, meses críticos)

O contrato v2 (ver Seção 8 para a justificativa) avalia magnitude na granularidade agregada e ranking na municipal:

| Métrica | Limite | **Valor** | Resultado |
|---|---:|---:|---|
| WAPE totais mensais — Ceará | ≤ 0,25 | **0,2245** | PASS |
| WAPE total sazonal — Ceará | ≤ 0,20 | **0,1794** | PASS |
| WAPE total sazonal — Chapada | ≤ 0,40 | **0,3723** | PASS |
| Recall@10 — Ceará | ≥ 0,70 | **0,775** | PASS |
| Recall@10 — Chapada | ≥ 0,60 | **0,900** | PASS |
| Zero indevido (ambos os escopos) | = 0,0 | **0,0** | PASS |
| WAPE municipal-mês — CE / Chapada | *informacional* | 0,4993 / 0,5110 | — |

Coerência com baseline: o campeão não perde para a climatologia municipal em nenhuma métrica do contrato, em nenhum escopo.

### 7.3 Calibração de intervalos (G5)

Conformal guardado com α = 0,04 (nominal 0,96), selecionado em 2022, avaliado em 2023–2024: cobertura geral **0,9170**, estação seca **0,9000**, estação chuvosa **0,9274** — dentro da faixa aceitável [0,90; 0,98] em todos os regimes.

### 7.4 Robustez espacial (G4)

Na janela de gate 2023–2024: zero municípios com regressão material; WAPE seco da fatia crítica 0,5078; fatia Chapada/Cariri aprovada. Fora da janela de gate (avaliação estendida 2015–2024), dois municípios de baixo volume (Jaguaruana, Porteiras) aparecem como alertas e são monitorados em produção.

## 8. Análise de viabilidade estatística: quanto erro é irredutível?

Pergunta: *que WAPE municipal-mês qualquer modelo pontual poderia atingir?* Método (EXP-25): **oráculo de média perfeita** — assume-se um modelo que conhece exatamente a média condicional de cada célula município-mês (aproximada pelo valor realizado, a suposição mais favorável possível ao previsor); o erro restante é apenas ruído de contagem, simulado por Monte Carlo (4.000 réplicas, semente fixa) sob duas distribuições:

- **Poisson** (dispersão mínima → limite inferior duro);
- **Binomial negativa** com dispersão agrupada estimada dos resíduos históricos 2015–2022 (referência realista; enviesada para cima por conter sinal previsível — caveat documentado).

Complementarmente, mede-se o **desacordo de medição** entre dois sistemas independentes de observação dos mesmos fogos (INPE vs. FIRMS multi-sensor reescalado pelo total) nas mesmas células do gate.

| Piso (gate 2023–2024, meses críticos) | Ceará | Chapada |
|---|---:|---:|
| Poisson, média perfeita (IC 2,5–97,5%) | 0,169 [0,138; 0,201] | 0,226 [0,171; 0,286] |
| Binomial negativa, dispersão histórica | 0,384 | 0,534 |
| Desacordo INPE vs. FIRMS (reescalado) | 0,412 | 0,427 |
| **Campeão (municipal-mês)** | **0,499** | **0,511** |

Leitura: (i) o campeão está a ~0,1 do piso NB realista — a maior parte do erro municipal-mês é ruído, não deficiência de modelo; (ii) o contrato original v1 (WAPE municipal-mês ≤ 0,20/0,25) exigiria prever o INPE melhor do que um satélite independente consegue *medi-lo*, com margem quase nula até sob Poisson puro; (iii) em agregações compatíveis com o ruído (totais mensais/sazonais por escopo), os pisos caem para 0,03–0,07 e o campeão entrega 0,18–0,37.

Com essa evidência, o owner do produto aprovou formalmente (2026-07-11, registrado com autoria no ledger: `DECISION-G3-CONTRACT-V2`) a migração do gate de magnitude para a granularidade agregada, mantendo ranking e zero indevido na granularidade municipal. **Transparência metodológica:** os limites v2 foram definidos com conhecimento do desempenho do campeão; a alegação estatística de qualidade deriva dos pisos acima e da superioridade sobre baselines — não da posição dos limites. Nenhum dado, split ou predição foi re-ajustado: a avaliação v2 (EXP-26) reutiliza as predições congeladas de todos os experimentos anteriores.

## 9. Resultados negativos (registrados no mesmo protocolo)

Dez famílias de hipóteses foram avaliadas contra o campeão com seleção em 2015–2022 e gate congelado 2023–2024. Nenhuma melhorou o WAPE crítico selecionável; várias degradaram o gate:

| EXP | Família | Resultado no gate (CE, selecionável) |
|---|---|---|
| 12 | Regressão/hurdle/clusterização/memória/lag-blends | melhor válido 0,4660; nada ≤ 0,20 |
| 13 | Eventos pontuais INPE defasados (FRP, risco) | REJECT |
| 14 | Kernel espacial de eventos | 0,5028 (pior que campeão) |
| 15–19 | FIRMS MODIS/VIIRS/multi-sensor | seletor manteve campeão |
| 20 | Grafo espacial IBGE (pressão de vizinhos) | 0,5043 (pior) |
| 21 | População/densidade/área IBGE | seletor manteve campeão |
| 22 | NDVI local (sem QA — inválido para promoção) | exploratório, manteve campeão |
| 23 | Ãrea agrícola PAM/IBGE por cultura | seletor manteve campeão |
| 24 | Seca observada INMET (déficit de chuva, VPD, IDW de 35 estações) | seleção Chapada degradou o gate (0,6247 vs. 0,5110) |

Observação instrutiva do EXP-24: a variante `inmet_tilt_vpd3` obteve o melhor WAPE de gate CE já visto (0,4639 *audit-only*), mas só seria escolhida consultando o gate — ilustrando por que a separação seleção/gate é indispensável: sem ela, o "melhor" resultado publicado seria um artefato de seleção a posteriori.

## 10. LLM-XAI verificado e producao

O ganho de XAI via LLM e deliberadamente restrito e verificavel. Como o campeao e uma formula glass-box, o sistema constroi para cada previsao um pacote com: climatologia municipal-mes, fator regional, produto exato, intervalo p90, janela de evidencia e hash do artefato. O LLM recebe apenas esse JSON como fatos aterrados; nao recebe permissao para prever, ranquear ou ajustar qualquer numero. Um verificador (`numeric_fact_guard_v1`) rejeita a narrativa se qualquer token numerico nao estiver no pacote.

Essa arquitetura transforma o LLM em interface de comunicacao auditavel, nao em fonte de verdade. Portanto, a explicacao em linguagem natural e util para operadores e para artigo, mas a garantia vem do pacote deterministico e dos testes: a decomposicao deve bater com `predict_one`, e uma frase com numero alucinado e reprovada.

## 11. Produção e monitoramento

- **Serving fail-closed (G6):** API FastAPI serve exclusivamente o artefato serializado com hash verificado (`model.json`, sha256 verificado no load); modelo ausente ou entrada inválida retorna erro explícito — nunca um número fabricado. Identidade treino/serving coberta pela suite atual (55 testes, incluindo carga concorrente, determinismo e LLM-XAI verificado).
- **Governança (G7):** model card com limitações explícitas; aprovação humana registrada para operação **interna** (`OPS-G7-APPROVAL-2026-07-11`); release **externo** condicionado a janela de shadow pontuada.
- **Shadow prospectivo:** previsões para 2026-05..08 foram registradas em log append-only **antes** de os desfechos serem conhecidos, com sha256 do artefato e do relatório de calibração; quando as observações chegarem, o desempenho atrasado é pontuado com alertas automáticos de degradação (WAPE > referência + 0,05), faltantes e frescor de dados.
- **Rollback:** artefatos versionados por hash; troca de modelo documentada em ledger.

## 12. Limitações e ameaças à validade

1. **Precisão municipal de magnitude:** WAPE municipal-mês ≈ 0,50 está na zona de ruído irredutível; o sistema **não deve** ser usado para prometer contagens exatas por município — o contrato explicita ranking e agregados.
2. **Limites v2 definidos post-hoc:** mitigado por (i) autoria humana registrada, (ii) ancoragem nos pisos estatísticos, (iii) reavaliação sem re-ajuste; ainda assim, a validação prospectiva definitiva é a janela de shadow em curso.
3. **Dependência do sensor:** o alvo é uma medição orbital; mudanças de satélite/algoritmo do INPE podem deslocar a série (mitigação: versão de sensor registrada, FIRMS como auditoria independente).
4. **Municípios de baixo volume:** dois alertas na avaliação estendida; monitorados em shadow.
5. **Cobertura do artefato:** 31/44 municípios têm climatologia servível (piso de histórico); os demais falham fechado.
6. **Escopo geográfico:** resultados restritos ao Ceará/Chapada; extrapolação para outros biomas exige novo ciclo completo de validação.

## 13. Reprodutibilidade

Todos os experimentos usam sementes fixas, snapshots imutáveis com sha256 e protocolo congelado. Artefatos principais:

| Artefato | Caminho |
|---|---|
| Ledger de experimentos (32 entradas) | `outputs/experiment_ledger.jsonl` |
| Campeão serializado + model card | `outputs/champion_climatology_regional_intensity12/` |
| Backtest estendido (métricas/predições) | `outputs/exp10_dynamic_regional_intensity/` |
| Avaliação do contrato v2 | `outputs/exp26_g3_contract_v2_evaluation/` |
| Auditoria de viabilidade (pisos) | `outputs/exp25_g3_feasibility_audit/` |
| Calibração conforme guardada | `outputs/g5_conformal_ic95_guarded_exp10/` |
| Robustez espacial | `outputs/g4_spatial_robustness_exp10_2023_2024/` |
| Shadow log prospectivo | `outputs/shadow_monitor/` |
| LLM-XAI verificado | `src/production/llm_xai.py`, `tests/test_llm_xai.py`, `docs/LLM_XAI_CONTRACT.md` |
| Contrato de gates | `configs/config.yaml` (seção `g3_contract`) |
| Alvo e fontes com manifestos | `data/snapshots/*/manifest.json` |

Suíte de verificação: `pytest tests -q` (56 testes), `scripts/check_data_ingestors.py` (20 snapshots, 26 ingestores), `python src/mlops/contracts.py --out outputs/production_ml_plan.json`, `tests/test_llm_xai.py`.

## Referências

1. INPE — Programa Queimadas, Dados Abertos. https://data.inpe.br/queimadas/portal/dados-abertos/
2. NASA FIRMS — Fire Information for Resource Management System. https://firms.modaps.eosdis.nasa.gov/
3. Hersbach, H. et al. (2020). The ERA5 global reanalysis. *QJRMS*, 146(730). (Acesso via Open-Meteo Historical API, produto fixado.)
4. INMET — Dados Históricos de Estações Automáticas. https://portal.inmet.gov.br/dadoshistoricos
5. IBGE — Malhas Territoriais e SIDRA (tabelas 6579, 1612). https://www.ibge.gov.br/
6. Pereira, J. et al. (2020). Desenvolvimento do Ãndice de Perigo de Incêndio (IPI). *Ciência e Natura*. (Base conceitual dos blocos combustível/físico/ignição avaliados como features candidatas.)
7. Vovk, V., Gammerman, A., Shafer, G. (2005). *Algorithmic Learning in a Random World*. Springer. (Predição conforme.)
8. Hyndman, R.J., Athanasopoulos, G. (2021). *Forecasting: Principles and Practice*, 3ª ed. (Protocolo walk-forward e baselines.)
