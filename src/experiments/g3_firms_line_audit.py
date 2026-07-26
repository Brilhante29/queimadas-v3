"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/g3_firms_line_audit.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "outputs" / "g3_firms_line_audit"
EXPERIMENT_OUTPUTS = [
    PROJECT_ROOT / "outputs" / "exp15_firms_modis_sp_g3",
    PROJECT_ROOT / "outputs" / "exp16_firms_viirs_snpp_sp_g3",
    PROJECT_ROOT / "outputs" / "exp17_firms_viirs_noaa20_sp_g3",
    PROJECT_ROOT / "outputs" / "exp18_firms_multi_sensor_g3",
    PROJECT_ROOT / "outputs" / "exp19_firms_regional_total_g3",
]
G3_CE_LIMIT = 0.20
G3_CHAPADA_LIMIT = 0.25


def load_report(path: Path) -> dict[str, Any]:
    """Carrega a etapa `load report` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_firms_line_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return json.loads((path / "run_manifest.json").read_text(encoding="utf-8-sig"))


def val(block: dict[str, Any], key: str, default: Any = None) -> Any:
    """Executa a etapa `val` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_firms_line_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return block.get(key, default)


def build_rows() -> list[dict[str, Any]]:
    """Constroi a etapa `build rows` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_firms_line_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows: list[dict[str, Any]] = []
    for out in EXPERIMENT_OUTPUTS:
        report = load_report(out)
        selected_ce = report["selected_ce_by_2015_2022"]
        selected_chapada = report["selected_chapada_by_2015_2022"]
        best_ce = report["best_gate_ceara_audit_only"]
        best_chapada = report["best_gate_chapada_audit_only"]
        rows.append(
            {
                "experiment_id": report["experiment_id"],
                "output_dir": str(out.relative_to(PROJECT_ROOT)),
                "decision": report["decision"],
                "hypothesis": report["hypothesis"],
                "selected_ce_model": selected_ce["model"],
                "selected_ce_selection_wape": val(selected_ce, "selection_2015_2022_wape_critical_ceara"),
                "selected_ce_gate_wape": val(selected_ce, "gate_2023_2024_wape_critical_ceara"),
                "selected_ce_passes_wape": bool(val(selected_ce, "passes_g3_ceara_wape", False)),
                "selected_chapada_model": selected_chapada["model"],
                "selected_chapada_selection_wape": val(selected_chapada, "selection_2015_2022_wape_critical_chapada_cariri"),
                "selected_chapada_gate_wape": val(selected_chapada, "gate_2023_2024_wape_critical_chapada_cariri"),
                "selected_chapada_passes_wape": bool(val(selected_chapada, "passes_g3_chapada_cariri_wape", False)),
                "best_gate_ce_model": best_ce["model"],
                "best_gate_ce_wape": val(best_ce, "gate_2023_2024_wape_critical_ceara"),
                "best_gate_chapada_model": best_chapada["model"],
                "best_gate_chapada_wape": val(best_chapada, "gate_2023_2024_wape_critical_chapada_cariri"),
            }
        )
    return rows


def write_markdown(df: pd.DataFrame, summary: dict[str, Any]) -> None:
    """Grava a etapa `write markdown` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/g3_firms_line_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    lines = [
        "# G3 FIRMS line audit",
        "",
        f"Generated at: {summary['generated_at']}",
        "",
        "## Verdict",
        "",
        "NASA FIRMS Standard Processing data is now integrated as real, versioned lagged features, but EXP-15 through EXP-19 do not pass G3.",
        "",
        f"Best selected Ceara gate WAPE: {summary['best_selected_ce_gate_wape']:.4f} (limit {G3_CE_LIMIT:.2f}).",
        f"Best selected Chapada/Cariri gate WAPE: {summary['best_selected_chapada_gate_wape']:.4f} (limit {G3_CHAPADA_LIMIT:.2f}).",
        f"Best audit-only Ceara gate WAPE: {summary['best_audit_ce_gate_wape']:.4f}.",
        f"Best audit-only Chapada/Cariri gate WAPE: {summary['best_audit_chapada_gate_wape']:.4f}.",
        "",
        "## Experiments",
        "",
        "| Experiment | Decision | Selected CE | CE gate WAPE | Selected Chapada | Chapada gate WAPE | Best audit CE | Best audit Chapada |",
        "|---|---|---|---:|---|---:|---|---|",
    ]
    for row in df.to_dict(orient="records"):
        lines.append(
            "| {experiment_id} | {decision} | {selected_ce_model} | {selected_ce_gate_wape:.4f} | "
            "{selected_chapada_model} | {selected_chapada_gate_wape:.4f} | "
            "{best_gate_ce_model} ({best_gate_ce_wape:.4f}) | {best_gate_chapada_model} ({best_gate_chapada_wape:.4f}) |".format(**row)
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "FIRMS improves observability and is useful as an audit/feature source, but in this municipal monthly contract it did not solve the magnitude/allocation WAPE gap. The next G3 attempt needs a different information channel, such as vegetation/fuel/human-pressure features with publication dates, or a formal product-contract revision.",
        ]
    )
    (OUT_DIR / "firms_line_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/g3_firms_line_audit.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(build_rows())
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "g3_limits": {"ceara": G3_CE_LIMIT, "chapada_cariri": G3_CHAPADA_LIMIT},
        "experiment_ids": df["experiment_id"].tolist(),
        "all_selected_fail_g3_wape": bool((~df["selected_ce_passes_wape"]).all() and (~df["selected_chapada_passes_wape"]).all()),
        "best_selected_ce_gate_model": df.sort_values("selected_ce_gate_wape").iloc[0]["selected_ce_model"],
        "best_selected_ce_gate_wape": float(df["selected_ce_gate_wape"].min()),
        "best_selected_chapada_gate_model": df.sort_values("selected_chapada_gate_wape").iloc[0]["selected_chapada_model"],
        "best_selected_chapada_gate_wape": float(df["selected_chapada_gate_wape"].min()),
        "best_audit_ce_gate_model": df.sort_values("best_gate_ce_wape").iloc[0]["best_gate_ce_model"],
        "best_audit_ce_gate_wape": float(df["best_gate_ce_wape"].min()),
        "best_audit_chapada_gate_model": df.sort_values("best_gate_chapada_wape").iloc[0]["best_gate_chapada_model"],
        "best_audit_chapada_gate_wape": float(df["best_gate_chapada_wape"].min()),
    }
    df.to_csv(OUT_DIR / "firms_line_audit.csv", index=False)
    (OUT_DIR / "firms_line_audit.json").write_text(json.dumps({"summary": summary, "rows": df.to_dict(orient="records")}, indent=2), encoding="utf-8")
    write_markdown(df, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
