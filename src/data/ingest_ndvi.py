"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_ndvi.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import glob
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def find_ndvi_files(search_paths):
    """Executa a etapa `find ndvi files` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ndvi.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    patterns = [
        "*NDVI*.csv", "*ndvi*.csv", "*NDVI*.csv", "*vegetation*.csv",
        "*EVI*.csv", "*modis*.csv", "*sentinel*.csv",
    ]
    found = []
    for path in search_paths:
        if not os.path.exists(path):
            continue
        for pattern in patterns:
            found.extend(glob.glob(os.path.join(path, pattern), recursive=True))
    return found


def read_ndvi_csv(filepath):
    """Carrega a etapa `read ndvi csv` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ndvi.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    try:
        df = pd.read_csv(filepath, encoding='latin-1', low_memory=False)
        # Detect common column names
        col_map = {}
        for col in df.columns:
            c = col.lower().strip()
            if 'municip' in c or 'cidade' in c or 'nome' in c:
                col_map[col] = 'municipio_nome'
            elif 'ano' in c or 'year' in c:
                col_map[col] = 'ano'
            elif 'mes' in c or 'month' in c:
                col_map[col] = 'mes'
            elif 'ndvi' in c:
                col_map[col] = 'ndvi'
            elif 'evi' in c:
                col_map[col] = 'evi'
        
        df = df.rename(columns=col_map)
        
        # Normalize municipality names
        if 'municipio_nome' in df.columns:
            import unicodedata
            df['municipio_nome'] = df['municipio_nome'].astype(str).str.lower().str.strip()
            df['municipio_nome'] = df['municipio_nome'].apply(
                lambda x: unicodedata.normalize('NFKD', x).encode('ASCII', 'ignore').decode('ASCII')
            )
        
        return df
    except Exception as e:
        logger.warning(f"Error reading NDVI {filepath}: {e}")
        return None


def ingest_ndvi(
    search_paths=None,
    output_dir="outputs",
    scope="ceara",
):
    """Executa a etapa `ingest ndvi` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_ndvi.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if search_paths is None:
        search_paths = ['.', './data', './inputs', '/mnt/data', '/mnt/data']
    
    logger.info("=" * 60)
    logger.info("NDVI Ingestion")
    logger.info("=" * 60)
    
    ndvi_files = find_ndvi_files(search_paths)
    logger.info(f"NDVI files found: {len(ndvi_files)}")
    for f in ndvi_files:
        logger.info(f"  {f}")
    
    all_ndvi = []
    for f in ndvi_files:
        df = read_ndvi_csv(f)
        if df is not None and len(df) > 0:
            all_ndvi.append(df)
    
    if all_ndvi:
        df_combined = pd.concat(all_ndvi, ignore_index=True)
        df_combined['ndvi_available'] = 1
        logger.info(f"NDVI loaded: {len(df_combined)} records from files")
        
        # Generate features
        if 'ndvi' in df_combined.columns:
            df_combined['ndvi_lag1'] = df_combined.groupby('municipio_nome')['ndvi'].shift(1)
            df_combined['ndvi_lag2'] = df_combined.groupby('municipio_nome')['ndvi'].shift(2)
            df_combined['ndvi_lag3'] = df_combined.groupby('municipio_nome')['ndvi'].shift(3)
            df_combined['ndvi_roll3'] = df_combined.groupby('municipio_nome')['ndvi'].transform(lambda x: x.rolling(3, min_periods=1).mean())
            
            # Anomaly
            if 'ano' in df_combined.columns and 'mes' in df_combined.columns:
                clim = df_combined.groupby('mes')['ndvi'].mean()
                df_combined['ndvi_anomaly'] = df_combined.apply(lambda r: r['ndvi'] - clim.get(r['mes'], 0), axis=1)
            
            # Drop
            df_combined['ndvi_drop_2m'] = df_combined.groupby('municipio_nome')['ndvi'].transform(lambda x: x - x.shift(2))
            df_combined['ndvi_drop_3m'] = df_combined.groupby('municipio_nome')['ndvi'].transform(lambda x: x - x.shift(3))
    else:
        logger.warning("No NDVI files found. Creating placeholder with missing indicator.")
        # Create template with missing indicator
        from src.data.ingest_open_meteo import load_municipality_coords
        coords = load_municipality_coords(scope)
        
        records = []
        for _, row in coords.iterrows():
            for year in range(2015, 2026):
                for month in range(1, 13):
                    records.append({
                        'municipio_nome': row['municipio_nome'],
                        'municipio_id': row['municipio_id'],
                        'estado': row['estado'],
                        'ano': year,
                        'mes': month,
                        'ndvi': np.nan,
                        'ndvi_available': 0,
                        'ndvi_lag1': np.nan,
                        'ndvi_lag2': np.nan,
                        'ndvi_lag3': np.nan,
                        'ndvi_roll3': np.nan,
                        'ndvi_anomaly': np.nan,
                        'ndvi_drop_2m': np.nan,
                        'ndvi_drop_3m': np.nan,
                    })
        df_combined = pd.DataFrame(records)
    
    df_combined.to_csv(f"{output_dir}/ndvi_monthly.csv", index=False)
    
    report = pd.DataFrame([{
        'source': 'ndvi',
        'files_found': len(ndvi_files),
        'records': len(df_combined),
        'has_real_data': len(all_ndvi) > 0,
        'scope': scope,
    }])
    report.to_csv(f"{output_dir}/ndvi_coverage_report.csv", index=False)
    
    logger.info(f"NDVI saved: {len(df_combined)} records")
    return df_combined
