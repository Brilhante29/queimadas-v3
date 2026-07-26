"""Modulo publico do FireCast para prototipos de pesquisa e ideias de fronteira.

Arquivo `src/research/hilt_fire.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
import logging

logger = logging.getLogger(__name__)


class HILTFire:
    """Representa `HILTFire` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/research/hilt_fire.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(
        self,
        extreme_threshold: int = 30,
        transfer_levels: list = None,
        invariant_components: int = 8,
    ):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.extreme_threshold = extreme_threshold
        self.transfer_levels = transfer_levels or ['ceara', 'chapada_araripe', 'brazil']
        self.n_invariant = invariant_components
        
        self.level_models = {}
        self.invariant_projector = None
        self.scalers = {}
        
        self.invariant_cols = []
        self.variant_cols = []
        
        self.is_fitted = False
        
        # Innovation ledger
        self.transfer_history = []
    
    def _split_features(self, df: pd.DataFrame):
        """Executa a etapa `split features` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        all_cols = [c for c in df.select_dtypes(include=[np.number]).columns]
        
        # Invariantes: climaticas puras (transferiveis)
        self.invariant_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'vpd', 'vapour_pressure', 'precipitation_sum', 'temperature',
            'soil_moisture', 'et0', 'humidity', 'radiation', 'wind',
            'nino', 'enso', 'month_sin', 'month_cos', 'is_critical',
            'is_dry_season', 'water_deficit', 'dry', 'anom',
        ])]
        
        # Variantes: locais (especificas do municipio/regiao)
        self.variant_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'road', 'human', 'agriculture', 'pasture', 'population',
            'land_cover', 'elevation', 'slope', 'osm', 'ibge',
            'municipio_id', 'state_encoded', 'region_encoded',
        ])]
        
        # Memoria de fogo e features temporais sao hibridas
        self.hybrid_cols = [c for c in all_cols if any(k in c.lower() for k in [
            'fire_lag', 'fire_roll', 'fire_ytd', 'neighbor', 'spatial',
            'trend', 'hist',
        ])]
        
        logger.info(f"HILT feature split:")
        logger.info(f"  Invariant (climate): {len(self.invariant_cols)}")
        logger.info(f"  Variant (local): {len(self.variant_cols)}")
        logger.info(f"  Hybrid: {len(self.hybrid_cols)}")
    
    def _extract_invariant_latent(self, df: pd.DataFrame, fit: bool = False):
        """Executa a etapa `extract invariant latent` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X_inv = df[self.invariant_cols].fillna(0) if self.invariant_cols else np.zeros((len(df), 1))
        
        if fit:
            self.invariant_projector = PCA(n_components=min(self.n_invariant, X_inv.shape[1]), random_state=42)
            latent = self.invariant_projector.fit_transform(X_inv)
            logger.info(f"  Invariant PCA: {X_inv.shape[1]} -> {latent.shape[1]} components")
            logger.info(f"  Explained variance: {self.invariant_projector.explained_variance_ratio_.sum():.3f}")
        else:
            latent = self.invariant_projector.transform(X_inv) if self.invariant_projector else X_inv
        
        return latent
    
    def fit(self, df_train: pd.DataFrame, df_cal: pd.DataFrame = None):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("=" * 60)
        logger.info("HILT-Fire: Hierarchical Invariant Latent Transfer")
        logger.info("=" * 60)
        
        self._split_features(df_train)
        
        y = df_train['fire_count'].values
        y_log = np.log1p(y)
        
        # Extract invariant latent representation
        logger.info("[L0] Training global invariant model...")
        latent_inv = self._extract_invariant_latent(df_train, fit=True)
        
        # Combine invariant + hybrid features for global model
        X_hybrid = df_train[self.hybrid_cols].fillna(0).values if self.hybrid_cols else np.zeros((len(df_train), 1))
        X_global = np.hstack([latent_inv, X_hybrid])
        
        self.scalers['global'] = StandardScaler()
        X_global_s = self.scalers['global'].fit_transform(X_global)
        
        self.level_models['global'] = GradientBoostingRegressor(
            n_estimators=100, max_depth=5, random_state=42
        )
        self.level_models['global'].fit(X_global_s, y_log)
        
        global_pred_log = self.level_models['global'].predict(X_global_s)
        
        # Regional adapters
        for level in self.transfer_levels:
            logger.info(f"[{level}] Training regional adapter...")
            
            # Determinar mascara regional
            if level == 'ceara':
                mask = df_train.get('estado', pd.Series('CE', index=df_train.index)) == 'CE'
            elif level == 'chapada_araripe':
                # Heuristica: municipios no sul do CE, norte de PE/PI
                estados = df_train.get('estado', pd.Series('CE', index=df_train.index))
                mask = estados.isin(['CE', 'PE', 'PI'])
            else:  # brazil
                mask = np.ones(len(df_train), dtype=bool)
            
            if mask.sum() < 50:
                logger.info(f"  Skipping {level}: insufficient data ({mask.sum()})")
                continue
            
            # Residual do nivel global nesta regiao
            residual_log = y_log[mask] - global_pred_log[mask]
            
            # Features variantes para esta regiao
            df_region = df_train[mask]
            X_var = df_region[self.variant_cols].fillna(0).values if self.variant_cols else np.zeros((mask.sum(), 1))
            X_lat = latent_inv[mask]
            
            X_region = np.hstack([X_lat, X_var])
            self.scalers[level] = StandardScaler()
            X_region_s = self.scalers[level].fit_transform(X_region)
            
            self.level_models[level] = RandomForestRegressor(
                n_estimators=50, max_depth=5, random_state=42, n_jobs=-1
            )
            self.level_models[level].fit(X_region_s, residual_log)
            
            region_pred = self.level_models[level].predict(X_region_s)
            residual_var_explained = 1 - np.var(residual_log - region_pred) / max(np.var(residual_log), 1e-6)
            
            self.transfer_history.append({
                'level': level,
                'n_samples': int(mask.sum()),
                'residual_var_explained': residual_var_explained,
            })
            logger.info(f"  Residual variance explained: {residual_var_explained:.3f}")
        
        self.is_fitted = True
        
        # Calibrate conformal (after is_fitted for predict to work)
        if df_cal is not None and len(df_cal) > 10:
            self._calibrate(df_cal)
        
        logger.info("HILT-Fire training complete!")
        return self
    
    def _calibrate(self, df_cal: pd.DataFrame):
        """Executa a etapa `calibrate` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred_cal = self.predict(df_cal)
        residuals = np.abs(df_cal['fire_count'].values - pred_cal['y_pred'].values)
        self.q80 = np.quantile(residuals, 0.80)
        self.q95 = np.quantile(residuals, 0.95)
        logger.info(f"  Conformal calibrated: q80={self.q80:.2f}, q95={self.q95:.2f}")
    
    def predict(self, df: pd.DataFrame, target_level: str = 'ceara') -> pd.DataFrame:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        result = df.copy()
        
        # Invariant latent
        latent_inv = self._extract_invariant_latent(df)
        
        # Global prediction
        X_hybrid = df[self.hybrid_cols].fillna(0).values if self.hybrid_cols else np.zeros((len(df), 1))
        X_global = np.hstack([latent_inv, X_hybrid])
        X_global_s = self.scalers['global'].transform(X_global)
        global_pred_log = self.level_models['global'].predict(X_global_s)
        
        # Regional residual adaptation
        level = target_level if target_level in self.level_models else 'global'
        if level != 'global' and level in self.level_models:
            X_var = df[self.variant_cols].fillna(0).values if self.variant_cols else np.zeros((len(df), 1))
            X_region = np.hstack([latent_inv, X_var])
            X_region_s = self.scalers[level].transform(X_region)
            regional_residual_log = self.level_models[level].predict(X_region_s)
        else:
            regional_residual_log = 0
        
        # Combine: y = exp(global_log + regional_residual_log) - 1
        y_pred = np.maximum(np.expm1(global_pred_log + regional_residual_log), 0)
        
        result['y_pred'] = y_pred
        result['global_component'] = np.maximum(np.expm1(global_pred_log), 0)
        result['regional_residual'] = regional_residual_log
        result['transfer_level_used'] = level
        
        # Occurrence probability
        result['p_occurrence'] = np.minimum(1 - np.exp(-result['global_component'] * 0.1), 0.95)
        
        # Extreme probability
        result['p_extreme'] = (result['y_pred'] > self.extreme_threshold).astype(float) * result['p_occurrence']
        
        # Risk score
        result['risk_score'] = (
            0.30 * result['p_occurrence']
            + 0.30 * np.minimum(result['y_pred'] / 50, 1.0)
            + 0.20 * result['p_extreme']
            + 0.20 * np.tanh(np.abs(regional_residual_log))
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
        
        return result
    
    def transfer_score(self, df_source: pd.DataFrame, df_target: pd.DataFrame) -> dict:
        """Executa a etapa `transfer score` do fluxo FireCast.
        
        A funcao faz parte de `src/research/hilt_fire.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        latent_source = self._extract_invariant_latent(df_source)
        latent_target = self._extract_invariant_latent(df_target)
        
        # Alignment via cosine similarity of means
        mean_source = latent_source.mean(axis=0)
        mean_target = latent_target.mean(axis=0)
        
        cos_sim = np.dot(mean_source, mean_target) / (
            np.linalg.norm(mean_source) * np.linalg.norm(mean_target) + 1e-6
        )
        
        # Distribution overlap (approx via mean distance)
        dist = np.linalg.norm(mean_source - mean_target) / (
            np.linalg.norm(mean_source) + np.linalg.norm(mean_target) + 1e-6
        )
        
        return {
            'cosine_similarity': float(cos_sim),
            'distribution_distance': float(dist),
            'transfer_recommended': cos_sim > 0.7 and dist < 0.5,
        }
