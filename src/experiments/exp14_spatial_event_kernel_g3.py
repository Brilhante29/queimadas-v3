"""Modulo publico do FireCast para experimentos reprodutiveis, auditorias de erro e validacao temporal.

Arquivo `src/experiments/exp14_spatial_event_kernel_g3.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.experiments.backtest_real_baselines import (  # noqa: E402
    MIN_TRAIN_MONTHS,
    build_features,
    load_merged_target,
)
from src.utils.metrics import wape  # noqa: E402

OUT_DIR = PROJECT_ROOT / "outputs" / "exp14_spatial_event_kernel_g3"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
EVENTS_CSV = PROJECT_ROOT / "data" / "snapshots" / "inpe_event_points_v1" / "events.csv"
EVENT_MANIFEST = PROJECT_ROOT / "data" / "snapshots" / "inpe_event_points_v1" / "manifest.json"
CENTROIDS_CSV = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi_attributes.csv"
CHAPADA_WEIGHTS = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_chapada_v1" / "era5_cell_weights.csv"
EXP10_PREDICTIONS = PROJECT_ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions.csv"
CONFIG_PATH = PROJECT_ROOT / "configs" / "config.yaml"

TEST_MONTHS = [pd.Period(f"{y}-{m:02d}", freq="M") for y in range(2015, 2025) for m in range(1, 13)]
CRITICAL_MONTHS = {10, 11}
DRY_MONTHS = {8, 9, 10, 11, 12}
G3_CE_LIMIT = 0.20
G3_CHAPADA_LIMIT = 0.25
WINDOW_GRID = [1, 3, 6, 12]
DISTANCE_GRID_KM = [25.0, 50.0, 100.0]
LAMBDA_GRID = [0.10, 0.25, 0.50, 0.75]
EVENT_WEIGHT_MODES = ["count", "frp", "frp_risk"]
EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class KernelConfig:
    """Representa `KernelConfig` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/experiments/exp14_spatial_event_kernel_g3.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    window_months: int
    distance_km: float
    lambda_weight: float
    event_weight_mode: str

    @property
    def model_name(self) -> str:
        """Executa a etapa `model name` do fluxo FireCast.
        
        A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        d = int(self.distance_km)
        lam = str(self.lambda_weight).replace(".", "p")
        return f"stk_{self.event_weight_mode}_w{self.window_months}_d{d}_l{lam}"


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def period_ordinal(period: pd.Period) -> int:
    """Executa a etapa `period ordinal` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return int(period.year * 12 + period.month)


def haversine_matrix(lat_a: np.ndarray, lon_a: np.ndarray, lat_b: np.ndarray, lon_b: np.ndarray) -> np.ndarray:
    """Executa a etapa `haversine matrix` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    lat1 = np.deg2rad(lat_a)[:, None]
    lon1 = np.deg2rad(lon_a)[:, None]
    lat2 = np.deg2rad(lat_b)[None, :]
    lon2 = np.deg2rad(lon_b)[None, :]
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def normalized_share(values: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """Executa a etapa `normalized share` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    values = np.maximum(np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0), 0.0)
    total = float(values.sum())
    if total > 1e-12:
        return values / total
    fallback = np.maximum(np.nan_to_num(fallback, nan=0.0, posinf=0.0, neginf=0.0), 0.0)
    fallback_total = float(fallback.sum())
    if fallback_total > 1e-12:
        return fallback / fallback_total
    return np.ones(len(values), dtype=float) / max(len(values), 1)


def event_strength(prior: pd.DataFrame, mode: str) -> np.ndarray:
    """Executa a etapa `event strength` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    strength = np.ones(len(prior), dtype=float)
    if mode in {"frp", "frp_risk"}:
        log_frp = np.log1p(np.maximum(prior["frp"].fillna(0.0).to_numpy(dtype=float), 0.0))
        positives = log_frp[log_frp > 0]
        scale = float(np.median(positives)) if len(positives) else 1.0
        if scale <= 0:
            scale = 1.0
        strength *= np.clip(1.0 + log_frp / scale, 1.0, 6.0)
    if mode == "frp_risk":
        risk = np.clip(prior["fire_risk"].fillna(0.0).to_numpy(dtype=float), 0.0, 1.0)
        strength *= np.clip(0.5 + risk, 0.5, 1.5)
    return strength


def load_chapada_geocodes() -> set[int]:
    """Carrega a etapa `load chapada geocodes` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    weights = pd.read_csv(CHAPADA_WEIGHTS)
    return set(weights["geocodigo"].astype(int).unique().tolist())


def load_centroids() -> pd.DataFrame:
    """Carrega a etapa `load centroids` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    centroids = pd.read_csv(CENTROIDS_CSV)
    cols = ["geocodigo", "centroid_lat", "centroid_lon"]
    centroids = centroids[cols].copy()
    centroids["geocodigo"] = centroids["geocodigo"].astype(int)
    return centroids


def load_canonical_events(target: pd.DataFrame) -> pd.DataFrame:
    """Carrega a etapa `load canonical events` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    cols = [
        "geocodigo",
        "ano",
        "mes",
        "lat",
        "lon",
        "frp",
        "fire_risk",
        "source_name",
    ]
    events = pd.read_csv(EVENTS_CSV, usecols=cols)
    events = events.dropna(subset=["geocodigo", "ano", "mes", "lat", "lon"])
    events["geocodigo"] = events["geocodigo"].astype(int)
    events["ano"] = events["ano"].astype(int)
    events["mes"] = events["mes"].astype(int)

    source_map = target[["geocodigo", "ano", "mes", "target_source"]].drop_duplicates().copy()
    source_map["geocodigo"] = source_map["geocodigo"].astype(int)
    source_map["ano"] = source_map["ano"].astype(int)
    source_map["mes"] = source_map["mes"].astype(int)

    events = events.merge(
        source_map,
        left_on=["geocodigo", "ano", "mes", "source_name"],
        right_on=["geocodigo", "ano", "mes", "target_source"],
        how="inner",
    )
    events["period"] = pd.PeriodIndex(
        pd.to_datetime(events["ano"].astype(str) + "-" + events["mes"].astype(str).str.zfill(2)),
        freq="M",
    )
    events["period_ord"] = events["ano"].astype(int) * 12 + events["mes"].astype(int)
    events["frp"] = events["frp"].fillna(0.0).clip(lower=0.0)
    events["fire_risk"] = events["fire_risk"].fillna(0.0).clip(lower=0.0, upper=1.0)
    return events


def kernel_scores(test: pd.DataFrame, prior: pd.DataFrame, cut_ord: int, cfg: KernelConfig) -> np.ndarray:
    """Executa a etapa `kernel scores` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if prior.empty:
        return np.zeros(len(test), dtype=float)
    distances = haversine_matrix(
        test["centroid_lat"].to_numpy(dtype=float),
        test["centroid_lon"].to_numpy(dtype=float),
        prior["lat"].to_numpy(dtype=float),
        prior["lon"].to_numpy(dtype=float),
    )
    ages = np.maximum(cut_ord - prior["period_ord"].to_numpy(dtype=float), 1.0)
    tau = max(float(cfg.window_months) / 2.0, 1.0)
    temporal = np.exp(-(ages - 1.0) / tau)
    spatial = np.exp(-distances / cfg.distance_km)
    weighted_events = event_strength(prior, cfg.event_weight_mode) * temporal
    return spatial @ weighted_events


def normalize_predictions(df: pd.DataFrame, model: str, family: str, note: str) -> pd.DataFrame:
    """Executa a etapa `normalize predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out = df[["geocodigo", "municipio_ibge", "uf", "ano", "mes", "fire_count", "y_pred"]].copy()
    out["cut"] = out["ano"].astype(str) + "-" + out["mes"].astype(str).str.zfill(2)
    out["model"] = model
    out["family"] = family
    out["note"] = note
    out["y_pred"] = np.maximum(out["y_pred"].astype(float), 0.0)
    return out


def build_predictions(df: pd.DataFrame, events: pd.DataFrame, centroids: pd.DataFrame) -> pd.DataFrame:
    """Constroi a etapa `build predictions` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    configs = [
        KernelConfig(window, distance, lam, mode)
        for mode in EVENT_WEIGHT_MODES
        for window in WINDOW_GRID
        for distance in DISTANCE_GRID_KM
        for lam in LAMBDA_GRID
    ]
    blocks: dict[str, list[pd.DataFrame]] = {cfg.model_name: [] for cfg in configs}
    cfg_by_name = {cfg.model_name: cfg for cfg in configs}
    champion_blocks: list[pd.DataFrame] = []

    exp10 = pd.read_csv(EXP10_PREDICTIONS)
    exp10 = exp10[exp10["model"] == "climatology_regional_intensity12"].copy()

    for cut in TEST_MONTHS:
        train = df[(df["period"] < cut) & df["fire_count"].notna() & df["fire_count_lag12"].notna()].copy()
        test = df[(df["period"] == cut) & df["fire_count"].notna()].copy()
        hist = train.groupby("geocodigo")["fire_count"].count()
        eligible = hist[hist >= MIN_TRAIN_MONTHS].index
        train = train[train["fire_count_lag12"].notna()].copy()
        test = test[test["geocodigo"].isin(eligible) & test["fire_count_lag12"].notna()].copy()
        if len(train) == 0 or len(test) == 0:
            continue

        test = test.merge(centroids, on="geocodigo", how="left")
        if test[["centroid_lat", "centroid_lon"]].isna().any().any():
            missing = sorted(test.loc[test["centroid_lat"].isna() | test["centroid_lon"].isna(), "geocodigo"].astype(int).unique().tolist())
            raise RuntimeError(f"Missing centroid for {cut}: {missing}")

        exp10_cut = exp10[(exp10["ano"] == cut.year) & (exp10["mes"] == cut.month)][["geocodigo", "y_pred"]]
        test_with_base = test.merge(exp10_cut, on="geocodigo", how="left", suffixes=("", "_exp10"))
        if test_with_base["y_pred"].isna().any():
            missing = sorted(test_with_base.loc[test_with_base["y_pred"].isna(), "geocodigo"].astype(int).unique().tolist())
            raise RuntimeError(f"EXP-10 prediction coverage gap for {cut}: {missing}")
        base_pred = np.maximum(test_with_base["y_pred"].to_numpy(dtype=float), 0.0)
        base_share = normalized_share(base_pred, np.ones(len(base_pred), dtype=float))
        total = float(base_pred.sum())

        champ = test.copy()
        champ["y_pred"] = base_pred
        champion_blocks.append(champ)

        cut_ord = period_ordinal(cut)
        for cfg in configs:
            start_ord = cut_ord - cfg.window_months
            prior = events[(events["period_ord"] >= start_ord) & (events["period_ord"] < cut_ord)]
            scores = kernel_scores(test, prior, cut_ord, cfg)
            kernel_share = normalized_share(scores, base_pred)
            pred = total * ((1.0 - cfg.lambda_weight) * base_share + cfg.lambda_weight * kernel_share)
            out = test.copy()
            out["y_pred"] = pred
            blocks[cfg.model_name].append(out)

    rows = [
        normalize_predictions(
            pd.concat(champion_blocks, ignore_index=True),
            model="climatology_regional_intensity12",
            family="champion",
            note="Current EXP-10 regional-intensity champion.",
        )
    ]
    for model_name, model_blocks in blocks.items():
        cfg = cfg_by_name[model_name]
        rows.append(
            normalize_predictions(
                pd.concat(model_blocks, ignore_index=True),
                model=model_name,
                family="spatial_event_kernel",
                note=(
                    "EXP-10 total-preserving spatial kernel from strictly prior INPE point events; "
                    f"mode={cfg.event_weight_mode}, window={cfg.window_months}, "
                    f"distance_km={cfg.distance_km:g}, lambda={cfg.lambda_weight:g}."
                ),
            )
        )
    return pd.concat(rows, ignore_index=True)


def wape_frame(frame: pd.DataFrame) -> float:
    """Executa a etapa `wape frame` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if frame.empty or float(frame["fire_count"].sum()) == 0.0:
        return float("nan")
    return float(wape(frame["fire_count"].to_numpy(dtype=float), frame["y_pred"].to_numpy(dtype=float)))


def metric_block(p: pd.DataFrame, chapada_geocodes: set[int]) -> dict[str, object]:
    """Executa a etapa `metric block` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    critical = p[p["mes"].isin(CRITICAL_MONTHS)]
    dry = p[p["mes"].isin(DRY_MONTHS)]
    selection = critical[critical["ano"].between(2015, 2022)]
    gate = critical[critical["ano"].between(2023, 2024)]
    gate_all_months = p[p["ano"].between(2023, 2024)]

    selection_ce = selection[selection["uf"] == "CE"]
    gate_ce = gate[gate["uf"] == "CE"]
    selection_chapada = selection[selection["geocodigo"].astype(int).isin(chapada_geocodes)]
    gate_chapada = gate[gate["geocodigo"].astype(int).isin(chapada_geocodes)]

    gate_ce_wape = wape_frame(gate_ce)
    gate_chapada_wape = wape_frame(gate_chapada)
    return {
        "extended_wape_all": wape_frame(p),
        "extended_wape_critical": wape_frame(critical),
        "extended_wape_dry": wape_frame(dry),
        "selection_2015_2022_wape_critical_all": wape_frame(selection),
        "selection_2015_2022_wape_critical_ceara": wape_frame(selection_ce),
        "selection_2015_2022_wape_critical_chapada_cariri": wape_frame(selection_chapada),
        "gate_2023_2024_wape_critical_all": wape_frame(gate),
        "gate_2023_2024_wape_critical_ceara": gate_ce_wape,
        "gate_2023_2024_wape_critical_chapada_cariri": gate_chapada_wape,
        "gate_2023_2024_wape_all_months": wape_frame(gate_all_months),
        "gate_critical_n_all": int(len(gate)),
        "gate_critical_y_total_all": float(gate["fire_count"].sum()),
        "gate_critical_n_ceara": int(len(gate_ce)),
        "gate_critical_y_total_ceara": float(gate_ce["fire_count"].sum()),
        "gate_critical_n_chapada_cariri": int(len(gate_chapada)),
        "gate_critical_y_total_chapada_cariri": float(gate_chapada["fire_count"].sum()),
        "passes_g3_ceara": bool(gate_ce_wape <= G3_CE_LIMIT) if np.isfinite(gate_ce_wape) else False,
        "passes_g3_chapada_cariri": bool(gate_chapada_wape <= G3_CHAPADA_LIMIT) if np.isfinite(gate_chapada_wape) else False,
    }


def summarize(preds: pd.DataFrame, chapada_geocodes: set[int]) -> pd.DataFrame:
    """Executa a etapa `summarize` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for (model, family), group in preds.groupby(["model", "family"], sort=False):
        row = {"model": model, "family": family, "note": group["note"].iloc[0]}
        row.update(metric_block(group, chapada_geocodes))
        rows.append(row)
    summary = pd.DataFrame(rows)
    return summary.sort_values(
        [
            "selection_2015_2022_wape_critical_ceara",
            "selection_2015_2022_wape_critical_chapada_cariri",
            "gate_2023_2024_wape_critical_ceara",
        ],
        na_position="last",
    ).reset_index(drop=True)


def write_frontier_report(summary: pd.DataFrame, report: dict[str, object]) -> None:
    """Grava a etapa `write frontier report` do fluxo FireCast.
    
    A funcao faz parte de `src/experiments/exp14_spatial_event_kernel_g3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    selected = report["selected_by_2015_2022"]
    best_ce = summary.sort_values("gate_2023_2024_wape_critical_ceara").iloc[0]
    best_chapada = summary.sort_values("gate_2023_2024_wape_critical_chapada_cariri").iloc[0]
    lines = [
        "# EXP-14 Spatial Event Kernel G3 Report",
        "",
        "## Hypothesis",
        "A total-preserving spatio-temporal kernel over strictly prior INPE point events can improve municipal allocation without target-month leakage.",
        "",
        "## Literature Position",
        "The test follows the same direction as current wildfire literature: spatial context and larger receptive fields (FireCastNet, https://arxiv.org/abs/2502.01550), partial-observability robustness (https://arxiv.org/abs/2603.09042), and calibrated operational uncertainty (https://arxiv.org/abs/2603.22331). The local novelty is an auditable municipal allocator from event points under an as-of protocol rather than a free regressor.",
        "",
        "## Protocol",
        "- Walk-forward 2015-2024, horizon 1 month.",
        "- Hyperparameters selected on 2015-2022 critical months only.",
        "- Frozen gate: 2023-2024 critical months.",
        "- 2025+ untouched.",
        "- EXP-10 regional total preserved for every cut.",
        "",
        "## Result",
        f"Selected by 2015-2022: {selected['model']}.",
        f"Selected frozen Ceara critical WAPE: {selected['gate_2023_2024_wape_critical_ceara']:.4f} (limit {G3_CE_LIMIT:.2f}).",
        f"Selected frozen Chapada critical WAPE: {selected['gate_2023_2024_wape_critical_chapada_cariri']:.4f} (limit {G3_CHAPADA_LIMIT:.2f}).",
        f"Best frozen Ceara model by audit only: {best_ce['model']} = {best_ce['gate_2023_2024_wape_critical_ceara']:.4f}.",
        f"Best frozen Chapada model by audit only: {best_chapada['model']} = {best_chapada['gate_2023_2024_wape_critical_chapada_cariri']:.4f}.",
        "",
        "## Decision",
        str(report["decision"]),
        "",
        "## Promotion Guard",
        "A model is not promoted if it improves only the frozen window but loses the predeclared selection window. That pattern is treated as selection leakage risk.",
    ]
    (OUT_DIR / "frontier_kernel_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/experiments/exp14_spatial_event_kernel_g3.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df, gaps = load_merged_target()
    df = build_features(df)
    events = load_canonical_events(df)
    centroids = load_centroids()
    chapada_geocodes = load_chapada_geocodes()

    preds = build_predictions(df, events, centroids)
    summary = summarize(preds, chapada_geocodes)
    selected = summary.iloc[0]
    best_gate_ce = summary.sort_values("gate_2023_2024_wape_critical_ceara").iloc[0]
    best_gate_chapada = summary.sort_values("gate_2023_2024_wape_critical_chapada_cariri").iloc[0]

    preds.to_csv(OUT_DIR / "predictions.csv", index=False)
    summary.to_csv(OUT_DIR / "summary.csv", index=False)

    decision = "G3_PASS" if bool(selected["passes_g3_ceara"] or selected["passes_g3_chapada_cariri"]) else "G3_FAIL"
    report = {
        "experiment_id": "EXP-2026-07-09-14",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "A total-preserving spatio-temporal kernel over lagged INPE point events improves municipal allocation without current-month leakage.",
        "protocol": "walk-forward 2015-2024; selection on 2015-2022 critical months; frozen gate on 2023-2024 critical months; 2025+ untouched",
        "target_snapshot_sha256": sha256_file(TARGET_SNAPSHOT),
        "event_snapshot_manifest_sha256": sha256_file(EVENT_MANIFEST),
        "events_sha256": sha256_file(EVENTS_CSV),
        "centroids_sha256": sha256_file(CENTROIDS_CSV),
        "chapada_weights_sha256": sha256_file(CHAPADA_WEIGHTS),
        "exp10_predictions_sha256": sha256_file(EXP10_PREDICTIONS),
        "config_sha256": sha256_file(CONFIG_PATH),
        "g3_limits": {"ceara": G3_CE_LIMIT, "chapada_cariri": G3_CHAPADA_LIMIT},
        "grid": {
            "window_months": WINDOW_GRID,
            "distance_km": DISTANCE_GRID_KM,
            "lambda_weight": LAMBDA_GRID,
            "event_weight_modes": EVENT_WEIGHT_MODES,
        },
        "selection_metric": "selection_2015_2022_wape_critical_ceara, tie-broken by chapada_cariri",
        "series_gaps_reindexed": [{"geocodigo": int(g), "missing_months": int(n)} for g, n in gaps],
        "canonical_event_rows": int(len(events)),
        "chapada_municipalities": int(len(chapada_geocodes)),
        "selected_by_2015_2022": selected.to_dict(),
        "best_gate_2023_2024_ceara_audit_only": best_gate_ce.to_dict(),
        "best_gate_2023_2024_chapada_audit_only": best_gate_chapada.to_dict(),
        "decision": decision,
        "artifacts": ["summary.csv", "predictions.csv", "frontier_kernel_report.md"],
    }
    (OUT_DIR / "run_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_frontier_report(summary, report)

    cols = [
        "model",
        "family",
        "selection_2015_2022_wape_critical_ceara",
        "selection_2015_2022_wape_critical_chapada_cariri",
        "gate_2023_2024_wape_critical_ceara",
        "gate_2023_2024_wape_critical_chapada_cariri",
        "passes_g3_ceara",
        "passes_g3_chapada_cariri",
    ]
    print("=== EXP-14 spatial event kernel ===")
    print(summary[cols].head(20).to_string(index=False))
    print(f"SELECTED_BY_SELECTION: {selected['model']}")
    print(f"BEST_GATE_CEARA_AUDIT_ONLY: {best_gate_ce['model']} {best_gate_ce['gate_2023_2024_wape_critical_ceara']:.4f}")
    print(f"BEST_GATE_CHAPADA_AUDIT_ONLY: {best_gate_chapada['model']} {best_gate_chapada['gate_2023_2024_wape_critical_chapada_cariri']:.4f}")
    print(f"DECISION: {decision}")


if __name__ == "__main__":
    main()
