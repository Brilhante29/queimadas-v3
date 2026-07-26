"""Modulo publico do FireCast para construcao de atributos e controles de vazamento.

Arquivo `src/features/leakage_audit.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Features PROIBIDAS (leakage garantido)
LEAKAGE_FEATURES = [
    # Alvo
    "fire_count",
    "FireCount",
    "focos",
    
    # FRP do próprio mês
    "frp_sum",
    "frp_mean",
    "FRP_sum",
    "FRP_mean",
    
    # Risco calculado após evento
    "risco_fogo_mean",
    "risco_fogo",
    "fire_risk",
    
    # NDVI do próprio mês (se publicado depois)
    "ndvi_atual",
    "ndvi_current",
    
    # Variáveis que só existem após o mês
    "queimadas_autorizadas_mes",
    "autuacoes_mes",
    "focos_confirmados",

    # Same-period labels derived directly from the target.
    "occurrence",
    "extreme_event",
]

# Features PERMITIDAS (lags, climatologia, previsões)
SAFE_PATTERNS = [
    "_lag1", "_lag2", "_lag3", "_lag6", "_lag12",
    "_roll3", "_roll6", "_roll12",
    "_ytd",
    "_clim", "_climatology",
    "_anom",
    "_prev", "_forecast",
    "enso_prob",
    "scenario",
]


def audit_feature_store(
    df: pd.DataFrame,
    feature_manifest: Optional[Dict] = None,
    cutoff_date: Optional[str] = None,
) -> pd.DataFrame:
    """Executa a etapa `audit feature store` do fluxo FireCast.
    
    A funcao faz parte de `src/features/leakage_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    audit_records = []
    
    for col in df.columns:
        risk = "low"
        reason = ""
        safe = True
        
        # Check 1: nome na lista de proibidas
        if col.lower() in [f.lower() for f in LEAKAGE_FEATURES]:
            risk = "CRITICAL"
            reason = f"Feature '{col}' está na lista de proibidas (leakage direto)"
            safe = False
        
        # Check 2: contém padrão suspeito
        elif any(p in col.lower() for p in ["firecount", "frp_sum", "risco_fogo"]):
            if not any(s in col.lower() for s in SAFE_PATTERNS):
                risk = "HIGH"
                reason = f"Feature '{col}' contém alvo sem lag/climatologia"
                safe = False
        
        # Check 3: feature manifest
        if feature_manifest and col in feature_manifest:
            fm = feature_manifest[col]
            if fm.get("leakage_risk_flag", False):
                risk = fm.get("leakage_risk_level", "HIGH")
                reason = fm.get("leakage_reason", "Flagged in manifest")
                safe = False
            
            # Check temporal availability
            if cutoff_date and "feature_available_at" in fm:
                if fm["feature_available_at"] > cutoff_date:
                    risk = "CRITICAL"
                    reason = f"Feature '{col}' disponível apenas em {fm['feature_available_at']} > cutoff {cutoff_date}"
                    safe = False
        
        # Check 4: correlação suspeita com alvo
        if "fire_count" in df.columns and col != "fire_count":
            if df[col].dtype in [np.float64, np.int64]:
                corr = df[col].corr(df["fire_count"])
                if abs(corr) > 0.95 and not any(s in col for s in SAFE_PATTERNS):
                    risk = "HIGH"
                    reason = f"Correlação suspeita com alvo: {corr:.3f}"
                    safe = False
        
        audit_records.append({
            "feature": col,
            "leakage_risk": risk,
            "reason": reason,
            "safe_to_use": safe,
            "action_required": "REMOVE" if risk == "CRITICAL" else ("REVIEW" if risk == "HIGH" else "NONE"),
        })
    
    audit_df = pd.DataFrame(audit_records)
    
    # Summary
    n_critical = (audit_df["leakage_risk"] == "CRITICAL").sum()
    n_high = (audit_df["leakage_risk"] == "HIGH").sum()
    n_safe = audit_df["safe_to_use"].sum()
    
    logger.info(f"Leakage Audit Complete:")
    logger.info(f"  Total features: {len(audit_df)}")
    logger.info(f"  CRITICAL (must remove): {n_critical}")
    logger.info(f"  HIGH (must review): {n_high}")
    logger.info(f"  SAFE: {n_safe}")
    
    if n_critical > 0:
        logger.error(f"CRITICAL LEAKAGE DETECTED in {n_critical} features!")
        for _, row in audit_df[audit_df["leakage_risk"] == "CRITICAL"].iterrows():
            logger.error(f"  - {row['feature']}: {row['reason']}")
    
    return audit_df


def verify_no_target_leakage(
    df: pd.DataFrame,
    target_col: str = "fire_count",
    id_col: str = "municipio_id",
    date_cols: List[str] = ["ano", "mes"],
) -> bool:
    """Valida a etapa `verify no target leakage` do fluxo FireCast.
    
    A funcao faz parte de `src/features/leakage_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    feature_cols = [c for c in df.columns if c not in [target_col, id_col] + date_cols]
    
    # Check: nenhuma feature deve ter correlação perfeita com alvo
    for col in feature_cols:
        if df[col].dtype in [np.float64, np.int64, np.float32, np.int32]:
            corr = df[col].corr(df[target_col])
            if abs(corr) > 0.99:
                logger.error(f"PERFECT CORRELATION: {col} vs {target_col} = {corr:.4f}")
                return False
    
    # Check: nenhuma feature deve ter nome de alvo
    forbidden = [target_col, "focos", "firecount", "frp_sum", "risco_fogo", "occurrence", "extreme_event"]
    for col in feature_cols:
        if any(f in col.lower() for f in forbidden):
            if not any(s in col.lower() for s in ["lag", "clim", "anom", "prev"]):
                logger.error(f"FORBIDDEN PATTERN: {col}")
                return False
    
    logger.info("✓ Target leakage verification PASSED")
    return True


def generate_data_coverage_report(
    df: pd.DataFrame,
    scope_name: str = "global",
) -> pd.DataFrame:
    """Executa a etapa `generate data coverage report` do fluxo FireCast.
    
    A funcao faz parte de `src/features/leakage_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    records = []
    
    # Cobertura temporal
    years = sorted(df["ano"].unique()) if "ano" in df.columns else []
    months = sorted(df["mes"].unique()) if "mes" in df.columns else []
    
    records.append({
        "scope": scope_name,
        "metric": "temporal_range",
        "value": f"{min(years)}-{max(years)}" if years else "N/A",
        "coverage_pct": 100.0,
    })
    
    records.append({
        "scope": scope_name,
        "metric": "total_records",
        "value": len(df),
        "coverage_pct": 100.0,
    })
    
    records.append({
        "scope": scope_name,
        "metric": "municipios",
        "value": df["municipio_id"].nunique() if "municipio_id" in df.columns else "N/A",
        "coverage_pct": 100.0,
    })
    
    # Cobertura por feature
    for col in df.columns:
        null_pct = df[col].isnull().mean() * 100
        records.append({
            "scope": scope_name,
            "metric": f"feature_{col}",
            "value": f"{100-null_pct:.1f}% non-null",
            "coverage_pct": 100 - null_pct,
        })
    
    return pd.DataFrame(records)


def generate_freshness_report(
    df: pd.DataFrame,
    source_manifest: Optional[Dict] = None,
) -> pd.DataFrame:
    """Executa a etapa `generate freshness report` do fluxo FireCast.
    
    A funcao faz parte de `src/features/leakage_audit.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    records = []
    
    if "ano" in df.columns and "mes" in df.columns:
        max_year = df["ano"].max()
        max_month = df[df["ano"] == max_year]["mes"].max()
        records.append({
            "source": "feature_store",
            "last_record": f"{max_year}-{max_month:02d}",
            "status": "current" if max_year >= 2025 else "stale",
        })
    
    if source_manifest:
        for source, info in source_manifest.items():
            records.append({
                "source": source,
                "last_record": info.get("last_update", "unknown"),
                "status": info.get("status", "unknown"),
            })
    
    return pd.DataFrame(records)
