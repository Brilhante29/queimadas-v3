"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/audit_ndvi_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
NDVI_CSV = REPO_ROOT / "NDVI_Ceara_Municipios_Mensal_FINAL.csv"
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "ndvi_snapshot_audit"

import sys
sys.path.insert(0, str(PROJECT_ROOT))
from src.data.ingest_inpe_local import load_ibge_lookup, normalize_name  # noqa: E402


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/audit_ndvi_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(NDVI_CSV)
    required = {"city", "month", "year", "ndvi"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"NDVI sem colunas obrigatórias: {sorted(missing)}")

    df = raw.rename(columns={"city": "municipio", "month": "mes", "year": "ano"}).copy()
    df["key"] = df["municipio"].map(normalize_name)
    geo = {k[0]: v for k, v in load_ibge_lookup().items() if k[1] == "CE"}
    df["geocodigo"] = df["key"].map(lambda x: geo.get(x, (np.nan, None, None))[0])
    df["ndvi_zero_or_negative"] = df["ndvi"] <= 0
    df["ndvi_valid"] = df["ndvi"].where(df["ndvi"] > 0)

    target_munis = pd.read_csv(TARGET)[["geocodigo", "municipio_ibge", "uf"]].drop_duplicates()
    mapped = df.dropna(subset=["geocodigo"]).copy()
    mapped["geocodigo"] = mapped["geocodigo"].astype(int)
    target_coverage = target_munis.merge(
        mapped.groupby("geocodigo").agg(
            ndvi_rows=("ndvi", "size"),
            valid_rows=("ndvi_valid", "count"),
            first_year=("ano", "min"),
            last_year=("ano", "max"),
            zero_or_negative=("ndvi_zero_or_negative", "sum"),
            ndvi_mean=("ndvi_valid", "mean"),
            ndvi_min=("ndvi_valid", "min"),
            ndvi_max=("ndvi_valid", "max"),
        ).reset_index(),
        on="geocodigo",
        how="left",
    )
    target_coverage["coverage_status"] = np.where(
        target_coverage["valid_rows"].fillna(0) >= 300, "OK_LOCAL_SERIES", "MISSING_OR_SHORT"
    )
    target_coverage.to_csv(OUT_DIR / "target_municipality_coverage.csv", index=False)

    unmapped = df[df["geocodigo"].isna()][["municipio", "key"]].drop_duplicates().sort_values("municipio")
    unmapped.to_csv(OUT_DIR / "unmapped_cities.csv", index=False)

    by_year = mapped.groupby("ano", as_index=False).agg(
        rows=("ndvi", "size"),
        valid_rows=("ndvi_valid", "count"),
        zero_or_negative=("ndvi_zero_or_negative", "sum"),
        ndvi_mean=("ndvi_valid", "mean"),
    )
    by_year.to_csv(OUT_DIR / "coverage_by_year.csv", index=False)

    ok_targets = int((target_coverage["coverage_status"] == "OK_LOCAL_SERIES").sum())
    report = f"""# Auditoria local do NDVI usado nos EXP-03/EXP-04

## Resultado

- Arquivo auditado: `{NDVI_CSV.name}`.
- Linhas brutas: {len(df)}.
- Período declarado no CSV: {int(df['ano'].min())}–{int(df['ano'].max())}.
- Cidades CE mapeadas por geocódigo: {mapped['geocodigo'].nunique()}.
- Municípios do alvo com série local suficiente: {ok_targets}/{len(target_coverage)}.
- Cidades não mapeadas no lookup CE: {len(unmapped)}.
- Valores NDVI <= 0 tratados como composição inválida no EXP-03: {int(df['ndvi_zero_or_negative'].sum())}.

## Limitação crítica

O CSV local não carrega campos de QA do MODIS, versão do produto, geometria zonal,
`published_at` nem `available_at`. Portanto ele é aceitável apenas como feature
exploratória defasada, não como evidência de produção. A próxima ação segura para
G1/G2 é substituir essa fonte local por um contrato MODIS/MOD13Q1 versionado com
QA e data de disponibilidade, ou priorizar a estatística zonal ERA5 antes de novo
modelo.
"""
    (OUT_DIR / "audit_report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
