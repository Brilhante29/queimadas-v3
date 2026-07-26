"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_firms_modis_sp_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point, shape
from shapely.prepared import prep

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
IBGE_GEOJSON = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi.geojson"
API_ROOT = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
OFFICIAL_API_DOC = "https://firms.modaps.eosdis.nasa.gov/api/area/"
MAP_KEY_PAGE = "https://firms.modaps.eosdis.nasa.gov/api/map_key/"
DEFAULT_SOURCE = "MODIS_SP"
DEFAULT_START = "2014-01-01"
DEFAULT_END = "2024-12-31"
DEFAULT_DAY_RANGE = 5
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "firms_modis_sp_ce_v1"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "cache" / "firms_modis_sp_ce_v1"


@dataclass(frozen=True)
class MunicipalGeometry:
    """Representa `MunicipalGeometry` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/data/ingest_firms_modis_sp_snapshot.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    geocodigo: int
    municipio_ibge: str
    uf: str
    bounds: tuple[float, float, float, float]
    geom: object
    prepared: object


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(value: str) -> date:
    """Executa a etapa `parse date` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def iter_windows(start: date, end: date, max_days: int) -> Iterable[tuple[date, int]]:
    """Executa a etapa `iter windows` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    cur = start
    while cur <= end:
        days = min(max_days, (end - cur).days + 1)
        yield cur, days
        cur = cur + timedelta(days=days)


def load_target_geometries() -> list[MunicipalGeometry]:
    """Carrega a etapa `load target geometries` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    target_geos = set(pd.read_csv(TARGET)["geocodigo"].astype(int).unique().tolist())
    geojson = json.loads(IBGE_GEOJSON.read_text(encoding="utf-8"))
    out: list[MunicipalGeometry] = []
    for feature in geojson["features"]:
        props = feature["properties"]
        geocodigo = int(props["geocodigo"])
        if geocodigo not in target_geos:
            continue
        geom = shape(feature["geometry"])
        out.append(
            MunicipalGeometry(
                geocodigo=geocodigo,
                municipio_ibge=str(props["municipio_ibge"]),
                uf=str(props["uf"]),
                bounds=tuple(float(x) for x in geom.bounds),
                geom=geom,
                prepared=prep(geom),
            )
        )
    if len(out) != len(target_geos):
        found = {g.geocodigo for g in out}
        missing = sorted(target_geos - found)
        raise RuntimeError(f"Missing IBGE geometries for target municipalities: {missing}")
    return out


def bbox_for_geometries(geoms: list[MunicipalGeometry], buffer_deg: float = 0.05) -> tuple[float, float, float, float]:
    """Executa a etapa `bbox for geometries` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    west = min(g.bounds[0] for g in geoms) - buffer_deg
    south = min(g.bounds[1] for g in geoms) - buffer_deg
    east = max(g.bounds[2] for g in geoms) + buffer_deg
    north = max(g.bounds[3] for g in geoms) + buffer_deg
    return west, south, east, north


def fetch_window(
    session: requests.Session,
    api_key: str,
    source: str,
    bbox: tuple[float, float, float, float],
    start: date,
    day_range: int,
    timeout: int,
    max_attempts: int,
) -> str:
    """Executa a etapa `fetch window` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    bbox_str = ",".join(f"{x:.6f}" for x in bbox)
    url = f"{API_ROOT}/{api_key}/{source}/{bbox_str}/{day_range}/{start.isoformat()}"
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.text
            last_error = f"status={resp.status_code} body={resp.text[:200]!r}"
            if resp.status_code in {429, 500, 502, 503, 504}:
                time.sleep(min(60, 2 ** attempt))
                continue
            raise RuntimeError(f"FIRMS request failed for {start}: {last_error}")
        except requests.RequestException as exc:
            last_error = repr(exc)
            time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"FIRMS request failed after {max_attempts} attempts for {start}: {last_error}")


def parse_firms_csv(text: str, source: str, query_start: date, day_range: int) -> pd.DataFrame:
    """Executa a etapa `parse firms csv` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    stripped = text.strip()
    if not stripped:
        return pd.DataFrame()
    first = stripped.splitlines()[0].lower()
    if "latitude" not in first or "longitude" not in first:
        # API sometimes returns a short human-readable no-data or error message.
        if len(stripped.splitlines()) <= 2:
            return pd.DataFrame()
        raise RuntimeError(f"Unexpected FIRMS CSV header for {query_start}: {stripped[:200]!r}")
    df = pd.read_csv(StringIO(text))
    if df.empty:
        return df
    df["firms_source"] = source
    df["query_start"] = query_start.isoformat()
    df["query_day_range"] = int(day_range)
    return df


def download_raw_events(
    api_key: str,
    source: str,
    bbox: tuple[float, float, float, float],
    start: date,
    end: date,
    day_range: int,
    cache_dir: Path,
    pause_seconds: float,
    timeout: int,
    max_attempts: int,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Executa a etapa `download raw events` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    requests_log: list[dict[str, object]] = []
    for query_start, days in iter_windows(start, end, day_range):
        cache_file = cache_dir / f"{source}_{query_start.isoformat()}_{days}d.csv"
        if cache_file.exists():
            text = cache_file.read_text(encoding="utf-8")
            from_cache = True
        else:
            text = fetch_window(session, api_key, source, bbox, query_start, days, timeout, max_attempts)
            cache_file.write_text(text, encoding="utf-8")
            from_cache = False
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        df = parse_firms_csv(text, source, query_start, days)
        if not df.empty:
            frames.append(df)
        requests_log.append(
            {
                "query_start": query_start.isoformat(),
                "day_range": int(days),
                "rows": int(len(df)),
                "from_cache": bool(from_cache),
                "cache_file": str(cache_file.resolve().relative_to(PROJECT_ROOT)),
            }
        )
        if len(requests_log) % 100 == 0:
            print(f"FIRMS progress: {len(requests_log)} windows, rows={sum(r['rows'] for r in requests_log)}", flush=True)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return raw, requests_log


def assign_municipalities(raw: pd.DataFrame, geoms: list[MunicipalGeometry]) -> pd.DataFrame:
    """Executa a etapa `assign municipalities` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if raw.empty:
        return raw.copy()
    joined_rows = []
    for row in raw.itertuples(index=False):
        lat = float(getattr(row, "latitude"))
        lon = float(getattr(row, "longitude"))
        pt = Point(lon, lat)
        matched = None
        for geom in geoms:
            minx, miny, maxx, maxy = geom.bounds
            if not (minx <= lon <= maxx and miny <= lat <= maxy):
                continue
            if geom.prepared.covers(pt):
                matched = geom
                break
        out = row._asdict()
        if matched is None:
            out.update({"geocodigo": np.nan, "municipio_ibge": None, "uf": None, "spatial_join_status": "outside_target"})
        else:
            out.update(
                {
                    "geocodigo": int(matched.geocodigo),
                    "municipio_ibge": matched.municipio_ibge,
                    "uf": matched.uf,
                    "spatial_join_status": "matched_ibge_polygon",
                }
            )
        joined_rows.append(out)
    joined = pd.DataFrame(joined_rows)
    return joined


def add_time_columns(events: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `add time columns` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if events.empty:
        return events.copy()
    out = events.copy()
    acq_time = out["acq_time"].astype(str).str.extract(r"(\d+)")[0].fillna("0").str.zfill(4)
    dt_text = out["acq_date"].astype(str) + " " + acq_time.str.slice(0, 2) + ":" + acq_time.str.slice(2, 4)
    event_utc = pd.to_datetime(dt_text, format="%Y-%m-%d %H:%M", utc=True, errors="coerce")
    if event_utc.isna().any():
        bad = out.loc[event_utc.isna(), ["acq_date", "acq_time"]].head().to_dict(orient="records")
        raise RuntimeError(f"Could not parse FIRMS acquisition time: {bad}")
    local = event_utc - pd.Timedelta(hours=3)
    out["event_time_utc"] = event_utc.astype(str)
    out["event_time_local_utc_minus_3"] = local.dt.tz_localize(None).astype(str)
    out["ano"] = local.dt.year.astype(int)
    out["mes"] = local.dt.month.astype(int)
    out["dia"] = local.dt.day.astype(int)
    return out


def clean_and_dedup(joined: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `clean and dedup` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if joined.empty:
        return joined.copy()
    out = add_time_columns(joined)
    for col in ["latitude", "longitude", "brightness", "bright_t31", "bright_ti4", "bright_ti5", "frp"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "confidence" in out.columns:
        raw_conf = out["confidence"]
        mapped = raw_conf.astype(str).str.lower().map({"l": 30.0, "n": 60.0, "h": 90.0})
        numeric = pd.to_numeric(raw_conf, errors="coerce")
        out["confidence_numeric"] = numeric.fillna(mapped)
    else:
        out["confidence_numeric"] = np.nan
    if "brightness" in out.columns:
        out["brightness_proxy"] = out["brightness"]
    elif "bright_ti4" in out.columns:
        out["brightness_proxy"] = out["bright_ti4"]
    else:
        out["brightness_proxy"] = np.nan
    key_cols = ["firms_source", "latitude", "longitude", "acq_date", "acq_time", "satellite", "instrument"]
    before = len(out)
    out = out.drop_duplicates(subset=[c for c in key_cols if c in out.columns]).reset_index(drop=True)
    out.attrs["dedup_removed"] = before - len(out)
    return out


def aggregate_monthly(events: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `aggregate monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    matched = events[events["spatial_join_status"].eq("matched_ibge_polygon")].copy()
    if matched.empty:
        return pd.DataFrame()
    matched["is_night"] = matched.get("daynight", "").astype(str).str.upper().eq("N").astype(float)
    grouped = (
        matched.groupby(["geocodigo", "municipio_ibge", "uf", "ano", "mes", "firms_source"], dropna=False)
        .agg(
            firms_fire_count=("latitude", "size"),
            firms_day_count=("dia", "nunique"),
            firms_frp_sum=("frp", "sum"),
            firms_frp_mean=("frp", "mean"),
            firms_frp_max=("frp", "max"),
            firms_frp_p90=("frp", lambda s: float(np.nanpercentile(s, 90)) if len(s) else np.nan),
            firms_confidence_mean=("confidence_numeric", "mean"),
            firms_confidence_min=("confidence_numeric", "min"),
            firms_brightness_mean=("brightness_proxy", "mean"),
            firms_brightness_max=("brightness_proxy", "max"),
            firms_night_share=("is_night", "mean"),
            firms_satellites=("satellite", lambda s: ";".join(sorted(set(map(str, s.dropna()))))),
        )
        .reset_index()
    )
    grouped["geocodigo"] = grouped["geocodigo"].astype(int)
    grouped["ano"] = grouped["ano"].astype(int)
    grouped["mes"] = grouped["mes"].astype(int)
    return grouped.sort_values(["geocodigo", "ano", "mes", "firms_source"]).reset_index(drop=True)


def write_manifest(
    out_dir: Path,
    source: str,
    start: date,
    end: date,
    bbox: tuple[float, float, float, float],
    day_range: int,
    request_log: list[dict[str, object]],
    raw_events: pd.DataFrame,
    events: pd.DataFrame,
    monthly: pd.DataFrame,
    retrieved_at: str,
) -> None:
    """Grava a etapa `write manifest` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_firms_modis_sp_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    matched = events[events["spatial_join_status"].eq("matched_ibge_polygon")]
    manifest = {
        "snapshot_name": out_dir.name,
        "created_at": retrieved_at,
        "role": "audit_geospatial_fire_points_and_lagged_features",
        "official_api_doc": OFFICIAL_API_DOC,
        "map_key_page": MAP_KEY_PAGE,
        "endpoint_template": f"{API_ROOT}/[MAP_KEY]/[SOURCE]/[WEST,SOUTH,EAST,NORTH]/[DAY_RANGE]/[YYYY-MM-DD]",
        "map_key_env_var": "FIRMS_MAP_KEY",
        "map_key_stored": False,
        "source": source,
        "product_note": f"NASA FIRMS Area API source {source} (Standard Processing), not NRT, used as independent active-fire audit/features.",
        "license": "NASA FIRMS open data; cite NASA FIRMS/LANCE/EOSDIS",
        "spatial_method": "FIRMS point coordinates spatially joined to versioned IBGE municipal polygons in EPSG:4326 using shapely covers().",
        "bbox_west_south_east_north": [float(x) for x in bbox],
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "day_range_max": int(day_range),
        "request_windows": int(len(request_log)),
        "request_rows_total": int(sum(int(r["rows"]) for r in request_log)),
        "raw_rows": int(len(raw_events)),
        "events_rows_after_dedup": int(len(events)),
        "dedup_removed": int(events.attrs.get("dedup_removed", 0)),
        "matched_rows": int(len(matched)),
        "outside_target_rows": int((events["spatial_join_status"] == "outside_target").sum()) if not events.empty else 0,
        "monthly_rows": int(len(monthly)),
        "municipalities_matched": int(matched["geocodigo"].nunique()) if not matched.empty else 0,
        "coverage_start_local_month": f"{int(monthly['ano'].min())}-{int(monthly['mes'].min()):02d}" if not monthly.empty else None,
        "coverage_end_local_month": f"{int(monthly['ano'].max())}-{int(monthly['mes'].max()):02d}" if not monthly.empty else None,
        "timezone_rule": "FIRMS acquisition date/time parsed as UTC; monthly assignment uses UTC-3 local time for Ceara alignment.",
        "available_at_rule": "Conservative for experiments: only lagged FIRMS features are allowed; a month M is usable for prediction cuts after M ends, never as current-month target evidence.",
        "deduplication_rule": "drop duplicates on source, latitude, longitude, acq_date, acq_time, satellite, instrument",
        "quality_rules": [
            "fail without FIRMS_MAP_KEY",
            "store no secret in artifacts",
            f"use {source} for historical standard processing",
            "no municipal aggregation before real IBGE polygon join",
            "do not sum FIRMS with INPE target without deduplication/audit",
        ],
        "outputs": {
            "events_raw.csv": {"sha256": sha256_file(out_dir / "events_raw.csv"), "rows": int(len(raw_events))},
            "events_joined.csv": {"sha256": sha256_file(out_dir / "events_joined.csv"), "rows": int(len(events))},
            "monthly_firms_features.csv": {"sha256": sha256_file(out_dir / "monthly_firms_features.csv"), "rows": int(len(monthly))},
            "request_log.csv": {"sha256": sha256_file(out_dir / "request_log.csv"), "rows": int(len(request_log))},
        },
        "contract_test": "PASS" if len(raw_events) > 0 and len(monthly) > 0 else "FAIL",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_firms_modis_sp_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--day-range", type=int, default=DEFAULT_DAY_RANGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--pause-seconds", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--max-attempts", type=int, default=5)
    args = parser.parse_args()

    api_key = os.environ.get("FIRMS_MAP_KEY")
    if not api_key:
        raise RuntimeError("FIRMS_MAP_KEY is required and must not be stored in source control")
    if not (1 <= args.day_range <= 5):
        raise ValueError("FIRMS Area API day range must be between 1 and 5")

    start = parse_date(args.start_date)
    end = parse_date(args.end_date)
    if end < start:
        raise ValueError("end-date must be >= start-date")

    geoms = load_target_geometries()
    bbox = bbox_for_geometries(geoms)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()

    raw, request_log = download_raw_events(
        api_key=api_key,
        source=args.source,
        bbox=bbox,
        start=start,
        end=end,
        day_range=args.day_range,
        cache_dir=args.cache_dir,
        pause_seconds=args.pause_seconds,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )
    if raw.empty:
        raise RuntimeError("FIRMS returned no rows for requested period/bbox")
    raw.to_csv(args.out_dir / "events_raw.csv", index=False)

    joined = assign_municipalities(raw, geoms)
    events = clean_and_dedup(joined)
    monthly = aggregate_monthly(events)
    events.to_csv(args.out_dir / "events_joined.csv", index=False)
    monthly.to_csv(args.out_dir / "monthly_firms_features.csv", index=False)
    pd.DataFrame(request_log).to_csv(args.out_dir / "request_log.csv", index=False)
    write_manifest(args.out_dir, args.source, start, end, bbox, args.day_range, request_log, raw, events, monthly, retrieved_at)

    print(json.dumps({
        "snapshot": str(args.out_dir.resolve().relative_to(PROJECT_ROOT)),
        "source": args.source,
        "windows": len(request_log),
        "raw_rows": int(len(raw)),
        "matched_rows": int((events["spatial_join_status"] == "matched_ibge_polygon").sum()),
        "monthly_rows": int(len(monthly)),
        "municipalities": int(monthly["geocodigo"].nunique()) if not monthly.empty else 0,
    }, indent=2))


if __name__ == "__main__":
    main()




