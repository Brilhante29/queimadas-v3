"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_open_meteo.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import time
import requests
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

OPENMETEO_HISTORICAL = "https://archive-api.open-meteo.com/v1/archive"
OPENMETEO_DAILY_VARS = [
    "temperature_2m_mean", "temperature_2m_max", "temperature_2m_min",
    "relative_humidity_2m_mean", "dew_point_2m_mean",
    "vapour_pressure_deficit_max",
    "precipitation_sum", "precipitation_hours", "rain_sum",
    "et0_fao_evapotranspiration",
    "shortwave_radiation_sum", "sunshine_duration",
    "wind_speed_10m_mean", "wind_speed_10m_max", "wind_gusts_10m_max",
    "soil_moisture_0_to_7cm_mean",
    "soil_moisture_7_to_28cm_mean",
    "soil_moisture_28_to_100cm_mean",
    "soil_temperature_0_to_7cm_mean",
    "surface_pressure_mean", "cloud_cover_mean",
]


def load_municipality_coords(
    scope: str = "ceara",
    custom_csv: Optional[str] = None,
) -> pd.DataFrame:
    """Carrega a etapa `load municipality coords` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_open_meteo.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if custom_csv and os.path.exists(custom_csv):
        return pd.read_csv(custom_csv)
    
    # Default coordinates for Ceará municipalities
    from src.data.municipality_coords import MUNICIPIOS_CE, MUNICIPIOS_PE, MUNICIPIOS_PI
    
    records = []
    if scope == "ceara":
        for name, lat, lon in MUNICIPIOS_CE:
            records.append({"municipio_id": f"CE_{name}", "municipio_nome": name, "estado": "CE", "latitude": lat, "longitude": lon})
    elif scope == "chapada_araripe":
        for name, lat, lon in MUNICIPIOS_CE:
            records.append({"municipio_id": f"CE_{name}", "municipio_nome": name, "estado": "CE", "latitude": lat, "longitude": lon})
        for name, lat, lon in MUNICIPIOS_PE:
            records.append({"municipio_id": f"PE_{name}", "municipio_nome": name, "estado": "PE", "latitude": lat, "longitude": lon})
        for name, lat, lon in MUNICIPIOS_PI:
            records.append({"municipio_id": f"PI_{name}", "municipio_nome": name, "estado": "PI", "latitude": lat, "longitude": lon})
    elif scope == "brazil":
        # For Brazil, use a representative sample + known state capitals
        for name, lat, lon in MUNICIPIOS_CE:
            records.append({"municipio_id": f"CE_{name}", "municipio_nome": name, "estado": "CE", "latitude": lat, "longitude": lon})
        for name, lat, lon in MUNICIPIOS_PE:
            records.append({"municipio_id": f"PE_{name}", "municipio_nome": name, "estado": "PE", "latitude": lat, "longitude": lon})
        for name, lat, lon in MUNICIPIOS_PI:
            records.append({"municipio_id": f"PI_{name}", "municipio_nome": name, "estado": "PI", "latitude": lat, "longitude": lon})
        # Add state capitals for broader coverage
        state_capitals = [
            ("Sao_Paulo", -23.5505, -46.6333, "SP"),
            ("Rio_de_Janeiro", -22.9068, -43.1729, "RJ"),
            ("Belo_Horizonte", -19.9167, -43.9345, "MG"),
            ("Salvador", -12.9714, -38.5014, "BA"),
            ("Brasilia", -15.7975, -47.8919, "DF"),
            ("Curitiba", -25.4284, -49.2733, "PR"),
            ("Manaus", -3.1190, -60.0217, "AM"),
            ("Belem", -1.4558, -48.4902, "PA"),
            ("Goiania", -16.6869, -49.2648, "GO"),
            ("Fortaleza", -3.7172, -38.5433, "CE"),
            ("Recife", -8.0476, -34.8770, "PE"),
            ("Porto_Alegre", -30.0346, -51.2177, "RS"),
            ("Campo_Grande", -20.4697, -54.6201, "MS"),
            ("Cuiaba", -15.6014, -56.0979, "MT"),
            ("Sao_Luis", -2.5307, -44.3068, "MA"),
            ("Aracaju", -10.9472, -37.0731, "SE"),
            ("Natal", -5.7945, -35.2110, "RN"),
            ("Joao_Pessoa", -7.1153, -34.8610, "PB"),
            ("Florianopolis", -27.5954, -48.5480, "SC"),
            ("Boa_Vista", 2.8235, -60.6758, "RR"),
            ("Porto_Velho", -8.7612, -63.9004, "RO"),
            ("Macapa", 0.0355, -51.0705, "AP"),
            ("Palmas", -10.1840, -48.3337, "TO"),
            ("Vitoria", -20.3155, -40.3128, "ES"),
            ("Teresina", -5.0892, -42.8016, "PI"),
        ]
        for name, lat, lon, uf in state_capitals:
            records.append({"municipio_id": f"{uf}_{name}", "municipio_nome": name, "estado": uf, "latitude": lat, "longitude": lon})
    
    df = pd.DataFrame(records).drop_duplicates(subset=["municipio_id"])
    logger.info(f"Loaded {len(df)} municipalities for scope '{scope}'")
    return df


def fetch_open_meteo(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    timezone: str = "America/Fortaleza",
) -> Optional[pd.DataFrame]:
    """Executa a etapa `fetch open meteo` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_open_meteo.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": ",".join(OPENMETEO_DAILY_VARS),
        "timezone": timezone,
    }
    
    try:
        response = requests.get(OPENMETEO_HISTORICAL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if "daily" not in data:
            return None
        
        df = pd.DataFrame(data["daily"])
        df["time"] = pd.to_datetime(df["time"])
        df["latitude"] = latitude
        df["longitude"] = longitude
        
        return df
    except Exception as e:
        logger.warning(f"Open-Meteo error ({latitude}, {longitude}): {e}")
        return None


def aggregate_daily_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `aggregate daily to monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_open_meteo.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = df.copy()
    df["ano"] = df["time"].dt.year
    df["mes"] = df["time"].dt.month
    
    # Define aggregation functions
    sum_vars = ["precipitation_sum", "rain_sum", "shortwave_radiation_sum", 
                "et0_fao_evapotranspiration", "sunshine_duration"]
    max_vars = ["temperature_2m_max", "vapour_pressure_deficit_max", 
                "wind_speed_10m_max", "wind_gusts_10m_max"]
    min_vars = ["temperature_2m_min"]
    mean_vars = [c for c in df.columns if c not in sum_vars + max_vars + min_vars + 
                 ["time", "ano", "mes", "latitude", "longitude", "precipitation_hours"]]
    
    # precipitation_hours uses sum
    if "precipitation_hours" in df.columns:
        sum_vars.append("precipitation_hours")
    
    agg_dict = {}
    for c in sum_vars:
        if c in df.columns:
            agg_dict[c] = "sum"
    for c in max_vars:
        if c in df.columns:
            agg_dict[c] = "max"
    for c in min_vars:
        if c in df.columns:
            agg_dict[c] = "min"
    for c in mean_vars:
        if c in df.columns and c not in ["time"]:
            agg_dict[c] = "mean"
    
    grouped = df.groupby(["ano", "mes"]).agg(agg_dict).reset_index()
    return grouped


def compute_dry_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula a etapa `compute dry features` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_open_meteo.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = df.copy()
    
    # Consecutive dry days proxy (from monthly precip hours)
    if "precipitation_sum" in df.columns:
        df["dry_month"] = (df["precipitation_sum"] < 20).astype(int)
    
    # Fuel drying index
    if "vapour_pressure_deficit_max" in df.columns and "temperature_2m_max" in df.columns:
        df["fuel_drying_index"] = (
            df["vapour_pressure_deficit_max"] / (df["vapour_pressure_deficit_max"].max() + 1e-6)
            + df["temperature_2m_max"] / (df["temperature_2m_max"].max() + 1e-6)
        ) / 2
    
    return df


def ingest_open_meteo(
    scope: str = "ceara",
    start_date: str = "2003-01-01",
    end_date: str = "2025-12-31",
    output_dir: str = "outputs",
    cache_dir: str = "cache/open_meteo",
) -> Optional[pd.DataFrame]:
    """Executa a etapa `ingest open meteo` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_open_meteo.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    logger.info("=" * 60)
    logger.info(f"Open-Meteo Ingestion: {scope}")
    logger.info(f"Period: {start_date} to {end_date}")
    logger.info("=" * 60)
    
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    
    # Load municipality coordinates
    coords_df = load_municipality_coords(scope)
    
    if len(coords_df) == 0:
        logger.error("No municipality coordinates loaded!")
        return None
    
    all_monthly = []
    
    for idx, row in coords_df.iterrows():
        mun_id = row["municipio_id"]
        cache_file = os.path.join(cache_dir, f"{mun_id}_{start_date}_{end_date}.csv")
        
        # Check cache
        if os.path.exists(cache_file):
            df = pd.read_csv(cache_file)
            if len(df) > 0:
                df["municipio_id"] = mun_id
                df["municipio_nome"] = row["municipio_nome"]
                df["estado"] = row["estado"]
                all_monthly.append(df)
                continue
        
        # Fetch from API
        df_daily = fetch_open_meteo(
            latitude=row["latitude"],
            longitude=row["longitude"],
            start_date=start_date,
            end_date=end_date,
        )
        
        if df_daily is None or len(df_daily) == 0:
            logger.warning(f"  No data for {mun_id}")
            continue
        
        # Aggregate
        df_monthly = aggregate_daily_to_monthly(df_daily)
        df_monthly = compute_dry_features(df_monthly)
        
        # Add metadata
        df_monthly["municipio_id"] = mun_id
        df_monthly["municipio_nome"] = row["municipio_nome"]
        df_monthly["estado"] = row["estado"]
        
        # Cache
        df_monthly.to_csv(cache_file, index=False)
        
        all_monthly.append(df_monthly)
        
        # Rate limiting
        if (idx + 1) % 10 == 0:
            logger.info(f"  Processed {idx + 1}/{len(coords_df)} municipalities")
        time.sleep(0.2)  # Be nice to the API
    
    if not all_monthly:
        logger.error("No Open-Meteo data retrieved!")
        return None
    
    df_final = pd.concat(all_monthly, ignore_index=True)
    
    # Save
    df_final.to_csv(f"{output_dir}/open_meteo_monthly.csv", index=False)
    
    # Coverage report
    n_mun_total = len(coords_df)
    n_mun_success = df_final["municipio_id"].nunique()
    
    report = pd.DataFrame([{
        "source": "open_meteo",
        "scope": scope,
        "municipalities_total": n_mun_total,
        "municipalities_success": n_mun_success,
        "coverage_pct": n_mun_success / n_mun_total * 100,
        "period_start": start_date,
        "period_end": end_date,
        "variables": len(OPENMETEO_DAILY_VARS),
        "records": len(df_final),
    }])
    report.to_csv(f"{output_dir}/open_meteo_coverage_report.csv", index=False)
    
    logger.info(f"Open-Meteo saved: {len(df_final)} records for {n_mun_success} municipalities")
    return df_final


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", default="ceara")
    parser.add_argument("--start", default="2003-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", default="outputs")
    args = parser.parse_args()
    
    result = ingest_open_meteo(scope=args.scope, start_date=args.start, end_date=args.end, output_dir=args.output)
    if result is not None:
        print(f"\nSuccess: {len(result)} records")
        print(result.head())
