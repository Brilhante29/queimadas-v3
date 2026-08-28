# Resposta ao Hugo — quais bases precisam ser buscadas

Data: 2026-08-14
Estado: verificado contra o código e os dados do repositório, não contra memória.

## Resumo em uma linha

**Não precisa buscar nada.** Os dados que faltavam já foram encontrados,
baixados e integrados. As outras bases não são necessárias para o modelo atual.

---

## 1. O problema que você levantou está resolvido

Você apontou certo: a "Chapada" que existia era só Ceará, faltavam PE e PI.

Isso mudou. O escopo agora tem **36 municípios nos três estados**:

| UF | municípios |
|---|---:|
| Ceará | 18 |
| Piauí | 10 |
| Pernambuco | 8 |
| **total** | **36** |

E não foi lista copiada de lugar nenhum. Foi **derivada** cruzando o limite
geoespacial oficial da APA (publicado pelo ICMBio) com a malha municipal do
IBGE, incluindo todo município com área de interseção maior que zero.

Detalhe que vale saber: **o decreto federal da APA não lista municípios**. Ele
define a unidade por curva de nível e coordenadas. Por isso as listas que
circulam por aí divergem (33, 36, 38) — cada uma é uma interpretação diferente
do mesmo polígono. A nossa é reprodutível: roda o script, sai o mesmo número,
com hash da geometria registrado.

## 2. O histórico do INPE: já está no repositório

Era o único dado realmente necessário, e ele é **público**. Estava num endereço
diferente do que o projeto usava.

| endpoint | cobertura |
|---|---|
| o que o projeto usava (`mensal/Brasil`) | só 2024 em diante |
| o correto (`anual/EstadosBr_sat_ref`) | **2003 a 2024**, CE, PE e PI |

Já baixado e processado: **66 arquivos**, resultando em **156.552 linhas**
município-mês (593 municípios × 264 meses), com hash de cada arquivo de origem
registrado para reprodução.

Dentro da APA: **16.102 focos** entre 2003 e 2024, e **os 36 municípios têm
histórico completo** — nenhum ficou de fora por falta de dado.

## 3. As outras bases: não precisa pegar nada agora

ERA5, FIRMS, população IBGE, PAM, INMET, ENSO, NDVI, MapBiomas.

**Nenhuma delas é necessária para o modelo atual.** Todas já foram testadas em
experimentos anteriores e **nenhuma superou o modelo simples** no protocolo de
validação. Estão registradas como resultados negativos, não como pendências.

O modelo campeão usa só o histórico do INPE:

```text
previsão = climatologia do município naquele mês
           × fator de intensidade regional dos últimos 12 meses
```

Só faria sentido buscar essas bases se a gente decidir **repetir toda a bateria
de experimentos** na Chapada completa — o que é uma segunda etapa, opcional, e
não bloqueia nada agora.

## 4. O que já foi feito

- escopo derivado dos 36 municípios, com geometria versionada;
- histórico INPE 2003-2024 dos três estados, ingerido e auditado;
- modelo retreinado **no escopo real da APA** (não mais só Ceará);
- validação temporal com 120 cortes mensais, treino sempre só com o passado;
- comparação contra o baseline, com intervalo de confiança por bootstrap.

Resultado do retreino — o modelo continua melhor que o baseline, e melhora
**nos três estados**:

| recorte | baseline | modelo | ganho |
|---|---:|---:|---:|
| geral | 0,7850 | 0,7074 | −9,9% |
| pico out-nov | 0,6710 | 0,5761 | −14,1% |
| Ceará | 0,8100 | 0,7457 | −7,9% |
| Pernambuco | 0,7053 | 0,6226 | −11,7% |
| Piauí | 0,9333 | 0,8301 | −11,1% |

(WAPE — quanto menor, melhor.)

Um dado que muda a leitura do problema: **os três municípios com mais focos da
APA são todos de Pernambuco** — Bodocó (2.397), Araripina (1.253) e Exu
(1.158). O modelo antigo, treinado só no Ceará, nunca tinha visto nenhum deles.

## 5. O que ainda falta (e é trabalho nosso, não seu)

1. **Calibração dos intervalos de incerteza.** O teste de cobertura ainda não
   passou: os intervalos declarados como 95% estão cobrindo ~88% na prática.
   Já identificamos a causa provável (deslocamento temporal na distribuição
   dos erros) e já temos um método corrigido congelado, aguardando um teste
   final limpo. **Enquanto isso não passar, o sistema entrega previsão pontual
   e devolve o intervalo como "não validado"** — não vamos publicar barra de
   erro que não se sustenta.
2. Revisão adversarial independente dos resultados.
3. Atualização do artigo, README e documentação de dados.
4. Ligar o back-end/front-end ao escopo novo. Detalhe importante: o sistema
   hoje conhece 29 cidades do Cariri numa lista fixa. Em vez de trocar por uma
   lista fixa de 36, o back vai **ler os municípios direto do artefato do
   modelo** — senão repetimos o mesmo problema daqui a um ano.

## 6. Resposta direta às suas perguntas

> "quais bases precisa pegar coisas delas?"

Nenhuma. O INPE já está integrado; o resto não entra no modelo atual.

> "e depois disso, o que fazer?"

Do seu lado, nada bloqueante. O que falta é calibração de incerteza, revisão e
documentação — trabalho interno.

Se quiser ajudar em algo de alto valor, o mais útil não é dado: é **validação
de campo**. Saber quais desses 36 municípios têm brigada ativa, qual a
capacidade real de resposta e como a previsão mensal seria usada na prática
muda mais o valor do sistema do que qualquer base adicional.
