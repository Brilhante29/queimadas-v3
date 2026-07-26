"""XAI verificavel do FireCast para o champion glass-box.

O modulo gera pacote de fatos, grafo dirigido e narrativa numericamente conferida; a camada de linguagem nunca altera predicao nem inventa numero."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.production.champion_climatology import (  # noqa: E402
    ARTIFACT_DIR,
    ChampionClimatologyModel,
)

DEFAULT_MODEL_PATH = ARTIFACT_DIR / "model.json"
NUMERIC_TOKEN_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:[\.,]\d+)?(?![A-Za-z_])")


class NarrativeValidationError(ValueError):
    """Representa `NarrativeValidationError` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/production/llm_xai.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""


def _period_label(ano: int, mes: int) -> str:
    """Executa a etapa `period label` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return f"{int(ano):04d}-{int(mes):02d}"


def _sha256_text(text: str) -> str:
    """Executa a etapa `sha256 text` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _round(value: float, digits: int = 6) -> float:
    """Executa a etapa `round` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return round(float(value), digits)


def _fmt(value: float, digits: int = 3) -> str:
    """Executa a etapa `fmt` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return f"{float(value):.{digits}f}"


def _find_climatology_record(model: ChampionClimatologyModel, geocodigo: int, mes: int) -> dict[str, Any]:
    """Executa a etapa `find climatology record` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    for row in model.artifact["climatology"]:
        if int(row["geocodigo"]) == int(geocodigo) and int(row["mes"]) == int(mes):
            return row
    raise ValueError(f"Sem climatologia para geocodigo={geocodigo}, mes={mes}; fail-closed")


def _find_intensity_record(model: ChampionClimatologyModel, ano: int, mes: int) -> tuple[dict[str, Any], bool]:
    """Executa a etapa `find intensity record` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    requested = _period_label(ano, mes)
    rows = model.artifact["regional_intensity"]
    for row in rows:
        if row["forecast_period"] == requested:
            return row, False
    return rows[-1], True


def build_xai_packet(model: ChampionClimatologyModel, geocodigo: int, ano: int, mes: int) -> dict[str, Any]:
    """Constroi a etapa `build xai packet` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not (1 <= int(mes) <= 12):
        raise ValueError(f"Mes invalido: {mes}")

    climatology = _find_climatology_record(model, geocodigo, mes)
    intensity, used_latest_ratio = _find_intensity_record(model, ano, mes)
    prediction = model.predict_one(geocodigo, ano, mes)

    base = float(climatology["prediction"])
    ratio = float(intensity["applied_ratio"])
    y_pred_exact = max(0.0, base * ratio)
    residual_abs_error_p90 = float(model.artifact["metrics"]["residual_abs_error_p90"])
    interval_low = max(0.0, y_pred_exact - residual_abs_error_p90)
    interval_high = y_pred_exact + residual_abs_error_p90

    if not math.isclose(float(prediction["y_pred"]), y_pred_exact, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("XAI attribution diverged from served prediction; fail-closed")
    if not math.isclose(float(prediction["interval_p90_low"]), interval_low, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("XAI interval low diverged from served prediction; fail-closed")
    if not math.isclose(float(prediction["interval_p90_high"]), interval_high, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("XAI interval high diverged from served prediction; fail-closed")

    ratio_clip = model.artifact["intensity_parameters"]["ratio_clip"]
    packet = {
        "schema_version": "firecast_xai_packet_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "xai_mode": "exact_glass_box_attribution_with_verified_llm_narration",
        "input": {
            "geocodigo": int(geocodigo),
            "ano": int(ano),
            "mes": int(mes),
            "forecast_period_requested": _period_label(ano, mes),
        },
        "model": {
            "model_name": model.artifact["model_name"],
            "model_type": model.artifact["model_type"],
            "artifact_sha256": model.artifact["artifact_sha256"],
            "status": model.artifact.get("status", "unknown"),
        },
        "prediction": {
            "y_pred": _round(y_pred_exact),
            "interval_p90_low": _round(interval_low),
            "interval_p90_high": _round(interval_high),
            "residual_abs_error_p90": _round(residual_abs_error_p90),
            "unit": "monthly active-fire foci",
        },
        "exact_attribution": {
            "equation": "y_pred = municipal_month_climatology * regional_intensity_ratio",
            "base_climatology": _round(base),
            "regional_intensity_ratio": _round(ratio),
            "regional_adjustment_delta": _round(y_pred_exact - base),
            "multiplication_check": _round(base * ratio),
            "clipped_to_zero": y_pred_exact == 0.0 and base * ratio < 0.0,
            "base_times_ratio_equals_prediction": True,
        },
        "climatology_evidence": {
            "geocodigo": int(climatology["geocodigo"]),
            "municipio_ibge": str(climatology.get("municipio_ibge", "")),
            "uf": str(climatology.get("uf", "")),
            "calendar_month": int(climatology["mes"]),
            "prediction_mean": _round(base),
            "train_months": int(climatology.get("train_months", 0)),
            "train_total": _round(float(climatology.get("train_total", 0.0))),
        },
        "regional_intensity_evidence": {
            "forecast_period_used": intensity["forecast_period"],
            "used_latest_training_ratio_for_future_period": bool(used_latest_ratio),
            "source_window_start": intensity["source_window_start"],
            "source_window_end": intensity["source_window_end"],
            "observed_trailing_12m": _round(float(intensity["observed_trailing_12m"])),
            "expected_trailing_12m": _round(float(intensity["expected_trailing_12m"])),
            "raw_ratio": _round(float(intensity["raw_ratio"])),
            "applied_ratio": _round(ratio),
            "ratio_clip_low": _round(float(ratio_clip[0])),
            "ratio_clip_high": _round(float(ratio_clip[1])),
            "trailing_months": int(model.artifact["intensity_parameters"]["trailing_months"]),
            "shrink_fire_count": _round(float(model.artifact["intensity_parameters"]["shrink_fire_count"])),
        },
        "llm_xai_contract": {
            "llm_may_change_prediction": False,
            "llm_may_introduce_numbers": False,
            "llm_role": "Narrate only the verified packet facts; never compute, forecast, tune, rank or overwrite model output.",
            "verifier": "numeric_fact_guard_v1",
            "failure_policy": "fail_closed_if_narrative_contains_unapproved_number",
        },
    }
    packet["packet_sha256"] = _sha256_text(json.dumps(packet, sort_keys=True, ensure_ascii=False))
    return packet



def build_xai_graph(packet: dict[str, Any]) -> dict[str, Any]:
    """Constroi a etapa `build xai graph` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    input_row = packet["input"]
    model = packet["model"]
    prediction = packet["prediction"]
    attribution = packet["exact_attribution"]
    climatology = packet["climatology_evidence"]
    intensity = packet["regional_intensity_evidence"]
    contract = packet["llm_xai_contract"]

    nodes = [
        {
            "id": "request",
            "label": "Forecast request",
            "type": "input",
            "value": input_row["forecast_period_requested"],
            "details": input_row,
        },
        {
            "id": "artifact",
            "label": "Hash-verified champion artifact",
            "type": "model",
            "value": model["model_name"],
            "details": model,
        },
        {
            "id": "target_history",
            "label": "Historical INPE target",
            "type": "data_source",
            "value": "AQUA_M-T municipal-month counts",
            "details": {
                "role": "training target",
                "source": "data/snapshots/inpe_local_v2",
                "entity_key": "geocodigo",
            },
        },
        {
            "id": "municipal_climatology",
            "label": "Municipal-month climatology",
            "type": "feature",
            "value": attribution["base_climatology"],
            "unit": prediction["unit"],
            "details": climatology,
        },
        {
            "id": "regional_intensity_window",
            "label": "Trailing regional intensity window",
            "type": "feature",
            "value": intensity["applied_ratio"],
            "unit": "multiplier",
            "details": intensity,
        },
        {
            "id": "exact_equation",
            "label": "Exact glass-box equation",
            "type": "operation",
            "value": attribution["equation"],
            "details": attribution,
        },
        {
            "id": "prediction",
            "label": "Point prediction",
            "type": "output",
            "value": prediction["y_pred"],
            "unit": prediction["unit"],
            "details": prediction,
        },
        {
            "id": "interval",
            "label": "Residual interval",
            "type": "uncertainty",
            "value": [prediction["interval_p90_low"], prediction["interval_p90_high"]],
            "unit": prediction["unit"],
            "details": {
                "interval_p90_low": prediction["interval_p90_low"],
                "interval_p90_high": prediction["interval_p90_high"],
                "residual_abs_error_p90": prediction["residual_abs_error_p90"],
            },
        },
        {
            "id": "numeric_guard",
            "label": "Numeric fact guard",
            "type": "verification",
            "value": contract["verifier"],
            "details": contract,
        },
    ]
    edges = [
        {"source": "request", "target": "municipal_climatology", "label": "selects municipality and calendar month"},
        {"source": "request", "target": "regional_intensity_window", "label": "selects forecast period"},
        {"source": "target_history", "target": "municipal_climatology", "label": "fit historical mean"},
        {"source": "target_history", "target": "regional_intensity_window", "label": "compute trailing observed/expected ratio"},
        {"source": "artifact", "target": "exact_equation", "label": "defines"},
        {
            "source": "municipal_climatology",
            "target": "exact_equation",
            "label": "base_climatology",
            "weight": attribution["base_climatology"],
        },
        {
            "source": "regional_intensity_window",
            "target": "exact_equation",
            "label": "regional_intensity_ratio",
            "weight": attribution["regional_intensity_ratio"],
        },
        {"source": "exact_equation", "target": "prediction", "label": "base * ratio", "weight": prediction["y_pred"]},
        {"source": "prediction", "target": "interval", "label": "add empirical residual error"},
        {"source": "prediction", "target": "numeric_guard", "label": "locks numeric facts"},
        {"source": "interval", "target": "numeric_guard", "label": "locks uncertainty facts"},
    ]
    graph = {
        "schema_version": "firecast_xai_graph_v1",
        "graph_type": "directed_attribution_graph",
        "created_at": packet["created_at"],
        "packet_sha256": packet["packet_sha256"],
        "layout_hint": "left_to_right",
        "nodes": nodes,
        "edges": edges,
    }
    graph["mermaid"] = render_xai_graph_mermaid(graph)
    graph["graph_sha256"] = _sha256_text(json.dumps(graph, sort_keys=True, ensure_ascii=False))
    return graph


def render_xai_graph_mermaid(graph: dict[str, Any]) -> str:
    """Renderiza a etapa `render xai graph mermaid` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    labels = {node["id"]: str(node["label"]).replace('"', "'") for node in graph["nodes"]}
    lines = ["flowchart LR"]
    for node_id, label in labels.items():
        lines.append(f'  {node_id}["{label}"]')
    for edge in graph["edges"]:
        label = str(edge.get("label", "")).replace('"', "'")
        lines.append(f'  {edge["source"]} -- "{label}" --> {edge["target"]}')
    return "\n".join(lines)


def _numeric_values(obj: Any) -> Iterable[float]:
    """Executa a etapa `numeric values` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        value = float(obj)
        if math.isfinite(value):
            yield value
        return
    if isinstance(obj, str):
        for token in NUMERIC_TOKEN_RE.findall(obj):
            try:
                value = float(token.replace(",", "."))
            except ValueError:
                continue
            if math.isfinite(value):
                yield value
        return
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _numeric_values(value)
        return
    if isinstance(obj, (list, tuple, set)):
        for value in obj:
            yield from _numeric_values(value)


def allowed_numeric_values(packet: dict[str, Any]) -> set[float]:
    """Executa a etapa `allowed numeric values` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    values = {round(v, 6) for v in _numeric_values(packet)}
    values.update({0.0, 1.0, 2.0, 10.0, 12.0, 90.0})
    return values


def _is_allowed_number(value: float, allowed: set[float]) -> bool:
    # Narratives use rounded display numbers; 0.005 tolerates three decimals but
    # still rejects material hallucinations such as 999 or wrong years.
    """Executa a etapa `is allowed number` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return any(abs(value - candidate) <= 0.005 for candidate in allowed)


def verify_narrative_against_packet(packet: dict[str, Any], narrative: str) -> dict[str, Any]:
    """Valida a etapa `verify narrative against packet` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    allowed = allowed_numeric_values(packet)
    unknown: list[dict[str, Any]] = []
    checked = 0
    for token in NUMERIC_TOKEN_RE.findall(narrative):
        checked += 1
        try:
            value = float(token.replace(",", "."))
        except ValueError:
            unknown.append({"token": token, "reason": "not_parseable"})
            continue
        if not _is_allowed_number(value, allowed):
            unknown.append({"token": token, "value": value})
    if unknown:
        raise NarrativeValidationError(f"Narrativa contem numero fora do pacote XAI: {unknown}")
    return {
        "status": "verified",
        "checked_numeric_tokens": checked,
        "allowed_numeric_values_count": len(allowed),
        "verifier": "numeric_fact_guard_v1",
    }


def build_llm_grounding_prompt(packet: dict[str, Any]) -> str:
    """Constroi a etapa `build llm grounding prompt` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    compact_packet = {
        "input": packet["input"],
        "model": packet["model"],
        "prediction": packet["prediction"],
        "exact_attribution": packet["exact_attribution"],
        "climatology_evidence": packet["climatology_evidence"],
        "regional_intensity_evidence": packet["regional_intensity_evidence"],
        "llm_xai_contract": packet["llm_xai_contract"],
    }
    facts_json = json.dumps(compact_packet, ensure_ascii=False, sort_keys=True, indent=2)
    return (
        "Voce e uma camada de narracao XAI do FireCast. Use SOMENTE os fatos JSON abaixo. "
        "Nao calcule nova previsao, nao introduza numeros novos, nao altere unidade, nao esconda o status. "
        "Se precisar de um numero que nao esta no JSON, responda que nao ha evidencia.\n\n"
        f"FATOS_VERIFICADOS_JSON:\n{facts_json}\n"
    )


def render_deterministic_narrative(packet: dict[str, Any]) -> str:
    """Renderiza a etapa `render deterministic narrative` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    p = packet["prediction"]
    x = packet["exact_attribution"]
    c = packet["climatology_evidence"]
    r = packet["regional_intensity_evidence"]
    i = packet["input"]
    text = (
        f"Explicacao XAI verificada para geocodigo {i['geocodigo']}, ano {i['ano']}, mes {i['mes']}: "
        f"a previsao e {_fmt(p['y_pred'])} focos. "
        f"A conta exata do artefato e climatologia municipal-mes {_fmt(x['base_climatology'])} "
        f"multiplicada por fator regional {_fmt(x['regional_intensity_ratio'], 4)}, resultando em {_fmt(p['y_pred'])}. "
        f"A climatologia vem de {c['train_months']} meses historicos do municipio e total historico {_fmt(c['train_total'])}. "
        f"O fator regional usa {r['trailing_months']} meses anteriores, com observado {_fmt(r['observed_trailing_12m'])} "
        f"e esperado {_fmt(r['expected_trailing_12m'])}; o ratio bruto foi {_fmt(r['raw_ratio'], 4)} "
        f"e o ratio aplicado foi {_fmt(r['applied_ratio'], 4)}. "
        f"O intervalo p90 vai de {_fmt(p['interval_p90_low'])} a {_fmt(p['interval_p90_high'])} focos. "
        "O LLM nao alterou a predicao; esta narrativa foi validada contra o pacote XAI."
    )
    verify_narrative_against_packet(packet, text)
    return text


def build_verified_xai_response(
    model: ChampionClimatologyModel,
    geocodigo: int,
    ano: int,
    mes: int,
    candidate_narrative: str | None = None,
) -> dict[str, Any]:
    """Constroi a etapa `build verified xai response` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    packet = build_xai_packet(model, geocodigo=geocodigo, ano=ano, mes=mes)
    graph = build_xai_graph(packet)
    prompt = build_llm_grounding_prompt(packet)
    narrative = candidate_narrative if candidate_narrative is not None else render_deterministic_narrative(packet)
    verification = verify_narrative_against_packet(packet, narrative)
    return {
        "schema_version": "firecast_verified_llm_xai_response_v1",
        "xai_packet": packet,
        "xai_graph": graph,
        "llm_narrative": {
            "text": narrative,
            "engine": "verified_template" if candidate_narrative is None else "external_llm_candidate_verified",
            "llm_touched_prediction": False,
        },
        "llm_contract": {
            "grounding_prompt": prompt,
            "grounding_prompt_sha256": _sha256_text(prompt),
            "verifier": verification["verifier"],
            "failure_policy": packet["llm_xai_contract"]["failure_policy"],
        },
        "verification": verification,
    }


def explain_from_path(model_path: Path, geocodigo: int, ano: int, mes: int) -> dict[str, Any]:
    """Produz a etapa `explain from path` do fluxo FireCast.
    
    A funcao faz parte de `src/production/llm_xai.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    model = ChampionClimatologyModel.load(model_path)
    return build_verified_xai_response(model, geocodigo=geocodigo, ano=ano, mes=mes)


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/production/llm_xai.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser(description="Build a verified LLM-safe XAI explanation for one FireCast prediction")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--geocodigo", type=int, default=2300101)
    parser.add_argument("--ano", type=int, default=2026)
    parser.add_argument("--mes", type=int, default=10)
    parser.add_argument("--graph-only", action="store_true", help="print only the XAI attribution graph")
    args = parser.parse_args()
    response = explain_from_path(args.model_path, args.geocodigo, args.ano, args.mes)
    payload = response["xai_graph"] if args.graph_only else response
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
