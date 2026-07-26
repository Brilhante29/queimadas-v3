"""Modulo publico do FireCast para prototipos de pesquisa e ideias de fronteira.

Arquivo `src/research/charm_fire.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
import logging

logger = logging.getLogger(__name__)


class CHARMFire:
    """Representa `CHARMFire` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/research/charm_fire.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, extreme_threshold: int = 30):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.extreme_threshold = extreme_threshold
        
        self.climate_model = None
        self.human_model = None
        self.ensemble_model = None
        
        self.scaler_climate = StandardScaler()
        self.scaler_human = StandardScaler()
        self.scaler_ensemble = StandardScaler()
        
        self.climate_cols = []
        self.human_cols = []
        self.cold_start_climate_avg = None
        
        self.is_fitted = False
        
        # Innovation tracking
        self.innovations = []
    
    def _assign_feature_groups(self, df: pd.DataFrame):
        """Executa a etapa `assign feature groups` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        all_cols = [c for c in df.select_dtypes(include=[np.number]).columns]
        
        # Climaticas: puros sinais meteorologicos
        self.climate_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'vpd', 'vapour', 'precip', 'temperature', 'temp', 'soil_moisture',
            'et0', 'evapotranspiration', 'humidity', 'radiation', 'wind',
            'nino', 'enso', 'anom', 'dry', 'drought', 'water_deficit',
            'climate', 'weather', 'rain'
        ])]
        
        # Humanas: antropogenicas (incluindo memoria de fogo como proxy)
        self.human_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'human', 'road', 'agriculture', 'pasture', 'population', 'rural',
            'urban', 'deforestation', 'land_use', 'osm', 'ibge', 'mapbiomas',
            'ignition', 'anthropic', 'infrastructure', 'distance'
        ])]
        
        logger.info(f"CHARM feature groups:")
        logger.info(f"  Climate: {len(self.climate_cols)} features")
        logger.info(f"  Human: {len(self.human_cols)} features")
    
    def fit(self, df_train: pd.DataFrame, df_cal: pd.DataFrame = None):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("=" * 60)
        logger.info("CHARM-Fire: Training Climate-Human decomposition")
        logger.info("=" * 60)
        
        self._assign_feature_groups(df_train)
        
        y = df_train['fire_count'].values
        y_log = np.log1p(y)
        
        # === Step 1: Climate Component ===
        logger.info("[C-Step] Training climate component...")
        
        X_clim = df_train[self.climate_cols].fillna(0) if self.climate_cols else pd.DataFrame(index=df_train.index)
        X_clim_s = self.scaler_climate.fit_transform(X_clim) if self.climate_cols else np.zeros((len(df_train), 1))
        
        self.climate_model = RandomForestRegressor(
            n_estimators=50, max_depth=6, random_state=42, n_jobs=-1
        )
        self.climate_model.fit(X_clim_s, y_log)
        
        climate_pred_log = self.climate_model.predict(X_clim_s)
        climate_pred = np.expm1(climate_pred_log)
        
        # === Step 2: Human Component (residual) ===
        logger.info("[H-Step] Training human component on residuals...")
        
        # Residual = observed - climate prediction (on log scale for stability)
        residual_log = y_log - climate_pred_log
        
        # Guardar media de cold-start para municipios sem historico
        self.cold_start_climate_avg = np.mean(climate_pred_log)
        
        X_human = df_train[self.human_cols].fillna(0) if self.human_cols else pd.DataFrame(index=df_train.index)
        X_human_s = self.scaler_human.fit_transform(X_human) if self.human_cols else np.zeros((len(df_train), 1))
        
        self.human_model = RandomForestRegressor(
            n_estimators=50, max_depth=6, random_state=42, n_jobs=-1
        )
        self.human_model.fit(X_human_s, residual_log)
        
        human_pred_log = self.human_model.predict(X_human_s)
        
        # === Step 3: Ensemble (C + H + interactions) ===
        logger.info("[E-Step] Training ensemble combination...")
        
        ensemble_features = np.column_stack([
            climate_pred_log,
            human_pred_log,
            climate_pred_log * human_pred_log,  # interaction
            np.abs(residual_log),  # residual magnitude
            np.sign(human_pred_log) * np.sqrt(np.abs(human_pred_log) + 1e-6),  # non-linear human
        ])
        
        self.scaler_ensemble.fit(ensemble_features)
        ens_s = self.scaler_ensemble.transform(ensemble_features)
        
        self.ensemble_model = Ridge(alpha=1.0)
        self.ensemble_model.fit(ens_s, y_log)
        
        self.is_fitted = True
        
        # Calibrate conformal (after is_fitted for predict to work)
        if df_cal is not None and len(df_cal) > 10:
            self._calibrate(df_cal)
        
        # Store innovation record
        self.innovations.append({
            'method': 'CHARM-Fire',
            'climate_features': len(self.climate_cols),
            'human_features': len(self.human_cols),
            'climate_r2': 1 - np.var(y_log - climate_pred_log) / np.var(y_log),
            'human_explains_residual_var': np.var(human_pred_log) / max(np.var(residual_log), 1e-6),
        })
        
        logger.info("CHARM-Fire training complete!")
        return self
    
    def _calibrate(self, df_cal: pd.DataFrame):
        """Executa a etapa `calibrate` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred_cal = self.predict(df_cal)
        residuals = np.abs(df_cal['fire_count'].values - pred_cal['y_pred'].values)
        self.q80 = np.quantile(residuals, 0.80)
        self.q95 = np.quantile(residuals, 0.95)
        logger.info(f"  Conformal calibrated: q80={self.q80:.2f}, q95={self.q95:.2f}")
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        result = df.copy()
        
        # Climate component
        X_clim = df[self.climate_cols].fillna(0) if self.climate_cols else pd.DataFrame(index=df.index)
        X_clim_s = self.scaler_climate.transform(X_clim) if self.climate_cols else np.zeros((len(df), 1))
        climate_log = self.climate_model.predict(X_clim_s)
        climate_count = np.maximum(np.expm1(climate_log), 0)
        
        # Human component
        X_human = df[self.human_cols].fillna(0) if self.human_cols else pd.DataFrame(index=df.index)
        X_human_s = self.scaler_human.transform(X_human) if self.human_cols else np.zeros((len(df), 1))
        human_log = self.human_model.predict(X_human_s)
        
        # Ensemble
        ens = np.column_stack([
            climate_log, human_log,
            climate_log * human_log,
            np.abs(human_log),
            np.sign(human_log) * np.sqrt(np.abs(human_log) + 1e-6),
        ])
        ens_s = self.scaler_ensemble.transform(ens)
        
        y_pred_log = self.ensemble_model.predict(ens_s)
        y_pred = np.maximum(np.expm1(y_pred_log), 0)
        
        # Store decomposed components
        result['climate_component'] = climate_count
        result['human_component_log'] = human_log
        result['human_pressure_index'] = np.tanh(human_log / 2)  # normalizado -1 a 1
        result['y_pred'] = y_pred
        
        # Occurrence probability
        result['p_occurrence'] = np.minimum(
            0.95 * (1 - np.exp(-climate_count * 0.1)) + 0.05,
            0.99
        )
        
        # Extreme probability
        result['p_extreme'] = (result['y_pred'] > self.extreme_threshold).astype(float) * result['p_occurrence']
        
        # Risk score (weighted by human pressure)
        result['risk_score'] = (
            0.25 * result['p_occurrence']
            + 0.30 * np.minimum(result['y_pred'] / 50, 1.0)
            + 0.25 * (result['human_pressure_index'] > 0.3).astype(float)
            + 0.20 * result['p_extreme']
        )
        
        # Conformal intervals
        if hasattr(self, 'q80'):
            result['ic80_lower'] = np.maximum(result['y_pred'] - self.q80, 0)
            result['ic80_upper'] = result['y_pred'] + self.q80
            result['ic95_lower'] = np.maximum(result['y_pred'] - self.q95, 0)
            result['ic95_upper'] = result['y_pred'] + self.q95
        
        result['risk_level'] = pd.cut(
            result['risk_score'],
            bins=[-1, 0.2, 0.5, 0.75, 1.0],
            labels=['baixo', 'moderado', 'alto', 'extremo']
        )
        
        # Dominant factor
        result['dominant_factor'] = np.where(
            np.abs(human_log) > climate_log * 0.5,
            'humano',
            np.where(climate_count > 5, 'climatico', 'moderado')
        )
        
        return result
    
    def explain(self, df_row: pd.Series) -> dict:
        """Produz a etapa `explain` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred = self.predict(df_row.to_frame().T)
        return {
            'prediction': float(pred['y_pred'].iloc[0]),
            'climate_component': float(pred['climate_component'].iloc[0]),
            'human_pressure': float(pred['human_pressure_index'].iloc[0]),
            'dominant_factor': str(pred['dominant_factor'].iloc[0]),
            'risk_level': str(pred['risk_level'].iloc[0]),
            'p_occurrence': float(pred['p_occurrence'].iloc[0]),
            'p_extreme': float(pred['p_extreme'].iloc[0]),
        }
    
    def get_human_anomaly_score(self, df: pd.DataFrame) -> pd.Series:
        """Executa a etapa `get human anomaly score` do fluxo FireCast.
        
        A funcao faz parte de `src/research/charm_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred = self.predict(df)
        return pred['human_pressure_index']
