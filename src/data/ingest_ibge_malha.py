"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_ibge_malha.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024"
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
UFS = ["CE", "PE", "PI"]
API_TEMPLATE = "https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf}?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio"
OFFICIAL_PAGE = "https://www.ibge.gov.br/geociencias/organizacao-do-territorio/malhas-territoriais/15774-malhas.html"


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_malha.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_uf(uf: str) -> Path:
    """Executa a etapa `fetch uf` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ibge_malha.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    raw = SNAPSHOT_DIR / "raw" / f"{uf}_municipios_2024_minima.geojson"
    raw.parent.mkdir(parents=True, exist_ok=True)
    url = API_TEMPLATE.format(uf=uf)
    resp = requests.get(url, timeout=120, headers={"Accept": "application/vnd.geo+json"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise ValueError(f"Resposta IBGE inválida para {uf}")
    raw.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return raw


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_ibge_malha.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    files = []
    frames = []
    for uf in UFS:
        raw = fetch_uf(uf)
        gdf = gpd.read_file(raw)
        gdf["uf"] = uf
        frames.append(gdf)
        files.append({"uf": uf, "path": str(raw.relative_to(PROJECT_ROOT)), "sha256": sha256_file(raw), "features": int(len(gdf))})

    malha = pd.concat(frames, ignore_index=True)
    code_col = "codarea" if "codarea" in malha.columns else "CD_MUN"
    malha["geocodigo"] = malha[code_col].astype(str).str.extract(r"(\d+)")[0].astype(int)

    # A API de malhas em qualidade mínima retorna só o código e a geometria;
    # nomes vêm do snapshot oficial de localidades já versionado no repo.
    ref = pd.read_json(PROJECT_ROOT / "data" / "reference" / "ibge_municipios_CE_PE_PI.json", encoding="utf-8-sig")
    ref = ref.rename(columns={"nome": "municipio_ibge"})[["geocodigo", "municipio_ibge", "uf"]]
    malha = malha.drop(columns=["uf"], errors="ignore").merge(ref, on="geocodigo", how="left")
    if malha["municipio_ibge"].isna().any():
        missing = malha.loc[malha["municipio_ibge"].isna(), "geocodigo"].tolist()
        raise ValueError(f"Geometrias sem nome no snapshot de referência: {missing[:10]}")
    malha = gpd.GeoDataFrame(malha[["geocodigo", "municipio_ibge", "uf", "geometry"]], geometry="geometry", crs="EPSG:4326")
    malha.to_file(SNAPSHOT_DIR / "municipios_ce_pe_pi.geojson", driver="GeoJSON")

    # áreas aproximadas em CRS métrico brasileiro, suficientes para QA de cobertura.
    metric = malha.to_crs("EPSG:5880")
    malha["area_km2_approx"] = metric.area / 1_000_000
    cent = metric.geometry.centroid.to_crs("EPSG:4326")
    malha["centroid_lon"] = cent.x
    malha["centroid_lat"] = cent.y
    attrs = pd.DataFrame(malha.drop(columns="geometry"))
    attrs.to_csv(SNAPSHOT_DIR / "municipios_ce_pe_pi_attributes.csv", index=False)

    target = pd.read_csv(TARGET)[["geocodigo", "municipio_ibge", "uf"]].drop_duplicates()
    coverage = target.merge(attrs, on="geocodigo", how="left", suffixes=("_target", "_malha"))
    coverage["coverage_status"] = coverage["area_km2_approx"].notna().map({True: "OK", False: "MISSING_GEOMETRY"})
    coverage.to_csv(SNAPSHOT_DIR / "target_geometry_coverage.csv", index=False)
    missing = coverage[coverage["coverage_status"] != "OK"]
    if not missing.empty:
        raise ValueError(f"Municípios-alvo sem geometria IBGE: {missing['geocodigo'].tolist()}")

    manifest = {
        "snapshot_name": "ibge_malha_municipal_2024",
        "retrieved_at": retrieved_at,
        "role": "municipal_geometry",
        "official_page": OFFICIAL_PAGE,
        "api_template": API_TEMPLATE,
        "ufs": UFS,
        "format": "GeoJSON via API v3 malhas, qualidade=minima, intrarregiao=municipio",
        "crs": "EPSG:4326",
        "files": files,
        "merged_geojson": str((SNAPSHOT_DIR / "municipios_ce_pe_pi.geojson").relative_to(PROJECT_ROOT)),
        "merged_geojson_sha256": sha256_file(SNAPSHOT_DIR / "municipios_ce_pe_pi.geojson"),
        "attributes_sha256": sha256_file(SNAPSHOT_DIR / "municipios_ce_pe_pi_attributes.csv"),
        "target_coverage": {"target_municipalities": int(len(target)), "covered": int((coverage["coverage_status"] == "OK").sum())},
        "limitations": ["qualidade=minima adequada para smoke/zonal inicial; confirmar escala final antes de produção", "áreas são aproximações para QA; pesos zonais devem usar CRS equal-area consistente"],
    }
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest["target_coverage"], indent=2))
    print(f"OK: snapshot em {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()
