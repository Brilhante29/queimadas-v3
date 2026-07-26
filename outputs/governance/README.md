# FireCast - Governanca (G7)

Atualizado em 2026-07-13.

Documentos exigidos pelo gate G7:

| Documento | Onde | Status |
|---|---|---|
| Model card | `outputs/champion_climatology_regional_intensity12/model_card.md` | OK |
| Data card | `outputs/governance/data_card.md` | OK |
| Changelog tecnico | `outputs/governance/changelog.md` | OK |
| Plano de rollback | `outputs/governance/rollback_plan.md` | OK |
| Uso pretendido e limitacoes | model card + `outputs/model_progress_report.md` + `PRODUCTION_READINESS.md` | OK |
| Shadow/monitoramento vivo | `outputs/shadow_monitor/` | OK para uso interno; alertas externos abertos |
| Containerizacao operacional | `Dockerfile`, `docker-compose.yml`, `docs/CONTAINERIZATION.md` | OK |
| Aprovacao humana para producao interna | ledger `OPS-G7-APPROVAL-2026-07-11` | OK |
| Aprovacao humana para implantacao externa | pendente | PENDENTE, obrigatoria, nao automatizavel |

## Status do gate

**G7 = PASS no escopo interno.** A documentacao, rollback, model/data cards, shadow harness, API fail-closed e containerizacao estao presentes e testados.

**Release externo = BLOQUEADO.** O bloqueio atual nao e falta de documento G7; e a combinacao de alertas no shadow publico AQUA-MT 2026-05..07 e ausencia de autorizacao humana externa especifica.

O estado operacional correto e: `APROVADO PARA PRODUCAO INTERNA_G3V2`, `EXTERNO_PENDENTE_SHADOW_E_AUTORIZACAO`.
