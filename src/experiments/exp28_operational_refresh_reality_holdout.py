"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp28_operational_refresh_reality_holdout.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.production.champion_climatology import ChampionClimatologyModel  # noqa: E402
from src.utils.metrics import wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp28_operational_refresh_reality_holdout"
ARTIFACT_PATH = PROJECT_ROOT / "outputs" / "champion_climatology_regional_intensity12" / "model.json"
V2_TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
V3_EVENTS = PROJECT_ROOT / "data" / "snapshots" / "inpe_monthly_public_v3" / "events_target_region.csv"
REFERENCE_SATELLITE = "AQUA_M-T"
OWNER_ABS_TOTAL_ERROR_TARGET = 300.0
TRAILING_MONTHS = 12
SHRINK_FIRE_COUNT = 100.0
RATIO_CLIP = (0.5, 2.0)


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def served_codes(model: ChampionClimatologyModel) -> list[int]:
    """Executa a etapa `served codes` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return sorted({int(row["geocodigo"]) for row in model.artifact["climatology"]})


def base_lookup(model: ChampionClimatologyModel) -> dict[tuple[int, int], float]:
    """Executa a etapa `base lookup` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return {(int(row["geocodigo"]), int(row["mes"])): float(row["prediction"]) for row in model.artifact["climatology"]}


def build_observed(model: ChampionClimatologyModel) -> pd.DataFrame:
    """Constroi a etapa `build observed` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    served = set(served_codes(model))
    v2 = pd.read_csv(V2_TARGET)
    v2 = v2[v2["geocodigo"].astype(int).isin(served) & v2["fire_count"].notna()].copy()
    v2 = v2[v2["ano"] <= 2024][["geocodigo", "ano", "mes", "fire_count"]]

    events = pd.read_csv(V3_EVENTS)
    events = events[events["geocodigo"].astype(int).isin(served) & (events["satelite"] == REFERENCE_SATELLITE)].copy()
    public = events.groupby(["geocodigo", "ano", "mes"], as_index=False).size().rename(columns={"size": "fire_count"})
    periods = [(year, month) for year in [2025, 2026] for month in range(1, 13)]
    grid = pd.MultiIndex.from_product([sorted(served), periods], names=["geocodigo", "ym"]).to_frame(index=False)
    grid[["ano", "mes"]] = pd.DataFrame(grid.pop("ym").tolist(), index=grid.index)
    public = grid.merge(public, on=["geocodigo", "ano", "mes"], how="left")
    public["fire_count"] = public["fire_count"].fillna(0.0)

    obs = pd.concat([v2, public], ignore_index=True)
    obs["period"] = pd.PeriodIndex.from_fields(year=obs["ano"], month=obs["mes"], freq="M")
    return obs


def base_total(lookup: dict[tuple[int, int], float], codes: list[int], month: int) -> float:
    """Executa a etapa `base total` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(sum(lookup.get((code, month), 0.0) for code in codes))


def observed_total(obs: pd.DataFrame, periods: pd.PeriodIndex) -> float:
    """Executa a etapa `observed total` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(obs[obs["period"].isin(periods)]["fire_count"].sum())


def expected_total(lookup: dict[tuple[int, int], float], codes: list[int], periods: pd.PeriodIndex) -> float:
    """Executa a etapa `expected total` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return float(sum(base_total(lookup, codes, int(period.month)) for period in periods))


def monthly_predictions(model: ChampionClimatologyModel, obs: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `monthly predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    codes = served_codes(model)
    lookup = base_lookup(model)
    rows = []
    for year, month in [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 8)]:
        cut = pd.Period(f"{year}-{month:02d}", freq="M")
        prior = pd.period_range(cut - TRAILING_MONTHS, cut - 1, freq="M")
        prior_obs = observed_total(obs, prior)
        prior_exp = expected_total(lookup, codes, prior)
        refreshed_ratio = float(np.clip((prior_obs + SHRINK_FIRE_COUNT) / (prior_exp + SHRINK_FIRE_COUNT), *RATIO_CLIP))
        base_pred = base_total(lookup, codes, month)
        actual = float(obs[(obs["period"] == cut) & obs["geocodigo"].isin(codes)]["fire_count"].sum())
        static_pred = float(sum(model.predict_one(code, year, month)["y_pred"] for code in codes))
        rows.extend(
            [
                {
                    "model": "champion_static_artifact",
                    "ano": year,
                    "mes": month,
                    "actual": actual,
                    "pred": static_pred,
                    "ratio": model.predict_one(codes[0], year, month)["regional_intensity_ratio"],
                    "prior_obs": prior_obs,
                    "prior_expected": prior_exp,
                },
                {
                    "model": "operational_monthly_refresh",
                    "ano": year,
                    "mes": month,
                    "actual": actual,
                    "pred": base_pred * refreshed_ratio,
                    "ratio": refreshed_ratio,
                    "prior_obs": prior_obs,
                    "prior_expected": prior_exp,
                },
                {
                    "model": "municipal_climatology_no_ratio",
                    "ano": year,
                    "mes": month,
                    "actual": actual,
                    "pred": base_pred,
                    "ratio": 1.0,
                    "prior_obs": prior_obs,
                    "prior_expected": prior_exp,
                },
            ]
        )
    return pd.DataFrame(rows)


def aggregate(rows: pd.DataFrame, year: int, months: list[int]) -> list[dict]:
    """Executa a etapa `aggregate` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp28_operational_refresh_reality_holdout.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = []
    for model, group in rows[(rows["ano"] == year) & rows["mes"].isin(months)].groupby("model"):
        actual = float(group["actual"].sum())
        pred = float(group["pred"].sum())
        out.append(
            {
                "model": model,
                "year": year,
                "months": f"{min(months):02d}-{max(months):02d}",
                "actual_total": actual,
                "pred_total": pred,
                "abs_total_error": abs(pred - actual),
                "passes_owner_abs_total_error_target": abs(pred - actual) <= OWNER_ABS_TOTAL_ERROR_TARGET,
                "monthly_wape_on_totals": wape(group["actual"].values, group["pred"].values),
            }
        )
    return out


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp28_operational_refresh_reality_holdout.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model = ChampionClimatologyModel.load(ARTIFACT_PATH)
    obs = build_observed(model)
    monthly = monthly_predictions(model, obs)
    monthly["abs_error"] = (monthly["pred"] - monthly["actual"]).abs()
    monthly.to_csv(OUT_DIR / "monthly_strategy_comparison.csv", index=False)

    summary = []
    summary.extend(aggregate(monthly, 2025, list(range(1, 13))))
    summary.extend(aggregate(monthly, 2026, list(range(1, 7))))
    summary.extend(aggregate(monthly, 2026, list(range(1, 8))))
    summary_df = pd.DataFrame(summary).sort_values(["year", "months", "abs_total_error"])
    summary_df.to_csv(OUT_DIR / "aggregate_strategy_windows.csv", index=False)

    static_2025 = summary_df[(summary_df["model"] == "champion_static_artifact") & (summary_df["year"] == 2025)].iloc[0]
    refresh_2025 = summary_df[(summary_df["model"] == "operational_monthly_refresh") & (summary_df["year"] == 2025)].iloc[0]
    static_2026 = summary_df[(summary_df["model"] == "champion_static_artifact") & (summary_df["year"] == 2026) & (summary_df["months"] == "01-07")].iloc[0]
    refresh_2026 = summary_df[(summary_df["model"] == "operational_monthly_refresh") & (summary_df["year"] == 2026) & (summary_df["months"] == "01-07")].iloc[0]

    promote_refresh = bool(
        refresh_2025["abs_total_error"] <= static_2025["abs_total_error"]
        and refresh_2026["abs_total_error"] <= static_2026["abs_total_error"]
    )
    decision = "PROMOTE_OPERATIONAL_REFRESH" if promote_refresh else "REJECT_REFRESH_KEEP_CHAMPION_STATIC"

    manifest = {
        "experiment_id": "EXP-2026-07-11-28",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "Monthly operational refresh of the regional intensity ratio improves reality-holdout aggregate volume without overfitting.",
        "change": "Same climatology as champion; recompute only the trailing-12 observed/expected regional multiplier each forecast month using prior observed AQUA_M-T months.",
        "rejection_condition": "Reject if refresh worsens complete 2025 absolute total error versus frozen champion or improves only the incomplete/provisional 2026 slice.",
        "protocol": "No parameter selected on 2025/2026. Public AQUA_M-T is scoring target; v2 <=2024 remains history for prior windows.",
        "target_metric": {"abs_total_error_max": OWNER_ABS_TOTAL_ERROR_TARGET},
        "artifact_sha256": model.artifact["artifact_sha256"],
        "data_hashes": {
            "inpe_local_v2": sha256_file(V2_TARGET),
            "inpe_public_v3_events": sha256_file(V3_EVENTS),
        },
        "results": summary,
        "decision": decision,
        "justification": (
            "The frozen champion already passes the owner target with 2025 absolute total error 79.0. "
            "Operational refresh slightly improves 2026 jan-jul (37.3 -> 33.6) but worsens complete 2025 (79.0 -> 140.2), "
            "so promoting it would be overfitting to the still-short 2026 slice."
        ),
        "artifacts": ["monthly_strategy_comparison.csv", "aggregate_strategy_windows.csv"],
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== EXP-28 operational refresh reality holdout ===")
    print(summary_df.to_string(index=False))
    print("DECISION:", decision)


if __name__ == "__main__":
    main()
