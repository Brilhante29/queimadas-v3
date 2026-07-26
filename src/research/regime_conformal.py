"""Modulo publico do FireCast para prototipos de pesquisa e ideias de fronteira.

Arquivo `src/research/regime_conformal.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import logging

logger = logging.getLogger(__name__)


class RegimeConformalFire:
    """Representa `RegimeConformalFire` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/research/regime_conformal.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(
        self,
        extreme_threshold: int = 30,
        coverage_levels: list = None,
        ytd_amplification_factor: float = 1.5,
    ):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.extreme_threshold = extreme_threshold
        self.coverage_levels = coverage_levels or [0.80, 0.95]
        self.ytd_amp = ytd_amplification_factor
        
        self.base_model = None
        self.regime_detector = None
        self.quantile_models = {}
        self.conformal_quantiles = {}
        
        self.scaler = StandardScaler()
        self.feature_cols = []
        
        self.is_fitted = False
    
    def _detect_regime(self, df: pd.DataFrame) -> np.ndarray:
        """Executa a etapa `detect regime` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if 'nino34_anomaly' in df.columns:
            nino = df['nino34_anomaly'].values
        elif 'enso_index' in df.columns:
            nino = df['enso_index'].values
        else:
            return np.zeros(len(df), dtype=int)  # neutro default
        
        # 0 = Neutro, 1 = El Nino, -1 = La Nina
        regime = np.where(nino > 0.5, 1, np.where(nino < -0.5, -1, 0))
        return regime
    
    def _compute_ytd_shock(self, df: pd.DataFrame) -> np.ndarray:
        """Executa a etapa `compute ytd shock` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if 'fire_ytd' not in df.columns:
            return np.ones(len(df))
        
        ytd = df['fire_ytd'].values
        
        # Climatologia YTD esperada (aprox por mes)
        if 'same_month_last_year' in df.columns:
            ytd_expected = df['same_month_last_year'].values * df.get('mes', pd.Series(6, index=df.index)).values
        else:
            ytd_expected = ytd.mean()  # fallback
        
        # Ratio
        ratio = ytd / (np.abs(ytd_expected) + 1e-6)
        
        # Amplificacao: suave, max 2x
        shock = 1 + np.tanh((ratio - 1) * 0.5) * (self.ytd_amp - 1)
        shock = np.clip(shock, 0.5, self.ytd_amp)
        
        return shock
    
    def _select_features(self, df: pd.DataFrame) -> list:
        """Executa a etapa `select features` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        exclude = [
            'fire_count', 'occurrence', 'extreme_event', 'hist_positive',
            'municipio_nome', 'municipio_norm', 'estado', 'ano', 'mes',
            'enso_regime', 'date_month',
        ]
        
        numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c not in exclude]
        
        # Prioritize features
        priority = [
            'fire_lag1', 'fire_lag2', 'fire_lag3', 'fire_roll3', 'fire_ytd',
            'vpd', 'precip', 'temperature', 'soil_moisture',
            'nino', 'enso', 'month_sin', 'month_cos',
            'is_critical', 'is_dry_season',
        ]
        
        selected = [c for c in priority if c in numeric_cols]
        remaining = [c for c in numeric_cols if c not in selected]
        selected.extend(remaining)
        
        return selected[:40]  # limit
    
    def fit(self, df_train: pd.DataFrame, df_cal: pd.DataFrame = None):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("=" * 60)
        logger.info("Regime-Conformal Fire: Training")
        logger.info("=" * 60)
        
        self.feature_cols = self._select_features(df_train)
        
        y = df_train['fire_count'].values
        y_log = np.log1p(y)
        
        X = df_train[self.feature_cols].fillna(0)
        Xs = self.scaler.fit_transform(X)
        
        # === Base Model ===
        logger.info("[1/4] Training base regressor...")
        self.base_model = RandomForestRegressor(
            n_estimators=100, max_depth=6, random_state=42, n_jobs=-1
        )
        self.base_model.fit(Xs, y_log)
        
        # === Regime Detector ===
        logger.info("[2/4] Training regime detector...")
        regime = self._detect_regime(df_train)
        
        self.regime_detector = RandomForestRegressor(
            n_estimators=50, max_depth=4, random_state=42, n_jobs=-1
        )
        # Predict regime as function of features
        self.regime_detector.fit(Xs, regime)
        
        regime_counts = pd.Series(regime).value_counts()
        logger.info(f"  Regime distribution: {regime_counts.to_dict()}")
        
        # === Quantile Models for Adaptive Intervals ===
        logger.info("[3/4] Training quantile models...")
        for q in [0.1, 0.25, 0.75, 0.9]:
            from sklearn.ensemble import GradientBoostingRegressor
            qmodel = GradientBoostingRegressor(
                n_estimators=50, max_depth=4, 
                loss='quantile', alpha=q,
                random_state=42
            )
            qmodel.fit(Xs, y)
            self.quantile_models[q] = qmodel
            logger.info(f"  Quantile {q} trained")
        
        # === Conformal Calibration by Regime ===
        if df_cal is not None and len(df_cal) > 10:
            logger.info("[4/4] Calibrating conformal by regime...")
            self._calibrate_conformal(df_cal)
        
        self.is_fitted = True
        logger.info("Regime-Conformal training complete!")
        return self
    
    def _calibrate_conformal(self, df_cal: pd.DataFrame):
        """Executa a etapa `calibrate conformal` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X_cal = df_cal[self.feature_cols].fillna(0)
        X_cal_s = self.scaler.transform(X_cal)
        
        y_cal_pred = np.expm1(self.base_model.predict(X_cal_s))
        y_cal_true = df_cal['fire_count'].values
        residuals = np.abs(y_cal_true - y_cal_pred)
        
        # Detectar regime no set de calibracao
        regime_cal = self._detect_regime(df_cal)
        
        # Calibrar global
        self.conformal_quantiles['global'] = {
            lev: np.quantile(residuals, lev) for lev in self.coverage_levels
        }
        
        # Calibrar por regime
        for reg_name, reg_val in [('neutro', 0), ('el_nino', 1), ('la_nina', -1)]:
            mask = regime_cal == reg_val
            if mask.sum() > 10:
                res_reg = residuals[mask]
                self.conformal_quantiles[reg_name] = {
                    lev: np.quantile(res_reg, lev) for lev in self.coverage_levels
                }
                logger.info(f"  {reg_name}: n={mask.sum()}, q80={self.conformal_quantiles[reg_name][0.80]:.2f}")
        
        logger.info(f"  Calibrated regimes: {list(self.conformal_quantiles.keys())}")
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        
        result = df.copy()
        
        X = df[self.feature_cols].fillna(0)
        Xs = self.scaler.transform(X)
        
        # Base prediction
        base_pred_log = self.base_model.predict(Xs)
        base_pred = np.maximum(np.expm1(base_pred_log), 0)
        
        # Regime detection
        regime = self._detect_regime(df)
        regime_name = np.where(regime > 0.5, 'el_nino', 
                              np.where(regime < -0.5, 'la_nina', 'neutro'))
        
        # YTD Shock amplification
        shock = self._compute_ytd_shock(df)
        
        # Apply amplification
        y_pred = base_pred * shock
        
        result['y_pred'] = y_pred
        result['base_pred'] = base_pred
        result['ytd_shock'] = shock
        result['regime_detected'] = regime_name
        
        # Occurrence probability
        result['p_occurrence'] = np.minimum(1 - np.exp(-base_pred * 0.1), 0.95)
        
        # Extreme probability
        result['p_extreme'] = (result['y_pred'] > self.extreme_threshold).astype(float) * result['p_occurrence']
        
        # Quantile-based intervals
        if self.quantile_models:
            q10 = self.quantile_models[0.1].predict(Xs)
            q25 = self.quantile_models[0.25].predict(Xs)
            q75 = self.quantile_models[0.75].predict(Xs)
            q90 = self.quantile_models[0.9].predict(Xs)
            
            result['q10'] = q10 * shock
            result['q25'] = q25 * shock
            result['q75'] = q75 * shock
            result['q90'] = q90 * shock
        
        # Conformal intervals (regime-aware)
        result['ic80_lower'] = result['y_pred'].copy()
        result['ic80_upper'] = result['y_pred'].copy()
        result['ic95_lower'] = result['y_pred'].copy()
        result['ic95_upper'] = result['y_pred'].copy()
        
        for i, reg in enumerate(regime_name):
            cq = self.conformal_quantiles.get(reg, self.conformal_quantiles.get('global', {0.80: 2.0, 0.95: 5.0}))
            
            q80 = cq.get(0.80, 2.0)
            q95 = cq.get(0.95, 5.0)
            
            # Adjust by shock
            q80_adj = q80 * shock[i]
            q95_adj = q95 * shock[i]
            
            result.loc[result.index[i], 'ic80_lower'] = max(result.loc[result.index[i], 'y_pred'] - q80_adj, 0)
            result.loc[result.index[i], 'ic80_upper'] = result.loc[result.index[i], 'y_pred'] + q80_adj
            result.loc[result.index[i], 'ic95_lower'] = max(result.loc[result.index[i], 'y_pred'] - q95_adj, 0)
            result.loc[result.index[i], 'ic95_upper'] = result.loc[result.index[i], 'y_pred'] + q95_adj
        
        # Risk score incorporating regime and shock
        result['risk_score'] = (
            0.25 * result['p_occurrence']
            + 0.25 * np.minimum(result['y_pred'] / 50, 1.0)
            + 0.20 * (result['regime_detected'] == 'el_nino').astype(float)
            + 0.15 * np.minimum((result['ytd_shock'] - 1) * 2, 1.0)
            + 0.15 * result['p_extreme']
        )
        
        result['risk_level'] = pd.cut(
            result['risk_score'],
            bins=[-1, 0.2, 0.5, 0.75, 1.0],
            labels=['baixo', 'moderado', 'alto', 'extremo']
        )
        
        return result
    
    def explain_regime_impact(self, df: pd.DataFrame) -> pd.DataFrame:
        """Produz a etapa `explain regime impact` do fluxo FireCast.
        
        A funcao faz parte de `src/research/regime_conformal.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        pred = self.predict(df)
        
        summary = pred.groupby('regime_detected').agg({
            'y_pred': ['mean', 'std', 'max'],
            'ytd_shock': 'mean',
            'p_extreme': 'mean',
            'risk_score': 'mean',
        }).round(3)
        
        return summary
