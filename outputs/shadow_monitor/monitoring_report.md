# FireCast - relatorio de monitoramento shadow

Gerado em 2026-07-11T14:06:30.060447+00:00.

- Ultimo mes observado no snapshot alvo: **2026-07**
- Alvo usado no relatorio: `data\snapshots\inpe_monthly_public_v3\events_target_region.csv` filtrado em `AQUA_M-T`
- Versao de scoring: `v2_event_absence_is_zero`
- Idade do dado observado: **0 meses**
- Registros shadow: 5 (4 live, 1 drill)
- Meses aguardando observado: ['2026-08']

## Desempenho atrasado

| Mes | Modo | Alvo | N | Observado | Predito | WAPE | MAE | Alertas |
|---|---|---|---:|---:|---:|---:|---:|---|
| 2025-03 | backfill_drill | AQUA_M-T | 31 | 6.00 | 3.42 | 1.1266 | 0.22 | WAPE 1.1266 excede referencia 0.6430 + 0.05 |
| 2026-05 | live_shadow | AQUA_M-T | 31 | 1.00 | 3.10 | 3.9757 | 0.13 | WAPE 3.9757 excede referencia 0.6430 + 0.05 |
| 2026-06 | live_shadow | AQUA_M-T | 31 | 10.00 | 6.27 | 1.1330 | 0.37 | WAPE 1.1330 excede referencia 0.6430 + 0.05 |
| 2026-07 | live_shadow | AQUA_M-T | 31 | 9.00 | 15.30 | 2.2805 | 0.66 | WAPE 2.2805 excede referencia 0.6430 + 0.05 |

## Rollback

- Artefato champion versionado por sha256 no shadow log; para rollback, apontar
  `--model-path` da API para o artefato anterior e registrar a troca no ledger.
- Status de release externo permanece controlado por G0-G7; este relatorio nao
  autoriza deploy.
