"""API fail-closed do FireCast para servir o champion aprovado internamente.

A API carrega apenas artefato verificado por hash, expoe predicao, resumo de metricas e XAI, e falha de forma explicita quando evidencia obrigatoria esta ausente."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.production.champion_climatology import (  # noqa: E402
    ARTIFACT_DIR,
    ChampionClimatologyModel,
)
from src.production.llm_xai import (  # noqa: E402
    NarrativeValidationError,
    build_verified_xai_response,
    build_xai_graph,
    build_xai_packet,
)
from src.utils.metrics import mae, wape  # noqa: E402

DEFAULT_MODEL_PATH = ARTIFACT_DIR / "model.json"

# Artefatos reais ja validados. EXP-10 promoveu o champion dinamico
# `climatology_regional_intensity12` no protocolo estendido (2015-2024), mas
# producao externa continua bloqueada por shadow/autorizacao externa. Estes endpoints so leem
# evidencias congeladas no repo: nao treinam, nao projetam metricas para 2025+
# e nao inventam numero quando falta artefato (fail closed).
BACKTEST_SUMMARY_PATH = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "summary.csv"
BACKTEST_PREDICTIONS_PATH = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions_2023_2024.csv"
G4_MUNICIPIO_PATH = PROJECT_ROOT / "outputs" / "g4_spatial_robustness_exp10_2023_2024" / "by_municipio.csv"
G5_REPORT_PATH = PROJECT_ROOT / "outputs" / "g5_conformal_ic95_guarded_exp10" / "g5_report.json"
PRODUCTION_PLAN_PATH = PROJECT_ROOT / "outputs" / "production_ml_plan.json"
ENSO_SNAPSHOT_PATH = PROJECT_ROOT / "data" / "snapshots" / "enso_cpc_v1" / "enso_monthly.csv"
APA_SERVING_ARTIFACT = PROJECT_ROOT / "outputs" / "apa_araripe" / "serving" / "model.json"
CHAMPION_MODEL_NAME = "climatology_regional_intensity12"

# Status de release definidos pela decisao humana de 2026-07-11
# (DECISION-G3-CONTRACT-V2 + OPS-G7-APPROVAL no ledger): producao INTERNA
# aprovada sob o contrato G3 v2; release EXTERNO segue condicionado a janela
# de shadow vivo. Fail-closed permanece inalterado.
PRODUCTION_STATUS_SERVING = "producao_interna_aprovada_g3v2"
PRODUCTION_STATUS_SUMMARY = "APROVADO_PRODUCAO_INTERNA_G3V2_EXTERNO_PENDENTE_SHADOW"


def _require_file(path: Path) -> Path:
    """Executa a etapa `require file` do fluxo FireCast.
    
    A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not path.exists():
        raise FileNotFoundError(f"Artefato de evidÃƒÂªncia ausente: {path} (fail closed, nada ÃƒÂ© inventado no lugar)")
    return path


class PredictionRequest(BaseModel):
    """Representa `PredictionRequest` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/production/serving_api.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    geocodigo: int = Field(..., description="CÃƒÂ³digo IBGE do municÃƒÂ­pio")
    ano: int = Field(..., ge=2000, le=2100, description="Ano de previsÃƒÂ£o")
    mes: int = Field(..., ge=1, le=12, description="MÃƒÂªs de previsÃƒÂ£o")


class PredictionResponse(BaseModel):
    """Representa `PredictionResponse` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/production/serving_api.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    geocodigo: int
    ano: int
    mes: int
    y_pred: float
    interval_p90_low: float
    interval_p90_high: float
    model_name: str
    artifact_sha256: str
    served_at: str
    production_status: str
    regional_intensity_ratio: float | None = None
    regional_intensity_ratio_period: str | None = None


@dataclass(frozen=True)
class FireCastServingService:
    """Representa `FireCastServingService` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/production/serving_api.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    model_path: Path = DEFAULT_MODEL_PATH

    def load_model(self) -> ChampionClimatologyModel:
        """Carrega a etapa `load model` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Artefato nÃƒÂ£o encontrado: {self.model_path}")
        return ChampionClimatologyModel.load(self.model_path)

    def health(self) -> dict[str, Any]:
        """Executa a etapa `health` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            model = self.load_model()
        except Exception as exc:
            return {
                "status": "unavailable",
                "reason": str(exc),
                "model_path": str(self.model_path),
                "production_status": "fail_closed",
            }
        return {
            "status": "ok",
            "model_name": model.artifact["model_name"],
            "artifact_sha256": model.artifact["artifact_sha256"],
            "artifact_status": model.artifact.get("status", "unknown"),
            "production_status": PRODUCTION_STATUS_SERVING,
        }

    def predict(self, request: PredictionRequest) -> dict[str, Any]:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            model = self.load_model()
        except Exception as exc:
            raise RuntimeError(f"Modelo indisponÃƒÂ­vel ou invÃƒÂ¡lido: {exc}") from exc
        prediction = model.predict_one(request.geocodigo, request.ano, request.mes)
        prediction["served_at"] = datetime.now(timezone.utc).isoformat()
        prediction["production_status"] = PRODUCTION_STATUS_SERVING
        return prediction

    def explain(self, request: PredictionRequest) -> dict[str, Any]:
        """Produz a etapa `explain` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            model = self.load_model()
        except Exception as exc:
            raise RuntimeError(f"Modelo indisponÃƒÂ­vel ou invÃƒÂ¡lido: {exc}") from exc
        response = build_verified_xai_response(
            model,
            geocodigo=request.geocodigo,
            ano=request.ano,
            mes=request.mes,
        )
        response["served_at"] = datetime.now(timezone.utc).isoformat()
        response["production_status"] = PRODUCTION_STATUS_SERVING
        return response

    def explain_graph(self, request: PredictionRequest) -> dict[str, Any]:
        """Produz a etapa `explain graph` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            model = self.load_model()
        except Exception as exc:
            raise RuntimeError(f"Modelo indispon????????vel ou inv????????lido: {exc}") from exc
        packet = build_xai_packet(model, geocodigo=request.geocodigo, ano=request.ano, mes=request.mes)
        graph = build_xai_graph(packet)
        graph["served_at"] = datetime.now(timezone.utc).isoformat()
        graph["production_status"] = PRODUCTION_STATUS_SERVING
        return graph

    def champion_summary(self) -> dict[str, Any]:
        """Executa a etapa `champion summary` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        summary = pd.read_csv(_require_file(BACKTEST_SUMMARY_PATH))
        row = summary[summary["model"] == CHAMPION_MODEL_NAME]
        if row.empty:
            raise FileNotFoundError(f"Champion '{CHAMPION_MODEL_NAME}' ausente em {BACKTEST_SUMMARY_PATH}")
        row = row.iloc[0]

        g5 = json.loads(_require_file(G5_REPORT_PATH).read_text(encoding="utf-8"))
        plan = json.loads(_require_file(PRODUCTION_PLAN_PATH).read_text(encoding="utf-8"))
        gates = {gate["gate"]: gate["status"] for gate in plan.get("gates", [])}

        return {
            "model_name": CHAMPION_MODEL_NAME,
            "protocol": "walk-forward estendido 2015-2024, h=1, 2025+ congelado; janela UI 2023-2024",
            "all_wape": float(row["all_wape"]),
            "all_mae": float(row["all_mae"]),
            "outnov_wape": float(row["outnov_wape"]),
            "outnov_mae": float(row["outnov_mae"]),
            "g5_protocol": g5["protocol"],
            "g5_coverage_overall": g5["overall_coverage_test_2023_2024"],
            "g5_coverage_dry_season": g5["dry_season_coverage_test"],
            "g5_coverage_target": g5.get("nominal_coverage_target", g5["nominal_coverage_selected"]),
            # Backward-compatible aliases for the current frontend contract. They
            # now point to the guarded IC95 G5 report, not the older 2023-only
            # calibration attempt.
            "coverage_test_2024_overall": g5["overall_coverage_test_2023_2024"],
            "coverage_test_2024_dry_season": g5["dry_season_coverage_test"],
            "coverage_acceptable_range": g5["ic_acceptable_range"],
            "gates": gates,
            "production_status": PRODUCTION_STATUS_SUMMARY,
        }

    def champion_monthly_series(self) -> list[dict[str, Any]]:
        """Executa a etapa `champion monthly series` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        preds = pd.read_csv(_require_file(BACKTEST_PREDICTIONS_PATH))
        preds = preds[preds["model"] == CHAMPION_MODEL_NAME].copy()
        rows = []
        for (ano, mes), group in preds.groupby(["ano", "mes"], sort=True):
            rows.append(
                {
                    "cut": f"{int(ano)}-{int(mes):02d}",
                    "ano": int(ano),
                    "mes": int(mes),
                    "y_sum": float(group["fire_count"].sum()),
                    "pred_sum": float(group["y_pred"].sum()),
                    "wape": wape(group["fire_count"].values, group["y_pred"].values),
                    "mae": mae(group["fire_count"].values, group["y_pred"].values),
                    "n": int(len(group)),
                }
            )
        return rows

    def champion_municipio_monthly_series(self, geocodigo: int, ano: int | None = None) -> list[dict[str, Any]]:
        """Executa a etapa `champion municipio monthly series` do fluxo FireCast.

        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        preds = pd.read_csv(_require_file(BACKTEST_PREDICTIONS_PATH))
        preds = preds[(preds["model"] == CHAMPION_MODEL_NAME) & (preds["geocodigo"] == geocodigo)].copy()
        if ano is not None:
            preds = preds[preds["ano"] == ano]
        if preds.empty:
            raise ValueError(f"Nenhuma evidencia de backtest para geocodigo={geocodigo} ano={ano}")
        meses_por_ano = {
            int(row_ano): sorted(int(mes) for mes in group["mes"].unique())
            for row_ano, group in preds.groupby("ano", sort=True)
        }
        rows = []
        for (row_ano, mes), group in preds.groupby(["ano", "mes"], sort=True):
            rows.append(
                {
                    "geocodigo": geocodigo,
                    "ano": int(row_ano),
                    "mes": int(mes),
                    "y_sum": float(group["fire_count"].sum()),
                    "pred_sum": float(group["y_pred"].sum()),
                    "n": int(len(group)),
                    "cobertura_completa": len(meses_por_ano[int(row_ano)]) == 12,
                }
            )
        return rows

    def champion_municipio_ranking(self) -> list[dict[str, Any]]:
        """Executa a etapa `champion municipio ranking` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        by_muni = pd.read_csv(_require_file(G4_MUNICIPIO_PATH)).sort_values("wape", ascending=False)
        return by_muni[["geocodigo", "municipio_ibge", "n", "volume_real", "wape", "mae", "flag_regressao"]].to_dict("records")

    def climate_enso(self) -> list[dict[str, Any]]:
        """Executa a etapa `climate enso` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        enso = pd.read_csv(_require_file(ENSO_SNAPSHOT_PATH))
        return enso[["ano", "mes", "nino34_anomaly", "enso_regime"]].to_dict("records")


def create_app(model_path: Path = DEFAULT_MODEL_PATH) -> FastAPI:
    """Constroi a etapa `create app` do fluxo FireCast.
    
    A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    service = FireCastServingService(model_path=model_path)
    app = FastAPI(
        title="FireCast Champion Serving API",
        version="1.0.0",
        description="Fail-closed internal serving API for the current FireCast champion artifact.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, Any]:
        """Executa a etapa `health` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        status = service.health()
        if status["status"] != "ok":
            raise HTTPException(status_code=503, detail=status)
        return status

    @app.post("/v1/predict", response_model=PredictionResponse)
    def predict(request: PredictionRequest) -> dict[str, Any]:
        """Gera a etapa `predict` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.predict(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/explain")
    def explain(request: PredictionRequest) -> dict[str, Any]:
        """Produz a etapa `explain` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.explain(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except NarrativeValidationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/explain/graph")
    def explain_graph(request: PredictionRequest) -> dict[str, Any]:
        """Produz a etapa `explain graph` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.explain_graph(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/champion/summary")
    def champion_summary() -> dict[str, Any]:
        """Executa a etapa `champion summary` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.champion_summary()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/champion/monthly_series")
    def champion_monthly_series() -> list[dict[str, Any]]:
        """Executa a etapa `champion monthly series` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.champion_monthly_series()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/champion/municipio_monthly_series")
    def champion_municipio_monthly_series(
        geocodigo: int = Query(..., gt=0, description="Codigo IBGE do municipio"),
        ano: int | None = None,
    ) -> list[dict[str, Any]]:
        """Executa a etapa `champion municipio monthly series` do fluxo FireCast.

        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.champion_municipio_monthly_series(geocodigo, ano)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/champion/municipio_ranking")
    def champion_municipio_ranking() -> list[dict[str, Any]]:
        """Executa a etapa `champion municipio ranking` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.champion_municipio_ranking()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/v1/climate/enso")
    def climate_enso() -> list[dict[str, Any]]:
        """Executa a etapa `climate enso` do fluxo FireCast.
        
        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.climate_enso()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # ------------------------------------------------------------------
    # Escopo APA Chapada do Araripe
    #
    # Existe para que o consumidor (back-end) leia a lista de municipios
    # DESTE artefato em vez de manter mapa hardcoded. Foi exatamente o
    # acoplamento por lista fixa que produziu o mapa de 29 cidades do Cariri
    # na integracao anterior; trocar por uma lista fixa de 36 repetiria o
    # mesmo erro um numero adiante.
    # ------------------------------------------------------------------

    @app.get("/v1/apa/scope")
    def apa_scope() -> dict[str, Any]:
        """Executa a etapa `apa scope` do fluxo FireCast.

        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            artifact = json.loads(_require_file(APA_SERVING_ARTIFACT).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "scope": artifact["scope"],
            "scope_sha256": artifact["scope_sha256"],
            "scope_n_municipios": artifact["scope_n_municipios"],
            "scope_by_uf": artifact["scope_by_uf"],
            "municipios": artifact["municipios"],
            "model_name": artifact["model_name"],
            "generated_at": artifact["generated_at"],
        }

    @app.get("/v1/apa/uncertainty_status")
    def apa_uncertainty_status() -> dict[str, Any]:
        """Executa a etapa `apa uncertainty status` do fluxo FireCast.

        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            artifact = json.loads(_require_file(APA_SERVING_ARTIFACT).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return artifact["uncertainty"]

    @app.post("/v1/apa/predict")
    def apa_predict(req: PredictionRequest) -> dict[str, Any]:
        """Gera a etapa `apa predict` do fluxo FireCast.

        Falha fechada para municipio fora da APA. O intervalo so e exposto se
        o gate de incerteza estiver validado -- enquanto nao estiver, devolve
        `interval: null` e `uncertainty_status` explicito, em vez de publicar
        barra de erro sem cobertura demonstrada."""
        from src.production.apa_araripe_serving import predict as apa_predict_fn

        try:
            artifact = json.loads(_require_file(APA_SERVING_ARTIFACT).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            return apa_predict_fn(artifact, req.geocodigo, req.ano, req.mes)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/production/serving_api.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser(description="Run FireCast champion serving API")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(create_app(args.model_path), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
