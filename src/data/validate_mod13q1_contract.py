"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/validate_mod13q1_contract.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
CONTRACT = PROJECT_ROOT / "configs" / "data_sources" / "mod13q1_v061.json"
LOCAL_CSV = REPO_ROOT / "NDVI_Ceara_Municipios_Mensal_FINAL.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "mod13q1_contract_smoke"

REQUIRED_CONTRACT_KEYS = {
    "source_name", "dataset_name", "dataset_id", "doi", "official_urls",
    "temporal_resolution", "spatial_resolution_m", "required_bands",
    "available_at_rule", "quality_rules",
}
PRODUCTION_REQUIRED_COLUMNS = {
    "geocodigo", "ano", "mes", "ndvi", "SummaryQA", "DetailedQA",
    "valid_pixel_fraction", "source_image_ids", "published_at", "available_at",
}


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/validate_mod13q1_contract.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    missing_contract = sorted(REQUIRED_CONTRACT_KEYS - set(contract))
    if missing_contract:
        raise ValueError(f"Contrato incompleto: {missing_contract}")

    local = pd.read_csv(LOCAL_CSV, nrows=5)
    local_cols = set(local.columns)
    missing_local = sorted(PRODUCTION_REQUIRED_COLUMNS - local_cols)
    status = "FAIL_LOCAL_CSV_NOT_PRODUCTION_READY" if missing_local else "PASS"
    report = {
        "contract": str(CONTRACT.relative_to(PROJECT_ROOT)),
        "local_csv": LOCAL_CSV.name,
        "status": status,
        "missing_local_columns_for_production": missing_local,
        "decision": "Use local CSV only for exploratory lagged features; build a versioned MOD13Q1 snapshot with QA/available_at before promotion.",
    }
    (OUT_DIR / "contract_smoke_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
