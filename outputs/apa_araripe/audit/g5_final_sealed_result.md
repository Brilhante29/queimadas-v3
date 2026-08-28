# G5 final — teste selado em 2025, execução única

Data: 2026-08-14
Código: `src/experiments/g5_final_sealed_2025.py`
Gate: `outputs/apa_araripe/gates/G5_final_sealed_2025.json`

## Veredito

```text
status : FAIL
```

**Uma única violação**, e ela é de *teto*, não de piso.

## Cobertura observada em 2025

| fatia | cobertura | dentro de [0,90; 0,98]? |
|---|---:|:--:|
| **geral** | **0,9537** | sim |
| seca (ago-dez) | 0,9500 | sim |
| úmida | 0,9563 | sim |
| CE | 0,9444 | sim |
| **PE** | **0,9896** | **não — acima do teto** |
| PI | 0,9417 | sim |
| volume baixo | 0,9375 | sim |
| volume médio | 0,9517 | sim |
| volume alto | 0,9720 | sim |
| crítico out-nov | 0,8889 | (não é critério do gate) |

Largura média do intervalo: 10,11 focos.

## O que mudou em relação ao G5 anterior

O método corrigido **resolveu o problema que derrubou a versão anterior**:

| | G5 anterior (2023-24) | G5 final (2025) |
|---|---:|---:|
| geral | 0,8762 | **0,9537** |
| CE | 0,8819 | 0,9444 |
| PE | 0,8490 | 0,9896 |
| PI | 0,8875 | 0,9417 |

A subcobertura sistemática acabou. `rolling_mondrian_48` com janela deslizante
de 48 meses entregou cobertura dentro da faixa em cinco das seis fatias
avaliadas e no agregado.

**O que sobrou é o oposto do problema original:** em Pernambuco os intervalos
ficaram *conservadores demais* (0,9896 contra teto de 0,98). O gate é
bilateral de propósito — subcobertura é insegura, supercobertura é inútil —
e PE estourou o lado da inutilidade por 0,96 ponto percentual.

## Por que continua FAIL

Regra acordada antes da execução:

> "Se 2025 reprovar, G5 permanece FAIL. Não haverá terceira tentativa usando
> 2025 para tuning."

O número foi observado. Reajustar α ou janela agora para acomodar PE seria
ajuste no holdout selado — precisamente o que o congelamento existia para
impedir. **G5 fica FAIL e não há nova tentativa nesta rodada.**

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

Fica documentado, sem execução, para quando houver holdout novo (2026):

1. O mecanismo de deslocamento temporal foi tratado com sucesso pela janela
   deslizante — essa parte da hipótese se confirmou.
2. A sobra é heterogeneidade **entre estados**: PE precisa de banda mais
   estreita que CE/PI. O candidato natural é estratificar também por UF
   (`estação × volume × UF`), que hoje não estava na família congelada.
3. Essa família ampliada teria de ser desenvolvida e congelada usando somente
   dados até 2025, e avaliada em 2026 — nunca reavaliada em 2025.
