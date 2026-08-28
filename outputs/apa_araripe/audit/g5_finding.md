# G5 conformal APA — FAIL, e por quê

Data: 2026-08-14
Código: `src/experiments/g5_conformal_apa_araripe.py`
Artefatos: `outputs/apa_araripe/g5/`, `outputs/apa_araripe/gates/G5_conformal.json`

## Resultado

```text
status : FAIL
```

Nenhuma configuração testada entregou cobertura empírica dentro de
`[0,90; 0,98]` na janela de holdout (2023-2024).

## Procedência da calibração (SDD 21 cumprido)

Zero reaproveitamento do Ceará. Todo resíduo vem de
`outputs/apa_araripe/exp10/predictions_2015_2024.csv`, que é o backtest do
escopo APA. O hash do arquivo de previsões está registrado no gate.

## O que foi tentado

Duas famílias de método competiram na **janela de validação** (2020-2022),
com avaliação final em janela **posterior e disjunta** (2023-2024):

| método | α | validação | pior UF (val.) | largura | passou guarda |
|---|---:|---:|---:|---:|:--:|
| season_only | 0,05 | 0,9437 | 0,8889 | 4,66 | não |
| season_only | 0,04 | 0,9599 | 0,9167 | 5,15 | sim |
| season_only | 0,03 | 0,9660 | 0,9201 | 5,68 | sim |
| season_only | 0,02 | 0,9722 | 0,9340 | 6,81 | sim |
| mondrian (estação × volume) | 0,05 | 0,9228 | 0,9151 | **4,35** | sim |
| mondrian | 0,04 | 0,9375 | 0,9321 | 4,67 | sim |
| mondrian | 0,03 | 0,9537 | 0,9479 | 5,12 | sim |
| mondrian | 0,02 | 0,9753 | 0,9653 | 5,76 | sim |

A regra de seleção vigente — **banda mais estreita entre as aprovadas** —
escolheu `mondrian, α=0,05`.

## O que aconteceu no holdout

```text
validação  2020-2022 : 0,9228
holdout    2023-2024 : 0,8762
```

Cobertura por fatia no holdout:

| fatia | cobertura |
|---|---:|
| geral | 0,8762 |
| seca | 0,8667 |
| crítico out-nov | 0,7917 |
| CE | 0,8819 |
| PE | 0,8490 |
| PI | 0,8875 |
| volume baixo | 0,9097 |
| volume médio | 0,8854 |
| volume alto | 0,8333 |

## Diagnóstico

**1. A primeira tentativa mascarava o problema.** O método `season_only`
reportou 0,8958 geral, mas com dispersão enorme entre estratos: volume baixo
0,9931 (supercobertura desperdiçada) e volume alto 0,7500 (subcobertura
grave). O agregado só parecia razoável porque os municípios pequenos —
numerosos e fáceis — inflavam a média. PE ficava em 0,7969.

Causa: banda única por estação agrupa resíduos de escalas incompatíveis. No
escopo APA, Bodocó/PE acumula 2.397 focos enquanto vizinhos ficam perto de
zero. Uma banda serve mal os dois extremos. No escopo CE-only isso era menos
visível porque os municípios eram mais homogêneos.

**2. O Mondrian corrigiu a dispersão, e expôs a cobertura real.** Estratificar
por (estação × tercil de volume) aproximou os estratos (volume alto
0,75 → 0,83; volume baixo 0,99 → 0,91), mas a cobertura geral caiu para
0,8762 — porque deixou de haver supercobertura dos pequenos compensando o
déficit dos grandes. **A cobertura verdadeira é ~0,88 em toda parte, com
nominal 0,95.**

**3. A causa raiz é não-estacionariedade, não estratificação.** Calibrar em
2015-2022 para prever 2023-2024 assume permutabilidade dos resíduos ao longo
do tempo. O regime de fogo mudou; a distribuição de calibração não é a
distribuição de teste. Nenhuma estratificação espacial conserta isso.

**4. A regra de seleção é frágil por construção.** "Banda mais estreita entre
as aprovadas" escolhe deliberadamente a configuração com **margem zero** sobre
o piso — a menos robusta a qualquer deslocamento. Para uma garantia de
cobertura, isso é a escolha errada de critério.

## Por que NÃO troquei a regra agora

A tabela sugere que uma regra conservadora (ex.: `mondrian, α=0,02`, validação
0,9753 e pior UF 0,9653) teria margem suficiente para provavelmente sobreviver
ao shift.

Mas **o holdout já foi observado**. Trocar o critério de seleção depois de ver
2023-2024 e reexecutar até passar é seleção em cima do holdout — exatamente o
que o SDD §17 proíbe e o que o §52 pergunta no red-team ("a seleção usou
holdout?"). Um IC95 obtido assim não seria um IC95 honesto.

O gate fica **FAIL** e a decisão de critério fica registrada como pendência
explícita, para ser tomada com o holdout fechado.

## Opções para retomar (nenhuma escolhida unilateralmente)

1. **Fixar critério conservador a priori e reavaliar em holdout novo.** Definir
   a regra (ex.: maximizar margem sobre o piso, ou menor α que não estoure
   `IC_MAX`), congelá-la, e avaliar em 2025+ — que hoje está reservado para
   scoring/realidade e nunca foi usado em seleção. Custo: consome a reserva.
2. **Reconhecer o gate como não atingido nesta iteração** e publicar o modelo
   com previsão pontual, declarando explicitamente que os intervalos ainda não
   satisfazem o contrato de cobertura. É a opção mais conservadora e não gasta
   a reserva de 2025+.
3. **Atacar a não-estacionariedade no método**, ex.: janela de calibração
   deslizante em vez de expansiva, ou conformal adaptativo com correção
   online de cobertura. Isso muda o estimador, não o gate, e precisaria de sua
   própria validação antes de tocar no holdout.

## O que este resultado NÃO invalida

O EXP-10 permanece intacto: `all_wape 0,7850 → 0,7074`, CI95 do ΔWAPE
`[-0,1315; -0,0307]`, `PROMOTE`. Cobertura de intervalo é um contrato
separado da acurácia pontual. O modelo prevê melhor que o baseline; o que
ainda não está demonstrado é que os intervalos declarados cobrem na taxa
nominal.

---

## Adendo (2026-08-14) — duas correções de higiene e o que elas mudaram

Revisão externa apontou duas sujeiras no código deste G5. Ambas corrigidas.
**O `FAIL` permanece** — nenhuma delas contaminava a construção dos
intervalos.

### 1. Estratificação por volume era ex-post

`coverage_report()` recalculava os tercis `low/mid/high` usando o
`fire_count` do **próprio conjunto avaliado**. A construção dos intervalos já
era causal (tercis vindos só da janela de calibração), então o `FAIL` não é
afetado — mas os números *reportados* por volume descreviam grupos definidos
pelo resultado que se queria medir.

Corrigido para usar o estrato causal atribuído em `run_alpha()`. O efeito não
foi cosmético:

| estrato | ex-post (antes) | causal (agora) |
|---|---:|---:|
| volume baixo | 0,9097 | 0,8933 |
| volume médio | 0,8854 | 0,8804 |
| volume alto | 0,8333 | 0,8542 |

A estratificação ex-post **exagerava o gradiente por volume**. Na leitura
causal a subcobertura é bem mais uniforme (0,85–0,89). Consequência para o
diagnóstico: a hipótese "o problema são os municípios de alto volume" era
parcialmente artefato de estratificar o holdout pelo próprio desfecho. O
déficit é sistêmico, não concentrado numa faixa.

Isso **reforça** a leitura de deslocamento temporal como mecanismo dominante,
em vez de heterocedasticidade pura entre escalas.

### 2. Proveniência por intervalo era insuficiente

`n_calib` registrava o tamanho global da calibração, não o número de resíduos
efetivamente usados no quantil daquele estrato. Um intervalo que caiu de
`high_dry` para `dry` por falta de amostra ficava indistinguível de um
calibrado no estrato certo.

Cada intervalo agora carrega: `stratum`, `n_calib_effective`,
`fallback_level`, `band`, `alpha_effective`, `calibration_window_start` e
`calibration_window_end`.

### 3. Correção de linguagem

"A causa raiz é não-estacionariedade" era afirmação forte demais para a
evidência disponível — pode haver contribuição de heterocedasticidade, mudança
de regime ou má especificação do modelo. A formulação sustentável, adotada
aqui e no artigo, é:

> **evidência de deslocamento temporal da distribuição dos erros**

