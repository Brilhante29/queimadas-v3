"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_inpe.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import glob
import zipfile
import pandas as pd
import numpy as np
import requests
from io import BytesIO
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# URLs da API BDQueimadas
BDQUEIMADAS_API = "https://queimadas.dgi.inpe.br/queimadas/dados-abertos/api/focos"


def discover_inpe_archives(search_paths: List[str]) -> List[str]:
    """Executa a etapa `discover inpe archives` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    found = []
    patterns = [
        "dados_INPE.zip", "dados_INPE_Monitor.zip", "dados.zip",
        "availability.zip", "drive-download*.zip", "*queimada*.csv",
        "*foco*.csv", "*fire*.csv", "*incendio*.csv",
    ]
    for path in search_paths:
        if not os.path.exists(path):
            continue
        for pattern in patterns:
            matches = glob.glob(os.path.join(path, pattern), recursive=True)
            found.extend(matches)
    logger.info(f"INPE archives found: {len(found)}")
    return found


def read_inpe_zip(zip_path: str) -> Optional[pd.DataFrame]:
    """Carrega a etapa `read inpe zip` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    records = []
    try:
        with zipfile.ZipFile(zip_path, 'r') as z:
            csv_files = [f for f in z.namelist() if f.endswith('.csv')]
            logger.info(f"  ZIP {zip_path}: {len(csv_files)} CSV files")
            for csv_file in csv_files:
                try:
                    with z.open(csv_file) as f:
                        df = pd.read_csv(f, encoding='latin-1', low_memory=False)
                        df.attrs['source_file'] = csv_file
                        df.attrs['source_zip'] = zip_path
                        records.append(df)
                except Exception as e:
                    logger.warning(f"  Error reading {csv_file}: {e}")
    except Exception as e:
        logger.error(f"Error opening {zip_path}: {e}")
        return None
    
    if records:
        return pd.concat(records, ignore_index=True)
    return None


def normalize_municipality_names(name: str) -> str:
    """Executa a etapa `normalize municipality names` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if pd.isna(name):
        return ""
    import unicodedata
    name = str(name).lower().strip()
    name = unicodedata.normalize('NFKD', name).encode('ASCII', 'ignore').decode('ASCII')
    name = name.replace("'", "").replace("-", " ").replace("  ", " ")
    return name


def deduplicate_fire_events(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `deduplicate fire events` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if 'DataHora' not in df.columns and 'data_hora_gmt' not in df.columns:
        logger.warning("No datetime column found for deduplication")
        return df
    
    datetime_col = 'DataHora' if 'DataHora' in df.columns else 'data_hora_gmt'
    
    # Round coordinates to 3 decimal places (~100m) for dedup
    for col in ['latitude', 'longitude']:
        if col in df.columns:
            df[col] = df[col].round(3)
    
    # Normalize municipality
    if 'municipio' in df.columns:
        df['municipio_norm'] = df['municipio'].apply(normalize_municipality_names)
    elif 'MUNICIPIO' in df.columns:
        df['municipio_norm'] = df['MUNICIPIO'].apply(normalize_municipality_names)
    else:
        df['municipio_norm'] = 'unknown'
    
    # Deduplicate
    subset_cols = [datetime_col]
    if 'satelite' in df.columns:
        subset_cols.append('satelite')
    elif 'satellite' in df.columns:
        subset_cols.append('satellite')
    subset_cols.extend(['latitude', 'longitude', 'municipio_norm'])
    subset_cols = [c for c in subset_cols if c in df.columns]
    
    before = len(df)
    df = df.drop_duplicates(subset=subset_cols)
    after = len(df)
    logger.info(f"  Deduplication: {before} -> {after} ({before-after} removed)")
    
    return df


def aggregate_monthly_fire(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `aggregate monthly fire` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    # Parse datetime
    datetime_col = None
    for col in ['DataHora', 'data_hora_gmt', 'datahora']:
        if col in df.columns:
            datetime_col = col
            break
    
    if datetime_col:
        df['datetime'] = pd.to_datetime(df[datetime_col], errors='coerce')
        df['ano'] = df['datetime'].dt.year
        df['mes'] = df['datetime'].dt.month
    else:
        # Try separate columns
        for col_year in ['ano', 'year', 'Ano']:
            if col_year in df.columns:
                df['ano'] = df[col_year]
                break
        for col_month in ['mes', 'month', 'Mes']:
            if col_month in df.columns:
                df['mes'] = df[col_month]
                break
    
    # Municipality
    if 'municipio_norm' not in df.columns:
        if 'municipio' in df.columns:
            df['municipio_norm'] = df['municipio'].apply(normalize_municipality_names)
        elif 'MUNICIPIO' in df.columns:
            df['municipio_norm'] = df['MUNICIPIO'].apply(normalize_municipality_names)
        else:
            df['municipio_norm'] = 'unknown'
    
    # State
    if 'estado' not in df.columns and 'uf' in df.columns:
        df['estado'] = df['uf']
    elif 'estado' not in df.columns and 'ESTADO' in df.columns:
        df['estado'] = df['ESTADO']
    elif 'estado' not in df.columns:
        df['estado'] = 'unknown'
    
    # Filter valid records
    valid_mask = df['ano'].notna() & df['mes'].notna() & df['municipio_norm'].notna()
    df = df[valid_mask].copy()
    
    # Aggregations
    agg_dict = {'municipio_norm': 'first'}
    
    # Fire count
    agg_dict['fire_count'] = ('municipio_norm', 'size')
    
    # FRP
    frp_col = None
    for col in ['frp', 'FRP', 'Frp', 'rsp']:
        if col in df.columns:
            frp_col = col
            break
    if frp_col:
        agg_dict['FRP_sum'] = (frp_col, 'sum')
        agg_dict['FRP_mean'] = (frp_col, 'mean')
        agg_dict['FRP_p90'] = (frp_col, lambda x: x.quantile(0.9) if len(x) > 0 else 0)
    
    # Dias sem chuva
    for col in ['dias_sem_chuva', 'diasemchuva', 'dias_sem_chuva_mean']:
        if col in df.columns:
            agg_dict['dias_sem_chuva_mean'] = (col, 'mean')
            break
    
    # Precipitação
    for col in ['precipitacao', 'precipitation', 'chuva']:
        if col in df.columns:
            agg_dict['precipitacao_evento_mean'] = (col, 'mean')
            break
    
    # Risco de fogo
    for col in ['risco_fogo', 'riscofogo', 'fire_risk']:
        if col in df.columns:
            agg_dict['risco_fogo_evento_mean'] = (col, 'mean')
            break
    
    # Source count
    agg_dict['source_event_count'] = ('municipio_norm', 'size')
    
    # Group by
    grouped = df.groupby(['municipio_norm', 'estado', 'ano', 'mes']).agg(**agg_dict).reset_index()
    
    # Ensure fire_count exists
    if 'fire_count' not in grouped.columns:
        count_df = df.groupby(['municipio_norm', 'estado', 'ano', 'mes']).size().reset_index(name='fire_count')
        grouped = grouped.merge(count_df, on=['municipio_norm', 'estado', 'ano', 'mes'], how='left')
    
    # Add source name
    grouped['source_name'] = 'INPE'
    
    logger.info(f"  Monthly aggregation: {len(grouped)} municipality-month records")
    logger.info(f"  Zeros: {(grouped['fire_count'] == 0).sum()} ({(grouped['fire_count'] == 0).mean()*100:.1f}%)")
    
    return grouped


def fetch_inpe_api(
    states: List[str],
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """Executa a etapa `fetch inpe api` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    logger.info(f"Fetching INPE API for states {states} from {start_date} to {end_date}")
    
    all_records = []
    
    for state in states:
        try:
            params = {
                'estado': state,
                'data_inicio': start_date,
                'data_fim': end_date,
                'formato': 'csv'
            }
            response = requests.get(BDQUEIMADAS_API, params=params, timeout=60)
            if response.status_code == 200:
                df = pd.read_csv(BytesIO(response.content), encoding='latin-1')
                df['estado'] = state
                all_records.append(df)
                logger.info(f"  {state}: {len(df)} records")
            else:
                logger.warning(f"  API returned {response.status_code} for {state}")
        except Exception as e:
            logger.warning(f"  Error fetching {state}: {e}")
    
    if all_records:
        return pd.concat(all_records, ignore_index=True)
    return None


def ingest_inpe(
    mode: str = "hybrid",
    search_paths: List[str] = None,
    states: List[str] = None,
    start_date: str = "2003-01-01",
    end_date: str = "2025-12-31",
    output_dir: str = "outputs",
) -> Optional[pd.DataFrame]:
    """Executa a etapa `ingest inpe` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if search_paths is None:
        search_paths = ['.', './data', './inputs', '/mnt/data', '/mnt/data']
    
    if states is None:
        states = ['CE', 'PE', 'PI']
    
    logger.info("=" * 60)
    logger.info("INPE Ingestion")
    logger.info(f"Mode: {mode}, States: {states}")
    logger.info("=" * 60)
    
    all_events = []
    
    # Local mode
    if mode in ['local', 'hybrid']:
        archives = discover_inpe_archives(search_paths)
        for archive in archives:
            logger.info(f"Processing: {archive}")
            df = read_inpe_zip(archive)
            if df is not None and len(df) > 0:
                all_events.append(df)
    
    # API mode
    if mode in ['api', 'hybrid']:
        df_api = fetch_inpe_api(states, start_date, end_date)
        if df_api is not None:
            all_events.append(df_api)
    
    if not all_events:
        logger.error("No INPE data found from any source!")
        return None
    
    # Combine
    df_combined = pd.concat(all_events, ignore_index=True)
    logger.info(f"Combined events: {len(df_combined)}")
    
    # Process
    df_combined = deduplicate_fire_events(df_combined)
    df_monthly = aggregate_monthly_fire(df_combined)
    
    # Save
    os.makedirs(output_dir, exist_ok=True)
    df_monthly.to_csv(f"{output_dir}/inpe_monthly.csv", index=False)
    
    # Report
    report = pd.DataFrame([{
        'file_name': 'inpe_monthly.csv',
        'absolute_path': os.path.abspath(f"{output_dir}/inpe_monthly.csv"),
        'file_type': 'parquet',
        'size_bytes': os.path.getsize(f"{output_dir}/inpe_monthly.csv"),
        'rows': len(df_monthly),
        'columns': len(df_monthly.columns),
        'date_min': f"{df_monthly['ano'].min()}-{int(df_monthly['mes'].min()):02d}" if len(df_monthly) > 0 else 'N/A',
        'date_max': f"{df_monthly['ano'].max()}-{int(df_monthly['mes'].max()):02d}" if len(df_monthly) > 0 else 'N/A',
        'municipios_detected': df_monthly['municipio_norm'].nunique() if 'municipio_norm' in df_monthly.columns else 0,
        'ufs_detected': df_monthly['estado'].nunique() if 'estado' in df_monthly.columns else 0,
        'used_in_pipeline': True,
        'reason_if_not_used': '',
    }])
    report.to_csv(f"{output_dir}/inpe_ingestion_report.csv", index=False)
    
    logger.info(f"INPE monthly saved: {len(df_monthly)} records")
    return df_monthly


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--states", default="CE,PE,PI")
    parser.add_argument("--start", default="2003-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", default="outputs")
    args = parser.parse_args()
    
    result = ingest_inpe(
        mode=args.mode,
        states=args.states.split(","),
        start_date=args.start,
        end_date=args.end,
        output_dir=args.output,
    )
    if result is not None:
        print(f"\nSuccess: {len(result)} municipality-month records")
        print(result.head())
