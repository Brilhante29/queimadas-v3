"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_ibge_pam_crop_area.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
NODES_PATH = PROJECT_ROOT / "data" / "snapshots" / "ibge_spatial_graph_v1" / "nodes.csv"
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "ibge_pam_crop_area_v1"
RAW_DIR = OUT_DIR / "raw"

SIDRA_TABLE = "1612"
SIDRA_VARIABLE = "109"  # Area plantada
PRODUCT_DIMENSION = "81"
OFFICIAL_URL = "https://sidra.ibge.gov.br/tabela/1612"
ENDPOINT_TEMPLATE = (
    "https://apisidra.ibge.gov.br/values/t/{table}/n6/{codes}/v/{variable}/p/{periods}/c{dimension}/all"
)
YEARS = list(range(2014, 2025))
CODES_PER_REQUEST = 2

PRODUCT_FEATURES = {
    "total": ["0"],
    "abacaxi": ["2688"],
    "algodao": ["2689"],
    "arroz": ["2692"],
    "cana_acucar": ["2696"],
    "cana_forragem": ["40470"],
    "fava": ["2701"],
    "feijao": ["2702"],
    "mamona": ["2707"],
    "mandioca": ["2708"],
    "milho": ["2711"],
    "soja": ["2713"],
    "sorgo": ["2714"],
}
BIOMASS_PROXY_PRODUCTS = ["milho", "feijao", "mandioca", "cana_acucar", "cana_forragem", "algodao", "arroz", "sorgo"]
DRY_RESIDUE_PROXY_PRODUCTS = ["milho", "feijao", "arroz", "algodao", "sorgo", "soja", "mamona"]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_pam_crop_area.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    """Executa a etapa `chunks` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_pam_crop_area.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    for i in range(0, len(values), size):
        yield values[i : i + size]


def fetch_chunk(codes: list[str], chunk_id: int) -> list[dict]:
    """Executa a etapa `fetch chunk` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_pam_crop_area.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    periods = f"{YEARS[0]}-{YEARS[-1]}"
    url = ENDPOINT_TEMPLATE.format(
        table=SIDRA_TABLE,
        codes=",".join(codes),
        variable=SIDRA_VARIABLE,
        periods=periods,
        dimension=PRODUCT_DIMENSION,
    )
    raw_path = RAW_DIR / f"sidra_1612_area_plantada_chunk_{chunk_id:02d}.json"
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:  # noqa: S310 official IBGE endpoint
                payload = response.read().decode("utf-8-sig")
            data = json.loads(payload)
            raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            return data
        except Exception as exc:  # pragma: no cover - network variability
            last_error = exc
            time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"Failed SIDRA chunk {chunk_id}: {last_error}")


def parse_value(raw: str | None) -> float:
    """Executa a etapa `parse value` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_pam_crop_area.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if raw is None:
        return math.nan
    text = str(raw).strip()
    if text in {"", "-", "..", "...", "X"}:
        return 0.0
    text = text.replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return math.nan


def main() -> int:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_ibge_pam_crop_area.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = pd.read_csv(TARGET_PATH, dtype={"geocodigo": str})
    codes = sorted(target["geocodigo"].astype(str).unique())
    nodes = pd.read_csv(NODES_PATH, dtype={"geocodigo": str})[["geocodigo", "municipio_ibge", "uf", "area_km2"]]

    rows: list[dict] = []
    raw_files: list[Path] = []
    for chunk_id, code_chunk in enumerate(chunks(codes, CODES_PER_REQUEST), start=1):
        data = fetch_chunk(code_chunk, chunk_id)
        raw_files.append(RAW_DIR / f"sidra_1612_area_plantada_chunk_{chunk_id:02d}.json")
        for record in data[1:]:
            rows.append(
                {
                    "geocodigo": str(record.get("D1C", "")),
                    "municipio_sidra": record.get("D1N", ""),
                    "ano": int(record.get("D3C")),
                    "product_code": str(record.get("D4C", "")),
                    "product_name": record.get("D4N", ""),
                    "area_planted_ha": parse_value(record.get("V")),
                    "raw_value": record.get("V"),
                    "unit": record.get("MN"),
                    "sidra_variable": record.get("D2N"),
                }
            )

    long = pd.DataFrame(rows)
    if long.empty:
        raise RuntimeError("SIDRA PAM crop-area snapshot returned no rows")
    long = long.merge(nodes, on="geocodigo", how="left")
    if long[["municipio_ibge", "area_km2"]].isna().any().any():
        raise RuntimeError("PAM crop-area snapshot has target/area coverage gaps")

    total = long[long["product_code"] == "0"]
    total_counts = total.groupby("ano")["geocodigo"].nunique().to_dict()
    partial_years = {int(year): int(count) for year, count in total_counts.items() if int(count) != len(codes)}
    missing_years = [int(y) for y in YEARS if int(total_counts.get(y, 0)) == 0]
    if partial_years:
        raise RuntimeError(f"Partial municipality coverage in SIDRA PAM years: {partial_years}")

    pivot = (
        long.pivot_table(
            index=["geocodigo", "ano"],
            columns="product_code",
            values="area_planted_ha",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    features = pivot[["geocodigo", "ano"]].copy()
    for name, product_codes in PRODUCT_FEATURES.items():
        cols = [code for code in product_codes if code in pivot.columns]
        value = pivot[cols].sum(axis=1) if cols else 0.0
        features[f"crop_area_{name}_ha"] = value

    features["crop_area_biomass_proxy_ha"] = features[
        [f"crop_area_{name}_ha" for name in BIOMASS_PROXY_PRODUCTS]
    ].sum(axis=1)
    features["crop_area_dry_residue_proxy_ha"] = features[
        [f"crop_area_{name}_ha" for name in DRY_RESIDUE_PROXY_PRODUCTS]
    ].sum(axis=1)
    features = features.merge(nodes, on="geocodigo", how="left")
    features["crop_area_total_per_km2"] = features["crop_area_total_ha"] / features["area_km2"].clip(lower=1e-6)
    features["crop_area_biomass_proxy_per_km2"] = features["crop_area_biomass_proxy_ha"] / features[
        "area_km2"
    ].clip(lower=1e-6)
    for col in [
        "crop_area_total_ha",
        "crop_area_biomass_proxy_ha",
        "crop_area_dry_residue_proxy_ha",
        "crop_area_total_per_km2",
        "crop_area_biomass_proxy_per_km2",
    ]:
        features[f"{col}_log1p"] = features[col].clip(lower=0).apply(math.log1p)
    denominator = features["crop_area_total_ha"].replace(0, math.nan)
    for name in ["milho", "feijao", "mandioca", "cana_acucar", "algodao", "arroz", "sorgo"]:
        features[f"crop_area_share_{name}"] = (features[f"crop_area_{name}_ha"] / denominator).fillna(0.0)

    long = long.sort_values(["geocodigo", "ano", "product_code"])
    features = features.sort_values(["geocodigo", "ano"])
    long_path = OUT_DIR / "annual_crop_area_long.csv"
    features_path = OUT_DIR / "annual_crop_area_features.csv"
    long.to_csv(long_path, index=False)
    features.to_csv(features_path, index=False)

    raw_symbol_counts = long["raw_value"].fillna("<null>").astype(str).value_counts().head(20).to_dict()
    manifest = {
        "snapshot_name": "ibge_pam_crop_area_v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_name": "IBGE SIDRA",
        "dataset_name": "Tabela 1612 - Producao Agricola Municipal: lavouras temporarias",
        "official_url": OFFICIAL_URL,
        "api_template": ENDPOINT_TEMPLATE,
        "sidra_table": SIDRA_TABLE,
        "sidra_variable": SIDRA_VARIABLE,
        "sidra_variable_name": "Area plantada",
        "sidra_category_dimension": f"c{PRODUCT_DIMENSION}/all",
        "role": "annual_crop_fuel_land_use_proxy",
        "license": "Dados abertos IBGE",
        "temporal_resolution": "annual",
        "spatial_resolution": "municipality",
        "keys": ["geocodigo", "ano"],
        "requested_years": YEARS,
        "available_years": sorted(int(y) for y in total_counts),
        "missing_years": missing_years,
        "target_municipalities": len(codes),
        "long_rows": int(len(long)),
        "feature_rows": int(len(features)),
        "product_feature_codes": PRODUCT_FEATURES,
        "biomass_proxy_products": BIOMASS_PROXY_PRODUCTS,
        "dry_residue_proxy_products": DRY_RESIDUE_PROXY_PRODUCTS,
        "available_at_rule": "Experiments must use the latest PAM crop-area estimate with year <= forecast_year - 1 unless official same-year publication date is encoded; no missing years are interpolated.",
        "symbol_handling": {
            "numeric": "parsed as hectares",
            "dash_or_ellipsis": "kept in raw_value and converted to 0.0 for planted-area absence/not-available category aggregation",
        },
        "raw_value_top_counts": raw_symbol_counts,
        "raw_files": [
            {"path": str(path.relative_to(PROJECT_ROOT)), "sha256": sha256_file(path)} for path in raw_files
        ],
        "outputs": {
            "annual_crop_area_long.csv": {"sha256": sha256_file(long_path), "rows": int(len(long))},
            "annual_crop_area_features.csv": {"sha256": sha256_file(features_path), "rows": int(len(features))},
        },
        "quality_rules": [
            "fail if any available year has partial target municipality coverage for total planted area",
            "use geocodigo IBGE as key",
            "derive density/share/log features from official planted area only",
            "do not use same-year estimates in backtests without explicit publication date",
        ],
    }
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"snapshot": manifest["snapshot_name"], "rows": len(features), "manifest": str(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



