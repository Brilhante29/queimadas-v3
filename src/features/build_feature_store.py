"""Modulo publico do FireCast para construcao de atributos e controles de vazamento.

Arquivo `src/features/build_feature_store.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import os
import pandas as pd
import numpy as np
from typing import Dict, Optional, List
import logging
import json

logger = logging.getLogger(__name__)


def build_feature_store(
    inpe_df: pd.DataFrame,
    openmeteo_df: pd.DataFrame,
    nasa_df: Optional[pd.DataFrame] = None,
    ndvi_df: Optional[pd.DataFrame] = None,
    enso_df: pd.DataFrame = None,
    human_geo: Dict = None,
    output_dir: str = "outputs",
) -> pd.DataFrame:
    """Constroi a etapa `build feature store` do fluxo FireCast.
    
    A funcao faz parte de `src/features/build_feature_store.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    logger.info("=" * 60)
    logger.info("Feature Store Builder")
    logger.info("=" * 60)
    
    os.makedirs(output_dir, exist_ok=True)
    
    # === 1. Start with INPE (alvo) ===
    logger.info("[1/6] Integrating INPE (target + fire memory)...")
    
    # Normalize municipality names
    inpe_df = inpe_df.copy()
    inpe_df['municipio_norm'] = inpe_df['municipio_nome'].astype(str).str.lower().str.strip().str.replace("'", "").str.replace("-", " ")
    
    # Fire memory features
    inpe_df = inpe_df.sort_values(['municipio_norm', 'ano', 'mes'])
    for lag in [1, 2, 3, 6, 12]:
        inpe_df[f'fire_lag{lag}'] = inpe_df.groupby('municipio_norm')['fire_count'].shift(lag)
    
    # Target-derived features stop at t-1. The current month's target is not
    # available when a real forecast is produced.
    inpe_df['fire_roll3'] = inpe_df.groupby('municipio_norm')['fire_count'].transform(
        lambda x: x.shift(1).rolling(3, min_periods=1).mean()
    )
    inpe_df['fire_roll6'] = inpe_df.groupby('municipio_norm')['fire_count'].transform(
        lambda x: x.shift(1).rolling(6, min_periods=1).mean()
    )
    inpe_df['fire_ytd'] = inpe_df.groupby(['municipio_norm', 'ano'])['fire_count'].transform(
        lambda x: x.shift(1).fillna(0).cumsum()
    )
    inpe_df['same_month_last_year'] = inpe_df.groupby(['municipio_norm', 'mes'])['fire_count'].shift(1)
    
    # Historical positive flag
    inpe_df['hist_positive'] = inpe_df.groupby('municipio_norm')['fire_count'].transform(lambda x: (x > 0).any()).astype(int)
    
    # Target derivatives
    inpe_df['occurrence'] = (inpe_df['fire_count'] > 0).astype(int)
    inpe_df['extreme_event'] = (inpe_df['fire_count'] >= 30).astype(int)
    
    logger.info(f"  INPE records: {len(inpe_df)}")
    
    # === 2. Merge Open-Meteo ===
    logger.info("[2/6] Integrating Open-Meteo (climate)...")
    
    openmeteo_df = openmeteo_df.copy()
    openmeteo_df['municipio_norm'] = openmeteo_df['municipio_nome'].astype(str).str.lower().str.strip().str.replace("'", "").str.replace("-", " ")
    
    # Climate features (lags + rollings)
    climate_cols = [c for c in openmeteo_df.columns if c not in 
                    ['municipio_id', 'municipio_nome', 'estado', 'ano', 'mes', 'municipio_norm']]
    
    for col in climate_cols:
        if openmeteo_df[col].dtype not in [np.float64, np.int64, np.float32, np.int32]:
            continue
        
        openmeteo_df = openmeteo_df.sort_values(['municipio_norm', 'ano', 'mes'])
        for lag in [1, 2, 3]:
            openmeteo_df[f'{col}_lag{lag}'] = openmeteo_df.groupby('municipio_norm')[col].shift(lag)
        openmeteo_df[f'{col}_roll3'] = openmeteo_df.groupby('municipio_norm')[col].transform(lambda x: x.rolling(3, min_periods=1).mean())
    
    # Anomalies (climatology per month)
    for col in ['vapour_pressure_deficit_max', 'precipitation_sum', 'soil_moisture_0_to_7cm_mean']:
        if col in openmeteo_df.columns:
            clim = openmeteo_df.groupby('mes')[col].mean()
            openmeteo_df[f'{col}_anom'] = openmeteo_df.apply(lambda r: r[col] - clim.get(r['mes'], 0), axis=1)
    
    # Dry features
    if 'precipitation_sum' in openmeteo_df.columns:
        openmeteo_df['dry_month'] = (openmeteo_df['precipitation_sum'] < 20).astype(int)
    
    if 'vapour_pressure_deficit_max' in openmeteo_df.columns and 'temperature_2m_max' in openmeteo_df.columns:
        openmeteo_df['fuel_drying_index'] = (
            openmeteo_df['vapour_pressure_deficit_max'] / (openmeteo_df['vapour_pressure_deficit_max'].max() + 1e-6)
            + openmeteo_df['temperature_2m_max'] / (openmeteo_df['temperature_2m_max'].max() + 1e-6)
        ) / 2
    
    if 'soil_moisture_0_to_7cm_mean' in openmeteo_df.columns:
        openmeteo_df['soil_moisture_deficit'] = 1 - openmeteo_df['soil_moisture_0_to_7cm_mean']
    
    logger.info(f"  Open-Meteo records: {len(openmeteo_df)}")
    
    # === 3. Merge NASA POWER ===
    logger.info("[3/6] Integrating NASA POWER...")
    
    if nasa_df is not None and len(nasa_df) > 0:
        nasa_df = nasa_df.copy()
        nasa_df['municipio_norm'] = nasa_df['municipio_nome'].astype(str).str.lower().str.strip().str.replace("'", "").str.replace("-", " ")
        
        # Keep only unique NASA columns
        nasa_cols = [c for c in nasa_df.columns if c not in openmeteo_df.columns and 
                     c not in ['municipio_id', 'ano', 'mes', 'municipio_norm']]
        nasa_df = nasa_df[['municipio_norm', 'ano', 'mes'] + nasa_cols]
        logger.info(f"  NASA records: {len(nasa_df)}, unique cols: {len(nasa_cols)}")
    else:
        nasa_df = None
        logger.info("  NASA POWER not available")
    
    # === 4. Merge NDVI ===
    logger.info("[4/6] Integrating NDVI...")
    
    if ndvi_df is not None and len(ndvi_df) > 0 and 'ndvi' in ndvi_df.columns and ndvi_df['ndvi'].notna().sum() > 0:
        ndvi_df = ndvi_df.copy()
        ndvi_df['municipio_norm'] = ndvi_df['municipio_nome'].astype(str).str.lower().str.strip().str.replace("'", "").str.replace("-", " ")
        
        # Fuel stress index
        if 'ndvi' in ndvi_df.columns and 'vapour_pressure_deficit_max' in openmeteo_df.columns:
            ndvi_df['ndvi_norm'] = (ndvi_df['ndvi'] - ndvi_df['ndvi'].min()) / (ndvi_df['ndvi'].max() - ndvi_df['ndvi'].min() + 1e-6)
        
        logger.info(f"  NDVI records with data: {ndvi_df['ndvi'].notna().sum()}")
    else:
        ndvi_df = None
        logger.info("  NDVI not available (using missing indicator)")
    
    # === 5. Merge ENSO ===
    logger.info("[5/6] Integrating ENSO (regime)...")
    
    if enso_df is not None and len(enso_df) > 0:
        logger.info(f"  ENSO records: {len(enso_df)}")
    else:
        from src.data.ingest_enso import fetch_enso_data
        enso_df = fetch_enso_data()
        logger.info(f"  ENSO loaded: {len(enso_df)} records")
    
    # === 6. Merge human/geospatial ===
    logger.info("[6/6] Integrating human/geospatial...")
    
    if human_geo:
        for name, df in human_geo.items():
            if df is not None and len(df) > 0:
                logger.info(f"  {name}: {len(df)} records")
    else:
        logger.info("  Human/geospatial data not available (using missing indicators)")
    
    # === MERGE ALL ===
    logger.info("\nMerging all sources...")
    
    # Start with INPE
    df = inpe_df.copy()
    
    # Merge Open-Meteo
    merge_cols = ['municipio_norm', 'ano', 'mes']
    df = df.merge(openmeteo_df, on=merge_cols, how='left', suffixes=('', '_om'))
    
    # Merge NASA
    if nasa_df is not None:
        df = df.merge(nasa_df, on=merge_cols, how='left', suffixes=('', '_nasa'))
    
    # Merge NDVI
    if ndvi_df is not None:
        ndvi_merge = ndvi_df[['municipio_norm', 'ano', 'mes', 'ndvi', 'ndvi_lag1', 'ndvi_lag2', 'ndvi_lag3', 
                               'ndvi_roll3', 'ndvi_anomaly', 'ndvi_drop_2m', 'ndvi_drop_3m', 'ndvi_available']]
        df = df.merge(ndvi_merge, on=merge_cols, how='left')
    else:
        df['ndvi_available'] = 0
    
    # Merge ENSO
    enso_merge = enso_df[['ano', 'mes', 'nino34_anomaly', 'enso_prob_el_nino', 'enso_regime']]
    df = df.merge(enso_merge, on=['ano', 'mes'], how='left')
    
    # Merge human/geospatial (static features)
    if human_geo:
        for name, hg_df in human_geo.items():
            if hg_df is not None and len(hg_df) > 0:
                # Select only unique columns not already in df
                keep_cols = ['municipio_id'] + [c for c in hg_df.columns 
                    if c not in df.columns and c not in ['municipio_nome', 'estado', 'municipio_norm']]
                if len(keep_cols) > 1:  # more than just municipio_id
                    hg_merge = hg_df[keep_cols].drop_duplicates(subset=['municipio_id'])
                    df = df.merge(hg_merge, on='municipio_id', how='left', suffixes=('', f'_{name}'))
    
    # === TEMPORAL FEATURES ===
    logger.info("Adding temporal features...")
    df['month_sin'] = np.sin(2 * np.pi * df['mes'] / 12)
    df['month_cos'] = np.cos(2 * np.pi * df['mes'] / 12)
    df['is_critical'] = df['mes'].isin([10, 11]).astype(int)
    df['is_dry_season'] = df['mes'].isin([5, 6, 7, 8, 9]).astype(int)
    df['trend_index'] = (df['ano'] - df['ano'].min()) * 12 + df['mes']
    
    # === SPATIAL FEATURES (neighbor) ===
    logger.info("Adding spatial features...")
    if 'estado' in df.columns:
        df['neighbor_fire_lag1'] = df.groupby('estado')['fire_lag1'].transform(lambda x: x.fillna(x.mean()))
        df['neighbor_fire_roll3'] = df.groupby('estado')['fire_roll3'].transform(lambda x: x.fillna(x.mean()))
    
    # === HUMAN PRESSURE ===
    if 'agriculture_share' in df.columns and df['agriculture_share'].notna().any():
        df['human_pressure_index'] = df['agriculture_share'].fillna(0) + df['pasture_share'].fillna(0)
    else:
        df['human_pressure_index'] = np.nan
    
    # === REGIME FEATURES ===
    if 'enso_prob_el_nino' in df.columns:
        df['regime_probability'] = df['enso_prob_el_nino'] / 100.0
    
    # === CLEANUP ===
    logger.info("Cleaning up...")
    
    # Remove duplicate columns from merges
    dup_cols = [c for c in df.columns if c.endswith('_om') or c.endswith('_nasa')]
    if dup_cols:
        df = df.drop(columns=dup_cols)
    
    # Drop rows without target
    df = df[df['fire_count'].notna()].copy()
    
    # Feature manifest
    feature_manifest = {}
    for col in df.columns:
        feature_manifest[col] = {
            'source': _detect_source(col),
            'leakage_risk': col in ['fire_count', 'frp_sum', 'occurrence', 'extreme_event'],
            'available': df[col].notna().mean() > 0.5,
        }
    
    # Save
    df.to_csv(f"{output_dir}/03_feature_store.csv", index=False)
    
    with open(f"{output_dir}/04_feature_manifest.json", 'w') as f:
        json.dump(feature_manifest, f, indent=2, default=str)
    
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Feature Store Complete!")
    logger.info(f"  Records: {len(df)}")
    logger.info(f"  Features: {len(df.columns)}")
    logger.info(f"  Municipalities: {df['municipio_norm'].nunique()}")
    logger.info(f"  Years: {df['ano'].min()}-{df['ano'].max()}")
    logger.info(f"  Zeros: {(df['fire_count'] == 0).mean()*100:.1f}%")
    logger.info(f"{'=' * 60}")
    
    return df


def _detect_source(col: str) -> str:
    """Executa a etapa `detect source` do fluxo FireCast.
    
    A funcao faz parte de `src/features/build_feature_store.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if col in ['fire_count', 'fire_lag1', 'fire_lag2', 'fire_lag3', 'fire_lag6', 'fire_lag12',
               'fire_roll3', 'fire_roll6', 'fire_ytd', 'hist_positive', 'occurrence', 'extreme_event',
               'FRP_sum', 'FRP_mean', 'FRP_p90']:
        return 'INPE'
    if 'temperature' in col or 'precip' in col or 'vpd' in col or 'humidity' in col or 'wind' in col or 'soil' in col or 'radiation' in col or 'et0' in col or 'sunshine' in col or 'cloud' in col or 'pressure' in col:
        return 'OpenMeteo'
    if 'ndvi' in col or 'evi' in col:
        return 'NDVI'
    if 'nino' in col or 'enso' in col:
        return 'ENSO'
    if 'human' in col or 'agriculture' in col or 'pasture' in col:
        return 'MapBiomas'
    if 'road' in col or 'osm' in col:
        return 'OSM'
    if 'neighbor' in col or 'spatial' in col:
        return 'Spatial'
    if 'month' in col or 'trend' in col or 'critical' in col or 'dry' in col:
        return 'Temporal'
    return 'Unknown'


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--inpe", required=True)
    parser.add_argument("--openmeteo", required=True)
    parser.add_argument("--nasa", default=None)
    parser.add_argument("--ndvi", default=None)
    parser.add_argument("--output", default="outputs")
    args = parser.parse_args()
    
    inpe = pd.read_csv(args.inpe)
    om = pd.read_csv(args.openmeteo)
    nasa = pd.read_csv(args.nasa) if args.nasa else None
    ndvi = pd.read_csv(args.ndvi) if args.ndvi else None
    
    result = build_feature_store(inpe, om, nasa, ndvi, output_dir=args.output)
    print(f"\nFeature store: {result.shape}")
