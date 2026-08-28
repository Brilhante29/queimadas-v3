"""CLI de reproducao do pipeline APA Chapada do Araripe.

Uso
---
```bash
python -m src.cli.apa rebuild        # pipeline completo, exceto o teste selado
python -m src.cli.apa rebuild --with-sealed-2025   # inclui o teste selado
python -m src.cli.apa status         # estado atual dos gates
```

`rebuild` executa, em ordem de dependencia:

```text
escopo -> ingestao -> backtest -> gates G0/G1/G2 -> conformal -> congelamento
```

O teste selado de 2025 fica FORA do `rebuild` por padrao, de proposito: ele e
uma execucao unica sobre holdout lacrado, nao uma etapa de rotina. Rodar de
novo depois de ver o resultado seria ajuste no holdout. Exige a flag explicita.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATES_DIR = PROJECT_ROOT / "outputs" / "apa_araripe" / "gates"

# Ordem de dependencia real. Cada etapa so faz sentido se a anterior passou.
STEPS = [
    ("escopo APA (intersecao ICMBio x IBGE)", ["-m", "src.scopes.apa_araripe"]),
    ("escopo legado (cariri_ce_legacy)", ["-m", "src.scopes.cariri_legacy"]),
    ("ingestao INPE 2003-2024 CE/PE/PI", ["-m", "src.data.ingest_inpe_ce_pe_pi_satref"]),
    ("backtest EXP-10 no escopo APA", ["-m", "src.experiments.exp10_apa_araripe_regional_intensity"]),
    ("gates G0/G1/G2", ["-m", "src.validation.apa_araripe_gates"]),
    ("G5 conformal (metodo incumbente)", ["-m", "src.experiments.g5_conformal_apa_araripe"]),
    ("familia conformal robusta a drift + congelamento", ["-m", "src.experiments.g5_conformal_drift_family"]),
    ("artefato de serving", ["-m", "src.production.apa_araripe_serving"]),
]

# Auditorias de integridade. Rodam DEPOIS do pipeline porque leem os artefatos
# que ele produz. Nenhuma delas altera o snapshot congelado -- todas gravam em
# `outputs/apa_araripe/audit/`.
AUDIT_STEPS = [
    ("auditoria: semantica de zero", ["scripts/audit_zero_semantics.py"]),
    ("auditoria: quebra estrutural do alvo", ["scripts/screen_target_structural_break.py"]),
    ("auditoria: decomposicao alpha x metodo no G5", ["scripts/decompose_g5_improvement.py"]),
    ("auditoria: champion x baselines competentes", ["scripts/benchmark_competent_baselines.py"]),
    ("auditoria: incerteza do ganho pontual de 2025", ["scripts/quantify_2025_point_gain.py"]),
    ("auditoria: equivalencia entre caminhos da fonte (usa rede na 1a vez)",
     ["scripts/validate_source_path_equivalence.py"]),
    ("summary publico + blocos de metricas", ["scripts/build_public_results_summary.py"]),
]

SEALED_STEPS = [
    ("ingestao 2025 (scoring)", ["-m", "src.data.ingest_inpe_2025_scoring"]),
    ("G5 FINAL selado em 2025 (execucao unica)", ["-m", "src.experiments.g5_final_sealed_2025"]),
]


def run_step(label: str, args: list[str]) -> tuple[bool, float]:
    """Executa a etapa `run step` do fluxo FireCast."""
    print(f"\n>>> {label}")
    started = time.time()
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - started
    if proc.returncode != 0:
        print(f"    FALHOU em {elapsed:.1f}s")
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-12:]
        for line in tail:
            print(f"    | {line}")
        return False, elapsed
    print(f"    ok em {elapsed:.1f}s")
    return True, elapsed


def cmd_rebuild(with_sealed: bool) -> int:
    """Executa a etapa `cmd rebuild` do fluxo FireCast.

    Para na primeira falha: etapa posterior construida sobre etapa quebrada
    produziria artefato invalido com aparencia de valido."""
    steps = list(STEPS)
    if with_sealed:
        steps += SEALED_STEPS
    steps += AUDIT_STEPS

    results = []
    for label, args in steps:
        ok, elapsed = run_step(label, args)
        results.append({"step": label, "ok": ok, "seconds": round(elapsed, 1)})
        if not ok:
            print("\nPipeline interrompido -- etapa seguinte dependeria de artefato invalido.")
            break

    print("\n=== resumo ===")
    for r in results:
        print(f"  [{'ok  ' if r['ok'] else 'FAIL'}] {r['step']}  ({r['seconds']}s)")
    return 0 if all(r["ok"] for r in results) else 1


def cmd_status() -> int:
    """Executa a etapa `cmd status` do fluxo FireCast."""
    if not GATES_DIR.exists():
        print("nenhum gate gerado ainda; rode `python -m src.cli.apa rebuild`")
        return 1
    print("=== gates APA Chapada do Araripe ===")
    worst = 0
    for path in sorted(GATES_DIR.glob("*.json")):
        gate = json.loads(path.read_text(encoding="utf-8"))
        status = gate.get("status", "?")
        print(f"  {path.stem:32s} {status}")
        for f in gate.get("failures", []) or []:
            print(f"      - {f}")
        if status != "PASS":
            worst = 1

    scope_csv = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
    if scope_csv.exists():
        import pandas as pd

        scope = pd.read_csv(scope_csv)
        by_uf = scope["uf"].value_counts().to_dict()
        print(f"\nescopo: {len(scope)} municipios {by_uf}")

    artifact = PROJECT_ROOT / "outputs" / "apa_araripe" / "serving" / "model.json"
    if artifact.exists():
        art = json.loads(artifact.read_text(encoding="utf-8"))
        print(f"serving: incerteza = {art['uncertainty']['status']}")
    return worst


def main() -> int:
    """Executa a etapa `main` do fluxo FireCast."""
    parser = argparse.ArgumentParser(
        prog="python -m src.cli.apa",
        description="Reproducao do pipeline APA Chapada do Araripe",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rebuild = sub.add_parser("rebuild", help="executa o pipeline completo")
    rebuild.add_argument(
        "--with-sealed-2025",
        action="store_true",
        help=(
            "inclui o teste selado de 2025. Execucao unica por contrato: "
            "reexecutar depois de ver o resultado e ajuste no holdout."
        ),
    )
    sub.add_parser("status", help="mostra o estado dos gates")

    args = parser.parse_args()
    if args.command == "rebuild":
        return cmd_rebuild(with_sealed=args.with_sealed_2025)
    return cmd_status()


if __name__ == "__main__":
    raise SystemExit(main())
