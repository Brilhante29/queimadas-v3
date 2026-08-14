# APA Chapada do Araripe — pesquisa de fonte oficial (PHASE 2)

Data da pesquisa: 2026-08-14
Executor: Claude Code (skill `/official-source-research`, SDD APA-33 §8)
Branch: `feat/firecast-apa33`

## Resumo executivo

Dois achados decisivos, ambos verificados contra fonte primária:

1. **O histórico do INPE é público e baixável.** Não é necessário solicitar dados a
   terceiros. Cobertura 2003–2024 confirmada para CE, PE e PI, no satélite de
   referência.
2. **O decreto federal da APA NÃO enumera municípios.** Ele delimita a APA por
   memorial descritivo geométrico. Toda "lista de N municípios" em circulação é
   uma interpretação derivada do polígono, e as interpretações divergem
   (33 / 36 / 38). A afirmação "os 33 municípios definidos no decreto" não é
   sustentável e não pode entrar no artigo nessa forma.

---

## Achado 1 — fonte histórica INPE (RESOLVE o bloqueio de dados)

### Endpoint errado (o que o repo usa hoje para scoring)

```text
https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/focos_mensal_br_YYYYMM.csv
```

Usado por `src/data/ingest_inpe_monthly_public_v3.py`. Sondagem HEAD mês a mês:

```text
200301 .. 202301  -> HTTP 404
202401            -> HTTP 200  (23.0 MB)
202412            -> HTTP 200  (34.9 MB)
```

Confirma o contrato já declarado no próprio repo: este ingestor é **scoring
recente**, não histórico. Não serve para reconstruir 2003–2024.

### Endpoint correto (arquivo histórico anual, satélite de referência)

```text
https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/
├── AMS_sat_ref/
├── Brasil_sat_ref/        focos_br_ref_2003.zip .. focos_br_ref_2025.zip
├── Brasil_todos_sats/
└── EstadosBr_sat_ref/     CE/ PE/ PI/ (+ 24 outras UFs)
```

`EstadosBr_sat_ref/{UF}/focos_br_{uf}_ref_{ano}.zip` — preferível: menor volume,
já filtrado por UF e por satélite de referência.

Cobertura verificada por listagem de diretório:

| UF | arquivos | anos |
|---|---:|---|
| CE | 22 | 2003–2024 |
| PE | 22 | 2003–2024 |
| PI | 22 | 2003–2024 |

Total necessário: **66 arquivos**, todos pequenos.

### Schema real (download completo verificado)

Arquivo baixado e inspecionado:

```text
url    : .../anual/EstadosBr_sat_ref/PE/focos_br_pe_ref_2003.zip
bytes  : 50231
sha256 : 35291d8a082eeb745d00b69cf25e062ff764fbac477518bcaf2cfde4558b2736
member : focos_br_pe_ref_2003.csv
linhas : 2771 (inclui cabecalho)
```

Cabeçalho:

```text
id_bdq,foco_id,lat,lon,data_pas,pais,estado,municipio,bioma
```

Linha exemplo:

```text
 8093798 ,54662217-...,   -8.838000 ,  -35.170000 ,2003-01-01 16:06:00,Brasil,PERNAMBUCO,SÃO JOSÉ DA COROA GRANDE,Mata Atlântica
```

### Consequências para a ingestão

- **Não há coluna `geocodigo`.** O join obrigatório é
  `normalize(municipio) + estado -> geocodigo IBGE`, exatamente o fallback
  previsto no SDD §4.2. A desambiguação Cedro/CE (2303808) vs Cedro/PE
  (2604304) só é possível porque `estado` existe no arquivo — join por nome
  isolado é proibido e falharia aqui.
- **Não há coluna de satélite.** O recorte `sat_ref` já é o filtro: o arquivo
  inteiro é o satélite de referência. O contrato de sensor deve ser registrado
  como propriedade do arquivo de origem, não derivado linha a linha.
- Valores vêm com espaçamento (` 8093798 `, `   -8.838000 `) — parser precisa
  de `strip`.
- Nome do município vem em CAIXA ALTA e acentuado; a normalização precisa
  tratar acento + caixa.

---

## Achado 2 — o decreto não define lista de municípios (BLOQUEIA §4 como escrito)

### O que a fonte legislativa oficial diz

`DECRETO DE 4 DE AGOSTO DE 1997` (Senado, legis.senado.leg.br/norma/376282),
Art. 3º:

> "A APA Chapada do Araripe apresenta a seguinte delimitação baseada nas cartas
> topográficas de escala de 1:100.000 da SUDENE e da DSG (...) tendo o seguinte
> memorial descrito: inicia no cruzamento da curva de nível de 500 m, com o
> limite interestadual Piauí/Ceará, de coordenadas UTM N=9212700, E=326550 (...)
> segue por essa curva de nível de 500 m, na direção geral leste/sudeste,
> percorrendo uma distância de 1.265.220 m (...)"

O decreto delimita por **curva de nível + coordenadas UTM/geográficas**. Ele
lista os três estados abrangidos (CE, PE, PI) e nomeia cartas topográficas
(Jardim, Bodocó, Campos Sales, Santana do Cariri, Crato, Milagres,
São José do Belmonte, Picos, Juazeiro do Norte) — mas **cartas topográficas não
são municípios do escopo**, e o decreto **não enumera municípios em lugar
nenhum**.

### O que a autarquia gestora publica

Página oficial do ICMBio para a UC
(`gov.br/icmbio/.../apa-da-chapada-do-araripe`) informa:

```text
NOME     : Área de Proteção Ambiental da Chapada do Araripe
BIOMA    : Caatinga
ÁREA     : 1.017.361,601 hectares
DIPLOMA  : Decreto s/n de 04 de agosto de 1997
```

**Não publica lista de municípios.**

### Contagens divergentes encontradas

| Fonte | Total | CE | PE | PI |
|---|---:|---:|---:|---:|
| Premissa do briefing interno | 33 | 15 | 11 | 7 |
| Busca web (secundária) | 38 | 15 | 12 | 11 |
| WikiAves | 36 | — | — | — |
| ICMBio (oficial) | não enumera | — | — | — |
| Decreto (oficial) | não enumera | — | — | — |

WikiAves documenta explicitamente a causa raiz:

> "O perímetro legal disponível na página eletrônica do ICMBio **não coincide**
> com o que é definido pelo decreto de criação, fazendo com que a área e lista
> de municípios integrantes **não seja definitiva**."

### Por que divergem

A APA é um polígono definido por cota altimétrica. Derivar municípios exige
escolher uma **regra de interseção espacial**, e cada regra dá um número
diferente:

- qualquer interseção não-nula com o polígono;
- interseção acima de um limiar de área (ex.: >1%, >5% da área municipal);
- centroide municipal dentro do polígono;
- sede municipal dentro do polígono.

Somado a isso, o polígono usado importa (decreto vs. perímetro publicado pelo
ICMBio, que a própria literatura aponta como não coincidentes), e a malha
municipal mudou desde 1997 (ex.: Moreilândia/PE foi emancipada de Parnamirim
em 1995 mas só instalada depois; nomes e códigos mudam ao longo do tempo).

---

## Impacto no SDD

### §4 (definição do escopo) — precisa mudar

Como escrito, o §4 manda "reconstruir a partir de fonte federal/oficial" uma
lista de 33. A fonte federal oficial não contém essa lista. Cumprir o §4 ao pé
da letra é impossível; cumprir o *espírito* dele (escopo oficial, versionado,
reprodutível, sem invenção) exige derivar a lista por **interseção espacial
reprodutível**, e versionar a regra junto com o resultado.

Caminho tecnicamente correto e disponível:

1. obter o polígono oficial da APA (ICMBio publica geometrias de UC);
2. interseccionar com a malha municipal IBGE (o repo já tem a referência
   IBGE CE/PE/PI, 593 municípios);
3. aplicar uma regra de inclusão **explícita e versionada**;
4. persistir `apa_chapada_araripe.csv` com `geocodigo`, `uf`, `municipio`,
   `area_intersect_km2`, `pct_area_municipal`, `rule`, `polygon_sha256`,
   `source`, `source_retrieved_at`.

Isso transforma "33 municípios do decreto" (não sustentável) em "N municípios
cuja área intersecta o polígono oficial da APA sob a regra R, com geometria
versionada por hash" (auditável, reprodutível, defensável em revisão).

### §44 (texto do artigo) — precisa mudar

A frase-alvo proposta no §44 afirma que o escopo "corresponde ao conjunto dos 33
municípios abrangidos pela APA". Isso não pode ser escrito como fato derivado do
decreto. A redação precisa declarar a regra de derivação e o polígono usado.

### §59 (proibições) — reforçado

"não inventar" e "falhar fechado em ambiguidade" se aplicam diretamente aqui: a
contagem de municípios É a ambiguidade. Fixar 33 sem derivação reprodutível
seria exatamente a invenção que o SDD proíbe.

---

## O que NÃO está bloqueado

A ingestão histórica do INPE **não depende** da resolução do escopo. Os arquivos
são por UF (CE, PE, PI) e o alvo municipal-mês pode ser construído para os 593
municípios da referência IBGE. O escopo APA vira um **filtro aplicado depois**,
barato e re-executável quantas vezes for preciso.

Ordem recomendada, que não trava:

```text
PHASE 3  ingerir CE+PE+PI 2003-2024 -> target municipal-mes (593 municipios)
PHASE 4  QA de cobertura, zero-vs-missing, duplicatas, mapeamento IBGE
   (em paralelo) resolver o poligono oficial + regra de intersecao
PHASE 1' derivar o escopo APA por intersecao, versionado
PHASE 5+ filtrar target pelo escopo e seguir o SDD normalmente
```

---

## Proveniência desta pesquisa

| item | valor |
|---|---|
| INPE anual sat_ref (índice) | https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/ |
| INPE EstadosBr_sat_ref | https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/EstadosBr_sat_ref/ |
| amostra baixada | `.../EstadosBr_sat_ref/PE/focos_br_pe_ref_2003.zip` sha256 `35291d8a082eeb745d00b69cf25e062ff764fbac477518bcaf2cfde4558b2736` (50231 bytes) |
| Decreto 04/08/1997 | https://legis.senado.leg.br/norma/376282/publicacao/15651757 |
| ICMBio UC | https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/unidade-de-conservacao/unidades-de-biomas/caatinga/lista-de-ucs/apa-da-chapada-do-araripe |
| WikiAves (secundária, usada só para documentar a divergência) | https://www.wikiaves.com.br/wiki/areas:apa_chapada_do_araripe:inicio |
| data de recuperação | 2026-08-14 |
