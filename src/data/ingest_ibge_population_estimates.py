"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_ibge_population_estimates.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
MALHA_ATTRS = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi_attributes.csv"
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "ibge_population_estimates_v1"
RAW_DIR = OUT_DIR / "raw"
SIDRA_TABLE = "6579"
SIDRA_VARIABLE = "9324"
YEARS = list(range(2014, 2025))
ENDPOINT_TEMPLATE = "https://apisidra.ibge.gov.br/values/t/{table}/n6/{codes}/v/{variable}/p/{periods}"
OFFICIAL_URL = "https://sidra.ibge.gov.br/tabela/6579"


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_population_estimates.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def chunks(values: list[int], size: int) -> list[list[int]]:
    """Executa a etapa `chunks` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_population_estimates.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return [values[i : i + size] for i in range(0, len(values), size)]


def fetch_chunk(codes: list[int], periods: str, chunk_id: int) -> Path:
    """Executa a etapa `fetch chunk` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_population_estimates.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"sidra_6579_population_chunk_{chunk_id:02d}.json"
    url = ENDPOINT_TEMPLATE.format(
        table=SIDRA_TABLE,
        codes=",".join(str(c) for c in codes),
        variable=SIDRA_VARIABLE,
        periods=periods,
    )
    response = requests.get(url, timeout=120, headers={"Accept": "application/json"})
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list) or len(data) <= 1:
        raise RuntimeError(f"SIDRA returned no data for chunk {chunk_id}")
    raw_path.write_text(json.dumps({"url": url, "response": data}, ensure_ascii=False), encoding="utf-8")
    return raw_path


def parse_raw(paths: list[Path]) -> pd.DataFrame:
    """Executa a etapa `parse raw` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_population_estimates.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    records: list[dict[str, object]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload["response"][1:]:
            value = row.get("V")
            records.append(
                {
                    "geocodigo": int(row["D1C"]),
                    "municipio_sidra": row["D1N"],
                    "ano": int(row["D3C"]),
                    "population_estimate": float(value) if value not in {None, "", "-"} else float("nan"),
                    "unit": row.get("MN"),
                    "sidra_variable": row.get("D2N"),
                }
            )
    df = pd.DataFrame(records).sort_values(["geocodigo", "ano"]).reset_index(drop=True)
    return df


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_ibge_population_estimates.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    target = pd.read_csv(TARGET)[["geocodigo", "municipio_ibge", "uf"]].drop_duplicates()
    target["geocodigo"] = target["geocodigo"].astype(int)
    codes = sorted(target["geocodigo"].unique().tolist())
    periods = f"{YEARS[0]}-{YEARS[-1]}"
    raw_paths = [fetch_chunk(chunk, periods, i + 1) for i, chunk in enumerate(chunks(codes, 20))]
    annual = parse_raw(raw_paths)

    attrs = pd.read_csv(MALHA_ATTRS)[["geocodigo", "area_km2_approx"]]
    annual = annual.merge(target, on="geocodigo", how="left").merge(attrs, on="geocodigo", how="left")
    if annual["municipio_ibge"].isna().any() or annual["area_km2_approx"].isna().any():
        raise RuntimeError("IBGE population snapshot has target/area coverage gaps")
    year_counts = annual.groupby("ano")["geocodigo"].nunique().to_dict()
    partial_years = {int(year): int(count) for year, count in year_counts.items() if int(count) != len(codes)}
    if partial_years:
        raise RuntimeError(f"Partial municipality coverage in SIDRA population years: {partial_years}")
    available_years = sorted(int(y) for y in year_counts)
    missing_years = sorted(set(YEARS) - set(available_years))
    annual["population_density_km2"] = annual["population_estimate"] / annual["area_km2_approx"].clip(lower=1e-6)
    annual["population_log1p"] = annual["population_estimate"].clip(lower=0).apply(lambda v: __import__("math").log1p(v))
    annual["population_density_log1p"] = annual["population_density_km2"].clip(lower=0).apply(lambda v: __import__("math").log1p(v))
    annual = annual[
        [
            "geocodigo",
            "municipio_ibge",
            "uf",
            "ano",
            "population_estimate",
            "area_km2_approx",
            "population_density_km2",
            "population_log1p",
            "population_density_log1p",
            "municipio_sidra",
            "unit",
            "sidra_variable",
        ]
    ]
    annual_path = OUT_DIR / "annual_population_estimates.csv"
    annual.to_csv(annual_path, index=False)

    manifest = {
        "snapshot_name": OUT_DIR.name,
        "retrieved_at": retrieved_at,
        "source_name": "IBGE SIDRA",
        "dataset_name": "Tabela 6579 - Populacao residente estimada",
        "official_url": OFFICIAL_URL,
        "api_template": ENDPOINT_TEMPLATE,
        "sidra_table": SIDRA_TABLE,
        "sidra_variable": SIDRA_VARIABLE,
        "role": "human_pressure_static_annual_population",
        "license": "Dados abertos IBGE",
        "temporal_resolution": "annual",
        "spatial_resolution": "municipality",
        "keys": ["geocodigo", "ano"],
        "requested_years": YEARS,
        "available_years": available_years,
        "missing_years": missing_years,
        "coverage_start": min(available_years),
        "coverage_end": max(available_years),
        "target_municipalities": int(len(codes)),
        "rows": int(len(annual)),
        "available_at_rule": "Experiments must use the latest population estimate with year <= forecast_year - 1 unless official same-year publication date is encoded; missing SIDRA years are not interpolated.",
        "raw_files": [
            {"path": str(path.relative_to(PROJECT_ROOT)), "sha256": sha256_file(path)}
            for path in raw_paths
        ],
        "outputs": {
            "annual_population_estimates.csv": {
                "sha256": sha256_file(annual_path),
                "rows": int(len(annual)),
            }
        },
        "quality_rules": [
            "fail if any available SIDRA year has partial target municipality coverage; record globally missing years without interpolation",
            "use geocodigo IBGE as key",
            "density computed from versioned IBGE municipal area snapshot",
            "do not use same-year estimates in backtests without explicit publication date",
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"rows": len(annual), "municipalities": len(codes), "years": [min(YEARS), max(YEARS)]}, indent=2))


if __name__ == "__main__":
    main()




