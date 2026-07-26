"""Modulo publico do FireCast para validacoes auxiliares e checagens operacionais.

Arquivo `scripts/check_data_ingestors.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "src" / "data"
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"

MANIFEST_NAMES = {"manifest.json", "MANIFEST.md", "MANIFEST.json"}

# Padrões de credencial hardcoded: nome de variável estilo *_API_KEY/*_TOKEN
# atribuído a uma string literal não vazia (não a os.environ/os.getenv).
HARDCODED_CREDENTIAL_RE = re.compile(
    r'^[A-Za-z_][A-Za-z0-9_]*(API_KEY|TOKEN|SECRET|MAP_KEY)\s*=\s*["\'](?!["\']\s*$)[^"\']+["\']',
    re.MULTILINE,
)
KNOWN_DEMO_LITERALS = {"demo_key", "demo", "changeme", "your_api_key_here", "your_key_here"}

BARE_TMP_RE = re.compile(r'["\']\s*/tmp/')


def check_snapshots_have_manifest() -> list[str]:
    """Valida a etapa `check snapshots have manifest` do fluxo FireCast.
    
    A funcao faz parte de `scripts/check_data_ingestors.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    problems = []
    if not SNAPSHOTS_DIR.exists():
        return problems
    for snap_dir in sorted(p for p in SNAPSHOTS_DIR.iterdir() if p.is_dir()):
        files = {f.name for f in snap_dir.iterdir() if f.is_file()}
        if not (files & MANIFEST_NAMES):
            problems.append(
                f"{snap_dir.relative_to(PROJECT_ROOT)}: sem manifest.json/MANIFEST.md "
                "(proveniência não documentada — ver checklist item 5)"
            )
    return problems


def check_no_hardcoded_credentials() -> list[str]:
    """Valida a etapa `check no hardcoded credentials` do fluxo FireCast.
    
    A funcao faz parte de `scripts/check_data_ingestors.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    problems = []
    if not DATA_DIR.exists():
        return problems
    for py_file in sorted(DATA_DIR.glob("*.py")):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for match in HARDCODED_CREDENTIAL_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            snippet = match.group(0)
            problems.append(
                f"{py_file.relative_to(PROJECT_ROOT)}:{line_no}: credencial hardcoded suspeita: "
                f"'{snippet}' (deve vir de os.environ, sem default de string real — ver checklist item 4)"
            )
    return problems


def check_no_bare_tmp_paths() -> list[str]:
    """Valida a etapa `check no bare tmp paths` do fluxo FireCast.
    
    A funcao faz parte de `scripts/check_data_ingestors.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    problems = []
    if not DATA_DIR.exists():
        return problems
    for py_file in sorted(DATA_DIR.glob("*.py")):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for match in BARE_TMP_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            problems.append(
                f"{py_file.relative_to(PROJECT_ROOT)}:{line_no}: caminho '/tmp/...' hardcoded "
                "(ambíguo entre bash e Python direto no Windows — use cache relativo ao "
                "repo, ex. firecast/cache/<fonte>/ — ver checklist item 3)"
            )
    return problems


def main() -> int:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `scripts/check_data_ingestors.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="no-op, mantido por simetria com sync_agent_checklists.py --check")
    parser.parse_args()

    problems = [
        *check_snapshots_have_manifest(),
        *check_no_hardcoded_credentials(),
        *check_no_bare_tmp_paths(),
    ]

    if problems:
        print(f"{len(problems)} problema(s) encontrado(s):\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nVer firecast/checklists/firecast-data-pipeline/references/ingestion-checklist.md "
            "para o porquê de cada regra (com o bug real que a motivou).",
            file=sys.stderr,
        )
        return 1

    n_snapshots = len(list(SNAPSHOTS_DIR.iterdir())) if SNAPSHOTS_DIR.exists() else 0
    n_ingestors = len(list(DATA_DIR.glob("*.py"))) if DATA_DIR.exists() else 0
    print(f"OK: {n_snapshots} snapshots com manifest, {n_ingestors} ingestores sem credencial hardcoded ou caminho /tmp ambíguo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
