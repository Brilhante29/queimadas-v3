"""Modulo publico do FireCast para contratos de producao, gates e operacao mensal.

Arquivo `src/mlops/monthly_ops.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PUBLIC_TARGET = "data/snapshots/inpe_monthly_public_v3/events_target_region.csv"
DEFAULT_TARGET_SATELLITE = "AQUA_M-T"


@dataclass(frozen=True)
class OperationalCommand:
    """Representa `OperationalCommand` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/monthly_ops.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    step: str
    gate_or_contract: str
    purpose: str
    command: str
    expected_artifact: str


@dataclass(frozen=True)
class MonthlyOperationPlan:
    """Representa `MonthlyOperationPlan` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/mlops/monthly_ops.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    created_at: str
    months: list[str]
    target_path: str
    target_satellite: str
    retraining_policy: str
    commands: list[OperationalCommand]

    def to_dict(self) -> dict[str, object]:
        """Executa a etapa `to dict` do fluxo FireCast.
        
        A funcao faz parte de `src/mlops/monthly_ops.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        return asdict(self)

    def to_markdown(self) -> str:
        """Executa a etapa `to markdown` do fluxo FireCast.
        
        A funcao faz parte de `src/mlops/monthly_ops.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        lines = [
            "# FireCast monthly operations plan",
            "",
            f"Generated at `{self.created_at}`.",
            f"Months: `{', '.join(self.months)}`.",
            f"Target: `{self.target_path}` filtered to `{self.target_satellite}`.",
            "",
            "Retraining policy: " + self.retraining_policy,
            "",
            "| Step | Contract | Purpose | Command | Expected artifact |",
            "|---|---|---|---|---|",
        ]
        for command in self.commands:
            lines.append(
                "| "
                + " | ".join(
                    [
                        command.step,
                        command.gate_or_contract,
                        command.purpose,
                        f"`{command.command}`",
                        f"`{command.expected_artifact}`",
                    ]
                )
                + " |"
            )
        return "\n".join(lines) + "\n"


def _normalize_months(raw_months: list[str]) -> list[str]:
    """Executa a etapa `normalize months` do fluxo FireCast.
    
    A funcao faz parte de `src/mlops/monthly_ops.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    months: list[str] = []
    for value in raw_months:
        text = str(value).strip()
        if not text:
            continue
        if len(text) != 6 or not text.isdigit():
            raise ValueError(f"invalid month {value!r}; use YYYYMM")
        month = int(text[4:6])
        if month < 1 or month > 12:
            raise ValueError(f"invalid month {value!r}; month must be 01..12")
        months.append(text)
    if not months:
        raise ValueError("at least one YYYYMM month is required")
    return sorted(dict.fromkeys(months))


def build_monthly_plan(
    months: list[str],
    target_path: str = DEFAULT_PUBLIC_TARGET,
    target_satellite: str = DEFAULT_TARGET_SATELLITE,
) -> MonthlyOperationPlan:
    """Constroi a etapa `build monthly plan` do fluxo FireCast.
    
    A funcao faz parte de `src/mlops/monthly_ops.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    normalized_months = _normalize_months(months)
    month_arg = ",".join(normalized_months)
    retraining_policy = (
        "Do not retrain only because a new month arrived. Retrain only after a documented trigger: "
        "shadow degradation, source/schema change, annual review, new as-of feature block, or human-approved contract revision."
    )
    commands = [
        OperationalCommand(
            "01_ingest_public_target",
            "G1",
            "Fetch the additive public INPE monthly files and keep the event-level sensor field.",
            f"python src/data/ingest_inpe_monthly_public_v3.py --months {month_arg}",
            "data/snapshots/inpe_monthly_public_v3/manifest.json",
        ),
        OperationalCommand(
            "02_validate_data_contracts",
            "G0/G1",
            "Check that every ingestor and snapshot has the expected manifest/status.",
            "python scripts/check_data_ingestors.py",
            "terminal OK plus unchanged source manifests",
        ),
        OperationalCommand(
            "03_reality_score_holdout",
            "G2/G3 reality check",
            "Score frozen 2025/2026 reality windows without changing model parameters.",
            "python src/experiments/exp27_reality_volume_2025_2026.py",
            "outputs/exp27_reality_volume_2025_2026/run_manifest.json",
        ),
        OperationalCommand(
            "04_shadow_score",
            "G7",
            "Score committed shadow predictions against the sensor-aligned public target.",
            f"python -m src.production.shadow_monitor score --target-path {target_path} --target-satellite {target_satellite}",
            "outputs/shadow_monitor/shadow_scores.jsonl",
        ),
        OperationalCommand(
            "05_shadow_report",
            "G7",
            "Emit delayed-performance, freshness and rollback report for the same target definition.",
            f"python -m src.production.shadow_monitor report --target-path {target_path} --target-satellite {target_satellite}",
            "outputs/shadow_monitor/monitoring_report.md",
        ),
        OperationalCommand(
            "06_api_contract_smoke",
            "G6",
            "Verify that the API still loads the approved artifact and exposes the champion summary.",
            "python -m pytest tests/test_serving_api.py tests/test_g6_serving_contract.py -q",
            "passing tests",
        ),
        OperationalCommand(
            "07_publish_results_registry",
            "G0/G7",
            "Refresh the public release plan and results registry for reviewers.",
            "python python src/mlops/contracts.py --out outputs/production_ml_plan.json",
            "outputs/production_ml_plan.json and outputs/public_results_summary.json valid",
        ),
    ]
    return MonthlyOperationPlan(
        created_at=datetime.now(timezone.utc).isoformat(),
        months=normalized_months,
        target_path=target_path,
        target_satellite=target_satellite,
        retraining_policy=retraining_policy,
        commands=commands,
    )


def write_plan(path: Path, plan: MonthlyOperationPlan, output_format: str = "json") -> None:
    """Grava a etapa `write plan` do fluxo FireCast.
    
    A funcao faz parte de `src/mlops/monthly_ops.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "md":
        path.write_text(plan.to_markdown(), encoding="utf-8")
    elif output_format == "json":
        path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        raise ValueError("output_format must be 'json' or 'md'")


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/mlops/monthly_ops.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser(description="Build a FireCast monthly operations plan")
    parser.add_argument("--months", nargs="+", required=True, help="Observed months to ingest/score, in YYYYMM format")
    parser.add_argument("--target-path", default=DEFAULT_PUBLIC_TARGET)
    parser.add_argument("--target-satellite", default=DEFAULT_TARGET_SATELLITE)
    parser.add_argument("--out", type=Path, default=Path("outputs/monthly_operations_plan.json"))
    parser.add_argument("--format", choices=["json", "md"], default="json")
    args = parser.parse_args()
    plan = build_monthly_plan(args.months, target_path=args.target_path, target_satellite=args.target_satellite)
    write_plan(args.out, plan, args.format)
    print(f"wrote {args.out} for months {','.join(plan.months)}")


if __name__ == "__main__":
    main()

