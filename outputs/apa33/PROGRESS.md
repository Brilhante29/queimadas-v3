# FireCast APA-33 — PROGRESS

Branch: `feat/firecast-apa33`
SDD: reconstrução do escopo Chapada do Araripe + ingestão histórica + retreino + validação
Regra: atualizar com **evidência**, não narrativa (§61).

## Estado por fase

```text
[PASS] PHASE 0   baseline do repo (branch criada, namespaces outputs/apa33/*)
[PASS] PHASE 2   descoberta/verificacao das fontes oficiais
[RUN ] PHASE 1'  escopo APA por intersecao espacial versionada (ICMBio x IBGE)
[RUN ] PHASE 3   ingestor historico INPE CE+PE+PI 2003-2024
[WAIT] PHASE 4   QA e data contracts (G0)
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
