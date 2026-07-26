"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_human_geospatial.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import pandas as pd
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def ingest_mapbiomas(
    search_paths=None,
    output_dir="outputs",
    scope="ceara",
):
    """Executa a etapa `ingest mapbiomas` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_human_geospatial.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if search_paths is None:
        search_paths = ['.', './data', './inputs', '/mnt/data']
    
    logger.info("MapBiomas: searching...")
    
    # Procurar arquivos
    import glob
    found = []
    for path in search_paths:
        if os.path.exists(path):
            for pattern in ['*mapbio*', '*land_use*', '*cobertura*', '*uso_solo*']:
                found.extend(glob.glob(os.path.join(path, pattern), recursive=True))
    
    if found:
        logger.info(f"  MapBiomas files found: {len(found)}")
    else:
        logger.warning("  No MapBiomas files found. Using fallback.")
    
    # Criar features humanas com fallback
    from src.data.ingest_open_meteo import load_municipality_coords
    coords = load_municipality_coords(scope)
    
    records = []
    for _, row in coords.iterrows():
        # Valores placeholder — serão substituídos quando dados reais disponíveis
        records.append({
            'municipio_id': row['municipio_id'],
            'municipio_nome': row['municipio_nome'],
            'estado': row['estado'],
            'agriculture_share': np.nan,
            'pasture_share': np.nan,
            'forest_share': np.nan,
            'urban_share': np.nan,
            'land_use_change_1y': np.nan,
            'mapbiomas_available': 0,
            'human_pressure_index': np.nan,
        })
    
    df = pd.DataFrame(records)
    df.to_csv(f"{output_dir}/mapbiomas_features.csv", index=False)
    
    # Template para preenchimento futuro
    template = df[['municipio_id', 'municipio_nome', 'estado']].copy()
    template.to_csv(f"{output_dir}/mapbiomas_template_required.csv", index=False)
    
    report = pd.DataFrame([{'source': 'mapbiomas', 'available': len(found) > 0, 'scope': scope}])
    report.to_csv(f"{output_dir}/mapbiomas_coverage_report.csv", index=False)
    
    return df


def ingest_osm(
    search_paths=None,
    output_dir="outputs",
    scope="ceara",
):
    """Executa a etapa `ingest osm` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_human_geospatial.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    logger.info("OSM: searching...")
    
    from src.data.ingest_open_meteo import load_municipality_coords
    coords = load_municipality_coords(scope)
    
    records = []
    for _, row in coords.iterrows():
        records.append({
            'municipio_id': row['municipio_id'],
            'municipio_nome': row['municipio_nome'],
            'estado': row['estado'],
            'road_density_km_km2': np.nan,
            'distance_to_nearest_road': np.nan,
            'osm_available': 0,
            'ignition_exposure_index': np.nan,
        })
    
    df = pd.DataFrame(records)
    df.to_csv(f"{output_dir}/osm_features.csv", index=False)
    
    report = pd.DataFrame([{'source': 'osm', 'available': False, 'scope': scope}])
    report.to_csv(f"{output_dir}/osm_coverage_report.csv", index=False)
    
    return df


def ingest_ibge(
    search_paths=None,
    output_dir="outputs",
    scope="ceara",
):
    """Executa a etapa `ingest ibge` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_human_geospatial.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    logger.info("IBGE: searching...")
    
    from src.data.ingest_open_meteo import load_municipality_coords
    coords = load_municipality_coords(scope)
    
    records = []
    for _, row in coords.iterrows():
        records.append({
            'municipio_id': row['municipio_id'],
            'municipio_nome': row['municipio_nome'],
            'estado': row['estado'],
            'area_km2': np.nan,
            'population_density': np.nan,
            'rural_population_share': np.nan,
            'agricultural_gdp_share': np.nan,
            'ibge_available': 0,
        })
    
    df = pd.DataFrame(records)
    df.to_csv(f"{output_dir}/ibge_municipal_features.csv", index=False)
    
    report = pd.DataFrame([{'source': 'ibge', 'available': False, 'scope': scope}])
    report.to_csv(f"{output_dir}/ibge_coverage_report.csv", index=False)
    
    return df


def ingest_all_human_geospatial(scope="ceara", output_dir="outputs"):
    """Executa a etapa `ingest all human geospatial` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_human_geospatial.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    logger.info("=" * 60)
    logger.info("Human/Geospatial Ingestion")
    logger.info("=" * 60)
    
    mapbio = ingest_mapbiomas(scope=scope, output_dir=output_dir)
    osm = ingest_osm(scope=scope, output_dir=output_dir)
    ibge = ingest_ibge(scope=scope, output_dir=output_dir)
    
    return {"mapbiomas": mapbio, "osm": osm, "ibge": ibge}
