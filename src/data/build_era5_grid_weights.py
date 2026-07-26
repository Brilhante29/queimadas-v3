"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/build_era5_grid_weights.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MALHA = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi.geojson"
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_v1"
RES_DEG = 0.25


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_era5_grid_weights.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/build_era5_grid_weights.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = pd.read_csv(TARGET)[["geocodigo"]].drop_duplicates()
    mun = gpd.read_file(MALHA).merge(target, on="geocodigo", how="inner")
    if len(mun) != len(target):
        raise ValueError("Malha não cobre todos os municípios-alvo")

    minx, miny, maxx, maxy = mun.total_bounds
    lons = np.arange(np.floor((minx - RES_DEG) / RES_DEG) * RES_DEG, np.ceil((maxx + RES_DEG) / RES_DEG) * RES_DEG + 1e-9, RES_DEG)
    lats = np.arange(np.floor((miny - RES_DEG) / RES_DEG) * RES_DEG, np.ceil((maxy + RES_DEG) / RES_DEG) * RES_DEG + 1e-9, RES_DEG)
    cells = []
    for lon in lons:
        for lat in lats:
            geom = box(lon - RES_DEG / 2, lat - RES_DEG / 2, lon + RES_DEG / 2, lat + RES_DEG / 2)
            cells.append({"cell_id": f"era5_{lat:.3f}_{lon:.3f}", "lat": round(float(lat), 3), "lon": round(float(lon), 3), "geometry": geom})
    grid = gpd.GeoDataFrame(cells, geometry="geometry", crs="EPSG:4326")
    grid = grid[grid.intersects(mun.union_all())].reset_index(drop=True)

    mun_m = mun.to_crs("EPSG:5880")
    grid_m = grid.to_crs("EPSG:5880")
    rows = []
    for _, m in mun_m.iterrows():
        m_area = float(m.geometry.area)
        hits = grid_m[grid_m.intersects(m.geometry)]
        for _, c in hits.iterrows():
            inter_area = float(m.geometry.intersection(c.geometry).area)
            if inter_area <= 0:
                continue
            rows.append({
                "geocodigo": int(m["geocodigo"]),
                "municipio_ibge": m["municipio_ibge"],
                "cell_id": c["cell_id"],
                "cell_lat": float(c["lat"]),
                "cell_lon": float(c["lon"]),
                "area_weight": inter_area / m_area,
                "intersection_area_km2": inter_area / 1_000_000,
            })
    weights = pd.DataFrame(rows)
    sums = weights.groupby("geocodigo")["area_weight"].sum().reset_index(name="weight_sum")
    if not np.allclose(sums["weight_sum"], 1.0, atol=0.01):
        raise ValueError("Pesos zonais não somam ~1 para todos os municípios")
    weights.to_csv(OUT_DIR / "era5_cell_weights.csv", index=False)
    grid.drop(columns="geometry").to_csv(OUT_DIR / "era5_grid_cells.csv", index=False)
    sums.to_csv(OUT_DIR / "weight_sums.csv", index=False)

    manifest = {
        "snapshot_name": "era5_grid_weights_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "spatial_weights_for_era5_zonal_statistics",
        "source_geometry": str(MALHA.relative_to(PROJECT_ROOT)),
        "source_geometry_sha256": sha256_file(MALHA),
        "era5_resolution_degrees": RES_DEG,
        "crs_area_calculation": "EPSG:5880",
        "target_municipalities": int(len(target)),
        "grid_cells_intersecting_target": int(len(grid)),
        "weight_rows": int(len(weights)),
        "weights_sha256": sha256_file(OUT_DIR / "era5_cell_weights.csv"),
        "limitations": ["grade regular 0,25° aproximada para ERA5; validar alinhamento exato quando baixar ERA5 em grade", "não substitui dados climáticos zonais até valores por célula serem ingeridos"],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"municipalities": len(target), "cells": len(grid), "weight_rows": len(weights)}, indent=2))


if __name__ == "__main__":
    main()
