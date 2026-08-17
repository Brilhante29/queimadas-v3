# FireCast APA-33 — PROGRESS

Branch: `feat/firecast-apa33`
SDD: reconstrução do escopo Chapada do Araripe + ingestão histórica + retreino + validação
Regra: atualizar com **evidência**, não narrativa (§61).

## Estado por fase

```text
[PASS] PHASE 0   baseline do repo (branch criada, namespaces outputs/apa33/*)
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

- Branch `feat/firecast-apa33` criada a partir de `feat/integracao-firecast-ia`.
- Namespaces criados: `outputs/apa33/audit/`, `data/snapshots/inpe_apa33_satref_v1/`.
- Nenhum output legado sobrescrito (§5, §59).

## PHASE 2 — fontes oficiais (PASS)

Artefato: `outputs/apa33/audit/source_research_findings.md` (commit `f9153b8`)

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
| `data-engineer` | `src/data/`, `data/snapshots/inpe_apa33_satref_v1/`, `cache/` | target `geocodigo × mês` 2003–2024 CE+PE+PI, manifest, provenance, coverage, mapping, QA |

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
`outputs/apa33/audit/scope_derivation_report.md` (commit `557c9b8`)

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

Artefatos: `src/data/ingest_inpe_apa33_satref.py`,
`data/snapshots/inpe_apa33_satref_v1/` (commit `90b25c3`)

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
