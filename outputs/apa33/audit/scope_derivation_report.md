# Derivação do escopo APA Chapada do Araripe — relatório

Data: 2026-08-14
Branch: `feat/firecast-apa33`
Código: `src/scopes/apa_araripe.py` (`python -m src.scopes.apa_araripe`)
Artefato: `data/reference/apa_chapada_araripe.csv`

> **O N não foi fixado.** É o resultado da interseção espacial entre o limite
> oficial da APA e a malha municipal do IBGE.

---

## 1. N total

```text
N = 36
```

## 2. N por UF

| UF | municípios |
|---|---:|
| CE | 18 |
| PI | 10 |
| PE | 8 |
| **total** | **36** |

## 3. Escopo completo

Ordenado por fração do município dentro da APA.

| geocódigo | UF | município | % do município na APA | área na APA (km²) |
|---:|---|---|---:|---:|
| 2301307 | CE | Araripe | 99,12 | 1.087,72 |
| 2311959 | CE | Salitre | 98,94 | 797,72 |
| 2202091 | PI | Caldeirão Grande do Piauí | 95,87 | 447,64 |
| 2205953 | PI | Marcolândia | 94,51 | 129,31 |
| 2312106 | CE | Santana do Cariri | 94,37 | 806,98 |
| 2307106 | CE | Jardim | 91,45 | 498,37 |
| 2311207 | CE | Potengi | 80,95 | 277,85 |
| 2607307 | PE | Ipubi | 75,42 | 523,39 |
| 2311108 | CE | Porteiras | 63,66 | 143,17 |
| 2601102 | PE | Araripina | 60,18 | 1.226,22 |
| 2309201 | CE | Nova Olinda | 54,93 | 155,23 |
| 2605301 | PE | Exu | 50,62 | 676,65 |
| 2210706 | PI | Simões | 49,43 | 531,94 |
| 2301901 | CE | Barbalha | 45,86 | 278,95 |
| 2204303 | PI | Fronteiras | 45,53 | 353,87 |
| 2304202 | CE | Crato | 42,80 | 487,04 |
| 2602001 | PE | Bodocó | 39,96 | 647,98 |
| 2308401 | CE | Missão Velha | 35,40 | 217,12 |
| 2614303 | PE | Moreilândia | 30,59 | 123,70 |
| 2200277 | PI | Alegrete do Piauí | 27,89 | 67,99 |
| 2300606 | CE | Altaneira | 22,36 | 16,24 |
| 2204154 | PI | Francisco Macedo | 21,68 | 38,87 |
| 2302701 | CE | Campos Sales | 20,42 | 221,11 |
| 2300101 | CE | Abaiara | 20,17 | 36,48 |
| 2615607 | PE | Trindade | 13,81 | 40,84 |
| 2203271 | PI | Curral Novo do Piauí | 10,36 | 78,27 |
| 2301604 | CE | Assaré | 9,42 | 108,82 |
| 2307205 | CE | Jati | 8,34 | 30,72 |
| 2302503 | CE | Brejo Santo | 7,11 | 46,57 |
| 2604304 | PE | **Cedro** | 3,60 | 5,35 |
| 2207207 | PI | Padre Marcos | 3,09 | 8,61 |
| 2210300 | PI | São Julião | 2,87 | 8,35 |
| 2614006 | PE | Serrita | 2,68 | 41,22 |
| 2310605 | CE | Penaforte | 1,97 | 2,97 |
| 2202554 | PI | Caridade do Piauí | 1,64 | 8,20 |
| 2304301 | CE | Farias Brito | 0,41 | 2,16 |

**Cedro é o de PE (2604304), não o do CE (2303808)** — confirmado pela
derivação, sem depender de join por nome.

## 4. Comparação contra as listas em circulação

| lista | N | CE | PE | PI | origem |
|---|---:|---:|---:|---:|---|
| **derivada (esta)** | **36** | **18** | **8** | **10** | interseção ICMBio × IBGE |
| WikiAves | 36 | — | — | — | secundária |
| briefing interno | 33 | 15 | 11 | 7 | premissa não verificada |
| busca web | 38 | 15 | 12 | 11 | secundária |
| legado do repo (`cariri_ce_legacy`) | 29 | 29 | 0 | 0 | exclusão manual, não espacial |

O total derivado coincide com o WikiAves (36), mas a distribuição por UF difere
de **todas** as listas em circulação.

## 5. Municípios que explicam cada divergência

### 5.1 vs. briefing interno (18 PE/PI alegados)

Coincidência notável: o briefing também soma **18 municípios de PE+PI**, e a
derivação também dá 18 — mas **a composição é diferente**, 5 entram e 5 saem.

**No briefing, mas sem interseção com a APA (5):**

| geocódigo | UF | município |
|---:|---|---|
| 2207801 | PI | Paulistana |
| 2208205 | PI | Pio IX |
| 2606309 | PE | Granito |
| 2609907 | PE | Ouricuri |
| 2612455 | PE | Santa Cruz |

**Na derivação, ausentes do briefing (5):**

| geocódigo | UF | município | % na APA |
|---:|---|---|---:|
| 2205953 | PI | **Marcolândia** | **94,51** |
| 2200277 | PI | Alegrete do Piauí | 27,89 |
| 2204154 | PI | Francisco Macedo | 21,68 |
| 2210300 | PI | São Julião | 2,87 |
| 2202554 | PI | Caridade do Piauí | 1,64 |

Marcolândia é o caso mais forte: **94,51% do município está dentro da APA** e
ele não constava do briefing. Isso, sozinho, invalida a lista do briefing como
definição de escopo.

### 5.2 vs. legado `cariri_ce_legacy` (29, só CE)

**No legado, mas sem interseção com a APA (12):** Antonina do Norte, Aurora,
Baixio, Barro, Caririaçu, Ipaumirim, **Juazeiro do Norte**, Lavras da
Mangabeira, Mauriti, Milagres, Tarrafas, Umari.

Juazeiro do Norte sair foi **derivado independentemente**, e confirma a
correção manual que já havia sido levantada: é Cariri, não é APA.

**Na derivação, ausentes do legado (19):** os 18 de PE/PI mais Potengi/CE
(80,95% dentro da APA — o legado, sendo CE-only por construção manual, ainda
assim o omitia).

Ou seja: o legado erra nas duas direções. Não é um subconjunto nem um
superconjunto da APA — é outro recorte.

## 6. Proveniência

| item | valor |
|---|---|
| polígono da APA | camada oficial `ICMBio:limiteucsfederais_a` |
| serviço | `https://geoservicos.inde.gov.br/geoserver/wfs` (INDE — Infraestrutura Nacional de Dados Espaciais) |
| filtro | `nomeuc ILIKE '%ARARIPE%'`, selecionando a UC de categoria "Proteção Ambiental" |
| UC excluída pelo filtro | FLONA Araripe-Apodi (o próprio decreto a exclui da APA) |
| CRS de origem | EPSG:4674 (SIRGAS 2000) |
| CRS de medição de área | Albers equivalente América do Sul (`+proj=aea +lat_1=-5 +lat_2=-42 +lat_0=-32 +lon_0=-60 +ellps=GRS80`) |
| malha municipal | API oficial IBGE v3 `/malhas/estados/{23,26,22}?intrarregiao=municipio&qualidade=maxima` |
| regra de pertencimento | `area_intersect_apa_km2 > 0` |
| geometrias reparadas | registradas em `cache/apa33_scope/derivation_meta.json` |
| hashes | SHA-256 de cada arquivo baixado, em `derivation_meta.json` e no CSV |

**Área nunca foi medida em graus.** Medir em EPSG:4674 daria número
fisicamente sem sentido; o próprio ICMBio calcula em Albers (campo
`areahaalb`).

### Validação independente da geometria

```text
soma das interseções municipais : 10.173,6  km²
área oficial declarada (ICMBio) :  1.017.361,601 ha = 10.173,616 km²
```

Bate em 4 algarismos significativos. Isso prova que os 36 municípios
**ladrilham a APA inteira** — não falta pedaço nem há dupla contagem. É a
checagem mais forte disponível de que a interseção está correta e completa.

## 7. Sensibilidade ao limiar (NÃO aplicada — registro para o artigo)

A regra adotada é `> 0`. Se um limiar de área fosse exigido:

| limiar | N | CE | PE | PI |
|---|---:|---:|---:|---:|
| > 0% (adotado) | 36 | 18 | 8 | 10 |
| > 1% | 35 | 17 | 8 | 10 |
| > 5% | 29 | 16 | 6 | 7 |
| > 10% | 26 | 13 | 6 | 7 |
| > 20% | 24 | 13 | 5 | 6 |

Isto explica mecanicamente por que as listas em circulação divergem: cada uma
corresponde, aproximadamente, a um limiar implícito diferente sobre o mesmo
polígono. Seis municípios têm menos de 4% de área na APA (Cedro/PE 3,60;
Padre Marcos 3,09; São Julião 2,87; Serrita 2,68; Penaforte 1,97; Caridade do
Piauí 1,64; Farias Brito 0,41) e são os que mais mudam de lista para lista.

Nenhuma interseção caiu na faixa de "poeira" numérica (< 1e-6 km²); a menor é
Farias Brito com 2,16 km², que é overlap real, não ruído topológico.

## 8. Limitações registradas

1. **O limite geoespacial atual do ICMBio não coincide com o memorial
   descritivo do decreto de 1997.** A literatura documenta isso
   explicitamente. Esta derivação usa o **limite geoespacial publicado pelo
   ICMBio** como definição operacional versionada do estudo — que é o objeto
   com geometria auditável — e não o memorial de 1997, que precisaria ser
   redigitalizado a partir de cartas 1:100.000. Registrado como limitação,
   não como bloqueio (decisão explícita do usuário).
2. A malha municipal do IBGE é a atual; a divisão municipal mudou desde 1997.
   Municípios emancipados depois do decreto (ex.: Moreilândia/PE) entram pela
   geometria atual, o que é o comportamento desejado para prever hoje.
3. `qualidade=maxima` na API do IBGE dá a malha mais detalhada disponível;
   uma malha mais generalizada mudaria marginalmente as áreas de interseção
   dos municípios de sliver, não a composição dos majoritários.

## 9. O que isso significa para o artigo

Não escrever:

> ~~"os 33 municípios definidos pelo decreto federal da APA"~~

O decreto não define lista nenhuma (ver
`outputs/apa33/audit/source_research_findings.md`, Art. 3º = memorial
descritivo). Escrever:

> "O escopo municipal foi derivado pela interseção espacial entre o limite
> geoespacial da APA Chapada do Araripe publicado pelo ICMBio e a malha
> municipal do IBGE, incluindo todo município com área de interseção maior
> que zero, resultando em 36 municípios (CE 18, PE 8, PI 10). A soma das
> áreas de interseção (10.173,6 km²) reproduz a área oficial declarada da
> unidade (10.173,6 km²)."
