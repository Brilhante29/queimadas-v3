# FireCast Champion Model Card -- climatology_regional_intensity12

Status: **APROVADO PARA PRODUCAO INTERNA (contrato G3 v2, decisao humana 2026-07-11);
release EXTERNO pendente de janela de shadow vivo**.

## Modelo

Climatologia municipal por mes multiplicada por um fator regional de intensidade
dos ultimos 12 meses observados. A mudanca foi validada no EXP-2026-07-09-10.

Formula:

```text
pred = climatologia_municipio_mes * clip((observado_12m + 100) / (esperado_12m + 100), 0.5, 2.0)
```

O mes alvo nunca entra no fator. Para previsoes alem do historico de alvo
empacotado, o serving usa o ultimo fator regional disponivel no treino e mantem o
status de release candidate.

## Metricas validadas

- Protocolo primario: walk-forward estendido 120 cortes mensais 2015-2024, h=1, 2025+ congelado.
- WAPE estendido: 0.6430 vs baseline 0.7906.
- WAPE out-nov estendido: 0.5419 vs baseline 0.6923.
- Janela 2023-2024: WAPE 0.5501; out-nov 0.4993.
- Erro absoluto empirico p50/p90/p95: 0.24 / 3.92 / 6.99 focos.

## Decisao experimental

EXP-10 superou o champion anterior no protocolo estendido: WAPE 0,7906 -> 0,6430,
out-nov 0,6923 -> 0,5419, 85/120 cortes vencidos, bootstrap delta WAPE CI95
[-0,2195, -0,0852], P(candidato melhor)=1,000. Decisao: PROMOTE para champion
interno.

## Gates (2026-07-11)

- G0-G2, G4, G6: PASS (ver PRODUCTION_READINESS.md).
- G3: PASS no contrato v2 (EXP-26: WAPE totais mensais CE 0,2245 <= 0,25; total
  sazonal CE 0,1794 <= 0,20; Chapada sazonal 0,3723 <= 0,40; Recall@10
  0,775/0,90; zero indevido 0,0). O contrato v1 (WAPE municipal-mes <= 0,20/0,25)
  foi demonstrado praticamente inatingivel pela auditoria EXP-25 (piso NB
  0,38/0,53; desacordo INPE-FIRMS 0,41/0,43) e esta registrado como historico.
- G5: PASS com IC95 guardado (cobertura 0,9170 geral / 0,9000 seca / 0,9274 chuva).
- G7: PASS para escopo INTERNO (aprovacao humana registrada em
  OPS-G7-APPROVAL; shadow mensal via src/production/shadow_monitor.py).
  Release EXTERNO pendente de janela de shadow vivo.

## Limitacoes

- WAPE municipal-mes (~0,50 no gate) esta na zona de ruido irredutivel do alvo
  (EXP-25); o contrato v2 nao exige precisao municipal de magnitude, exige
  ranking (Recall@10) e magnitude agregada por escopo.
- O multiplicador regional melhora anos altos/baixos, mas pode piorar municipios
  de baixo volume em avaliacao estendida (2/31 flagados fora da janela de gate).
- Alvo INPE atualizado ate 2026-04; shadow vivo pontua conforme novos meses chegam.
