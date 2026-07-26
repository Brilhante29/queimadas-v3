"""Modulo publico do FireCast para familias de modelos e baselines comparaveis.

Arquivo `src/models/baselines.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor, TweedieRegressor
from sklearn.preprocessing import StandardScaler
import logging

logger = logging.getLogger(__name__)


class BaselineModel:
    """Representa `BaselineModel` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, name: str):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.name = name
        self.is_fitted = False
    
    def fit(self, df_train: pd.DataFrame, feature_cols: list, target_col: str = "fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not feature_cols:
            raise ValueError("feature_cols must contain at least one feature")
        missing = [col for col in feature_cols if col not in df_train.columns]
        if missing:
            raise ValueError(f"training data is missing features: {missing}")
        self.feature_cols = list(feature_cols)
        self.target_col = target_col
        return self
    
    def predict(self, df_test: pd.DataFrame) -> np.ndarray:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        raise NotImplementedError


class NaiveLag12(BaselineModel):
    """Representa `NaiveLag12` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("naive_lag12")
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        return df_test["fire_count_lag12"].fillna(0).values if "fire_count_lag12" in df_test.columns else np.zeros(len(df_test))


class ClimatologyMunicipal(BaselineModel):
    """Representa `ClimatologyMunicipal` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("climatology_municipal")
        self.climatology = {}
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        if "municipio_id" in df_train.columns and "mes" in df_train.columns:
            self.climatology = df_train.groupby(["municipio_id", "mes"])[target_col].mean().to_dict()
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        preds = []
        for _, row in df_test.iterrows():
            key = (row.get("municipio_id"), row.get("mes"))
            preds.append(self.climatology.get(key, 0))
        return np.array(preds)


class ClimatologyState(BaselineModel):
    """Representa `ClimatologyState` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("climatology_state")
        self.climatology = {}
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        if "estado" in df_train.columns and "mes" in df_train.columns:
            self.climatology = df_train.groupby(["estado", "mes"])[target_col].mean().to_dict()
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        preds = []
        for _, row in df_test.iterrows():
            key = (row.get("estado"), row.get("mes"))
            preds.append(self.climatology.get(key, 0))
        return np.array(preds)


class HistoricalMean(BaselineModel):
    """Representa `HistoricalMean` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, n_years=3):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__(f"historical_mean_{n_years}y")
        self.n_years = n_years
        self.means = {}
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        if "municipio_id" in df_train.columns and "mes" in df_train.columns:
            recent = df_train[df_train["ano"] >= df_train["ano"].max() - self.n_years]
            self.means = recent.groupby(["municipio_id", "mes"])[target_col].mean().to_dict()
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        preds = []
        for _, row in df_test.iterrows():
            key = (row.get("municipio_id"), row.get("mes"))
            preds.append(self.means.get(key, 0))
        return np.array(preds)


class XGBPoissonFlat(BaselineModel):
    """Representa `XGBPoissonFlat` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("xgboost_poisson_flat")
        self.model = HistGradientBoostingRegressor(loss="poisson", max_iter=100, random_state=42)
        self.scaler = StandardScaler()
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        X = df_train[self.feature_cols].fillna(0)
        y = df_train[target_col].values
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X = df_test[self.feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return np.maximum(self.model.predict(X_scaled), 0)


class XGBPoissonMunicipal(BaselineModel):
    """Representa `XGBPoissonMunicipal` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("xgboost_poisson_municipal")
        self.model = HistGradientBoostingRegressor(loss="poisson", max_iter=200, random_state=42)
        self.scaler = StandardScaler()
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        X = df_train[self.feature_cols].fillna(df_train[self.feature_cols].median())
        y = df_train[target_col].values
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X = df_test[self.feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return np.maximum(self.model.predict(X_scaled), 0)


class GLMPoisson(BaselineModel):
    """Representa `GLMPoisson` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("glm_poisson")
        self.model = PoissonRegressor(alpha=0.1, max_iter=1000)
        self.scaler = StandardScaler()
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        X = df_train[self.feature_cols].fillna(0)
        y = df_train[target_col].values
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X = df_test[self.feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return np.maximum(self.model.predict(X_scaled), 0)


class TweedieModel(BaselineModel):
    """Representa `TweedieModel` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, power=1.5):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__(f"tweedie_p{power}")
        self.power = power
        self.model = TweedieRegressor(power=power, alpha=0.1, max_iter=1000)
        self.scaler = StandardScaler()
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        X = df_train[self.feature_cols].fillna(0)
        y = df_train[target_col].values
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X = df_test[self.feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return np.maximum(self.model.predict(X_scaled), 0)


class RandomForestCount(BaselineModel):
    """Representa `RandomForestCount` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, n_estimators=100):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__(f"random_forest_{n_estimators}")
        self.model = RandomForestRegressor(n_estimators=n_estimators, max_depth=12, random_state=42, n_jobs=-1)
        self.scaler = StandardScaler()
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        X = df_train[self.feature_cols].fillna(0)
        y = np.log1p(df_train[target_col].values)
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X = df_test[self.feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return np.maximum(np.expm1(self.model.predict(X_scaled)), 0)


class QuantileRegressor(BaselineModel):
    """Representa `QuantileRegressor` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/models/baselines.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, quantiles=[0.1, 0.5, 0.9]):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().__init__("quantile_regressor")
        self.quantiles = quantiles
        self.models = {}
        self.scaler = StandardScaler()
    
    def fit(self, df_train, feature_cols, target_col="fire_count"):
        """Executa a etapa `fit` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        super().fit(df_train, feature_cols, target_col)
        X = df_train[feature_cols].fillna(0)
        y = df_train[target_col].values
        X_scaled = self.scaler.fit_transform(X)
        
        for q in self.quantiles:
            from sklearn.linear_model import QuantileRegressor as QR
            model = QR(quantile=q, alpha=0.1)
            model.fit(X_scaled, y)
            self.models[q] = model
        
        self.is_fitted = True
        return self
    
    def predict(self, df_test):
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        X = df_test[self.feature_cols].fillna(0)
        X_scaled = self.scaler.transform(X)
        return {q: np.maximum(m.predict(X_scaled), 0) for q, m in self.models.items()}


def get_all_baselines() -> list:
    """Executa a etapa `get all baselines` do fluxo FireCast.
    
    A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return [
        NaiveLag12(),
        ClimatologyMunicipal(),
        ClimatologyState(),
        HistoricalMean(n_years=3),
        XGBPoissonFlat(),
        XGBPoissonMunicipal(),
        GLMPoisson(),
        TweedieModel(power=1.5),
        RandomForestCount(n_estimators=100),
    ]


def run_baselines(
    df_train: pd.DataFrame,
    df_test: pd.DataFrame,
    feature_cols: list,
    target_col: str = "fire_count",
) -> pd.DataFrame:
    """Executa a etapa `run baselines` do fluxo FireCast.
    
    A funcao faz parte de `src/models/baselines.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    from src.utils.metrics import wape, rmse, mae, r2_score
    
    results = []
    baselines = get_all_baselines()
    
    yt = df_test[target_col].values
    
    for model in baselines:
        try:
            model.fit(df_train, feature_cols, target_col)
            yp = model.predict(df_test)
            
            results.append({
                "model": model.name,
                "wape": wape(yt, yp),
                "rmse": rmse(yt, yp),
                "mae": mae(yt, yp),
                "r2": r2_score(yt, yp),
                "status": "OK",
            })
            logger.info(f"  {model.name}: WAPE={wape(yt, yp):.4f}, RMSE={rmse(yt, yp):.2f}")
        except Exception as e:
            logger.warning(f"  {model.name} failed: {e}")
            results.append({
                "model": model.name,
                "wape": np.nan,
                "rmse": np.nan,
                "mae": np.nan,
                "r2": np.nan,
                "status": f"ERROR: {e}",
            })
    
    return pd.DataFrame(results)
