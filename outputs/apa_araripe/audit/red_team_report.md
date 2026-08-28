# Red-team científico independente — FireCast APA Chapada do Araripe

Auditoria adversarial das conclusões do escopo APA. O objetivo declarado foi
**derrubar** as afirmações, não confirmá-las. Nada foi editado no modelo, nos
dados ou nos experimentos; este arquivo é o único artefato produzido.

- Repositório: `firecast_entrega_limpa_20260715/firecast`
- Branch auditada: `feat/firecast-apa33`
- HEAD no início da auditoria: `4c5b008`; durante a auditoria a árvore avançou
  para `5112b31` e depois `b0e1cc0` (ver achado M8)
- Python 3.10.11, pandas; toda recomputação foi feita a partir dos artefatos
  brutos, sem importar o código do experimento quando a independência importava

---

## 1. Veredito por afirmação

| # | Afirmação | Veredito |
|---|---|---|
| 1 | Escopo = 36 municípios (CE 18, PE 8, PI 10) por interseção ICMBio × IBGE, regra `área > 0` | **SUSTAINED** |
| 2 | Alvo 2003-2024 (593 municípios, 156.552 linhas) com semântica zero-vs-ausente correta e sem zeros fabricados | **WEAKENED** |
| 3 | EXP-10 no escopo APA: `all_wape 0,7850 → 0,7074`, IC95 bootstrap `[-0,1315; -0,0307]`, `PROMOTE` | **SUSTAINED** |
| 4 | Sem vazamento temporal: 120 cortes, treino só no passado, `MIN_TRAIN_MONTHS=60` inalterado, 2025+ fora da seleção | **SUSTAINED** |
| 5 | Teste selado de 2025 executado uma vez, config congelada antes; FAIL por teto (PE 0,9896 > 0,98), cobertura geral 0,9537 | **Fatos SUSTAINED / interpretação WEAKENED** |
| 6 | Acurácia pontual fora da amostra em 2025: WAPE 0,6485 → 0,5611 | **Aritmética SUSTAINED / força probatória WEAKENED** |
| 11 | Nenhum número legado é apresentado como resultado da APA | **REFUTED** |
| 12 | A documentação não afirma mais do que os resultados sustentam | **REFUTED (nos documentos de topo)** |

---

## 2. Evidência, afirmação por afirmação

### Afirmação 1 — escopo de 36 municípios — **SUSTAINED**

Ataque tentado: slivers numéricos. A regra `area_intersect_apa_km2 > 0` não tem
limiar mínimo, então ruído de ponto flutuante em uma fronteira compartilhada
poderia inflar o N artificialmente.

O ataque falha. A menor interseção do escopo é **2,164 km² (Farias Brito/CE,
0,41% do município)** — três ordens de grandeza acima de qualquer sliver
numérico. Nenhum município entra por ruído.

Conservação de área (recomputada de `data/reference/apa_chapada_araripe.csv` e
`cache/apa_araripe_scope/derivation_meta.json`):

```text
soma das 36 interseções  : 10.173,603 km²
areahaalb_icmbio         : 1.017.366,3393 ha = 10.173,663 km²
apa_area_km2_computed    : 10.173,603 km²
```

A soma reproduz a área do polígono empregado — os 36 ladrilham a APA inteira,
sem buraco e sem dupla contagem. Malha: CE 184 + PE 185 + PI 224 = 593, bate
com a referência IBGE. Zero geocódigos duplicados. Zero nomes repetidos dentro
do escopo. O filtro exclui corretamente a FLONA Araripe-Apodi e o RVS do
Soldadinho-do-Araripe.

O `scope_derivation_report.md` é, nesta parte, exemplar: declara explicitamente
**o que a checagem de área NÃO valida** (a coincidência com o memorial de 1997)
e retrata por escrito a frase "os 33 municípios definidos pelo decreto". Não há
overclaim aqui. Ver contraste no achado C1.

### Afirmação 2 — semântica do alvo — **WEAKENED**

O que se sustenta (recomputado de `municipality_month.csv`):

```text
156.552 linhas = 593 × 22 × 12 (exato)
0 chaves (geocodigo, ano, mes) duplicadas
0 linhas observed=False com fire_count preenchido
0 linhas observed=True com fire_count nulo
113.405 zeros / 392.757 focos / 16.102 focos na APA  -> batem com PROGRESS.md
```

Conservação ponta a ponta verificada nos ZIPs brutos de 2024: 19.804 linhas
brutas em CE+PE+PI, `foco_id` e `id_bdq` sem nenhuma duplicata entre os três
arquivos estaduais, zero focos aparecendo em mais de um arquivo, zero linhas
cujo campo `estado` discorde da UF do arquivo — e `sum(fire_count)` do alvo
para 2024 = **19.804**, idêntico. Não há dupla contagem entre arquivos
estaduais.

**O que derruba parcialmente a afirmação.** O `mapping_report.csv` resolve 588
municípios; **5 municípios de PE nunca aparecem em nenhum dos 66 arquivos
fonte**: Fernando de Noronha (2605459), Ilha de Itamaracá (2607604), Jupi
(2608305), Olinda (2609600), Paulista (2610707). A grade completa é emitida
mesmo assim, então esses 5 recebem **1.320 linhas com `observed=True,
fire_count=0`** ao longo de 264 meses. Nessas linhas o pipeline não consegue,
por construção, distinguir "não houve fogo" de "o INPE nunca emitiu esse nome"
— uma falha de emissão de nome é indistinguível de um zero real, porque um nome
ausente jamais vira `UNRESOLVED`. A checagem de QA
`zero_unresolved_municipality_names` não cobre esse caminho, e o teste que
protege o invariante (`test_missing_not_silently_zeroed`) é **vacuamente
verdadeiro**: como os 66 arquivos validaram, o subconjunto `observed=False` é
vazio e a asserção passa trivialmente.

Mitigação real: 3 dos 5 são urbanos densos ou ilhas oceânicas (Olinda,
Paulista, Fernando de Noronha, Ilha de Itamaracá), onde zero em 22 anos é
plausível; Jupi é o mais frágil. E — decisivo para o escopo — **nenhum dos 5
está na APA**. Nenhum município da APA tem zero focos no período (o menor é
Cedro/PE com 27). O resultado APA não é afetado; a afirmação global sobre o
alvo de 593 municípios é que está mais forte do que a evidência.

### Afirmação 3 — números do EXP-10 — **SUSTAINED**

Recomputados de `outputs/apa_araripe/exp10/predictions_2015_2024.csv` sem usar
`result.json`:

```text
                    recomputado      reportado
all_wape baseline   0,784959         0,784959
all_wape candidate  0,707420         0,707420
delta               -0,077540        -0,077540
critical (out/nov)  0,671004 / 0,576081   idem
```

`scope_sha256` e `target_sha256` de `result.json` conferem com o SHA-256 dos
arquivos em disco. 8.640 linhas = 2 modelos × 120 cortes × 36 municípios.

### Afirmação 9 (estimando do bootstrap) — **SUSTAINED**

Reimplementado do zero, mesma semente: reamostra os 120 cortes com reposição,
concatena e recalcula o **WAPE global** — não a média de WAPEs por corte.

```text
réplica independente : CI95 = [-0,1315; -0,0307]   P(delta<0) = 0,9995   n=2000
reportado            : CI95 = [-0,13148...; -0,03068...]  P = 0,9995   degenerate = 0
```

O intervalo exclui zero e o estimando é de fato o do EXP-10 original.

### Afirmações 4, 5(escopo do fator) e 6(vazamento) — **SUSTAINED**

Duas verificações independentes.

(a) Contra as colunas registradas em `regional_ratio_by_cut.csv`, nos 120 cortes:

```text
prior_window_end >= cut            : 0 violações
train_max_period >= cut            : 0 violações
prior_max_period_observed >= cut   : 0 violações
prior_window_end == cut-1          : 120/120
n_eligible_municipios              : sempre 36
n_prior_rows                       : sempre 432 = 36 × 12
cortes com ano >= 2025             : 0
razão aplicada                     : [0,558; 1,710], nenhum corte no clip
```

O fator regional nunca inclui município fora do escopo APA, em nenhum corte.

(b) **Sem confiar em nenhuma coluna registrada**: reimplementei o walk-forward
inteiro a partir de `data/snapshots/inpe_ce_pe_pi_satref_v1/municipality_month.csv`,
recalculando climatologia, elegibilidade, janela de 12 meses e razão para os
120 cortes. Resultado comparado linha a linha com as 4.320 predições do repo:

```text
max |diff| baseline  : 3,55e-15
max |diff| candidate : 7,11e-15
max |diff| razão (120 cortes) : 2,22e-16
fire_count divergentes : 0
all_wape independente : 0,784959 -> 0,707420  (delta -0,077540)
```

Reprodução bit-a-bit. Não há vazamento temporal no EXP-10 APA.
`assign_volume_strata` é chamado apenas com `calib` (períodos estritamente
anteriores ao corte) — o conjunto avaliado nunca entra na estratificação.

### Afirmação 7 — ordenação do congelamento — **SUSTAINED (com ressalva de verificabilidade)**

```text
frozen_at (frozen_config.json)          2026-08-28T18:13:39Z
commit do frozen_config (ab3efbd)       2026-08-28T18:15:18Z
download do snapshot 2025 (retrieved_at)2026-08-28T18:23:30Z
g5_final_report generated_at            2026-08-28T18:25:03Z
commit do teste selado (5112b31)        2026-08-28T18:25:56Z
```

`frozen_config.json` foi criado em `ab3efbd` e **nunca modificado depois**
(histórico do arquivo tem um único commit). `g5_final_sealed_2025.py` aparece
pela primeira vez no commit do próprio teste. A ordem congelamento → download
de 2025 → execução → commit está correta e nenhum arquivo com métrica de 2025
precede o congelamento. Ressalva em "não verificável".

### Afirmação 10 — cobertura conformal de 2025 — **SUSTAINED numericamente, WEAKENED como evidência**

Recomputada de `interval_predictions_2025.csv` (432 linhas = 36 × 12):

```text
overall  0,953704  (reportado 0,953704)
CE  216 linhas  0,944444  (12 misses)
PE   96 linhas  0,989583  ( 1 miss)
PI  120 linhas  0,941667  ( 7 misses)
crítico out/nov  0,888889
janela de calibração: 47 meses, sempre terminando em cut-1, 0 violações
fallback_level: 432/432 em "stratum" (nenhum fallback acionado)
```

Os números batem exatamente. O que **enfraquece** a leitura está nos achados
I1 e I2 abaixo: o teto é malespecificado e 97,2% dos intervalos têm limite
inferior vacuoso.

### Afirmação 6 — acurácia pontual em 2025 — **aritmética SUSTAINED**

Recomputado de `predictions_2025.csv`:

```text
baseline  WAPE 0,648458   soma prevista   699,90
champion  WAPE 0,561109   soma prevista 1.236,37   MAE 1,871662
observado 2025 (36 municípios) : 1.441
```

Confere com o reportado. Ganho relativo -13,47%. Ressalvas em I8/M7: um único
ano, n=432 linhas correlacionadas em 36 séries, sem qualquer intervalo de
confiança sobre esse delta, e o campeão ainda subestima o total em 14%.

---

## 3. Achados, por severidade

### CRÍTICO

**C1 — Números legados do escopo CE são apresentados, nos documentos de topo,
como resultados de "Chapada do Araripe / CE-PE-PI".**

`outputs/apa_araripe/PROGRESS.md` registra a regra do próprio projeto (§23):

> "Números legados da antiga «Chapada» (WAPE sazonal 0,3723; G4 sobre 29
> geocódigos; slice de 16) **não podem** ser apresentados como APA."

A regra está violada, em produção, nos arquivos que um leitor externo abre
primeiro:

- `README.md:8` descreve o produto como *"prever focos mensais de queimadas por
  município na região operacional **Chapada do Araripe / CE-PE-PI**"* e, na
  linha 58, exibe `G3 v2 Chapada sazonal | WAPE | 0.3723 <= 0.40` como gate
  aprovado. Esse 0,3723 vem do escopo legado Cariri/CE — **29 municípios, só
  Ceará** (`src/scopes/cariri_legacy.py`), que segundo o próprio
  `PROGRESS.md` "tem 12 municípios sem interseção e omite 19 do escopo — não é
  subconjunto nem superconjunto".
- `PRODUCTION_READINESS.md:18` traz o mesmo 0,3723 e, na linha do G2, o EXP-10
  antigo `WAPE 0.6430 vs 0.7906, CI95 [-0.2195, -0.0852]` — números do alvo
  CE-only, materialmente melhores que os reais da APA (0,7074 vs 0,7850, CI95
  [-0,1315; -0,0307]).
- `docs/ARTIGO_FIRECAST.md:10` (resumo) anuncia 0,7906 → 0,6430 e
  *"intervalos conformes com cobertura empírica 0,917 para 95% nominal"* para
  um sistema descrito como "Ceará e a Chapada do Araripe", com alvo de
  "44 municípios do Ceará".
- `outputs/public_results_summary.json:16`, `outputs/production_release_audit.md`,
  `docs/ML_PRODUCTION_ARCHITECTURE.md`, `outputs/model_progress_report.md` e o
  docstring de `src/production/champion_climatology.py:278` repetem o mesmo
  número.

Contagem de menções nesses arquivos: `README.md` — "Chapada" 2, "APA" 0,
"legacy/legado" **0**. `PRODUCTION_READINESS.md` — "Chapada" 1, "APA" 0,
"legacy" **0**. `docs/ARTIGO_FIRECAST.md` — "Chapada" 11, "APA" 0, "legado" 1.
**Não existe seção legacy nem qualquer ressalva de escopo em nenhum deles.**
Um leitor não tem como saber que "Chapada" ali significa Cariri/CE-29 e não a
APA/CE-PE-PI-36.

**C2 — `PRODUCTION_READINESS.md` declara G0–G7 PASS e "APPROVED FOR INTERNAL
PRODUCTION" enquanto o G5 da APA está FAIL.**

Linha 18: `| G5 | PASS | g5_conformal_ic95_guarded_exp10: 2023-2024 coverage
0.9170 ... inside [0.90, 0.98] |`. No escopo APA o G5 reprovou **duas vezes**:
`gates/G5_conformal.json` (status FAIL, cobertura geral 0,8762) e
`gates/G5_final_sealed_2025.json` (status FAIL, teto PE). O documento nunca foi
atualizado para o escopo APA e continua com o veredito do escopo antigo. O
`CLAUDE.md` do workspace exige declarar `NÃO APROVADO PARA PRODUÇÃO` até G0–G7
passarem; a string não aparece em lugar nenhum. O artefato de serving
(`outputs/apa_araripe/serving/model.json`) é honesto — `uncertainty.status =
not_validated`, intervalo bloqueado — mas o documento que o público lê diz o
contrário.

### IMPORTANTE

**I1 — O teto do gate conformal é malespecificado: `IC_MAX` (0,98) é igual à
cobertura nominal (1−α = 0,98).**

A config congelada escolheu `alpha = 0.02`, ou seja, intervalos de 98% nominal,
e o gate exige cobertura empírica **≤ 0,98**. Um intervalo perfeitamente
calibrado tende exatamente ao teto. Em PE (n = 96):

```text
0 misses -> 1,0000 -> FAIL
1 miss   -> 0,9896 -> FAIL   <- resultado observado
2 misses -> 0,9792 -> PASS
3 misses -> 0,9688 -> PASS
P(0 ou 1 miss | intervalo 98% perfeitamente calibrado, n=96) = 0,4255
```

Ou seja: um método **perfeito** reprovaria esse teto com ~43% de probabilidade
por puro acaso amostral. O FAIL reportado é factualmente correto e foi
reportado com integridade, mas **não carrega quase nenhuma informação sobre a
qualidade do modelo** — e um PASS também não carregaria. A discretização
agrava: com 96 linhas, o gate não tem nenhum valor admissível entre 0,9792 e
1,0000. Reprovar por 1 acerto a mais em 96 não é evidência de defeito.

**I2 — 97,2% dos intervalos de 2025 têm limite inferior vacuoso; a "cobertura"
é, na prática, um teste unilateral.**

`interval_low = clip(y_pred − band, 0, None)` e o alvo é uma contagem ≥ 0.
Quando `y_pred − band ≤ 0`, o limite inferior vira 0 e **qualquer observação
passa no lado de baixo**.

```text
linhas com limite inferior testável (low > 0) :  12 / 432  (2,8%)
   cobertura nessas 12 linhas                 :  0,5833  (3 misses por baixo)
linhas com limite inferior vacuoso (low <= 0) : 420 / 432  (97,2%)
   cobertura nessas (só teto)                 :  0,9643
cobertura só-teto sobre todas as 432 linhas   :  0,9606
largura média / observado médio               :  3,03
largura mediana 4,81  vs  observado mediano 0,00
```

A cobertura de 0,9537 é essencialmente um teste de limite superior. Nas poucas
linhas onde o limite inferior é de fato testável, a cobertura cai para 58%.
Nenhum documento registra essa decomposição.

**I3 — A comparação "o método corrigido resolveu o problema" é confundida: α,
método e janela de avaliação mudaram ao mesmo tempo.**

`g5_final_sealed_result.md` põe lado a lado:

| | G5 anterior | G5 final |
|---|---:|---:|
| geral | 0,8762 | 0,9537 |

e conclui *"A subcobertura sistemática acabou... `rolling_mondrian_48` com
janela deslizante de 48 meses entregou cobertura dentro da faixa"*. Mas o G5
anterior (`gates/G5_conformal.json`) usou **α = 0,05, nominal 95%, avaliado em
2023-2024**; o G5 final usou **α = 0,02, nominal 98%, avaliado em 2025**. Parte
substancial do salto de 0,8762 para 0,9537 é simplesmente ter alargado o nível
nominal em 3 pontos. Atribuir o ganho à janela deslizante, sem manter α fixo,
não é sustentável pelo experimento realizado. Um contrafactual óbvio — o método
antigo com α = 0,02 — nunca foi medido.

**I4 — "Uma única violação" subestima: a fatia de pico de estação está abaixo
do mesmo piso e simplesmente não é critério.**

O gate (`g5_final_sealed_2025.py`, linhas 299-307) verifica apenas `overall` e
as três UFs. `critical_out_nov = 0,8889` está **abaixo do piso 0,90** que o
gate aplica em toda parte, e não conta como falha. O relatório disclosa o
número entre parênteses ("não é critério do gate"), o que é honesto, mas a
manchete **"Uma única violação, e ela é de *teto*, não de piso"** é falsa como
descrição da evidência empírica: há dois valores fora de [0,90; 0,98], um
acima e um **abaixo**, e o abaixo é justamente outubro-novembro, a fatia
operacionalmente mais importante. Volume, seca/úmida e crítico são calculados e
relatados, mas nenhum entra no gate.

**I5 — 1.320 linhas de zero `observed=True` para 5 municípios que a fonte nunca
emitiu; o teste que protegeria o invariante é vacuamente verdadeiro.**

Detalhado na Afirmação 2. Fora do escopo APA, mas invalida a afirmação global
"os 113.405 zeros são observação real, não fabricação" para essas 1.320 linhas.
`test_missing_not_silently_zeroed` filtra `observed == False`, conjunto vazio
neste snapshot — passa sem testar nada. Nenhum teste cobre o caminho real de
risco (município ausente da fonte → grade preenchida com zero observado).

**I6 — A homogeneidade do satélite de referência em 2003-2024 é asserção, não
verificação.**

Inspecionei os ZIPs brutos: as colunas são
`id_bdq, foco_id, lat, lon, data_pas, pais, estado, municipio, bioma` — **não
existe coluna de satélite em nenhum arquivo**, nem no histórico nem em 2025. O
`manifest.json` declara o contrato de sensor como "propriedade do arquivo
fonte", o que é uma afirmação sobre o produto do INPE, não uma medição. A série
tem variação estrutural relevante — CE cai de 11.626 (2003) para 2.327 (2014) e
volta a 7.160 (2024) — compatível com dinâmica real de seca, mas também com
mudança de sensor, e **nenhum teste de quebra estrutural foi executado**. Se o
contrato de sensor mudou em silêncio, a definição do alvo mudou junto, e nada
no repositório detectaria isso.

**I7 — O snapshot de 2025 vem de um caminho de distribuição diferente do
histórico; "mesmo produto" é asserção não cruzada.**

Histórico: `EstadosBr_sat_ref/{UF}/focos_br_{uf}_ref_{ano}.zip` (66 arquivos por
estado). 2025: `Brasil_sat_ref/focos_br_ref_2025.zip` (arquivo nacional único).
O manifest de 2025 afirma *"mesmo produto do historico"*.

O que consegui verificar e **sustenta** a afirmação: esquema de colunas
idêntico; campo `estado` com nome completo do estado nos dois; mesma
`normalize_text` / `repair_mojibake` / mesma referência IBGE; e o mapeamento
geocódigo → (nome, UF) é **idêntico nos 593 municípios** entre o alvo 2003-2024
e o de 2025 (0 divergências, merge `both` = 593). O que **não** foi verificado:
nenhum ano de sobreposição foi baixado dos dois caminhos e comparado. O teste é
barato (`Brasil_sat_ref/focos_br_ref_2024.zip` vs os três arquivos EstadosBr de
2024) e não foi feito.

### MENOR

- **M1** — `g5_final_sealed_result.md` traz "Data: 2026-08-14", mas
  `generated_at` do relatório é `2026-08-28T18:25:03Z` e o commit é de
  2026-08-28. Data errada num documento cujo valor probatório é justamente
  cronológico.
- **M2** — `MIN_TRAIN_MONTHS = 60` está preservado, mas é **inerte**: no
  primeiro corte (2015-01) o município com menor histórico já tem 132 meses.
  "36/36 elegíveis com MIN_TRAIN_MONTHS preservado" é verdade e não testa nada.
- **M3** — `serving/model.json` (gerado 18:16:27Z) registra
  `uncertainty.reason` com a falha **antiga** ("cobertura geral 0.8762"), não o
  resultado do teste selado de 2025 (18:25:03Z). Conclusão inalterada (FAIL),
  mas o motivo publicado está desatualizado.
- **M4** — O join municipal é **por nome** (`normalize(nome) + UF →
  geocódigo`); a fonte do INPE não traz geocódigo, então não há alternativa. A
  canária Cedro está correta (Cedro/PE 2604304 no escopo, Cedro/CE 2303808
  fora, resolvido por geometria e não por nome), a referência não tem nome
  duplicado dentro de UF, e verifiquei 0 linhas de 2024 cujo `estado` discorde
  da UF do arquivo. Mas o desenho continua dependente da correção do campo
  `estado` do INPE, e os 4 nomes compartilhados entre UFs (Aracoiaba, Cedro,
  Jurema, Santa Filomena) só sobrevivem por causa desse campo.
- **M5** — O baseline é climatologia municipal de longo prazo pura. O candidato
  é essa mesma climatologia multiplicada por um escalar de nível. Como a série
  tem tendência forte, o ganho é em boa parte correção de nível — nenhum
  baseline com tendência ou janela recente entrou na comparação. "Bate a
  climatologia municipal" é afirmação mais fraca do que "bate um baseline
  competente", e só a primeira foi demonstrada.
- **M6** — O cache em disco é `cache/inpe_apa33_satref/`, mas
  `ingest_inpe_ce_pe_pi_satref.py` aponta para `cache/inpe_apa_araripe_satref/`.
  Uma reexecução re-baixaria os 66 arquivos em vez de reaproveitar o cache
  presente. Deriva entre o código renomeado e o artefato em disco.
- **M7** — O delta de acurácia pontual de 2025 é reportado sem nenhum intervalo:
  um ano, 432 linhas, 36 séries correlacionadas. "A previsão pontual é robusta"
  é mais forte do que n = 1 ano suporta. O campeão ainda subestima o total de
  2025 em 14% (1.236 previstos vs 1.441 observados).
- **M8** — A árvore de trabalho **mudou durante a auditoria**: HEAD passou de
  `4c5b008` (início) para `5112b31` e depois `b0e1cc0`/`9b2a5b5` enquanto eu
  lia. Há um processo concorrente commitando na mesma branch. Isso não invalida
  nada que recomputei (os hashes de escopo e alvo conferem), mas significa que
  qualquer auditoria desta branch precisa fixar um SHA antes de começar.

---

## 4. O que NÃO consegui verificar, e por quê

1. **Identidade do sensor ao longo de 2003-2024 e entre 2003-2024 e 2025.**
   Não há coluna de satélite em nenhum arquivo fonte. Verificar exigiria os
   metadados de produto do INPE ou baixar `Brasil_sat_ref/focos_br_ref_2024.zip`
   e comparar com os arquivos `EstadosBr` de 2024 — não fiz download por estar
   em modo somente-auditoria.

2. **Que o teste selado de 2025 foi executado uma única vez.** Uma reexecução
   local não deixa rastro; as datas de commit são autodeclaradas
   (`GIT_COMMITTER_DATE` é editável) e a branch não tem evidência independente
   de push com carimbo de servidor. A ordenação interna dos artefatos é
   consistente e não achei nenhuma contradição — mas consistência não é prova
   de execução única.

3. **Se os 5 municípios de PE sem nenhum foco em 22 anos são zeros genuínos ou
   uma lacuna de emissão de nome.** Precisaria de um produto de fogo
   independente (FIRMS/MODIS) recortado por essas geometrias. Fora do escopo
   APA, então não bloqueia as conclusões da APA.

4. **Se o polígono do ICMBio corresponde ao memorial descritivo do decreto de
   1997.** Já registrado como limitação explícita pelo próprio projeto; exigiria
   redigitalizar as cartas SUDENE/DSG 1:100.000.

5. **A seleção interna da família conformal drift-robust** (28 candidatos, 4
   elegíveis). Li `frozen_config.json`, `candidate_selection.csv` e o código do
   gate, e a regra está registrada — mas não re-executei a seleção dos 28
   candidatos nas dobras 2021-2024, então não posso afirmar que a família
   congelada é a que a regra declarada realmente elegeria.

6. **Análise de multiplicidade do caminho adaptativo do G5.** O G5 falhou
   (`4c5b008`), a família foi redesenhada, 2023-2024 foi *rebaixado de holdout
   para desenvolvimento* e a grade de α foi estendida até 0,02 — tudo depois de
   observar a falha. Isso está documentado com honestidade, mas nenhuma
   correção para seleção adaptativa foi aplicada nem quantificada, e eu não
   tinha como reconstruir quantas configurações foram efetivamente examinadas ao
   longo de todo o caminho.

---

## 5. Síntese adversarial

O núcleo quantitativo **resistiu ao ataque**. O escopo de 36 municípios é
geometricamente sólido e conservativo em área; o alvo conserva focos ponta a
ponta sem dupla contagem; o EXP-10 reproduz bit-a-bit a partir dos dados brutos,
com o estimando de bootstrap que declara usar; e não encontrei nenhum caminho de
vazamento temporal em 120 cortes reconstruídos independentemente. Onde os
artefatos do escopo APA falham, eles **reportam a própria falha** — o G5 está
FAIL, o serving devolve `interval: null`, e o relatório de derivação de escopo
declara explicitamente o que a checagem de área não valida. Isso é raro e vale
registrar.

O que não resiste está na **camada de comunicação e no desenho do gate de
intervalos**, não na modelagem:

- os documentos de topo (README, PRODUCTION_READINESS, artigo) continuam
  vendendo números do escopo CE legado sob o rótulo "Chapada do Araripe /
  CE-PE-PI", com G5 marcado PASS quando na APA está FAIL — exatamente o que a
  regra §23 do próprio projeto proíbe;
- o teto de 0,98 contra um nominal de 0,98 torna o gate conformal quase não
  informativo, e o FAIL anunciado como resultado científico é, estatisticamente,
  próximo de um lance de moeda;
- e a cobertura de 0,9537 é, em 97% das linhas, um teste unilateral — o número
  mede menos do que o nome sugere.

O achado mais grave é o C1: não é um erro de cálculo, é uma atribuição de
escopo. Os números certos existem, estão corretos e estão piores; são os errados
que estão publicados.

---

*Relatório produzido por auditoria adversarial independente. Nenhum arquivo do
modelo, dos dados ou dos experimentos foi modificado.*
