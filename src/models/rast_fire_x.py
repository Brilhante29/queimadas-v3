"""Modulo publico do FireCast para familias de modelos e baselines comparaveis.

Arquivo `src/models/rast_fire_x.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import StandardScaler
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class RASTFireX:
    """Representa `RASTFireX` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/rast_fire_x.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(
        self,
        extreme_threshold: int = 30,
        occurrence_model: str = "xgboost",
        count_model: str = "xgboost",
        extreme_model: str = "xgboost",
        regime_model: str = "xgboost",
        use_human_latent: bool = True,
        use_regime_aware: bool = True,
    ):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.extreme_threshold = extreme_threshold
        self.use_human_latent = use_human_latent
        self.use_regime_aware = use_regime_aware
        
        # Modelos
        self.m1_occurrence = None
        self.m2_count = None
        self.m3_extreme = None
        self.m4_regime = None
        self.m5_conformal = {}
        
        # Scalers
        self.scaler_m1 = StandardScaler()
        self.scaler_m2 = StandardScaler()
        self.scaler_m3 = StandardScaler()
        self.scaler_m4 = StandardScaler()
        
        # Features
        self.feature_cols_m1 = None
        self.feature_cols_m2 = None
        self.feature_cols_m3 = None
        self.feature_cols_m4 = None
        self.imputation_values = {}
        
        # Estado
        self.is_fitted = False
        self.innovation_ledger = []
    
    def _select_features(self, df: pd.DataFrame, mode: str = "all") -> list:
        """Executa a etapa `select features` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        exclude = [
            "fire_count", "y", "hist_positive", "municipio_id", "municipio_nome",
            "enso_regime", "estacao", "regime_label", "date_month",
            "occurrence", "extreme_event", "frp_sum", "frp_mean",
        ]
        
        excluded_names = {c.lower() for c in exclude}
        numeric_cols = [
            c for c in df.select_dtypes(include=[np.number]).columns
            if c.lower() not in excluded_names
        ]
        
        if mode == "occurrence":
            # M1: foco em clima + vegetação + humano
            priority = ["vpd", "soil", "ndvi", "precip", "temp", "human", "fuel", "dry", "month"]
            return [c for c in numeric_cols if any(p in c.lower() for p in priority)] or numeric_cols
        
        elif mode == "count":
            # M2: todas as features exceto targets
            return numeric_cols
        
        elif mode == "extreme":
            # M3: foco em acumulados, ENSO, estresse
            priority = ["ytd", "enso", "vpd", "fuel", "dry", "human", "stress", "regime"]
            return [c for c in numeric_cols if any(p in c.lower() for p in priority)] or numeric_cols
        
        elif mode == "regime":
            # M4: acumulados + ENSO + contexto espacial
            priority = ["ytd", "enso", "vpd", "precip", "fire", "human", "month", "state"]
            return [c for c in numeric_cols if any(p in c.lower() for p in priority)] or numeric_cols
        
        return numeric_cols
    
    def fit(self, df_train: pd.DataFrame, df_cal: Optional[pd.DataFrame] = None):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("=" * 60)
        logger.info("RAST-Fire-X: Training")
        logger.info("=" * 60)
        
        # === M1: Ocorrência ===
        logger.info("[M1] Training occurrence classifier...")
        self.feature_cols_m1 = self._select_features(df_train, "occurrence")
        self.imputation_values["m1"] = df_train[self.feature_cols_m1].median().fillna(0)
        X1 = df_train[self.feature_cols_m1].fillna(self.imputation_values["m1"])
        y1 = (df_train["fire_count"] > 0).astype(int).values
        X1s = self.scaler_m1.fit_transform(X1)
        
        self.m1_occurrence = CalibratedClassifierCV(
            RandomForestClassifier(50, max_depth=6, class_weight="balanced", random_state=42, n_jobs=-1),
            cv=3
        )
        self.m1_occurrence.fit(X1s, y1)
        logger.info(f"  Features: {len(self.feature_cols_m1)}, AUC: ~{self._approx_auc(X1s, y1):.3f}")
        
        # === M2: Contagem ===
        logger.info("[M2] Training count regressor...")
        self.feature_cols_m2 = self._select_features(df_train, "count")
        self.imputation_values["m2"] = df_train[self.feature_cols_m2].median().fillna(0)
        X2 = df_train[self.feature_cols_m2].fillna(self.imputation_values["m2"])
        y2 = np.log1p(df_train["fire_count"].values)  # log transform
        X2s = self.scaler_m2.fit_transform(X2)
        
        self.m2_count = HistGradientBoostingRegressor(
            loss="squared_error", max_iter=200, max_depth=8, random_state=42
        )
        self.m2_count.fit(X2s, y2)
        logger.info(f"  Features: {len(self.feature_cols_m2)}")
        
        # === M3: Extremo ===
        logger.info("[M3] Training extreme classifier...")
        self.feature_cols_m3 = self._select_features(df_train, "extreme")
        self.imputation_values["m3"] = df_train[self.feature_cols_m3].median().fillna(0)
        X3 = df_train[self.feature_cols_m3].fillna(self.imputation_values["m3"])
        y3 = (df_train["fire_count"] >= self.extreme_threshold).astype(int).values
        X3s = self.scaler_m3.fit_transform(X3)
        
        if y3.sum() > 10 and (1 - y3).sum() > 10:
            self.m3_extreme = CalibratedClassifierCV(
                RandomForestClassifier(100, max_depth=6, class_weight="balanced", random_state=42, n_jobs=-1),
                cv=3
            )
            self.m3_extreme.fit(X3s, y3)
            logger.info(f"  Features: {len(self.feature_cols_m3)}, Positives: {y3.sum()}")
        else:
            logger.warning("  Too few extremes, using fallback")
            self.m3_extreme = None
        
        # === M4: Regime ===
        logger.info("[M4] Training regime detector...")
        self.feature_cols_m4 = self._select_features(df_train, "regime")
        self.imputation_values["m4"] = df_train[self.feature_cols_m4].median().fillna(0)
        X4 = df_train[self.feature_cols_m4].fillna(self.imputation_values["m4"])
        
        # Definir regime: percentil 75 = alto, 90 = extremo
        p75 = max(1, df_train["fire_count"].quantile(0.75))
        p90 = max(p75 + 1, df_train["fire_count"].quantile(0.90))
        y4 = pd.cut(df_train["fire_count"], bins=[-1, 0, p75, p90, 9999], labels=[0, 1, 2, 3]).astype(int)
        
        X4s = self.scaler_m4.fit_transform(X4)
        self.m4_regime = RandomForestClassifier(100, max_depth=6, random_state=42, n_jobs=-1)
        self.m4_regime.fit(X4s, y4)
        logger.info(f"  Features: {len(self.feature_cols_m4)}, Regimes: {y4.value_counts().to_dict()}")
        
        # === M5: Conformal Prediction ===
        if df_cal is not None:
            logger.info("[M5] Calibrating conformal prediction...")
            self._calibrate_conformal(df_cal)
        
        self.is_fitted = True
        logger.info("RAST-Fire-X training complete!")
        return self
    
    def _approx_auc(self, X, y):
        """Executa a etapa `approx auc` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            from sklearn.metrics import roc_auc_score
            prob = self.m1_occurrence.predict_proba(X)[:, 1]
            return roc_auc_score(y, prob)
        except:
            return 0.5
    
    def _calibrate_conformal(self, df_cal: pd.DataFrame):
        """Executa a etapa `calibrate conformal` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        # Prever no set de calibração
        X2 = self._prepare_features(df_cal, self.feature_cols_m2, "m2")
        X2s = self.scaler_m2.transform(X2)
        y_cal_pred = np.expm1(self.m2_count.predict(X2s))
        y_cal_true = df_cal["fire_count"].values
        
        residuals = np.abs(y_cal_true - y_cal_pred)
        
        # Calibrar por regime
        for regime_name, mask_func in [
            ("global", lambda df: np.ones(len(df), dtype=bool)),
            ("critical", lambda df: df["mes"].isin([10, 11]).values if "mes" in df.columns else np.ones(len(df), dtype=bool)),
        ]:
            mask = mask_func(df_cal)
            if mask.sum() > 10:
                res = residuals[mask]
                self.m5_conformal[regime_name] = {
                    "q80": np.quantile(res, 0.80),
                    "q95": np.quantile(res, 0.95),
                }
        
        logger.info(f"  Conformal calibrated for regimes: {list(self.m5_conformal.keys())}")
    
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")
        
        result = df.copy()
        
        # M1: Ocorrência
        X1 = self._prepare_features(df, self.feature_cols_m1, "m1")
        X1s = self.scaler_m1.transform(X1)
        result["p_occurrence"] = self.m1_occurrence.predict_proba(X1s)[:, 1]
        
        # M2: Contagem
        X2 = self._prepare_features(df, self.feature_cols_m2, "m2")
        X2s = self.scaler_m2.transform(X2)
        result["y_pred_raw"] = np.expm1(self.m2_count.predict(X2s))
        result["y_pred"] = result["p_occurrence"] * result["y_pred_raw"]
        result["y_pred"] = np.maximum(result["y_pred"].values, 0)
        
        # M3: Extremo
        if self.m3_extreme is not None:
            X3 = self._prepare_features(df, self.feature_cols_m3, "m3")
            X3s = self.scaler_m3.transform(X3)
            result["p_extreme"] = self.m3_extreme.predict_proba(X3s)[:, 1]
        else:
            result["p_extreme"] = result["p_occurrence"] * 0.1
        
        # M4: Regime
        X4 = self._prepare_features(df, self.feature_cols_m4, "m4")
        X4s = self.scaler_m4.transform(X4)
        regime_probs = self.m4_regime.predict_proba(X4s)
        class_prob = {int(label): regime_probs[:, i] for i, label in enumerate(self.m4_regime.classes_)}
        result["p_regime_normal"] = class_prob.get(0, np.zeros(len(df)))
        result["p_regime_alto"] = class_prob.get(1, np.zeros(len(df)))
        result["p_regime_extremo"] = class_prob.get(2, np.zeros(len(df)))
        result["p_regime_incerto"] = class_prob.get(3, np.zeros(len(df)))
        
        # M5: Intervalos conformais
        is_critical = df["mes"].isin([10, 11]).values if "mes" in df.columns else np.ones(len(df), dtype=bool)
        
        q80 = self.m5_conformal.get("critical", self.m5_conformal.get("global", {"q80": 2.0, "q95": 5.0}))["q80"]
        q95 = self.m5_conformal.get("critical", self.m5_conformal.get("global", {"q80": 2.0, "q95": 5.0}))["q95"]
        
        # Ajustar por regime
        regime_boost = 1 + 0.3 * result["p_regime_extremo"].values + 0.15 * result["p_regime_alto"].values
        
        result["ic80_lower"] = np.maximum(result["y_pred"].values - q80 * regime_boost, 0)
        result["ic80_upper"] = result["y_pred"].values + q80 * regime_boost
        result["ic95_lower"] = np.maximum(result["y_pred"].values - q95 * regime_boost, 0)
        result["ic95_upper"] = result["y_pred"].values + q95 * regime_boost
        
        # M6: Risk Score
        result["risk_score"] = (
            0.35 * result["p_extreme"]
            + 0.20 * result["p_occurrence"]
            + 0.15 * np.minimum(result["y_pred"] / 50, 1.0)
            + 0.10 * result.get("human_pressure_index", pd.Series(0, index=result.index))
            + 0.10 * result.get("spatial_pressure_index", pd.Series(0, index=result.index))
            + 0.10 * result["p_regime_extremo"]
        )
        
        result["risk_level"] = pd.cut(
            result["risk_score"],
            bins=[-1, 0.2, 0.5, 0.75, 1.0],
            labels=["baixo", "moderado", "alto", "extremo"],
        )
        
        return result

    def _prepare_features(self, df: pd.DataFrame, feature_cols: list, model_key: str) -> pd.DataFrame:
        """Executa a etapa `prepare features` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        missing = [col for col in feature_cols if col not in df.columns]
        if missing:
            raise ValueError(f"inference data is missing {model_key} features: {missing}")
        return df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(
            self.imputation_values[model_key]
        )
    
    def log_innovation(self, hypothesis: str, result: str, metrics: Dict):
        """Executa a etapa `log innovation` do fluxo FireCast.
        
        A funcao faz parte de `src/models/rast_fire_x.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.innovation_ledger.append({
            "timestamp": pd.Timestamp.now(),
            "hypothesis": hypothesis,
            "result": result,
            **metrics,
        })
