# FireCast APA Chapada do Araripe — PROGRESS

Branch: `feat/firecast-apa_araripe`
SDD: reconstrução do escopo Chapada do Araripe + ingestão histórica + retreino + validação
Regra: atualizar com **evidência**, não narrativa (§61).

## Estado por fase

```text
[PASS] PHASE 0   baseline do repo (branch criada, namespaces outputs/apa_araripe/*)
[PASS] PHASE 2   descoberta/verificacao das fontes oficiais
[PASS] PHASE 1'  escopo APA por intersecao espacial versionada -> N = 36
[PASS] PHASE 3   ingestor historico INPE CE+PE+PI 2003-2024 -> 156.552 linhas
[RUN ] PHASE 4   QA e data contracts (G0)
[WAIT] PHASE 5   parametrizacao do treino (target_snapshot + scope)
[WAIT] PHASE 6   reproducao do baseline (climatology_municipal)
[WAIT] PHASE 7   reproducao do EXP-10 no escopo APA
[WAIT] PHASE 8   bootstrap + gates G1/G2
[WAIT] PHASE 9   conformal G5
[WAIT] PHASE 10  serving
[WAIT] PHASE 11  red-team
[WAIT] PHASE 12  paper/docs
[WAIT] PHASE 13  reproducao limpa
[WAIT] PHASE 14  relatorio final
```

## PHASE 0 — baseline (PASS)

- Branch `feat/firecast-apa_araripe` criada a partir de `feat/integracao-firecast-ia`.
- Namespaces criados: `outputs/apa_araripe/audit/`, `data/snapshots/inpe_ce_pe_pi_satref_v1/`.
- Nenhum output legado sobrescrito (§5, §59).

## PHASE 2 — fontes oficiais (PASS)

Artefato: `outputs/apa_araripe/audit/source_research_findings.md` (commit `f9153b8`)

Evidência:

| verificação | resultado |
|---|---|
| endpoint `mensal/Brasil` (usado hoje p/ scoring) | 200301..202301 = HTTP 404; 202401+ = 200. Confirma que é scoring recente, não histórico |
| endpoint `anual/EstadosBr_sat_ref/{UF}/` | CE/PE/PI, 22 arquivos cada, **2003–2024** |
| download real PE/2003 | 50.231 bytes, sha256 `35291d8a...b2736`, 2.771 linhas |
| schema | `id_bdq,foco_id,lat,lon,data_pas,pais,estado,municipio,bioma` — **sem `geocodigo`** |
| decreto 04/08/1997 (Senado) | Art. 3º = memorial descritivo (curva de nível/UTM). **Não enumera municípios** |
| ICMBio página da UC | publica nome/bioma/área/decreto. **Não publica lista de municípios** |

Consequências registradas:
- §4 não é executável ao pé da letra (fonte oficial não tem lista para "reconstruir").
- §44 (frase do artigo) precisa mudar: "N municípios definidos pelo decreto" é insustentável.
- Decisão do usuário: derivar por **interseção espacial versionada**, N calculado, nunca fixado.

## PHASE 1' + PHASE 3 — em execução, em paralelo (§29)

Caminhos disjuntos, sem conflito de arquivo:

| agente | escreve em | entrega |
|---|---|---|
| `scope-engineer` | `data/reference/`, `src/scopes/` | `apa_chapada_araripe.csv` (N derivado), `cariri_ce_legacy`, relatório de derivação + divergência vs 29/33/36/38 |
| `data-engineer` | `src/data/`, `data/snapshots/inpe_ce_pe_pi_satref_v1/`, `cache/` | target `geocodigo × mês` 2003–2024 CE+PE+PI, manifest, provenance, coverage, mapping, QA |

Contratos exigidos dos dois (§10, §4.2, §50, §53):
- zero vs missing derivado da **validade do arquivo-fonte**, nunca de "primeiro/último foco";
- join obrigatório `normalize(nome)+UF → geocódigo IBGE`, falha fechada em ambiguidade (Cedro/CE vs Cedro/PE);
- download atômico, SHA-256, retry/backoff, cache idempotente;
- ZIP sem `extractall` cego;
- brutos fora do Git, proveniência dentro.

## Pendências conhecidas (não bloqueantes do Milestone 1)

- Divergência entre o limite geoespacial atual do ICMBio e o memorial legal de 1997 → registrar como limitação/proveniência (decisão do usuário).
- Números legados da antiga "Chapada" (WAPE sazonal 0,3723; G4 sobre 29 geocódigos; slice de 16) **não podem** ser apresentados como APA (§23). Ficam em seção legacy.

## PHASE 1' — escopo derivado (PASS)

Artefatos: `data/reference/apa_chapada_araripe.csv`, `src/scopes/apa_araripe.py`,
`outputs/apa_araripe/audit/scope_derivation_report.md` (commit `557c9b8`)

```text
N = 36   (CE 18, PE 8, PI 10)   <- COMPUTADO, nunca fixado
regra   : area_intersect_apa_km2 > 0
poligono: ICMBio:limiteucsfederais_a via geoserver INDE
malha   : IBGE API v3 /malhas/estados/{23,26,22} qualidade=maxima
area    : Albers equivalente America do Sul (nunca em graus)
```

Validacao geometrica independente:

```text
soma das intersecoes municipais : 10.173,6   km2
area oficial declarada (ICMBio) : 10.173,616 km2
```

Bate em 4 algarismos -> os 36 ladrilham a APA inteira, sem buraco nem
dupla contagem.

Divergencias explicadas municipio a municipio no relatorio. Destaques:
- briefing interno (33) incluia 5 municipios sem intersecao alguma
  (Paulistana, Pio IX, Granito, Ouricuri, Santa Cruz) e omitia Marcolandia/PI,
  que tem 94,51% da area dentro da APA;
- legado (29) tem 12 municipios sem intersecao e omite 19 do escopo -- nao e
  subconjunto nem superconjunto, e outro recorte;
- Juazeiro do Norte fica FORA, derivado independentemente;
- Cedro resolve para PE (2604304) por geometria, nao por nome.

## PHASE 3 — ingestao historica (PASS)

Artefatos: `src/data/ingest_inpe_ce_pe_pi_satref.py`,
`data/snapshots/inpe_ce_pe_pi_satref_v1/` (commit `90b25c3`)

```text
66/66 arquivos-fonte baixados e validados por hash
156.552 linhas = 593 municipios x 264 meses (exato)
0 chaves (geocodigo,ano,mes) duplicadas
0 nomes de municipio nao resolvidos
CE 184 / PE 185 / PI 224 -- bate com a referencia IBGE
392.757 focos no total CE+PE+PI 2003-2024
```

Semantica zero-vs-missing: todos `observed=true` porque os 66 arquivos
validaram; os 113.405 zeros sao observacao real, nao fabricacao.

Sanidade sazonal: media mensal pico set 6,35 / out 6,91 / nov 5,88 e vale
mar 0,13 / abr 0,09 -- temporada de fogo real.

## Cruzamento escopo x alvo (entrada da PHASE 4)

```text
36/36 municipios do escopo presentes no alvo
9.504 linhas = 36 x 264 (exato)
36/36 ELEGIVEIS com MIN_TRAIN_MONTHS = 60 preservado (nao afrouxado)
minimo de meses observados no escopo: 264 (todos completos)
16.102 focos na APA 2003-2024
```

Achado com peso cientifico: os 3 municipios de maior incidencia da APA sao
todos de **Pernambuco** -- Bodoco (2.397 focos), Araripina (1.253), Exu
(1.158). O champion atual, treinado so no CE, **nunca viu nenhum deles**.

## PHASE 6 - contrato de divulgacao (§23, §44, §46, §47)

Auditoria independente (red-team, `outputs/apa_araripe/audit/red_team_report.md`)
sustentou o EXP-10, o escopo e a ausencia de leakage -- reimplementou os 120
cortes sem importar o repo e bateu previsao a previsao ate 1e-15, replicando o
bootstrap em [-0,1315; -0,0307], P = 0,9995.

Mas **refutou** duas afirmacoes de documentacao. Ambas corrigidas aqui.

### C1 - numeros legados publicados como se fossem da APA  [x]

`README.md`, `PRODUCTION_READINESS.md`, `docs/ARTIGO_FIRECAST.md` e
`outputs/public_results_summary.json` publicavam metricas do escopo Cariri/CE
(WAPE 0,3723; EXP-10 0,6430; G5 PASS 0,9170) sob o rotulo
`"scope": "Chapada do Araripe / CE-PE-PI"`, com gates PASS. No escopo APA o
WAPE e mais alto e o G5 reprovou. O leitor tirava a conclusao invertida.

Correcao estrutural, nao textual: `scripts/build_public_results_summary.py`
gera o summary e os blocos de metricas do README e do PRODUCTION_READINESS a
partir dos artefatos, via `pluck()`, que **levanta erro** se a chave sumir.
Numero digitado a mao deixou de existir nesses arquivos. `--check` roda no CI
e nos testes.

Os dois escopos agora sao blocos nomeados: `current_scope`
(`apa_chapada_araripe`) e `legacy_cariri_ce`, este ultimo com
`status: "LEGADO -- NAO SE APLICA A APA CHAPADA DO ARARIPE"`.

### C2 - "APPROVED FOR INTERNAL PRODUCTION" com G5 reprovado  [x]

Substituido pelo status gerado, que le os gates: **NAO APROVADO PARA
PRODUCAO**. O serving passou a ler `G5_final_sealed_2025.json` com precedencia
sobre `G5_conformal.json` -- um PASS antigo nao pode sobrepor o FAIL do
holdout selado.

### Duas ressalvas metodologicas ao proprio G5  [x] publicadas

Medidas, nao opinadas; ambas geradas a partir dos artefatos.

1. **O intervalo e unilateral na pratica.** 420 de 432 intervalos de 2025
   (97,2%) tem `interval_low <= 0`, limite que quase nunca pode ser violado.
   Nas 12 linhas com piso testavel a cobertura cai para **0,5833**. Das
   violacoes, 17 sao por cima e 3 por baixo. Ou seja: a cobertura global de
   0,9537 mede sobretudo o teto do intervalo, nao o intervalo inteiro.

2. **O teto do gate coincide com o nivel nominal.** Com `alpha = 0,02` o
   intervalo e nominalmente 0,98 e o teto aceitavel tambem e 0,98. Um metodo
   perfeitamente calibrado estoura esse teto so por acaso amostral com
   probabilidade CE 0,5660 / PE 0,4255 / PI 0,5687. PE reprovou com **1 erro
   em 96** -- precisaria de pelo menos 2 para passar. O gate penalizou acerto.

Consequencia registrada: o G5 **permanece FAIL**. Reespecificar o criterio
depois de ver o holdout seria ajuste no holdout, que o contrato de execucao
unica proibe. O registro honesto e que o metodo nao foi validado **e** que o
gate, como especificado, tambem nao serve. Qualquer nova tentativa exige gate
reescrito e pre-registrado antes de tocar em outro ano -- e 2025 ja esta
queimado para esse fim.

### Reparos adjacentes  [x]

- `docs/ARTIGO_FIRECAST.md` estava gravado como UTF-8 de texto ja decodificado
  como cp1252: todo acento ilegivel. Reparado, com banner de escopo no topo.
- 12 testes novos em `tests/test_scope_disclosure_contract.py` travam a
  propriedade: valor legado so pode aparecer abaixo do cabecalho que o
  desqualifica, e nenhum documento pode afirmar aprovacao enquanto um gate da
  APA reprovar. Suite: **114 passando**.

## PHASE 7 - integridade do alvo e honestidade do registro (I3-I7)

Os cinco achados "Importantes" restantes da auditoria independente. Cada um
trocou uma assercao por uma medicao. Todos os artefatos ficam em
`outputs/apa_araripe/audit/`.

### I7 - equivalencia entre caminhos da fonte  [x] SUSTENTADA COM EVIDENCIA

O treino vem de `EstadosBr_sat_ref/{UF}/` e o scoring de 2025 vem de
`Brasil_sat_ref/` (arquivo nacional). O manifest afirmava "mesmo produto" sem
nunca ter cruzado os dois caminhos.

Baixei 2024 pelos dois caminhos e comparei celula a celula:

```text
2.401 celulas comparadas
19.804 focos pelo caminho nacional
19.804 focos pelo caminho por UF
0 celulas divergentes, delta maximo 0
```

Identico. Tratar 2025 como o mesmo produto agora e **verificado**, nao
asserido. `scripts/validate_source_path_equivalence.py`.

### I6 - homogeneidade de sensor  [x] ASSERCAO SUBSTITUIDA POR RASTREIO

Confirmei que os arquivos-fonte **nao tem coluna de satelite**:
`id_bdq, foco_id, lat, lon, data_pas, pais, estado, municipio, bioma`. Ou seja,
o contrato de sensor era afirmacao sobre o produto do INPE, e uma troca
silenciosa nao seria detectada por nada no repositorio.

Rodei teste de Pettitt (nao parametrico) na serie mensal dessazonalizada e nos
totais anuais. **Quebra significativa em 2012**:

```text
UF CE   ponto 2012  p=0,0082  nivel depois/antes = 0,558
UF PE   ponto 2012  p=0,0189  nivel depois/antes = 0,542
UF PI   ponto 2013  p=1,0000  ns
escopo APA          p=0,0582  ns (marginal)
CE+PE+PI agregado   p=0,1223  ns
```

Nao da para atribuir: 2012 e o inicio da grande seca do Nordeste (2012-2017) e
tambem poderia ser troca de sensor. As duas produzem degrau de nivel. O
rastreio declara isso explicitamente.

**Impacto no modelo, e um achado com valor proprio:** o fator regional de
intensidade e razao observado/esperado nos 12 meses antes do corte. A janela
mais antiga comeca em **2014-01**, depois da quebra -- nenhuma das 120 janelas
mistura regimes. Mais: a razao do primeiro corte e **0,5583**, praticamente
identica a razao de nivel medida na propria quebra em CE (0,558). O fator
regional **absorve empiricamente o degrau de 2012**. Isso e explicacao mecanica
de por que o champion supera a climatologia pura, nao so ganho empirico sem
causa.

Risco residual registrado: a climatologia municipal e estimada sobre 2003-2024
inteiro e **atravessa** a quebra. O fator regional corrige no agregado, nao por
municipio. Recalibrar so com pos-2012 e experimento legitimo e **nao foi
feito** -- o EXP-10 esta congelado por decisao registrada, e refaze-lo agora
seria escolher metodo depois de ver o diagnostico.

### I5 - semantica de zero  [x] ALARME PARCIALMENTE FALSO, LACUNA REAL FECHADA

Os 5 municipios com zero em 264 meses sao Fernando de Noronha, Ilha de
Itamaraca, Jupi, Olinda e Paulista -- ilhas oceanicas e area urbana densa da
regiao metropolitana do Recife. Zero deteccao em 22 anos e plausivel para esse
perfil. **Nenhum esta no escopo APA**, entao nenhum resultado da APA depende
dessas 1.320 linhas (1,2% de todos os zeros).

O ponto de fundo procede: o codigo nao distingue "sem deteccao" de "join
falhou". Fechado por tres caminhos:

1. A ingestao **falha fechada** em nome nao resolvido -- erro de join aborta em
   vez de virar zero. O snapshot registra `n_unresolved_municipality_names = 0`.
2. `test_ingestion_fails_closed_on_unresolvable_municipality` exercita esse
   caminho de verdade: trunca a referencia IBGE para so o Piaui e exige
   `ValueError`. Roda offline. Substitui a cobertura vacua de
   `test_missing_not_silently_zeroed`, que filtra `observed == False` --
   conjunto vazio -- e passava sem testar nada.
3. `test_grid_minus_source_equals_the_never_emitted_set` amarra as contagens:
   593 na grade menos 588 resolvidos pela fonte tem que dar exatamente os 5.
   Uma terceira causa de zero quebraria o teste.

### I3 - comparacao confundida  [x] DECOMPOSTA

O registro anterior punha 0,8762 contra 0,9537 e atribuia o salto a janela
deslizante. Mas metodo, alpha **e** ano de avaliacao mudaram juntos.

Decomposicao nos 4 folds de desenvolvimento, **sem tocar em 2025**:

```text
expanding_mondrian  @ a=0,05 -> 0,8964
expanding_mondrian  @ a=0,02 -> 0,9537   so alpha:  +0,0573
rolling_mondrian_48 @ a=0,05 -> 0,9149   so metodo: +0,0185
rolling_mondrian_48 @ a=0,02 -> 0,9635   total:     +0,0671
```

**Alpha responde por 85% da melhora, o metodo por 28%** (somam mais de 100%
porque a interacao e -0,0087). A atribuicao anterior nao se sustenta: o efeito
dominante foi alargar o nivel nominal de 0,95 para 0,98.

O efeito do ano de avaliacao nao e separavel -- exigiria rodar outras
configuracoes no holdout selado. Fica declarado, nao estimado.

### I4 - "uma unica violacao" era falso  [x] CORRIGIDO

O gate avalia so `overall` e as tres UFs. A fatia **critico out-nov = 0,8889
esta ABAIXO do piso 0,90** e simplesmente nao conta como falha. Outubro e
novembro sao o pico da estacao seca, a janela de uso operacional real.

Ha dois valores fora de [0,90; 0,98], um acima e um abaixo, e o abaixo e o que
mais importa. Incluir a fatia critica no gate **agora**, depois de ver o
numero, seria mudar criterio em cima do holdout -- fica registrado como
requisito obrigatorio do proximo gate.

### Registro final do G5

`g5_final_sealed_result.md` foi reescrito com secao de correcoes explicita (as
tres frases refutadas ficam listadas, nao apagadas). Veredito duplo:

> O metodo nao foi validado **e** o gate, como especificado, tambem nao serve.

Proxima rodada exige gate reescrito e pre-registrado antes de tocar em 2026:
teto com folga contra o nominal, fatia critica como criterio, e cobertura
medida **por lado** -- a agregada atual e quase toda do lado superior.

Suite: **126 passando**.

## PHASE 8 - achados menores, com dois resultados negativos que importam

Os "Menores" da auditoria. Dois deles nao eram menores.

### M5 - o baseline do G2 era fraco demais  [x] RESULTADO NEGATIVO PUBLICADO

O G2 compara o champion so contra climatologia de longo prazo, que nao corrige
nivel. Numa serie com degrau em 2012, vencer esse baseline nao prova que o
fator regional importa -- qualquer janela recente faria parte do trabalho.

Rodei o champion contra tres baselines que tambem corrigem nivel, no mesmo
protocolo de 120 cortes, com o mesmo estimando de bootstrap:

```text
modelo                          WAPE    out-nov
champion                       0,7074   0,5761
climatology_recent_60          0,7375   0,6161
climatology_x_municipal_r12    0,7725   0,6572
climatology_municipal          0,7976   0,6922
seasonal_naive_12              0,8456   0,6931
```

IC95 do delta contra o champion:

```text
climatology_municipal        [-0,1545; -0,0380]  VENCE
seasonal_naive_12            [-0,1978; -0,0858]  VENCE
climatology_x_municipal_r12  [-0,1135; -0,0274]  VENCE
climatology_recent_60        [-0,0643; +0,0088]  NAO VENCE
```

**O champion nao supera com significancia uma climatologia dos ultimos 60
meses** -- sem fator regional, sem encolhimento, sem clip. P = 0,9425.

O G2 continua valido **como foi definido**: o champion bate
`climatology_municipal` com IC95 inteiramente negativo. Mas a leitura
cientifica fica mais modesta do que "o fator regional de intensidade e o que
importa". Publicado no README e no PRODUCTION_READINESS, nao escondido no
arquivo de auditoria. Qualquer G2 futuro precisa incluir baseline de janela
recente.

O champion **nao** foi trocado: seria selecionar metodo a partir de um
diagnostico rodado depois do congelamento -- e `climatology_recent_60` e pior
na estimativa pontual de todo jeito.

### M7 - o ganho de 2025 nao tinha intervalo  [x] RESULTADO NEGATIVO PUBLICADO

O registro dizia "-13,5%" e "a previsao pontual e robusta" a partir de um ano.
Bootstrap por mes (o cluster honesto -- municipios do mesmo mes nao sao
independentes):

```text
delta de WAPE      -0,0873   IC95 [-0,1872; +0,2881]
ganho relativo     -13,5%    IC95 [-29,7%; +39,7%]
P(champion melhor) 0,7738
```

**O IC95 cruza o zero.** 2025 nao confirma nem refuta o ganho; e apenas
consistente com ele. O que sustenta o EXP-10 continua sendo o walk-forward de
120 cortes, IC95 [-0,1315; -0,0307].

Alem disso, o champion **subestima o total de 2025 em 14,2%** (1.236 previstos
contra 1.441 observados) -- o lado errado do erro em contexto de risco de fogo,
e isso tambem nao estava reportado.

### M6 - deriva de cache  [x] BUG REAL

O codigo apontava para `cache/inpe_apa_araripe_satref/` e o disco tinha
`cache/inpe_apa33_satref/` -- sobra da remocao do nome `apa33`. Uma reexecucao
re-baixaria os 66 arquivos. Diretorio renomeado; 67 arquivos voltaram a ser
alcancaveis.

### M1 - data errada  [x] / M3 - motivo desatualizado no serving  [x]

M1: o registro do teste selado dizia "2026-08-14"; o `generated_at` do gate diz
`2026-08-28T18:25:03Z`. Agora as duas datas -- congelamento
(`18:13:39Z`) e execucao (`18:25:03Z`) -- sao lidas dos artefatos, e a ordem
fica verificavel: congelou **antes** de acessar 2025.

M3: o `serving/model.json` publicava o motivo do G5 **antigo**. Corrigido na
PHASE 6 -- o serving agora le `G5_final_sealed_2025.json` com precedencia.

### M2, M4, M8 - registrados sem acao de codigo

- **M2**: `MIN_TRAIN_MONTHS = 60` esta preservado mas e inerte -- no primeiro
  corte o municipio com menor historico ja tem 132 meses. "36/36 elegiveis" e
  verdade e nao testa nada.
- **M4**: o join municipal e por nome porque a fonte do INPE nao traz
  geocodigo. A canaria Cedro esta correta (Cedro/PE dentro, Cedro/CE fora,
  resolvido por geometria). O desenho depende da correcao do campo `estado` do
  INPE, e os 4 nomes compartilhados entre UFs so sobrevivem por causa dele.
- **M8**: a arvore mudou durante a auditoria porque havia trabalho concorrente
  na mesma branch. Auditoria futura precisa fixar um SHA antes de comecar.

### Balanco

A auditoria adversarial sustentou o nucleo -- escopo, EXP-10, ausencia de
vazamento, reproduzido do zero ate 1e-15. E derrubou a forma como quase tudo
estava sendo **contado**: numeros legados publicados como se fossem da APA,
aprovacao de producao com gate reprovado, atribuicao causal sem controle,
"uma unica violacao" que eram duas, e dois ganhos publicados sem a incerteza
que os relativiza.

Suite: **130 passando**.
