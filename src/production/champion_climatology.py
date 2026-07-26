"""Empacotamento e inferencia do modelo champion climatologico-regional.

A rotina reconstrui a climatologia municipal por mes, aplica o fator regional de 12 meses e preserva identidade entre treino e serving."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

TARGET_PATH = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
BACKTEST_DIR = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity"
ARTIFACT_DIR = PROJECT_ROOT / "outputs" / "champion_climatology_regional_intensity12"
MODEL_NAME = "climatology_regional_intensity12"
BASELINE_MODEL_NAME = "climatology_municipal"
TRAIN_END_YEAR = 2024
TRAIN_END_MONTH = 12
TRAILING_MONTHS = 12
SHRINK_FIRE_COUNT = 100.0
RATIO_CLIP = [0.5, 2.0]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def artifact_sha256(payload: dict[str, Any]) -> str:
    """Executa a etapa `artifact sha256` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _period_key(year: int, month: int) -> int:
    """Executa a etapa `period key` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return int(year) * 100 + int(month)


def _period_label(period: pd.Period) -> str:
    """Executa a etapa `period label` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return f"{period.year}-{period.month:02d}"


def load_training_frame(target_path: Path = TARGET_PATH) -> pd.DataFrame:
    """Carrega a etapa `load training frame` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = pd.read_csv(target_path)
    needed = {"geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Target snapshot sem colunas obrigatorias: {sorted(missing)}")
    df = df[df["fire_count"].notna()].copy()
    df["period_key"] = df["ano"].astype(int) * 100 + df["mes"].astype(int)
    df = df[df["period_key"] <= _period_key(TRAIN_END_YEAR, TRAIN_END_MONTH)]
    if df.empty:
        raise ValueError("Target snapshot sem linhas de treino validas para o champion")
    return df


def build_climatology_table(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Constroi a etapa `build climatology table` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    grouped = df.groupby(["geocodigo", "municipio_ibge", "uf", "mes"], as_index=False)["fire_count"]
    table = grouped.agg(prediction="mean", train_months="count", train_total="sum")
    table["prediction"] = table["prediction"].clip(lower=0)
    table["geocodigo"] = table["geocodigo"].astype(int)
    table["mes"] = table["mes"].astype(int)
    return table.sort_values(["geocodigo", "mes"]).to_dict("records")


def _climatology_lookup(climatology: list[dict[str, Any]]) -> dict[tuple[int, int], float]:
    """Executa a etapa `climatology lookup` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return {(int(row["geocodigo"]), int(row["mes"])): float(row["prediction"]) for row in climatology}


def build_regional_intensity_table(df: pd.DataFrame, climatology: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Constroi a etapa `build regional intensity table` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    hist = df[["geocodigo", "ano", "mes", "fire_count"]].copy()
    hist["period"] = pd.PeriodIndex(
        pd.to_datetime(hist["ano"].astype(str) + "-" + hist["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    lookup = _climatology_lookup(climatology)
    min_period = hist["period"].min() + TRAILING_MONTHS
    train_end = pd.Period(f"{TRAIN_END_YEAR}-{TRAIN_END_MONTH:02d}", freq="M")
    max_forecast_period = train_end + 1

    rows = []
    for forecast_period in pd.period_range(min_period, max_forecast_period, freq="M"):
        prior_periods = pd.period_range(forecast_period - TRAILING_MONTHS, forecast_period - 1, freq="M")
        prior = hist[hist["period"].isin(prior_periods)].copy()
        if prior.empty:
            observed = 0.0
            expected = 0.0
            raw_ratio = 1.0
        else:
            observed = float(prior["fire_count"].sum())
            expected = float(
                sum(lookup.get((int(row.geocodigo), int(row.mes)), 0.0) for row in prior.itertuples(index=False))
            )
            raw_ratio = (observed + SHRINK_FIRE_COUNT) / (expected + SHRINK_FIRE_COUNT)
        applied = float(np.clip(raw_ratio, RATIO_CLIP[0], RATIO_CLIP[1]))
        rows.append(
            {
                "forecast_period": _period_label(forecast_period),
                "source_window_start": _period_label(forecast_period - TRAILING_MONTHS),
                "source_window_end": _period_label(forecast_period - 1),
                "observed_trailing_12m": observed,
                "expected_trailing_12m": expected,
                "raw_ratio": float(raw_ratio),
                "applied_ratio": applied,
                "n_rows": int(len(prior)),
            }
        )
    return rows


def load_metrics(backtest_dir: Path = BACKTEST_DIR) -> dict[str, Any]:
    """Carrega a etapa `load metrics` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    summary_path = backtest_dir / "summary.csv"
    predictions_path = backtest_dir / "predictions.csv"
    manifest_path = backtest_dir / "run_manifest.json"
    if not summary_path.exists() or not predictions_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("EXP-10 ausente; rode exp10_dynamic_regional_intensity.py antes de empacotar")

    summary = pd.read_csv(summary_path)
    row = summary[summary["model"] == MODEL_NAME]
    baseline = summary[summary["model"] == BASELINE_MODEL_NAME]
    if row.empty or baseline.empty:
        raise ValueError(f"Resumo EXP-10 sem metricas para {MODEL_NAME} e baseline")

    preds = pd.read_csv(predictions_path)
    preds = preds[preds["model"] == MODEL_NAME].copy()
    preds["abs_error"] = (preds["fire_count"] - preds["y_pred"]).abs()
    gate_window = preds[preds["ano"].isin([2023, 2024])].copy()
    outnov_gate = gate_window[gate_window["mes"].isin([10, 11])]

    metrics = row.iloc[0].to_dict()
    metrics.update(
        {
            "baseline_model": BASELINE_MODEL_NAME,
            "baseline_extended_wape": float(baseline.iloc[0]["all_wape"]),
            "baseline_extended_outnov_wape": float(baseline.iloc[0]["outnov_wape"]),
            "backtest_protocol": "walk-forward estendido 120 cortes mensais 2015-2024, h=1, 2025+ congelado",
            "gate_window_protocol": "walk-forward 24 cortes mensais 2023-2024, h=1, inpe_local_v2",
            "gate_window_all_wape": float(np.abs(gate_window["fire_count"] - gate_window["y_pred"]).sum() / gate_window["fire_count"].sum()),
            "gate_window_outnov_wape": float(
                np.abs(outnov_gate["fire_count"] - outnov_gate["y_pred"]).sum() / outnov_gate["fire_count"].sum()
            ),
            "prediction_rows": int(len(preds)),
            "residual_abs_error_p50": float(preds["abs_error"].quantile(0.50)),
            "residual_abs_error_p90": float(preds["abs_error"].quantile(0.90)),
            "residual_abs_error_p95": float(preds["abs_error"].quantile(0.95)),
            "backtest_summary_sha256": sha256_file(summary_path),
            "backtest_predictions_sha256": sha256_file(predictions_path),
            "backtest_manifest_sha256": sha256_file(manifest_path),
        }
    )
    return metrics


def build_artifact() -> dict[str, Any]:
    """Constroi a etapa `build artifact` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    train = load_training_frame()
    climatology = build_climatology_table(train)
    intensity = build_regional_intensity_table(train, climatology)
    metrics = load_metrics()
    artifact = {
        "schema_version": "1.0",
        "model_name": MODEL_NAME,
        "model_type": "municipal_month_climatology_with_regional_trailing_intensity",
        "status": "release_candidate_not_production_approved",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "training_data": {
            "snapshot": "inpe_local_v2/inpe_monthly_merged.csv",
            "sha256": sha256_file(TARGET_PATH),
            "train_end": f"{TRAIN_END_YEAR}-{TRAIN_END_MONTH:02d}",
            "rows": int(len(train)),
            "municipalities": int(train["geocodigo"].nunique()),
        },
        "metrics": metrics,
        "intensity_parameters": {
            "trailing_months": TRAILING_MONTHS,
            "shrink_fire_count": SHRINK_FIRE_COUNT,
            "ratio_clip": RATIO_CLIP,
            "future_policy": "use latest available training-window regional ratio when requested forecast period is beyond target history",
        },
        "fail_closed_contract": {
            "required_inputs": ["geocodigo", "ano", "mes"],
            "missing_municipality_or_month": "raise ValueError; never fabricate zero/random prediction",
            "prediction_semantics": "municipal-month climatology scaled by regional trailing-12-month fire intensity",
            "interval_semantics": "global empirical absolute-error interval from EXP-10 extended walk-forward residuals",
        },
        "climatology": climatology,
        "regional_intensity": intensity,
    }
    artifact["artifact_sha256"] = artifact_sha256(artifact)
    return artifact


def write_model_card(artifact: dict[str, Any], out_dir: Path) -> None:
    """Grava a etapa `write model card` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    m = artifact["metrics"]
    text = f"""# FireCast Champion Model Card -- {artifact['model_name']}

Status: **APROVADO PARA PRODUCAO INTERNA (contrato G3 v2, decisao humana 2026-07-11);
release EXTERNO pendente de janela de shadow vivo**.

## Modelo

Climatologia municipal por mes multiplicada por um fator regional de intensidade
dos ultimos 12 meses observados. A mudanca foi validada no EXP-2026-07-09-10.

Formula:

```text
pred = climatologia_municipio_mes * clip((observado_12m + 100) / (esperado_12m + 100), 0.5, 2.0)
```

O mes alvo nunca entra no fator. Para previsoes alem do historico de alvo
empacotado, o serving usa o ultimo fator regional disponivel no treino e mantem o
status de release candidate.

## Metricas validadas

- Protocolo primario: {m['backtest_protocol']}.
- WAPE estendido: {float(m['all_wape']):.4f} vs baseline {float(m['baseline_extended_wape']):.4f}.
- WAPE out-nov estendido: {float(m['outnov_wape']):.4f} vs baseline {float(m['baseline_extended_outnov_wape']):.4f}.
- Janela 2023-2024: WAPE {float(m['gate_window_all_wape']):.4f}; out-nov {float(m['gate_window_outnov_wape']):.4f}.
- Erro absoluto empirico p50/p90/p95: {float(m['residual_abs_error_p50']):.2f} / {float(m['residual_abs_error_p90']):.2f} / {float(m['residual_abs_error_p95']):.2f} focos.

## Decisao experimental

EXP-10 superou o champion anterior no protocolo estendido: WAPE 0,7906 -> 0,6430,
out-nov 0,6923 -> 0,5419, 85/120 cortes vencidos, bootstrap delta WAPE CI95
[-0,2195, -0,0852], P(candidato melhor)=1,000. Decisao: PROMOTE para champion
interno.

## Gates (2026-07-11)

- G0-G2, G4, G6: PASS (ver PRODUCTION_READINESS.md).
- G3: PASS no contrato v2 (EXP-26: WAPE totais mensais CE 0,2245 <= 0,25; total
  sazonal CE 0,1794 <= 0,20; Chapada sazonal 0,3723 <= 0,40; Recall@10
  0,775/0,90; zero indevido 0,0). O contrato v1 (WAPE municipal-mes <= 0,20/0,25)
  foi demonstrado praticamente inatingivel pela auditoria EXP-25 (piso NB
  0,38/0,53; desacordo INPE-FIRMS 0,41/0,43) e esta registrado como historico.
- G5: PASS com IC95 guardado (cobertura 0,9170 geral / 0,9000 seca / 0,9274 chuva).
- G7: PASS para escopo INTERNO (aprovacao humana registrada em
  OPS-G7-APPROVAL; shadow mensal via src/production/shadow_monitor.py).
  Release EXTERNO pendente de janela de shadow vivo.

## Limitacoes

- WAPE municipal-mes (~0,50 no gate) esta na zona de ruido irredutivel do alvo
  (EXP-25); o contrato v2 nao exige precisao municipal de magnitude, exige
  ranking (Recall@10) e magnitude agregada por escopo.
- O multiplicador regional melhora anos altos/baixos, mas pode piorar municipios
  de baixo volume em avaliacao estendida (2/31 flagados fora da janela de gate).
- Alvo INPE atualizado ate 2026-04; shadow vivo pontua conforme novos meses chegam.
"""
    (out_dir / "model_card.md").write_text(text, encoding="utf-8")


@dataclass(frozen=True)
class ChampionClimatologyModel:
    """Representa `ChampionClimatologyModel` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/production/champion_climatology.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    artifact: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "ChampionClimatologyModel":
        """Executa a etapa `load` do fluxo FireCast.
        
        A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        artifact = json.loads(path.read_text(encoding="utf-8"))
        expected = artifact.get("artifact_sha256")
        payload = dict(artifact)
        payload.pop("artifact_sha256", None)
        actual = artifact_sha256(payload)
        if expected != actual:
            raise ValueError(f"Hash do artefato invalido: esperado {expected}, obtido {actual}")
        return cls(artifact)

    def base_prediction(self, geocodigo: int, mes: int) -> float:
        """Executa a etapa `base prediction` do fluxo FireCast.
        
        A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        for row in self.artifact["climatology"]:
            if int(row["geocodigo"]) == int(geocodigo) and int(row["mes"]) == int(mes):
                return float(row["prediction"])
        raise ValueError(f"Sem climatologia para geocodigo={geocodigo}, mes={mes}; fail-closed")

    def regional_intensity_ratio(self, ano: int, mes: int) -> tuple[float, str]:
        """Executa a etapa `regional intensity ratio` do fluxo FireCast.
        
        A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        requested = f"{int(ano)}-{int(mes):02d}"
        rows = self.artifact["regional_intensity"]
        for row in rows:
            if row["forecast_period"] == requested:
                return float(row["applied_ratio"]), row["forecast_period"]
        latest = rows[-1]
        return float(latest["applied_ratio"]), latest["forecast_period"]

    def predict_one(self, geocodigo: int, ano: int, mes: int) -> dict[str, Any]:
        """Gera a etapa `predict one` do fluxo FireCast.
        
        A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if not (1 <= int(mes) <= 12):
            raise ValueError(f"Mes invalido: {mes}")
        base = self.base_prediction(geocodigo, mes)
        ratio, ratio_period = self.regional_intensity_ratio(ano, mes)
        pred = max(0.0, base * ratio)
        err = float(self.artifact["metrics"]["residual_abs_error_p90"])
        return {
            "geocodigo": int(geocodigo),
            "ano": int(ano),
            "mes": int(mes),
            "y_pred": pred,
            "interval_p90_low": max(0.0, pred - err),
            "interval_p90_high": pred + err,
            "model_name": self.artifact["model_name"],
            "artifact_sha256": self.artifact["artifact_sha256"],
            "regional_intensity_ratio": ratio,
            "regional_intensity_ratio_period": ratio_period,
        }


def package(out_dir: Path = ARTIFACT_DIR) -> dict[str, Any]:
    """Executa a etapa `package` do fluxo FireCast.
    
    A funcao faz parte de `src/production/champion_climatology.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = build_artifact()
    model_path = out_dir / "model.json"
    model_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    write_model_card(artifact, out_dir)
    print(f"OK: artefato em {model_path}")
    print(
        f"WAPE_EXT={float(artifact['metrics']['all_wape']):.4f}; "
        f"out-nov EXT={float(artifact['metrics']['outnov_wape']):.4f}; "
        f"WAPE_2023_2024={float(artifact['metrics']['gate_window_all_wape']):.4f}"
    )
    return artifact


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/production/champion_climatology.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ARTIFACT_DIR)
    parser.add_argument("--predict", action="store_true")
    parser.add_argument("--geocodigo", type=int)
    parser.add_argument("--ano", type=int)
    parser.add_argument("--mes", type=int)
    args = parser.parse_args()
    if args.predict:
        if args.geocodigo is None or args.ano is None or args.mes is None:
            raise SystemExit("--predict exige --geocodigo --ano --mes")
        model = ChampionClimatologyModel.load(args.out_dir / "model.json")
        print(json.dumps(model.predict_one(args.geocodigo, args.ano, args.mes), indent=2, ensure_ascii=False))
    else:
        package(args.out_dir)


if __name__ == "__main__":
    main()
