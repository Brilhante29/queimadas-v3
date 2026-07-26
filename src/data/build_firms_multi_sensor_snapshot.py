"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/build_firms_multi_sensor_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "firms_multi_sensor_ce_v1"
INPUTS = [
    PROJECT_ROOT / "data" / "snapshots" / "firms_modis_sp_ce_v1",
    PROJECT_ROOT / "data" / "snapshots" / "firms_viirs_snpp_sp_ce_v1",
    PROJECT_ROOT / "data" / "snapshots" / "firms_viirs_noaa20_sp_ce_v1",
]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_firms_multi_sensor_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def weighted_mean(df: pd.DataFrame, value: str, weight: str = "firms_fire_count") -> float:
    """Executa a etapa `weighted mean` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_firms_multi_sensor_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    vals = pd.to_numeric(df[value], errors="coerce")
    weights = pd.to_numeric(df[weight], errors="coerce").fillna(0.0)
    mask = vals.notna() & (weights > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(vals[mask], weights=weights[mask]))


def combine() -> tuple[pd.DataFrame, dict[str, object]]:
    """Executa a etapa `combine` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_firms_multi_sensor_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    frames = []
    input_meta = []
    for path in INPUTS:
        monthly_path = path / "monthly_firms_features.csv"
        manifest_path = path / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        df = pd.read_csv(monthly_path)
        df["input_snapshot"] = path.name
        frames.append(df)
        input_meta.append(
            {
                "snapshot": path.name,
                "source": manifest.get("source"),
                "period_start": manifest.get("period_start"),
                "period_end": manifest.get("period_end"),
                "monthly_sha256": sha256_file(monthly_path),
                "manifest_sha256": sha256_file(manifest_path),
                "rows": int(len(df)),
            }
        )
    all_monthly = pd.concat(frames, ignore_index=True)
    grouped = []
    for key, g in all_monthly.groupby(["geocodigo", "municipio_ibge", "uf", "ano", "mes"], dropna=False):
        row = dict(zip(["geocodigo", "municipio_ibge", "uf", "ano", "mes"], key))
        row["firms_source"] = "FIRMS_MULTI_SENSOR_SP"
        row["firms_fire_count"] = float(g["firms_fire_count"].sum())
        row["firms_day_count"] = float(g["firms_day_count"].max())
        row["firms_frp_sum"] = float(g["firms_frp_sum"].sum())
        row["firms_frp_mean"] = weighted_mean(g, "firms_frp_mean")
        row["firms_frp_max"] = float(pd.to_numeric(g["firms_frp_max"], errors="coerce").max())
        row["firms_frp_p90"] = float(pd.to_numeric(g["firms_frp_p90"], errors="coerce").max())
        row["firms_confidence_mean"] = weighted_mean(g, "firms_confidence_mean")
        row["firms_confidence_min"] = float(pd.to_numeric(g["firms_confidence_min"], errors="coerce").min())
        row["firms_brightness_mean"] = weighted_mean(g, "firms_brightness_mean")
        row["firms_brightness_max"] = float(pd.to_numeric(g["firms_brightness_max"], errors="coerce").max())
        row["firms_night_share"] = weighted_mean(g, "firms_night_share")
        row["firms_satellites"] = ";".join(sorted(set(";".join(g["firms_satellites"].fillna("").astype(str)).split(";")) - {""}))
        row["firms_input_snapshots"] = ";".join(sorted(g["input_snapshot"].unique()))
        grouped.append(row)
    combined = pd.DataFrame(grouped).sort_values(["geocodigo", "ano", "mes"]).reset_index(drop=True)
    manifest = {
        "snapshot_name": OUT_DIR.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "combined_lagged_geospatial_fire_pressure_features",
        "inputs": input_meta,
        "aggregation_rule": "Monthly municipal FIRMS Standard Processing sources combined by summing counts/FRP and weighted averaging continuous fields; used only as lagged features, never as target.",
        "available_at_rule": "Only lagged combined FIRMS features are valid for prediction cuts; no target-month leakage.",
        "limitations": [
            "multi-sensor detections are not deduplicated across sensors; this snapshot is a pressure/intensity feature, not a target count",
            "NOAA20 starts in 2018, so early years contain MODIS/SNPP only",
        ],
        "rows": int(len(combined)),
        "municipalities": int(combined["geocodigo"].nunique()),
        "coverage_start": f"{int(combined['ano'].min())}-{int(combined['mes'].min()):02d}",
        "coverage_end": f"{int(combined['ano'].max())}-{int(combined['mes'].max()):02d}",
    }
    return combined, manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/build_firms_multi_sensor_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    combined, manifest = combine()
    out = OUT_DIR / "monthly_firms_features.csv"
    combined.to_csv(out, index=False)
    manifest["outputs"] = {"monthly_firms_features.csv": {"sha256": sha256_file(out), "rows": int(len(combined))}}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"snapshot": str(OUT_DIR.relative_to(PROJECT_ROOT)), "rows": len(combined), "municipalities": combined.geocodigo.nunique()}, indent=2))


if __name__ == "__main__":
    main()

