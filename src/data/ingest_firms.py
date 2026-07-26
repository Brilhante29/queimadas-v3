"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_firms.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import time
import requests
import pandas as pd
import numpy as np
from typing import Optional, List
from io import StringIO
import logging

logger = logging.getLogger(__name__)

# NASA FIRMS API
FIRMS_API_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
# Chave real e gratuita, uma por usuário: https://firms.modaps.eosdis.nasa.gov/api/map_key/
# Nunca hardcodar aqui; sem a variável de ambiente, a ingestão deve falhar
# fechada em vez de usar uma chave demo/pública silenciosamente.
FIRMS_API_KEY = os.environ.get("FIRMS_MAP_KEY")

# Bounding boxes por estado
STATE_BBOX = {
    "CE": [-41.5, -8.0, -37.0, -2.5],    # Ceará
    "PE": [-42.0, -10.0, -34.5, -7.0],    # Pernambuco
    "PI": [-46.0, -11.0, -40.5, -2.5],    # Piaui
}

SATELLITES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"]


def fetch_firms(
    state: str,
    year: int,
    month: int,
    satellite: str = "VIIRS_SNPP_NRT",
    api_key: str | None = FIRMS_API_KEY,
) -> Optional[pd.DataFrame]:
    """Executa a etapa `fetch firms` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not api_key:
        raise ValueError(
            "FIRMS_MAP_KEY ausente no ambiente. Gerar chave gratuita em "
            "https://firms.modaps.eosdis.nasa.gov/api/map_key/ e exportar "
            "FIRMS_MAP_KEY antes de rodar este ingestor (fail-closed: nunca "
            "usar chave demo/pública silenciosamente)."
        )
    if state not in STATE_BBOX:
        logger.warning(f"No bbox for state {state}")
        return None
    
    bbox = STATE_BBOX[state]
    bbox_str = ",".join(map(str, bbox))
    
    # Date range
    from datetime import datetime, timedelta
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1) - timedelta(days=1)
    
    date_range = f"{start_date.strftime('%Y-%m-%d')}..{end_date.strftime('%Y-%m-%d')}"
    
    url = f"{FIRMS_API_URL}/{api_key}/{satellite}/{bbox_str}/1/{date_range}"
    
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 200 and len(resp.text) > 100:
            df = pd.read_csv(StringIO(resp.text))
            df['state'] = state
            df['satellite'] = satellite
            df['year'] = year
            df['month'] = month
            return df
        else:
            logger.warning(f"FIRMS {state} {year}-{month}: status={resp.status_code}, len={len(resp.text)}")
            return None
    except Exception as e:
        logger.warning(f"FIRMS error {state} {year}-{month}: {e}")
        return None


def aggregate_firms_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `aggregate firms monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if df is None or len(df) == 0:
        return pd.DataFrame()
    
    if 'municipio' not in df.columns and 'admin_name' in df.columns:
        df['municipio'] = df['admin_name']
    if 'municipio' not in df.columns:
        raise ValueError(
            "FIRMS response has no municipality/admin_name column. "
            "Do a real geospatial join to IBGE municipalities before aggregation; "
            "lat/lon rounded is not a valid municipal identity."
        )
    
    # Normalize
    import unicodedata
    df['municipio_norm'] = df['municipio'].astype(str).str.lower().str.strip()
    df['municipio_norm'] = df['municipio_norm'].apply(
        lambda x: unicodedata.normalize('NFKD', x).encode('ASCII', 'ignore').decode('ASCII')
        .replace("'", "").replace("-", " ")
    )
    
    if 'estado' not in df.columns:
        if 'state' in df.columns:
            df['estado'] = df['state']
        elif 'admin1' in df.columns:
            df['estado'] = df['admin1']
        else:
            raise ValueError(
                "FIRMS response has no estado/state/admin1 column. "
                "Do not assume a default UF; attach state via geospatial join."
            )
    
    # Aggregate
    agg_dict = {
        'fire_count': ('municipio_norm', 'size'),
        'FRP_sum': ('frp', 'sum') if 'frp' in df.columns else ('brightness', 'sum') if 'brightness' in df.columns else ('municipio_norm', 'count'),
        'FRP_mean': ('frp', 'mean') if 'frp' in df.columns else ('brightness', 'mean') if 'brightness' in df.columns else ('municipio_norm', 'count'),
    }
    
    try:
        grouped = df.groupby(['municipio_norm', 'estado', 'year', 'month']).agg(**agg_dict).reset_index()
    except Exception as exc:
        raise ValueError(
            "FIRMS aggregation failed; do not silently replace FRP fields with zeros."
        ) from exc
    
    grouped['source_name'] = 'NASA_FIRMS'
    grouped['hist_positive'] = (grouped['fire_count'] > 0).astype(int)
    
    return grouped


def ingest_firms_all(
    states: List[str] = None,
    start_year: int = 2015,
    end_year: int = 2025,
    output_dir: str = "outputs",
    cache_dir: str = "cache/firms",
) -> Optional[pd.DataFrame]:
    """Executa a etapa `ingest firms all` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if states is None:
        states = ["CE"]
    
    logger.info("=" * 60)
    logger.info(f"NASA FIRMS Ingestion: {states}")
    logger.info(f"Period: {start_year}-{end_year}")
    logger.info("=" * 60)
    
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    
    all_records = []
    
    for state in states:
        for year in range(start_year, end_year + 1):
            for month in range(1, 13):
                cache_file = os.path.join(cache_dir, f"{state}_{year}_{month:02d}.csv")
                
                if os.path.exists(cache_file):
                    df = pd.read_csv(cache_file)
                else:
                    # Try each satellite
                    df = None
                    for sat in SATELLITES:
                        df = fetch_firms(state, year, month, satellite=sat)
                        if df is not None and len(df) > 0:
                            break
                    
                    if df is not None and len(df) > 0:
                        df.to_csv(cache_file)
                        time.sleep(0.5)
                
                if df is not None and len(df) > 0:
                    monthly = aggregate_firms_monthly(df)
                    if len(monthly) > 0:
                        all_records.append(monthly)
    
    if not all_records:
        logger.error("No FIRMS data retrieved!")
        return None
    
    df_final = pd.concat(all_records, ignore_index=True)
    df_final.to_csv(f"{output_dir}/inpe_monthly.csv", index=False)
    
    logger.info(f"FIRMS saved: {len(df_final)} municipality-month records")
    logger.info(f"  Municipalities: {df_final['municipio_norm'].nunique()}")
    logger.info(f"  Zeros: {(df_final['fire_count'] == 0).mean()*100:.1f}%")
    logger.info(f"  Max fire count: {df_final['fire_count'].max()}")
    
    return df_final
