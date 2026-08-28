# G5 final — teste selado em 2025, execução única

Data da execução: 2026-08-14
Revisado em 2026-08-28 após auditoria independente (ver "Correções" no fim).
Código: `src/experiments/g5_final_sealed_2025.py`
Gate: `outputs/apa_araripe/gates/G5_final_sealed_2025.json`

## Veredito

```text
status : FAIL
```

O gate registra **uma** falha — cobertura de PE acima do teto. Mas a evidência
empírica tem **dois** valores fora de [0,90; 0,98], um acima e um abaixo, e o
que está abaixo é a fatia operacionalmente mais importante. Ver a próxima
seção.

## Cobertura observada em 2025

| fatia | cobertura | dentro de [0,90; 0,98]? | é critério do gate? |
|---|---:|:--:|:--:|
| **geral** | **0,9537** | sim | sim |
| seca (ago-dez) | 0,9500 | sim | não |
| úmida | 0,9563 | sim | não |
| CE | 0,9444 | sim | sim |
| **PE** | **0,9896** | **não — acima do teto** | sim |
| PI | 0,9417 | sim | sim |
| volume baixo | 0,9375 | sim | não |
| volume médio | 0,9517 | sim | não |
| volume alto | 0,9720 | sim | não |
| **crítico out-nov** | **0,8889** | **não — abaixo do piso** | **não** |

Largura média do intervalo: 10,11 focos.

**A fatia crítica out-nov está abaixo do mesmo piso 0,90 que o gate aplica em
toda parte, e não conta como falha porque o gate só avalia `overall` e as três
UFs** (`g5_final_sealed_2025.py`, linhas 299-307). Outubro e novembro são o
pico da estação seca — a janela em que o intervalo teria uso operacional real.
Descrever o resultado como "uma única violação, e ela é de teto" seria falso: a
violação que mais importa é de **piso**, e o gate simplesmente não olha para
ela.

Qualquer gate futuro precisa incluir a fatia crítica como critério. Incluí-la
**agora**, depois de ver o número, seria mudar o critério em cima do holdout.

## Duas falhas de especificação do próprio gate

Ambas medidas, não opinadas. Artefatos:
`outputs/public_results_summary.json` (bloco `known_limitations`).

### 1. O teto do gate coincide com o nível nominal

Com `alpha = 0,02` o intervalo é nominalmente 0,98 e o teto aceitável também é
0,98. Um método perfeitamente calibrado estoura esse teto por puro acaso
amostral com probabilidade:

| UF | n | cobertura | erros observados | erros mínimos p/ passar o teto | P(método perfeito reprova) |
|---|---:|---:|---:|---:|---:|
| CE | 216 | 0,9444 | 12 | 5 | 0,5660 |
| PE | 96 | 0,9896 | 1 | 2 | 0,4255 |
| PI | 120 | 0,9417 | 7 | 3 | 0,5687 |

**PE reprovou com 1 erro em 96 e precisaria de pelo menos 2 para passar.** O
gate penalizou acerto. A reprovação de PE é evidência fraca contra o método e
evidência forte contra o critério.

### 2. Os intervalos são unilaterais na prática

420 dos 432 intervalos de 2025 (**97,2%**) têm `interval_low <= 0` — limite que
quase nunca pode ser violado. Nas 12 linhas com piso testável a cobertura cai
para **0,5833**. Das violações, 17 são por cima e 3 por baixo.

A cobertura global de 0,9537 mede sobretudo o teto do intervalo, não o
intervalo inteiro.

## O que mudou em relação ao G5 anterior

| | G5 anterior | G5 final |
|---|---:|---:|
| método | `expanding_mondrian` | `rolling_mondrian_48` |
| α (nominal) | 0,05 (0,95) | 0,02 (0,98) |
| janela de avaliação | 2023-2024 | 2025 |
| cobertura geral | 0,8762 | 0,9537 |

**Três coisas mudaram ao mesmo tempo, então a comparação direta 0,8762 contra
0,9537 não atribui causa.** Alargar o nominal em 3 pontos aumenta a cobertura
por construção.

A decomposição está em
`outputs/apa_araripe/audit/g5_improvement_decomposition.json`, feita sobre os 4
folds de desenvolvimento (2021-2024), **sem tocar em 2025**:

| configuração | cobertura média entre folds |
|---|---:|
| `expanding_mondrian` @ α=0,05 | 0,8964 |
| `expanding_mondrian` @ α=0,02 | 0,9537 (só α: **+0,0573**) |
| `rolling_mondrian_48` @ α=0,05 | 0,9149 (só método: **+0,0185**) |
| `rolling_mondrian_48` @ α=0,02 | 0,9635 (total: +0,0671) |

**α responde por 85% da melhora; a janela deslizante, por 28%** (as frações
somam mais de 100% porque o termo de interação é −0,0087: α e método empurram a
cobertura contra o mesmo teto).

Atribuir a correção à janela deslizante — como a versão anterior deste
documento fazia — não se sustenta. O efeito dominante foi alargar o nível
nominal.

O efeito do **ano de avaliação** (2023-2024 contra 2025) não é separável:
estimá-lo exigiria rodar outras configurações sobre o holdout selado, que é
exatamente o que o contrato de execução única proíbe. Fica declarado como
confundimento residual, não estimado.

## Por que continua FAIL

Regra acordada antes da execução:

> "Se 2025 reprovar, G5 permanece FAIL. Não haverá terceira tentativa usando
> 2025 para tuning."

O número foi observado. Reajustar α, janela ou **o próprio critério do gate**
agora seria ajuste no holdout selado — precisamente o que o congelamento
existia para impedir. Isso vale inclusive para as duas falhas de especificação
descritas acima: elas são reais, e ainda assim não convertem o FAIL em PASS
nesta rodada.

**O registro honesto é duplo: o método não foi validado, e o gate, como
especificado, também não serve.**

O serving permanece devolvendo `interval: null` e
`uncertainty_status: "not_validated"`, lido do gate.

## Acurácia pontual em 2025 (registro, não é critério do G5)

Confirmação fora da amostra, em dado que o modelo nunca viu:

| métrica | baseline | champion |
|---|---:|---:|
| WAPE 2025 | 0,6485 | **0,5611** |

Ganho de **−13,5%**, maior que os −9,9% do período de desenvolvimento.

```text
observado 2025 : 1.441 focos
previsto  2025 : 1.236 focos
MAE municipal  : 1,87
```

O EXP-10 se sustenta em dado novo. A previsão pontual é robusta; o que não
passou é o contrato de cobertura dos intervalos.

## Caminho registrado para a próxima rodada (não executado)

Para quando houver holdout novo (2026). **2025 está queimado para esse fim.**

1. **Reescrever o gate antes de qualquer coisa.** O critério atual tem teto
   colado no nominal e ignora a fatia crítica. Um gate novo precisa: teto com
   folga explícita em relação ao nominal; a fatia out-nov como critério; e um
   critério de cobertura **por lado**, já que a cobertura agregada atual é
   quase toda do lado superior.
2. O ganho da janela deslizante é real mas pequeno (+0,0185 na cobertura média
   entre folds). Não se pode dizer que "o deslocamento temporal foi tratado com
   sucesso" — essa parte da hipótese **não** foi isolada pelo experimento
   realizado.
3. A heterogeneidade entre estados continua candidata: estratificar por
   `estação × volume × UF`, que não estava na família congelada.
4. Qualquer família ampliada precisa ser desenvolvida e congelada com dados até
   2025 e avaliada em 2026 — nunca reavaliada em 2025.

## Correções aplicadas em 2026-08-28

Auditoria independente (`red_team_report.md`) refutou três afirmações da
versão anterior deste documento. Registradas aqui em vez de apagadas:

| afirmação anterior | situação |
|---|---|
| "Uma única violação, e ela é de teto, não de piso" | **falsa** — out-nov 0,8889 está abaixo do piso; o gate não a avalia |
| "O método corrigido resolveu o problema" / "a subcobertura sistemática acabou" | **não sustentada** — α, método e ano mudaram juntos; α responde por 85% |
| "O mecanismo de deslocamento temporal foi tratado com sucesso pela janela deslizante" | **não sustentada** — efeito do método isolado é +0,0185, contra +0,0573 de α |
