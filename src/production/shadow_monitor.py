"""Modulo publico do FireCast para serving, artefato champion, monitoramento e XAI.

Arquivo `src/production/shadow_monitor.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.production.champion_climatology import ChampionClimatologyModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "outputs" / "champion_climatology_regional_intensity12" / "model.json"
G5_REPORT_PATH = PROJECT_ROOT / "outputs" / "g5_conformal_ic95_guarded_exp10" / "g5_report.json"
TARGET_PATH = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
PUBLIC_AQUA_EVENTS_PATH = PROJECT_ROOT / "data" / "snapshots" / "inpe_monthly_public_v3" / "events_target_region.csv"
OUT_DIR = PROJECT_ROOT / "outputs" / "shadow_monitor"
SHADOW_LOG = OUT_DIR / "shadow_log.jsonl"
SCORE_LOG = OUT_DIR / "shadow_scores.jsonl"
REPORT_PATH = OUT_DIR / "monitoring_report.md"

# Reference WAPE for degradation alerts: champion extended walk-forward WAPE
# (EXP-10, 2015-2024, 120 cuts). Config drift threshold is additive.
REFERENCE_ALL_WAPE = 0.6430
WAPE_INCREASE_ALERT = 0.05
FRESHNESS_ALERT_MONTHS = 2
SCORE_SCHEMA_VERSION = "v2_event_absence_is_zero"


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _require(path: Path, what: str) -> Path:
    """Executa a etapa `require` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not path.exists():
        raise FileNotFoundError(f"{what} ausente: {path} - operacao shadow fail-closed")
    return path


def _target_label(path: Path) -> str:
    """Executa a etapa `target label` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Executa a etapa `read jsonl` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Executa a etapa `append jsonl` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_observed(target_path: Path = TARGET_PATH, target_satellite: str | None = None) -> pd.DataFrame:
    """Carrega a etapa `load observed` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = pd.read_csv(_require(target_path, "Target snapshot"))
    required = {"geocodigo", "ano", "mes"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Target snapshot sem colunas obrigatorias: {sorted(missing)}")

    event_level_target = False
    if "fire_count" in df.columns:
        if target_satellite is not None and "satelite" not in df.columns:
            raise ValueError(
                "Filtro de satelite solicitado, mas o alvo mensal ja agregado nao tem coluna 'satelite'. "
                "Use o arquivo event-level events_target_region.csv para scoring AQUA_M-T."
            )
        monthly = df[df["fire_count"].notna()][["geocodigo", "ano", "mes", "fire_count"]].copy()
    else:
        if "satelite" not in df.columns:
            raise ValueError("Target event-level sem coluna 'satelite' e sem 'fire_count'; alvo ambiguo")
        if not target_satellite:
            raise ValueError("Target event-level mistura sensores; informe --target-satellite para evitar alvo ambiguo")
        event_level_target = True
        filtered = df[df["satelite"].astype(str) == target_satellite].copy()
        monthly = (
            filtered.groupby(["geocodigo", "ano", "mes"], as_index=False)
            .size()
            .rename(columns={"size": "fire_count"})
        )

    monthly["geocodigo"] = monthly["geocodigo"].astype(int)
    monthly["ano"] = monthly["ano"].astype(int)
    monthly["mes"] = monthly["mes"].astype(int)
    monthly["fire_count"] = monthly["fire_count"].astype(float)
    monthly.attrs["event_level_target"] = event_level_target
    return monthly


def latest_observed_period(df: pd.DataFrame) -> pd.Period:
    """Executa a etapa `latest observed period` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    keys = pd.PeriodIndex(
        pd.to_datetime(df["ano"].astype(str) + "-" + df["mes"].astype(str).str.zfill(2)), freq="M"
    )
    return keys.max()


def record(ano: int, mes: int, target_path: Path = TARGET_PATH, target_satellite: str | None = None) -> dict[str, Any]:
    """Executa a etapa `record` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    model = ChampionClimatologyModel.load(_require(MODEL_PATH, "Champion artifact"))
    g5_hash = sha256_file(_require(G5_REPORT_PATH, "G5 report"))
    model_hash = sha256_file(MODEL_PATH)

    for entry in _read_jsonl(SHADOW_LOG):
        if entry["ano"] == ano and entry["mes"] == mes and entry["model_sha256"] == model_hash:
            raise RuntimeError(
                f"Shadow record duplicado para {ano}-{mes:02d} com o mesmo artefato; log e append-only"
            )

    observed = load_observed(target_path=target_path, target_satellite=target_satellite)
    latest = latest_observed_period(observed)
    target_period = pd.Period(f"{ano}-{mes:02d}", freq="M")
    is_backfill = target_period <= latest

    geocodes = sorted({int(row["geocodigo"]) for row in model.artifact["climatology"]})
    predictions = []
    for geo in geocodes:
        pred = model.predict_one(geo, ano, mes)
        predictions.append({"geocodigo": geo, "y_pred": float(pred["y_pred"])})

    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "ano": ano,
        "mes": mes,
        "mode": "backfill_drill" if is_backfill else "live_shadow",
        "model_sha256": model_hash,
        "g5_report_sha256": g5_hash,
        "n_municipios": len(predictions),
        "total_pred": float(sum(p["y_pred"] for p in predictions)),
        "predictions": predictions,
    }
    _append_jsonl(SHADOW_LOG, entry)
    return {k: v for k, v in entry.items() if k != "predictions"}


def score(target_path: Path = TARGET_PATH, target_satellite: str | None = None) -> list[dict[str, Any]]:
    """Calcula a etapa `score` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    observed = load_observed(target_path=target_path, target_satellite=target_satellite)
    event_absence_is_zero = bool(observed.attrs.get("event_level_target"))
    target_hash = sha256_file(_require(target_path, "Target snapshot"))
    target_label = _target_label(target_path)
    scored_keys = {
        (
            s["ano"],
            s["mes"],
            s["model_sha256"],
            s.get("target_sha256", "legacy-target"),
            s.get("target_satellite"),
            s.get("score_schema_version", "legacy"),
        )
        for s in _read_jsonl(SCORE_LOG)
    }
    results = []
    for entry in _read_jsonl(SHADOW_LOG):
        key = (
            entry["ano"],
            entry["mes"],
            entry["model_sha256"],
            target_hash,
            target_satellite,
            SCORE_SCHEMA_VERSION,
        )
        if key in scored_keys:
            continue
        obs = observed[(observed["ano"] == entry["ano"]) & (observed["mes"] == entry["mes"])]
        if obs.empty:
            continue
        pred = pd.DataFrame(entry["predictions"])
        merged = pred.merge(obs[["geocodigo", "fire_count"]], on="geocodigo", how="left")
        if event_absence_is_zero:
            missing = 0
            merged["fire_count"] = merged["fire_count"].fillna(0.0)
            valid = merged
        else:
            missing = int(merged["fire_count"].isna().sum())
            valid = merged.dropna(subset=["fire_count"])
        denom = float(valid["fire_count"].sum())
        wape = float((valid["fire_count"] - valid["y_pred"]).abs().sum() / denom) if denom > 0 else None
        mae = float((valid["fire_count"] - valid["y_pred"]).abs().mean()) if len(valid) else None
        alerts = []
        if wape is not None and wape > REFERENCE_ALL_WAPE + WAPE_INCREASE_ALERT:
            alerts.append(
                f"WAPE {wape:.4f} excede referencia {REFERENCE_ALL_WAPE:.4f} + {WAPE_INCREASE_ALERT:.2f}"
            )
        if missing > 0:
            alerts.append(f"{missing} municipios sem observado no snapshot")
        result = {
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "score_schema_version": SCORE_SCHEMA_VERSION,
            "ano": entry["ano"],
            "mes": entry["mes"],
            "mode": entry["mode"],
            "model_sha256": entry["model_sha256"],
            "target_path": target_label,
            "target_sha256": target_hash,
            "target_satellite": target_satellite,
            "event_absence_is_zero": event_absence_is_zero,
            "n_scored": int(len(valid)),
            "n_missing_observed": missing,
            "observed_total": denom,
            "predicted_total": float(valid["y_pred"].sum()) if len(valid) else None,
            "wape": wape,
            "mae": mae,
            "alerts": alerts,
        }
        _append_jsonl(SCORE_LOG, result)
        results.append(result)
    return results

def report(target_path: Path = TARGET_PATH, target_satellite: str | None = None) -> str:
    """Executa a etapa `report` do fluxo FireCast.
    
    A funcao faz parte de `src/production/shadow_monitor.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    observed = load_observed(target_path=target_path, target_satellite=target_satellite)
    latest = latest_observed_period(observed)
    now_period = pd.Period(datetime.now(timezone.utc).strftime("%Y-%m"), freq="M")
    freshness_months = int((now_period - latest).n)
    target_hash = sha256_file(_require(target_path, "Target snapshot"))
    scores = _read_jsonl(SCORE_LOG)
    records = _read_jsonl(SHADOW_LOG)
    current_scores = [
        s
        for s in scores
        if s.get("target_sha256") == target_hash
        and s.get("target_satellite") == target_satellite
        and s.get("score_schema_version") == SCORE_SCHEMA_VERSION
    ]
    if not current_scores and target_path.resolve() == TARGET_PATH.resolve() and target_satellite is None:
        current_scores = [s for s in scores if "target_sha256" not in s]
    scored_keys = {
        (
            s["ano"],
            s["mes"],
            s["model_sha256"],
            s.get("target_sha256", "legacy-target"),
            s.get("target_satellite"),
            s.get("score_schema_version", "legacy"),
        )
        for s in current_scores
    }
    pending = [
        f"{e['ano']}-{e['mes']:02d}"
        for e in records
        if (e["ano"], e["mes"], e["model_sha256"], target_hash, target_satellite, SCORE_SCHEMA_VERSION)
        not in scored_keys
    ]
    target_desc = f"`{_target_label(target_path)}`"
    if target_satellite:
        target_desc += f" filtrado em `{target_satellite}`"
    lines = [
        "# FireCast - relatorio de monitoramento shadow",
        "",
        f"Gerado em {datetime.now(timezone.utc).isoformat()}.",
        "",
        f"- Ultimo mes observado no snapshot alvo: **{latest}**",
        f"- Alvo usado no relatorio: {target_desc}",
        f"- Versao de scoring: `{SCORE_SCHEMA_VERSION}`",
        f"- Idade do dado observado: **{freshness_months} meses**"
        + (" [ALERTA] dado observado velho" if freshness_months > FRESHNESS_ALERT_MONTHS else ""),
        f"- Registros shadow: {len(records)} ({sum(1 for e in records if e['mode'] == 'live_shadow')} live, "
        f"{sum(1 for e in records if e['mode'] == 'backfill_drill')} drill)",
        f"- Meses aguardando observado: {pending if pending else 'nenhum'}",
        "",
        "## Desempenho atrasado",
        "",
        "| Mes | Modo | Alvo | N | Observado | Predito | WAPE | MAE | Alertas |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for s in current_scores:
        wape_txt = f"{s['wape']:.4f}" if s["wape"] is not None else "n/a"
        mae_txt = f"{s['mae']:.2f}" if s["mae"] is not None else "n/a"
        observed_txt = f"{s['observed_total']:.2f}" if s.get("observed_total") is not None else "n/a"
        predicted_txt = f"{s['predicted_total']:.2f}" if s.get("predicted_total") is not None else "n/a"
        alert_txt = "; ".join(s["alerts"]) if s["alerts"] else "-"
        source_txt = s.get("target_satellite") or "legacy/v2"
        lines.append(
            f"| {s['ano']}-{s['mes']:02d} | {s['mode']} | {source_txt} | {s['n_scored']} | "
            f"{observed_txt} | {predicted_txt} | {wape_txt} | {mae_txt} | {alert_txt} |"
        )
    lines += [
        "",
        "## Rollback",
        "",
        "- Artefato champion versionado por sha256 no shadow log; para rollback, apontar",
        "  `--model-path` da API para o artefato anterior e registrar a troca no ledger.",
        "- Status de release externo permanece controlado por G0-G7; este relatorio nao",
        "  autoriza deploy.",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(text, encoding="utf-8")
    return text

def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/production/shadow_monitor.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_record = sub.add_parser("record", help="registrar predicoes do champion para um mes")
    p_record.add_argument("--ano", type=int, required=True)
    p_record.add_argument("--mes", type=int, required=True, choices=range(1, 13))
    p_record.add_argument("--target-path", type=Path, default=TARGET_PATH)
    p_record.add_argument("--target-satellite", default=None)
    p_score = sub.add_parser("score", help="pontuar meses registrados cujo observado ja chegou")
    p_score.add_argument("--target-path", type=Path, default=TARGET_PATH)
    p_score.add_argument("--target-satellite", default=None)
    p_report = sub.add_parser("report", help="gerar relatorio de monitoramento")
    p_report.add_argument("--target-path", type=Path, default=TARGET_PATH)
    p_report.add_argument("--target-satellite", default=None)
    args = parser.parse_args()
    if args.command == "record":
        print(json.dumps(record(args.ano, args.mes, args.target_path, args.target_satellite), indent=2))
    elif args.command == "score":
        print(json.dumps(score(args.target_path, args.target_satellite), indent=2))
    else:
        print(report(args.target_path, args.target_satellite))


if __name__ == "__main__":
    main()







