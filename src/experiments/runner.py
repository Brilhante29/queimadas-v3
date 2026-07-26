"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/runner.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
import logging

from src.utils.metrics import evaluate_scope, acceptance_gate, compare_to_baseline
from src.models.baselines import run_baselines
from src.models.rast_fire_x import RASTFireX
from src.features.leakage_audit import audit_feature_store, verify_no_target_leakage, generate_data_coverage_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ExperimentRunner:
    """Representa `ExperimentRunner` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/experiments/runner.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    
    def __init__(self, output_dir: str = "outputs"):
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.results = {}
        self.innovation_ledger = []
    
    def run_t0_sanity(self, df: pd.DataFrame) -> pd.DataFrame:
        """Executa a etapa `run t0 sanity` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("\n" + "=" * 60)
        logger.info("T0 — SANITY CHECK / CENSUS / LEAKAGE AUDIT")
        logger.info("=" * 60)
        
        # Census
        census = pd.DataFrame([{
            "n_records": len(df),
            "n_columns": len(df.columns),
            "n_municipios": df["municipio_id"].nunique() if "municipio_id" in df.columns else 0,
            "n_years": df["ano"].nunique() if "ano" in df.columns else 0,
            "year_range": f"{df['ano'].min()}-{df['ano'].max()}" if "ano" in df.columns else "N/A",
            "zeros_pct": (df["fire_count"] == 0).mean() * 100 if "fire_count" in df.columns else 0,
            "duplicates": df.duplicated().sum(),
        }])
        census.to_csv(f"{self.output_dir}/00_input_census.csv", index=False)
        logger.info(f"  Records: {len(df)}, Municipios: {census['n_municipios'].iloc[0]}")
        
        # Coverage
        coverage = generate_data_coverage_report(df)
        coverage.to_csv(f"{self.output_dir}/01_data_coverage_report.csv", index=False)
        
        # Leakage audit
        audit = audit_feature_store(df)
        audit.to_csv(f"{self.output_dir}/05_leakage_audit.csv", index=False)
        
        n_critical = (audit["leakage_risk"] == "CRITICAL").sum()
        if n_critical > 0:
            logger.error(f"  CRITICAL LEAKAGE: {n_critical} features must be removed!")
        else:
            logger.info("  ✓ No critical leakage detected")
        
        # Verify
        if "fire_count" in df.columns:
            verify_no_target_leakage(df)
        
        return census
    
    def run_t1_t3_temporal(self, df: pd.DataFrame, scopes: Dict[str, Dict]) -> pd.DataFrame:
        """Executa a etapa `run t1 t3 temporal` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("\n" + "=" * 60)
        logger.info("T1-T3 — TEMPORAL VALIDATION")
        logger.info("=" * 60)
        
        all_results = []
        
        for scope_name, scope_cfg in scopes.items():
            logger.info(f"\n  Scope: {scope_name}")
            
            # Filtrar escopo
            if "states" in scope_cfg and scope_cfg["states"]:
                df_scope = df[df["estado"].isin(scope_cfg["states"])].copy()
            else:
                df_scope = df.copy()
            
            # Split temporal
            train_mask = df_scope["ano"] <= 2023
            test_mask = df_scope["ano"].isin([2024, 2025])
            
            df_train = df_scope[train_mask].copy()
            df_test = df_scope[test_mask].copy()
            
            if len(df_train) == 0 or len(df_test) == 0:
                logger.warning(f"  Insufficient data for {scope_name}")
                continue
            
            # Features
            exclude = ["fire_count", "hist_positive", "municipio_id", "municipio_nome", 
                      "enso_regime", "estacao", "ano", "mes"]
            feature_cols = [c for c in df_train.select_dtypes(include=[np.number]).columns if c not in exclude]
            
            # Baselines
            logger.info(f"  Running baselines...")
            baseline_results = run_baselines(df_train, df_test, feature_cols)
            
            # RAST-Fire-X
            logger.info(f"  Running RAST-Fire-X...")
            model = RASTFireX(extreme_threshold=30)
            
            # Split cal
            cal_mask = df_train["ano"] >= df_train["ano"].max() - 1
            df_cal = df_train[cal_mask].copy()
            df_train_real = df_train[~cal_mask].copy()
            
            model.fit(df_train_real, df_cal)
            df_pred = model.predict(df_test)
            df_pred["y_true"] = df_test["fire_count"].values
            df_pred["hist_positive"] = df_test["hist_positive"].values if "hist_positive" in df_test.columns else 1
            df_pred["municipio_id"] = df_test["municipio_id"].values if "municipio_id" in df_test.columns else ""
            df_pred["month"] = df_test["mes"].values if "mes" in df_test.columns else 1
            
            # Evaluate
            metrics = evaluate_scope(df_pred, scope_name)
            metrics["best_baseline_wape"] = baseline_results["wape"].min() if not baseline_results.empty else np.nan
            all_results.append(metrics)
            
            logger.info(f"  WAPE (critical): {metrics.get('wape_critical_out_nov', np.nan):.4f}")
            logger.info(f"  IC95: {metrics.get('ic95_critical_out_nov', np.nan):.4f}")
            logger.info(f"  Zero indevido: {metrics.get('zero_indevido_critical_out_nov', np.nan):.4f}")
        
        results_df = pd.DataFrame(all_results)
        
        # Save
        for scope_name in scopes.keys():
            scope_results = results_df[results_df["scope"] == scope_name]
            if not scope_results.empty:
                fname = f"06_backtest_{scope_name}_2024_2025.csv"
                scope_results.to_csv(f"{self.output_dir}/{fname}", index=False)
        
        return results_df
    
    def run_t4_state_holdout(self, df: pd.DataFrame) -> pd.DataFrame:
        """Executa a etapa `run t4 state holdout` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("\n" + "=" * 60)
        logger.info("T4 — STATE HOLDOUT")
        logger.info("=" * 60)
        
        if "estado" not in df.columns:
            logger.warning("  No 'estado' column, skipping")
            return pd.DataFrame()
        
        results = []
        states = df["estado"].unique()
        
        for holdout_state in states:
            logger.info(f"  Holdout: {holdout_state}")
            
            df_train = df[df["estado"] != holdout_state].copy()
            df_test = df[df["estado"] == holdout_state].copy()
            
            # Only test 2024-2025
            df_test = df_test[df_test["ano"].isin([2024, 2025])]
            
            if len(df_train) < 100 or len(df_test) < 10:
                continue
            
            exclude = ["fire_count", "hist_positive", "municipio_id", "municipio_nome",
                      "enso_regime", "estacao", "ano", "mes"]
            feature_cols = [c for c in df_train.select_dtypes(include=[np.number]).columns if c not in exclude]
            
            model = RASTFireX()
            model.fit(df_train)
            df_pred = model.predict(df_test)
            df_pred["y_true"] = df_test["fire_count"].values
            df_pred["hist_positive"] = df_test["hist_positive"].values if "hist_positive" in df_test.columns else 1
            df_pred["municipio_id"] = df_test["municipio_id"].values if "municipio_id" in df_test.columns else ""
            df_pred["month"] = df_test["mes"].values if "mes" in df_test.columns else 1
            
            metrics = evaluate_scope(df_pred, f"holdout_{holdout_state}")
            metrics["holdout_state"] = holdout_state
            results.append(metrics)
            
            logger.info(f"    WAPE: {metrics.get('wape_critical_out_nov', np.nan):.4f}")
        
        results_df = pd.DataFrame(results)
        results_df.to_csv(f"{self.output_dir}/09_state_holdout_results.csv", index=False)
        return results_df
    
    def run_t8_ablation(self, df: pd.DataFrame) -> pd.DataFrame:
        """Executa a etapa `run t8 ablation` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("\n" + "=" * 60)
        logger.info("T8 — ABLATION STUDY")
        logger.info("=" * 60)
        
        ablation_configs = {
            "full": [],
            "no_enso": ["enso", "nino"],
            "no_ndvi": ["ndvi", "evi"],
            "no_human": ["human", "agriculture", "pasture", "road", "population"],
            "no_soil_vpd": ["soil", "vpd", "moisture"],
            "no_spatial": ["neighbor", "spatial", "adjacent"],
            "no_regime": ["regime", "ytd_vs_clim"],
        }
        
        results = []
        
        for ablation_name, exclude_patterns in ablation_configs.items():
            logger.info(f"  Ablation: {ablation_name}")
            
            train_mask = df["ano"] <= 2023
            test_mask = df["ano"].isin([2024, 2025])
            
            df_train = df[train_mask].copy()
            df_test = df[test_mask].copy()
            
            exclude = ["fire_count", "hist_positive", "municipio_id", "municipio_nome",
                      "enso_regime", "estacao", "ano", "mes"]
            
            # Remove features matching ablation patterns
            feature_cols = [c for c in df_train.select_dtypes(include=[np.number]).columns 
                          if c not in exclude and not any(p in c.lower() for p in exclude_patterns)]
            
            if len(feature_cols) < 5:
                logger.warning(f"    Too few features after ablation")
                continue
            
            try:
                model = RASTFireX()
                model.fit(df_train)
                df_pred = model.predict(df_test)
                df_pred["y_true"] = df_test["fire_count"].values
                df_pred["hist_positive"] = df_test["hist_positive"].values if "hist_positive" in df_test.columns else 1
                df_pred["municipio_id"] = df_test["municipio_id"].values if "municipio_id" in df_test.columns else ""
                df_pred["month"] = df_test["mes"].values if "mes" in df_test.columns else 1
                
                metrics = evaluate_scope(df_pred, ablation_name)
                metrics["n_features"] = len(feature_cols)
                metrics["removed_patterns"] = str(exclude_patterns)
                results.append(metrics)
                
                logger.info(f"    WAPE: {metrics.get('wape_critical_out_nov', np.nan):.4f}, Features: {len(feature_cols)}")
            except Exception as e:
                logger.warning(f"    Failed: {e}")
        
        results_df = pd.DataFrame(results)
        results_df.to_csv(f"{self.output_dir}/13_ablation_table.csv", index=False)
        return results_df
    
    def run_t9_forecast(self, df: pd.DataFrame, scopes: Dict) -> pd.DataFrame:
        """Executa a etapa `run t9 forecast` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("\n" + "=" * 60)
        logger.info("T9 — FORECAST 2026-2027")
        logger.info("=" * 60)
        
        # Treinar com todos os dados até 2025
        df_train = df[df["ano"] <= 2025].copy()
        
        exclude = ["fire_count", "hist_positive", "municipio_id", "municipio_nome",
                  "enso_regime", "estacao", "ano", "mes"]
        feature_cols = [c for c in df_train.select_dtypes(include=[np.number]).columns if c not in exclude]
        
        model = RASTFireX()
        model.fit(df_train)
        
        # Pegar último mês disponível como template
        last_year = df["ano"].max()
        last_month = df[df["ano"] == last_year]["mes"].max()
        
        all_forecasts = []
        
        for scope_name, scope_cfg in scopes.items():
            logger.info(f"  Scope: {scope_name}")
            
            if "states" in scope_cfg and scope_cfg["states"]:
                df_scope = df[df["estado"].isin(scope_cfg["states"])].copy()
            else:
                df_scope = df.copy()
            
            # Template: último mês de cada município
            template = df_scope.loc[df_scope.groupby("municipio_id")["ano"].idxmax()].copy()
            
            for year in [2026, 2027]:
                for month in range(1, 13):
                    df_scenario = template.copy()
                    df_scenario["ano"] = year
                    df_scenario["mes"] = month
                    
                    # Atualizar features temporais
                    df_scenario["month_sin"] = np.sin(2 * np.pi * month / 12)
                    df_scenario["month_cos"] = np.cos(2 * np.pi * month / 12)
                    df_scenario["is_critico"] = 1 if month in [10, 11] else 0
                    
                    for scenario_name, enso_mod in [("base", 0.0), ("alto", 0.5), ("extremo", 1.0)]:
                        df_s = df_scenario.copy()
                        
                        # Ajustar para cenário
                        if "vapour_pressure_deficit_mean" in df_s.columns:
                            df_s["vapour_pressure_deficit_mean"] *= (1 + enso_mod * 0.3)
                        if "fuel_stress_index" in df_s.columns:
                            df_s["fuel_stress_index"] *= (1 + enso_mod * 0.4)
                        if "enso_prob_el_nino" in df_s.columns:
                            df_s["enso_prob_el_nino"] = min(95, df_s["enso_prob_el_nino"].mean() + enso_mod * 30)
                        
                        pred = model.predict(df_s)
                        pred["ano"] = year
                        pred["mes"] = month
                        pred["cenario"] = scenario_name
                        pred["escopo"] = scope_name
                        
                        cols = ["municipio_id", "ano", "mes", "cenario", "escopo", 
                               "y_pred", "p_occurrence", "p_extreme", "risk_score", "risk_level",
                               "ic80_lower", "ic80_upper", "ic95_lower", "ic95_upper"]
                        available_cols = [c for c in cols if c in pred.columns]
                        all_forecasts.append(pred[available_cols])
        
        if all_forecasts:
            forecasts_df = pd.concat(all_forecasts, ignore_index=True)
            forecasts_df.to_csv(f"{self.output_dir}/16_forecasts_2026_2027_scenarios.csv", index=False)
            
            # Risk ranking
            ranking = forecasts_df[forecasts_df["cenario"] == "extremo"].groupby("municipio_id").agg({
                "y_pred": "sum",
                "p_extreme": "mean",
                "risk_score": "mean",
            }).sort_values("risk_score", ascending=False).head(50)
            ranking.to_csv(f"{self.output_dir}/17_risk_ranking.csv")
            
            return forecasts_df
        
        return pd.DataFrame()
    
    def run_all(self, df: pd.DataFrame, scopes: Dict):
        """Executa a etapa `run all` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/runner.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        logger.info("\n" + "=" * 70)
        logger.info("FIRECAST — FULL EXPERIMENT MATRIX")
        logger.info("=" * 70)
        
        # T0
        self.run_t0_sanity(df)
        
        # T1-T3
        temporal_results = self.run_t1_t3_temporal(df, scopes)
        
        # T4
        if "estado" in df.columns and df["estado"].nunique() > 1:
            self.run_t4_state_holdout(df)
        
        # T8
        self.run_t8_ablation(df)
        
        # T9
        self.run_t9_forecast(df, scopes)
        
        # Acceptance gate
        logger.info("\n" + "=" * 60)
        logger.info("ACCEPTANCE GATE")
        logger.info("=" * 60)
        
        gate_config = {
            "ceara": {"wape_critical_threshold": 0.20, "ic95_min": 0.90, "ic95_max": 0.98, "zero_indevido_threshold": 0.0, "recall10_threshold": 0.70},
            "chapada_araripe": {"wape_critical_threshold": 0.25, "ic95_min": 0.88, "ic95_max": 0.98, "zero_indevido_threshold": 0.0, "recall10_threshold": 0.60},
            "brazil": {"wape_critical_threshold": 0.35, "ic95_min": 0.85, "ic95_max": 0.99, "zero_indevido_threshold": 0.0, "recall10_threshold": 0.50},
        }
        
        if not temporal_results.empty:
            gate_results = acceptance_gate(temporal_results, gate_config)
            gate_results.to_csv(f"{self.output_dir}/acceptance_gate_results.csv", index=False)
            
            for _, row in gate_results.iterrows():
                status = "PASS" if row.get("passed", False) else "FAIL"
                logger.info(f"  {row['scope']}: {status} — {row.get('pass_reasons', '')}")
        
        logger.info("\n" + "=" * 70)
        logger.info("ALL EXPERIMENTS COMPLETE")
        logger.info(f"Outputs saved to: {self.output_dir}/")
        logger.info("=" * 70)
