"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/build_inpe_event_points_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "inpe_event_points_v1"

SOURCES = [
    {
        "zip_path": WORKSPACE_ROOT / "dados_INPE.zip",
        "source_name": "inpe_bdq_aqua_ref",
        "sensor_note": "AQUA_M-T reference export with event timestamp and satellite column.",
    },
    {
        "zip_path": WORKSPACE_ROOT / "dados_INPE_Monitor.zip",
        "source_name": "inpe_bdq_aqua_ref",
        "sensor_note": "AQUA_M-T monitor export, mostly 2025, same schema as dados_INPE.zip.",
    },
    {
        "zip_path": WORKSPACE_ROOT / "dados.zip",
        "source_name": "inpe_bdq_legacy",
        "sensor_note": "Legacy export without satellite column; used only with explicit source flag.",
    },
]

COLUMN_ALIASES = {
    "datetime": ["Data / Hora", "DataHora", "data_hora_gmt", "datahora"],
    "satellite": ["Satélite", "Satelite", "satellite", "satelite"],
    "country": ["País", "Pais", "pais"],
    "state": ["Estado", "estado", "UF", "uf"],
    "municipality": ["Município", "Municipio", "municipio", "MUNICIPIO"],
    "biome": ["Bioma", "bioma"],
    "days_no_rain": ["N. Dias Sem Chuva", "DiaSemChuva", "dias_sem_chuva"],
    "precip_mm": ["Precipitação", "Precipitacao", "precipitacao"],
    "fire_risk": ["Risco Fogo", "RiscoFogo", "risco_fogo"],
    "lat": ["Latitude", "latitude", "lat"],
    "lon": ["Longitude", "longitude", "lon"],
    "frp": ["FRP", "frp"],
}

STATE_MAP = {
    "CEARA": "CE",
    "CEARÁ": "CE",
    "CE": "CE",
    "PERNAMBUCO": "PE",
    "PE": "PE",
    "PIAUI": "PI",
    "PIAUÍ": "PI",
    "PI": "PI",
}


def normalize_name(value: object) -> str:
    """Executa a etapa `normalize name` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\b(ceara|ce|pernambuco|pe|piaui|pi)\b$", "", text).strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def pick_col(df: pd.DataFrame, role: str) -> str | None:
    """Executa a etapa `pick col` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    by_lower = {str(c).lower(): c for c in df.columns}
    for candidate in COLUMN_ALIASES[role]:
        if candidate in df.columns:
            return candidate
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def parse_datetime(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Executa a etapa `parse datetime` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    raw = series.astype(str)
    is_legacy_date = raw.str.match(r"^\d{1,2}/\d{1,2}/\d{4}$", na=False)
    parsed_iso = pd.to_datetime(raw.where(~is_legacy_date), errors="coerce", utc=True)
    local_iso = parsed_iso.dt.tz_convert("Etc/GMT+3").dt.tz_localize(None)
    parsed_legacy = pd.to_datetime(raw.where(is_legacy_date), errors="coerce", dayfirst=True)
    local = local_iso.fillna(parsed_legacy)
    utc = parsed_iso.astype("datetime64[ns, UTC]").astype(str).replace("NaT", "")
    return utc, local


def load_name_map() -> dict[tuple[str, str], dict[str, object]]:
    """Carrega a etapa `load name map` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    refs = json.loads((PROJECT_ROOT / "data" / "reference" / "ibge_municipios_CE_PE_PI.json").read_text(encoding="utf-8-sig"))
    out = {}
    for row in refs:
        uf = str(row.get("uf", "")).upper()
        norm = normalize_name(row.get("municipio_ibge", row.get("nome", "")))
        out[(norm, uf)] = row
    return out


def read_csv_from_zip(zf: zipfile.ZipFile, member: str) -> pd.DataFrame:
    """Carrega a etapa `read csv from zip` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    with zf.open(member) as handle:
        try:
            return pd.read_csv(handle, encoding="utf-8-sig", low_memory=False)
        except UnicodeDecodeError:
            handle.seek(0)
            return pd.read_csv(handle, encoding="latin1", low_memory=False)


def member_municipality(member: str) -> str:
    """Executa a etapa `member municipality` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    parts = Path(member).parts
    if len(parts) >= 2:
        return parts[-2]
    return Path(member).stem.rsplit("_", 2)[0]


def normalize_events() -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Executa a etapa `normalize events` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    name_map = load_name_map()
    frames = []
    source_reports = []

    for source in SOURCES:
        zip_path = source["zip_path"]
        if not zip_path.exists():
            source_reports.append({"zip": str(zip_path), "exists": False, "rows": 0})
            continue
        rows_before = 0
        frames_before = len(frames)
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
            for member in members:
                df = read_csv_from_zip(zf, member)
                rows_before += len(df)
                if len(df) == 0:
                    continue

                cols = {role: pick_col(df, role) for role in COLUMN_ALIASES}
                if not cols["datetime"] or not cols["lat"] or not cols["lon"]:
                    continue

                municipio_raw = df[cols["municipality"]] if cols["municipality"] else pd.Series(member_municipality(member), index=df.index)
                state_raw = df[cols["state"]] if cols["state"] else pd.Series("CE", index=df.index)
                uf = state_raw.astype(str).str.upper().map(lambda v: STATE_MAP.get(v, STATE_MAP.get(normalize_name(v).upper(), v[:2])))
                norm = municipio_raw.map(normalize_name)
                mapped = [name_map.get((n, u), {}) for n, u in zip(norm, uf)]

                event_utc, event_local = parse_datetime(df[cols["datetime"]])
                out = pd.DataFrame(
                    {
                        "geocodigo": [m.get("geocodigo") for m in mapped],
                        "municipio_ibge": [m.get("municipio_ibge", m.get("nome")) for m in mapped],
                        "uf": uf,
                        "municipio_source": municipio_raw.astype(str),
                        "municipio_norm": norm,
                        "event_time_utc": event_utc,
                        "event_time_local": event_local,
                        "ano": event_local.dt.year,
                        "mes": event_local.dt.month,
                        "dia": event_local.dt.day,
                        "satellite": df[cols["satellite"]].astype(str) if cols["satellite"] else "UNKNOWN",
                        "biome": df[cols["biome"]].astype(str) if cols["biome"] else "",
                        "days_no_rain": pd.to_numeric(df[cols["days_no_rain"]], errors="coerce") if cols["days_no_rain"] else np.nan,
                        "precip_mm": pd.to_numeric(df[cols["precip_mm"]], errors="coerce") if cols["precip_mm"] else np.nan,
                        "fire_risk": pd.to_numeric(df[cols["fire_risk"]], errors="coerce") if cols["fire_risk"] else np.nan,
                        "lat": pd.to_numeric(df[cols["lat"]], errors="coerce"),
                        "lon": pd.to_numeric(df[cols["lon"]], errors="coerce"),
                        "frp": pd.to_numeric(df[cols["frp"]], errors="coerce") if cols["frp"] else np.nan,
                        "source_name": source["source_name"],
                        "source_zip": zip_path.name,
                        "source_member": member,
                    }
                )
                out = out[out["geocodigo"].notna() & out["event_time_local"].notna() & out["ano"].notna() & out["mes"].notna() & out["lat"].notna() & out["lon"].notna()].copy()
                frames.append(out)
        source_reports.append(
            {
                "zip": zip_path.name,
                "sha256": sha256_file(zip_path),
                "source_name": source["source_name"],
                "sensor_note": source["sensor_note"],
                "members": len(members) if zip_path.exists() else 0,
                "rows_raw": int(rows_before),
                "frames_loaded": len(frames) - frames_before,
            }
        )

    if not frames:
        raise RuntimeError("No INPE point events could be read from local ZIPs")

    events = pd.concat(frames, ignore_index=True)
    before = len(events)
    events["lat_round5"] = events["lat"].round(5)
    events["lon_round5"] = events["lon"].round(5)
    events = events.drop_duplicates(
        subset=["event_time_local", "lat_round5", "lon_round5", "satellite", "source_name", "geocodigo"]
    ).drop(columns=["lat_round5", "lon_round5"])
    events = events.sort_values(["source_name", "geocodigo", "event_time_local", "lat", "lon"]).reset_index(drop=True)
    source_reports.append({"deduplication": {"rows_before": int(before), "rows_after": int(len(events)), "removed": int(before - len(events))}})
    return events, source_reports


def aggregate_monthly(events: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `aggregate monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    def p90(x: pd.Series) -> float:
        """Executa a etapa `p90` do fluxo FireCast.
        
        A funcao faz parte de `src/data/build_inpe_event_points_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        return float(x.dropna().quantile(0.90)) if x.notna().any() else np.nan

    grouped = (
        events.groupby(["geocodigo", "municipio_ibge", "uf", "ano", "mes", "source_name"], dropna=False)
        .agg(
            event_fire_count=("frp", "size"),
            event_day_count=("dia", "nunique"),
            event_frp_sum=("frp", "sum"),
            event_frp_mean=("frp", "mean"),
            event_frp_max=("frp", "max"),
            event_frp_p90=("frp", p90),
            event_fire_risk_mean=("fire_risk", "mean"),
            event_fire_risk_max=("fire_risk", "max"),
            event_days_no_rain_mean=("days_no_rain", "mean"),
            event_days_no_rain_max=("days_no_rain", "max"),
            event_precip_mm_mean=("precip_mm", "mean"),
            event_lat_mean=("lat", "mean"),
            event_lon_mean=("lon", "mean"),
            event_lat_std=("lat", "std"),
            event_lon_std=("lon", "std"),
        )
        .reset_index()
    )
    grouped["event_lat_std"] = grouped["event_lat_std"].fillna(0.0)
    grouped["event_lon_std"] = grouped["event_lon_std"].fillna(0.0)
    return grouped.sort_values(["source_name", "geocodigo", "ano", "mes"]).reset_index(drop=True)


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/build_inpe_event_points_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events, source_reports = normalize_events()
    monthly = aggregate_monthly(events)

    events_path = OUT_DIR / "events.csv"
    monthly_path = OUT_DIR / "monthly_event_features.csv"
    events.to_csv(events_path, index=False)
    monthly.to_csv(monthly_path, index=False)

    manifest = {
        "snapshot_name": "inpe_event_points_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "target_auxiliary_geospatial_features",
        "official_url": "https://data.inpe.br/queimadas/portal/dados-abertos/",
        "license": "dados abertos INPE",
        "source_zips": source_reports,
        "available_at_rule": "same as inpe_local_v2: exports limited by source export timestamp; experiments must use only lagged event-derived features for prediction cuts",
        "timezone_rule": "ISO timestamps converted from UTC to America/Fortaleza equivalent UTC-3 for month assignment; legacy date-only rows treated as local date",
        "deduplication_rule": "drop duplicate event_time_local, rounded lat/lon, satellite, source_name, geocodigo",
        "rows_events": int(len(events)),
        "rows_monthly_features": int(len(monthly)),
        "municipalities": int(events["geocodigo"].nunique()),
        "coverage_start": f"{int(events['ano'].min())}-{int(events['mes'].min()):02d}",
        "coverage_end": f"{int(events['ano'].max())}-{int(events['mes'].max()):02d}",
        "outputs": {
            "events.csv": {"sha256": sha256_file(events_path), "rows": int(len(events))},
            "monthly_event_features.csv": {"sha256": sha256_file(monthly_path), "rows": int(len(monthly))},
        },
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== INPE event points snapshot ===")
    print(f"events={len(events)} monthly_features={len(monthly)} municipalities={events['geocodigo'].nunique()}")
    print(f"output={OUT_DIR}")


if __name__ == "__main__":
    main()



