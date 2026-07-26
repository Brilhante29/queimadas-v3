"""Modulo publico do FireCast para prototipos de pesquisa e ideias de fronteira.

Arquivo `src/research/spatial_contagion.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from scipy.spatial.distance import cdist
import logging

logger = logging.getLogger(__name__)


class SpatialContagionFire:
    """Representa `SpatialContagionFire` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/research/spatial_contagion.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(
        self,
        extreme_threshold: int = 30,
        contagion_decay: float = 0.05,
        alpha_contagion: float = 0.3,
        n_neighbors: int = 5,
    ):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.extreme_threshold = extreme_threshold
        self.contagion_decay = contagion_decay
        self.alpha = alpha_contagion
        self.n_neighbors = n_neighbors
        
        self.local_model = None
        self.fusion_weights = None
        
        self.scaler = StandardScaler()
        self.feature_cols = []
        
        self.is_fitted = False
    
    def _build_spatial_weights(self, df: pd.DataFrame) -> np.ndarray:
        """Executa a etapa `build spatial weights` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        n = len(df)
        
        if 'latitude' in df.columns and 'longitude' in df.columns:
            coords = df[['latitude', 'longitude']].values
        elif 'lat' in df.columns and 'lon' in df.columns:
            coords = df[['lat', 'lon']].values
        else:
            # Heuristica: agrupar por estado e municipio
            # Pesos baseados em mesmo estado = vizinhanca
            estados = df.get('estado', pd.Series('CE', index=df.index)).values
            W = np.zeros((n, n))
            for i in range(n):
                for j in range(i+1, n):
                    if estados[i] == estados[j]:
                        W[i, j] = 0.5
                        W[j, i] = 0.5
            return W
        
        # Distancia geografica
        dist = cdist(coords, coords, metric='euclidean')
        
        # Decaimento exponencial
        W = np.exp(-self.contagion_decay * dist)
        
        # Zerar diagonal
        np.fill_diagonal(W, 0)
        
        # Manter apenas k vizinhos mais proximos
        for i in range(n):
            idx = np.argsort(W[i])[:-self.n_neighbors]
            W[i, idx] = 0
        
        # Normalizar por linha
        row_sums = W.sum(axis=1, keepdims=True)
        W = W / (row_sums + 1e-6)
        
        return W
    
    def _compute_contagion_effect(self, df: pd.DataFrame) -> np.ndarray:
        """Executa a etapa `compute contagion effect` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        W = self._build_spatial_weights(df)
        
        # Usar fire_lag1 como proxy do estado anterior dos vizinhos
        if 'fire_lag1' in df.columns:
            fire_lag = df['fire_lag1'].fillna(0).values
        elif 'fire_count' in df.columns:
            fire_lag = df['fire_count'].fillna(0).values
        else:
            return np.zeros(len(df))
        
        # Contagio = W * fire_lag (vizinhos queimando no mes anterior)
        contagion = W.dot(fire_lag)
        
        return contagion
    
    def _adaptive_fusion_weights(self, df: pd.DataFrame) -> dict:
        """Executa a etapa `adaptive fusion weights` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        sources = {}
        
        # Fonte climatica
        climate_cols = [c for c in df.columns if any(k in c.lower() for k in [
            'temperature', 'precip', 'vpd', 'humidity'
        ])]
        if climate_cols:
            climate_var = df[climate_cols].var().mean()
            sources['climate'] = 1.0 / (1 + climate_var)
        
        # Fonte de memoria
        memory_cols = [c for c in df.columns if 'fire_lag' in c or 'fire_roll' in c]
        if memory_cols:
            memory_var = df[memory_cols].var().mean()
            sources['memory'] = 1.0 / (1 + memory_var)
        
        # Fonte humana
        human_cols = [c for c in df.columns if any(k in c.lower() for k in [
            'human', 'road', 'agriculture'
        ])]
        if human_cols:
            human_var = df[human_cols].var().mean()
            sources['human'] = 1.0 / (1 + human_var)
        
        # Normalizar
        total = sum(sources.values())
        if total > 0:
            sources = {k: v / total for k, v in sources.items()}
        
        return sources
    
    def _select_features(self, df: pd.DataFrame) -> list:
        """Executa a etapa `select features` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        exclude = [
            'fire_count', 'occurrence', 'extreme_event', 'hist_positive',
            'municipio_nome', 'municipio_norm', 'estado',
        ]
        
        numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c not in exclude]
        
        # Incluir contagion e spatial features
        priority = [
            'fire_lag1', 'fire_lag2', 'fire_lag3', 'fire_roll3', 'fire_ytd',
            'spatial_contagion', 'neighbor_fire', 'neighbor_count',
            'vpd', 'precip', 'temperature',
            'nino', 'enso', 'month_sin', 'month_cos',
        ]
        
        selected = [c for c in priority if c in numeric_cols]
        remaining = [c for c in numeric_cols if c not in selected]
        selected.extend(remaining)
        
        return selected[:40]
    
    def fit(self, df_train: pd.DataFrame, df_cal: pd.DataFrame = None):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("=" * 60)
        logger.info("Spatial-Contagion Fire: Training")
        logger.info("=" * 60)
        
        self.feature_cols = self._select_features(df_train)
        
        y = df_train['fire_count'].values
        y_log = np.log1p(y)
        
        # === Contagion Feature ===
        logger.info("[1/4] Computing spatial contagion...")
        contagion = self._compute_contagion_effect(df_train)
        df_train = df_train.copy()
        df_train['spatial_contagion'] = contagion
        
        contagion_corr = np.corrcoef(contagion, y)[0, 1] if len(y) > 1 else 0
        logger.info(f"  Contagion-fire correlation: {contagion_corr:.3f}")
        
        # === Local Model ===
        logger.info("[2/4] Training local model...")
        X = df_train[self.feature_cols + ['spatial_contagion']].fillna(0)
        Xs = self.scaler.fit_transform(X)
        
        self.local_model = RandomForestRegressor(
            n_estimators=100, max_depth=6, random_state=42, n_jobs=-1
        )
        self.local_model.fit(Xs, y_log)
        
        # === Fusion Weights ===
        logger.info("[3/4] Computing adaptive fusion weights...")
        self.fusion_weights = self._adaptive_fusion_weights(df_train)
        logger.info(f"  Fusion weights: {self.fusion_weights}")
        
        self.is_fitted = True
        
        # Calibrate conformal (after is_fitted for predict to work)
        if df_cal is not None and len(df_cal) > 10:
            logger.info("[4/4] Calibrating conformal...")
            self._calibrate(df_cal)
        
        logger.info("Spatial-Contagion training complete!")
        return self
    
    def _calibrate(self, df_cal: pd.DataFrame):
        """Executa a etapa `calibrate` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred_cal = self.predict(df_cal)
        residuals = np.abs(df_cal['fire_count'].values - pred_cal['y_pred'].values)
        self.q80 = np.quantile(residuals, 0.80)
        self.q95 = np.quantile(residuals, 0.95)
        logger.info(f"  Conformal calibrated: q80={self.q80:.2f}, q95={self.q95:.2f}")
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        result = df.copy()
        
        # Compute contagion
        contagion = self._compute_contagion_effect(df)
        result['spatial_contagion'] = contagion
        
        # Predict
        X = result[self.feature_cols + ['spatial_contagion']].fillna(0)
        Xs = self.scaler.transform(X)
        
        y_pred_log = self.local_model.predict(Xs)
        y_pred = np.maximum(np.expm1(y_pred_log), 0)
        
        # Blend local + contagion
        local_component = y_pred * (1 - self.alpha)
        contagion_component = contagion * self.alpha
        y_pred_blend = local_component + contagion_component
        
        result['y_pred'] = y_pred_blend
        result['local_component'] = local_component
        result['contagion_component'] = contagion_component
        
        # Occurrence probability
        result['p_occurrence'] = np.minimum(1 - np.exp(-y_pred * 0.1), 0.95)
        
        # Extreme probability
        result['p_extreme'] = (result['y_pred'] > self.extreme_threshold).astype(float) * result['p_occurrence']
        
        # Risk score with spatial dimension
        result['risk_score'] = (
            0.25 * result['p_occurrence']
            + 0.25 * np.minimum(result['y_pred'] / 50, 1.0)
            + 0.20 * result['p_extreme']
            + 0.15 * np.minimum(result['spatial_contagion'] / 10, 1.0)
            + 0.15 * result.get('human_pressure_index', pd.Series(0, index=result.index)).fillna(0)
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
        
        # Fusion diagnostics
        if self.fusion_weights:
            result['fusion_weight_climate'] = self.fusion_weights.get('climate', 0.33)
            result['fusion_weight_memory'] = self.fusion_weights.get('memory', 0.33)
            result['fusion_weight_human'] = self.fusion_weights.get('human', 0.33)
        
        return result
    
    def get_spatial_risk_map(self, df: pd.DataFrame) -> pd.DataFrame:
        """Executa a etapa `get spatial risk map` do fluxo FireCast.
        
        A funcao faz parte de `src/research/spatial_contagion.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred = self.predict(df)
        
        # Identificar clusters de alto risco
        high_risk = pred[pred['risk_level'].isin(['alto', 'extremo'])]
        
        # Agrupar por estado
        risk_map = pred.groupby('estado' if 'estado' in pred.columns else 'municipio_norm').agg({
            'y_pred': 'sum',
            'risk_score': 'mean',
            'spatial_contagion': 'mean',
            'p_extreme': 'mean',
        }).round(3)
        
        return risk_map.sort_values('risk_score', ascending=False)
