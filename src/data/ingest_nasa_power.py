"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_nasa_power.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import time
import requests
import pandas as pd
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_VARS = "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR,RH2M,WS10M,WS10M_MAX,ALLSKY_SFC_SW_DWN,PS,QV2M"


def fetch_nasa_power(lat: float, lon: float, start: str, end: str) -> Optional[pd.DataFrame]:
    """Executa a etapa `fetch nasa power` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_nasa_power.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    params = {
        "parameters": NASA_VARS,
        "community": "RE",
        "longitude": lon,
        "latitude": lat,
        "start": start.replace("-", ""),
        "end": end.replace("-", ""),
        "format": "JSON",
    }
    try:
        resp = requests.get(NASA_POWER_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "properties" not in data or "parameter" not in data["properties"]:
            return None
        df = pd.DataFrame(data["properties"]["parameter"])
        df.index = pd.to_datetime(df.index)
        df = df.reset_index().rename(columns={"index": "time"})
        df["latitude"] = lat
        df["longitude"] = lon
        return df
    except Exception as e:
        logger.warning(f"NASA POWER error ({lat},{lon}): {e}")
        return None


def ingest_nasa_power(
    scope: str = "ceara",
    start_date: str = "2003-01-01",
    end_date: str = "2025-12-31",
    output_dir: str = "outputs",
    cache_dir: str = "cache/nasa_power",
) -> Optional[pd.DataFrame]:
    """Executa a etapa `ingest nasa power` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_nasa_power.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    from src.data.ingest_open_meteo import load_municipality_coords
    
    logger.info("=" * 60)
    logger.info(f"NASA POWER Ingestion: {scope}")
    logger.info("=" * 60)
    
    os.makedirs(cache_dir, exist_ok=True)
    coords = load_municipality_coords(scope)
    
    all_records = []
    for idx, row in coords.iterrows():
        mun_id = row["municipio_id"]
        cache_file = os.path.join(cache_dir, f"{mun_id}.csv")
        
        if os.path.exists(cache_file):
            df = pd.read_csv(cache_file)
        else:
            df = fetch_nasa_power(row["latitude"], row["longitude"], start_date, end_date)
            if df is not None:
                df.to_csv(cache_file)
                time.sleep(0.5)
        
        if df is not None and len(df) > 0:
            # Aggregate monthly
            df["time"] = pd.to_datetime(df["time"])
            df["ano"] = df["time"].dt.year
            df["mes"] = df["time"].dt.month
            
            numeric_cols = [c for c in df.columns if c not in ["time", "ano", "mes", "latitude", "longitude"]]
            agg_dict = {c: "mean" for c in numeric_cols}
            
            monthly = df.groupby(["ano", "mes"]).agg(agg_dict).reset_index()
            monthly["municipio_id"] = mun_id
            monthly["municipio_nome"] = row["municipio_nome"]
            monthly["estado"] = row["estado"]
            all_records.append(monthly)
    
    if not all_records:
        logger.error("No NASA POWER data retrieved")
        return None
    
    df_final = pd.concat(all_records, ignore_index=True)
    df_final.to_csv(f"{output_dir}/nasa_power_monthly.csv", index=False)
    logger.info(f"NASA POWER saved: {len(df_final)} records")
    return df_final
