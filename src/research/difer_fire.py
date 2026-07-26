"""Modulo publico do FireCast para prototipos de pesquisa e ideias de fronteira.

Arquivo `src/research/difer_fire.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
import logging

logger = logging.getLogger(__name__)


class DIFERFire:
    """Representa `DIFERFire` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/research/difer_fire.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, extreme_threshold: int = 30):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/research/difer_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.extreme_threshold = extreme_threshold
        
        # Modulos
        self.fuel_model = None
        self.drying_model = None
        self.ignition_model = None
        self.spread_model = None
        self.regime_model = None
        self.count_model = None
        
        # Scalers
        self.scalers = {}
        
        # Feature groups
        self.fuel_cols = []
        self.drying_cols = []
        self.ignition_cols = []
        self.spread_cols = []
        self.regime_cols = []
        
        self.is_fitted = False
    
    def _assign_feature_groups(self, df: pd.DataFrame):
        """Executa a etapa `assign feature groups` do fluxo FireCast.
        
        A funcao faz parte de `src/research/difer_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        all_cols = [c for c in df.select_dtypes(include=[np.number]).columns]
        
        self.fuel_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'ndvi', 'fuel', 'greenup', 'vegetation', 'land_cover'
        ])]
        
        self.drying_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'vpd', 'et0', 'soil_moisture', 'precip', 'dry', 'radiation',
            'temp_max', 'hot_dry', 'consecutive_dry'
        ])]
        
        self.ignition_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'human', 'road', 'agriculture', 'pasture', 'population', 'rural',
            'ignition', 'anthropic'
        ])]
        
        self.spread_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'neighbor', 'spatial', 'spread', 'contagion', 'wind', 'graph'
        ])]
        
        self.regime_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'enso', 'nino', 'regime', 'fire_ytd', 'ytd_vs', 'trend',
            'month_sin', 'month_cos', 'is_critical'
        ])]
        
        logger.info(f"DIFER-Fire feature groups:")
        logger.info(f"  Fuel: {len(self.fuel_cols)} features")
        logger.info(f"  Drying: {len(self.drying_cols)} features")
        logger.info(f"  Ignition: {len(self.ignition_cols)} features")
        logger.info(f"  Spread: {len(self.spread_cols)} features")
        logger.info(f"  Regime: {len(self.regime_cols)} features")
    
    def fit(self, df_train: pd.DataFrame, df_cal: pd.DataFrame = None):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/research/difer_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("=" * 60)
        logger.info("DIFER-Fire: Training decomposed modules")
        logger.info("=" * 60)
        
        self._assign_feature_groups(df_train)
        
        # Target
        y = df_train['fire_count'].values
        y_log = np.log1p(y)
        
        # === M1: Fuel Module ===
        logger.info("[Fuel] Training fuel availability...")
        X_fuel = df_train[self.fuel_cols].fillna(0) if self.fuel_cols else pd.DataFrame(index=df_train.index)
        self.scalers['fuel'] = StandardScaler()
        X_fuel_s = self.scalers['fuel'].fit_transform(X_fuel) if self.fuel_cols else np.zeros((len(df_train), 1))
        
        self.fuel_model = RandomForestRegressor(30, max_depth=5, random_state=42, n_jobs=-1)
        self.fuel_model.fit(X_fuel_s, y_log)
        fuel_pred = np.expm1(self.fuel_model.predict(X_fuel_s))
        
        # === M2: Drying Module ===
        logger.info("[Drying] Training atmospheric drying...")
        X_dry = df_train[self.drying_cols].fillna(0) if self.drying_cols else pd.DataFrame(index=df_train.index)
        self.scalers['drying'] = StandardScaler()
        X_dry_s = self.scalers['drying'].fit_transform(X_dry) if self.drying_cols else np.zeros((len(df_train), 1))
        
        self.drying_model = RandomForestRegressor(30, max_depth=5, random_state=42, n_jobs=-1)
        self.drying_model.fit(X_dry_s, y_log)
        drying_pred = np.expm1(self.drying_model.predict(X_dry_s))
        
        # === M3: Ignition Module ===
        logger.info("[Ignition] Training human ignition pressure...")
        X_ign = df_train[self.ignition_cols].fillna(0) if self.ignition_cols else pd.DataFrame(index=df_train.index)
        self.scalers['ignition'] = StandardScaler()
        X_ign_s = self.scalers['ignition'].fit_transform(X_ign) if self.ignition_cols else np.zeros((len(df_train), 1))
        
        self.ignition_model = RandomForestRegressor(30, max_depth=5, random_state=42, n_jobs=-1)
        self.ignition_model.fit(X_ign_s, y_log)
        ignition_pred = np.expm1(self.ignition_model.predict(X_ign_s))
        
        # === M4: Spread Module ===
        logger.info("[Spread] Training spatial propagation...")
        X_spr = df_train[self.spread_cols].fillna(0) if self.spread_cols else pd.DataFrame(index=df_train.index)
        self.scalers['spread'] = StandardScaler()
        X_spr_s = self.scalers['spread'].fit_transform(X_spr) if self.spread_cols else np.zeros((len(df_train), 1))
        
        self.spread_model = RandomForestRegressor(30, max_depth=5, random_state=42, n_jobs=-1)
        self.spread_model.fit(X_spr_s, y_log)
        spread_pred = np.expm1(self.spread_model.predict(X_spr_s))
        
        # === M5: Regime Module ===
        logger.info("[Regime] Training regime detector...")
        X_reg = df_train[self.regime_cols].fillna(0) if self.regime_cols else pd.DataFrame(index=df_train.index)
        self.scalers['regime'] = StandardScaler()
        X_reg_s = self.scalers['regime'].fit_transform(X_reg) if self.regime_cols else np.zeros((len(df_train), 1))
        
        self.regime_model = RandomForestRegressor(30, max_depth=5, random_state=42, n_jobs=-1)
        self.regime_model.fit(X_reg_s, y_log)
        regime_pred = np.expm1(self.regime_model.predict(X_reg_s))
        
        # === Ensemble: Multiplicative Composition ===
        logger.info("[Ensemble] Training multiplicative ensemble...")
        
        # Create ensemble features
        ensemble_features = np.column_stack([
            fuel_pred, drying_pred, ignition_pred, spread_pred, regime_pred,
            fuel_pred * drying_pred,
            drying_pred * ignition_pred,
            ignition_pred * spread_pred,
            spread_pred * regime_pred,
            fuel_pred * drying_pred * ignition_pred,
        ])
        
        self.count_model = RandomForestRegressor(50, max_depth=6, random_state=42, n_jobs=-1)
        self.count_model.fit(ensemble_features, y_log)
        
        self.is_fitted = True
        
        # Calibrate conformal (after is_fitted for predict to work)
        if df_cal is not None and len(df_cal) > 10:
            self._calibrate(df_cal)
        
        logger.info("DIFER-Fire training complete!")
        return self
    
    def _calibrate(self, df_cal: pd.DataFrame):
        """Executa a etapa `calibrate` do fluxo FireCast.
        
        A funcao faz parte de `src/research/difer_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred_cal = self.predict(df_cal)
        residuals = np.abs(df_cal['fire_count'].values - pred_cal['y_pred'].values)
        self.q80 = np.quantile(residuals, 0.80)
        self.q95 = np.quantile(residuals, 0.95)
        logger.info(f"  Conformal calibrated: q80={self.q80:.2f}, q95={self.q95:.2f}")
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/research/difer_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        result = df.copy()
        
        # Predict each module
        X_fuel = df[self.fuel_cols].fillna(0) if self.fuel_cols else pd.DataFrame(index=df.index)
        X_fuel_s = self.scalers['fuel'].transform(X_fuel) if self.fuel_cols else np.zeros((len(df), 1))
        fuel_score = np.expm1(self.fuel_model.predict(X_fuel_s))
        
        X_dry = df[self.drying_cols].fillna(0) if self.drying_cols else pd.DataFrame(index=df.index)
        X_dry_s = self.scalers['drying'].transform(X_dry) if self.drying_cols else np.zeros((len(df), 1))
        drying_score = np.expm1(self.drying_model.predict(X_dry_s))
        
        X_ign = df[self.ignition_cols].fillna(0) if self.ignition_cols else pd.DataFrame(index=df.index)
        X_ign_s = self.scalers['ignition'].transform(X_ign) if self.ignition_cols else np.zeros((len(df), 1))
        ignition_score = np.expm1(self.ignition_model.predict(X_ign_s))
        
        X_spr = df[self.spread_cols].fillna(0) if self.spread_cols else pd.DataFrame(index=df.index)
        X_spr_s = self.scalers['spread'].transform(X_spr) if self.spread_cols else np.zeros((len(df), 1))
        spread_score = np.expm1(self.spread_model.predict(X_spr_s))
        
        X_reg = df[self.regime_cols].fillna(0) if self.regime_cols else pd.DataFrame(index=df.index)
        X_reg_s = self.scalers['regime'].transform(X_reg) if self.regime_cols else np.zeros((len(df), 1))
        regime_score = np.expm1(self.regime_model.predict(X_reg_s))
        
        # Store module scores
        result['fuel_score'] = fuel_score
        result['drying_score'] = drying_score
        result['ignition_score'] = ignition_score
        result['spread_score'] = spread_score
        result['regime_score'] = regime_score
        
        # Ensemble prediction
        ens = np.column_stack([
            fuel_score, drying_score, ignition_score, spread_score, regime_score,
            fuel_score * drying_score,
            drying_score * ignition_score,
            ignition_score * spread_score,
            spread_score * regime_score,
            fuel_score * drying_score * ignition_score,
        ])
        result['y_pred'] = np.maximum(np.expm1(self.count_model.predict(ens)), 0)
        
        # Occurrence probability
        result['p_occurrence'] = np.minimum(fuel_score * drying_score * ignition_score / (result['y_pred'] + 1e-6), 1.0)
        
        # Extreme probability
        result['p_extreme'] = (result['y_pred'] > self.extreme_threshold).astype(float) * result['p_occurrence']
        
        # Risk score
        result['risk_score'] = (
            0.20 * fuel_score / (fuel_score.max() + 1e-6)
            + 0.25 * drying_score / (drying_score.max() + 1e-6)
            + 0.20 * ignition_score / (ignition_score.max() + 1e-6)
            + 0.15 * spread_score / (spread_score.max() + 1e-6)
            + 0.20 * regime_score / (regime_score.max() + 1e-6)
        )
        
        # Conformal intervals
        if hasattr(self, 'q80'):
            result['ic80_lower'] = np.maximum(result['y_pred'] - self.q80, 0)
            result['ic80_upper'] = result['y_pred'] + self.q80
            result['ic95_lower'] = np.maximum(result['y_pred'] - self.q95, 0)
            result['ic95_upper'] = result['y_pred'] + self.q95
        
        result['risk_level'] = pd.cut(result['risk_score'], 
            bins=[-1, 0.15, 0.35, 0.6, 1.0],
            labels=['baixo', 'moderado', 'alto', 'extremo'])
        
        # Top factors
        result['top_factor'] = result[['fuel_score', 'drying_score', 'ignition_score', 
                                       'spread_score', 'regime_score']].idxmax(axis=1).str.replace('_score', '')
        
        return result
    
    def explain(self, df_row: pd.Series) -> dict:
        """Produz a etapa `explain` do fluxo FireCast.
        
        A funcao faz parte de `src/research/difer_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred = self.predict(df_row.to_frame().T)
        return {
            'prediction': float(pred['y_pred'].iloc[0]),
            'fuel': float(pred['fuel_score'].iloc[0]),
            'drying': float(pred['drying_score'].iloc[0]),
            'ignition': float(pred['ignition_score'].iloc[0]),
            'spread': float(pred['spread_score'].iloc[0]),
            'regime': float(pred['regime_score'].iloc[0]),
            'top_factor': str(pred['top_factor'].iloc[0]),
            'risk_level': str(pred['risk_level'].iloc[0]),
        }
