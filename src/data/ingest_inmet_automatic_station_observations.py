"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_inmet_automatic_station_observations.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import calendar
import hashlib
import io
import json
import math
import re
import shutil
import unicodedata
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import shape

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET_PATH = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
MUNICIPAL_GEOJSON = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi.geojson"
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "inmet_automatic_station_observed_v1"
RAW_DIR = OUT_DIR / "raw" / "station_csv"
CACHE_DIR = PROJECT_ROOT / "cache" / "inmet_official"

BASE_URL = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{year}.zip"
OFFICIAL_URL = "https://portal.inmet.gov.br/dadoshistoricos"
YEARS = list(range(2014, 2025))
DISCOVERY_YEAR = 2024
MAX_STATION_DISTANCE_KM = 250.0
# Accumulated variables (precip, radiation) are summed with missing hours as
# zero, so low observed fractions bias totals down; require most of the month.
# Mean variables tolerate partial coverage better.
MIN_FRACTION_SUM_VARS = 0.70
MIN_FRACTION_MEAN_VARS = 0.30

TARGET_STATES = {"CE", "PE", "PI"}

VAR_ALIASES = {
    "precip_mm": "PRECIPITACAO TOTAL",
    "temp_c": "TEMPERATURA DO AR - BULBO SECO",
    "rh_pct": "UMIDADE RELATIVA DO AR",
    "wind_ms": "VENTO, VELOCIDADE HORARIA",
    "gust_ms": "VENTO, RAJADA MAXIMA",
    "radiation_kj_m2": "RADIACAO GLOBAL",
}


@dataclass(frozen=True)
class StationMeta:
    """Representa `StationMeta` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/data/ingest_inmet_automatic_station_observations.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
    station_code: str
    station_name: str
    region: str
    uf: str
    latitude: float
    longitude: float
    altitude_m: float | None
    foundation_date: str | None
    discovery_entry: str
    min_target_distance_km: float


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_year_zip(year: int) -> Path:
    """Executa a etapa `download year zip` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{year}.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    url = BASE_URL.format(year=year)
    tmp = path.with_suffix(".zip.part")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (FireCast ingest)"})
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 official INMET URL
        with tmp.open("wb") as fh:
            shutil.copyfileobj(response, fh)
    tmp.replace(path)
    return path


def parse_decimal(text: str | None) -> float | None:
    """Executa a etapa `parse decimal` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if text is None:
        return None
    clean = str(text).strip().replace(",", ".")
    if not clean:
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def parse_metadata(raw_head: bytes, entry_name: str, target_points: list[tuple[float, float]]) -> StationMeta | None:
    """Executa a etapa `parse metadata` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    lines = raw_head.decode("latin1", errors="replace").splitlines()[:8]
    fields: dict[str, str] = {}
    for line in lines:
        if ";" not in line:
            continue
        key, value = line.split(";", 1)
        fields[key.strip().upper().rstrip(":")] = value.strip()
    code = fields.get("CODIGO (WMO)")
    lat = parse_decimal(fields.get("LATITUDE"))
    lon = parse_decimal(fields.get("LONGITUDE"))
    if not code or lat is None or lon is None:
        return None
    distances = [haversine_km(lat, lon, point_lat, point_lon) for point_lat, point_lon in target_points]
    return StationMeta(
        station_code=code,
        station_name=fields.get("ESTACAO", ""),
        region=fields.get("REGIAO", ""),
        uf=fields.get("UF", ""),
        latitude=lat,
        longitude=lon,
        altitude_m=parse_decimal(fields.get("ALTITUDE")),
        foundation_date=fields.get("DATA DE FUNDACAO"),
        discovery_entry=entry_name,
        min_target_distance_km=float(min(distances)) if distances else float("nan"),
    )


def normalize_col(name: str) -> str:
    """Executa a etapa `normalize col` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().strip()
    # 2014-2019 files wrap units/qualifiers in punctuation, e.g. "HORA (UTC)";
    # match on alphanumeric words only so both vintages resolve the same column.
    text = re.sub(r"[^0-9A-Z]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_column(columns: list[str], token: str) -> str | None:
    """Executa a etapa `find column` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    token_norm = normalize_col(token)
    for col in columns:
        if token_norm in normalize_col(col):
            return col
    return None


def to_float(series: pd.Series) -> pd.Series:
    """Executa a etapa `to float` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    text = series.astype(str).str.strip().str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    text = text.mask(text.isin(["", "nan", "NaN", "-9999", "-9999.0"]))
    return pd.to_numeric(text, errors="coerce")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Executa a etapa `haversine km` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    r = 6371.0088
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_target_centroids() -> pd.DataFrame:
    """Carrega a etapa `load target centroids` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    target = pd.read_csv(TARGET_PATH, dtype={"geocodigo": str})
    target_codes = set(target["geocodigo"].astype(str).unique())
    data = json.loads(MUNICIPAL_GEOJSON.read_text(encoding="utf-8"))
    rows = []
    for feature in data["features"]:
        props = feature["properties"]
        geocodigo = str(props["geocodigo"])
        if geocodigo not in target_codes:
            continue
        geom = shape(feature["geometry"])
        point = geom.representative_point()
        rows.append(
            {
                "geocodigo": geocodigo,
                "municipio_ibge": props["municipio_ibge"],
                "uf": props["uf"],
                "latitude": float(point.y),
                "longitude": float(point.x),
            }
        )
    if len(rows) != len(target_codes):
        raise RuntimeError("Municipality centroid coverage gap for INMET target set")
    return pd.DataFrame(rows)


def discover_stations(discovery_zip: Path, centroids: pd.DataFrame) -> list[StationMeta]:
    """Executa a etapa `discover stations` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    target_points = list(zip(centroids["latitude"].astype(float), centroids["longitude"].astype(float)))
    stations: dict[str, StationMeta] = {}
    with zipfile.ZipFile(discovery_zip) as zf:
        for entry in zf.infolist():
            if not entry.filename.upper().endswith(".CSV"):
                continue
            with zf.open(entry) as fh:
                head = fh.read(4096)
            meta = parse_metadata(head, entry.filename, target_points)
            if meta is None:
                continue
            if meta.uf not in TARGET_STATES:
                continue
            if meta.min_target_distance_km > MAX_STATION_DISTANCE_KM:
                continue
            stations[meta.station_code] = meta
    if not stations:
        raise RuntimeError("No INMET stations selected from discovery zip")
    return sorted(stations.values(), key=lambda m: (m.min_target_distance_km, m.station_code))


def extract_selected_station_csvs(year_zip: Path, year: int, station_codes: set[str]) -> list[Path]:
    """Executa a etapa `extract selected station csvs` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_year = RAW_DIR / str(year)
    out_year.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(year_zip) as zf:
        for entry in zf.infolist():
            if not entry.filename.upper().endswith(".CSV"):
                continue
            match = re.search(r"_([AB]\d{3})_", entry.filename)
            if not match or match.group(1) not in station_codes:
                continue
            raw = zf.read(entry)
            out_path = out_year / Path(entry.filename).name
            out_path.write_bytes(raw)
            extracted.append(out_path)
    return extracted


def parse_station_csv(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    """Executa a etapa `parse station csv` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    raw = path.read_bytes()
    meta = parse_metadata(raw[:4096], path.name, [])
    if meta is None:
        raise RuntimeError(f"Could not parse INMET station metadata: {path}")
    df = pd.read_csv(io.BytesIO(raw), sep=";", encoding="latin1", skiprows=8, dtype=str)
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    columns = list(df.columns)
    date_col = find_column(columns, "Data")
    hour_col = find_column(columns, "Hora UTC")
    if date_col is None or hour_col is None:
        raise RuntimeError(f"Missing date/hour columns in {path}")
    parsed = pd.DataFrame(
        {
            "station_code": meta.station_code,
            "date": pd.to_datetime(df[date_col], errors="coerce"),
        }
    )
    parsed["period"] = parsed["date"].dt.to_period("M")
    for out_col, token in VAR_ALIASES.items():
        source_col = find_column(columns, token)
        parsed[out_col] = to_float(df[source_col]) if source_col is not None else np.nan
    parsed = parsed.dropna(subset=["date"])
    return parsed, {
        "station_code": meta.station_code,
        "station_name": meta.station_name,
        "region": meta.region,
        "uf": meta.uf,
        "latitude": meta.latitude,
        "longitude": meta.longitude,
        "altitude_m": meta.altitude_m,
        "foundation_date": meta.foundation_date,
    }


def aggregate_station_monthly(raw_paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa a etapa `aggregate station monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    frames: list[pd.DataFrame] = []
    metas: dict[str, dict[str, object]] = {}
    for path in raw_paths:
        parsed, meta = parse_station_csv(path)
        frames.append(parsed)
        metas[meta["station_code"]] = meta
    hourly = pd.concat(frames, ignore_index=True)
    hourly["ano"] = hourly["period"].dt.year
    hourly["mes"] = hourly["period"].dt.month
    rows = []
    for (station_code, period), group in hourly.groupby(["station_code", "period"], sort=True):
        year = int(period.year)
        month = int(period.month)
        expected_hours = calendar.monthrange(year, month)[1] * 24
        row = {
            "station_code": station_code,
            "ano": year,
            "mes": month,
            "expected_hours": expected_hours,
            "rows_reported": int(len(group)),
        }
        for col in VAR_ALIASES:
            values = group[col]
            valid = values.notna()
            row[f"{col}_valid_hours"] = int(valid.sum())
            row[f"{col}_observed_fraction"] = float(valid.sum() / expected_hours)
        row["precip_total_mm"] = float(group["precip_mm"].fillna(0.0).sum()) if row["precip_mm_valid_hours"] > 0 else np.nan
        row["temp_mean_c"] = float(group["temp_c"].mean())
        row["rh_mean_pct"] = float(group["rh_pct"].mean())
        row["wind_mean_ms"] = float(group["wind_ms"].mean())
        row["gust_max_ms"] = float(group["gust_ms"].max())
        row["radiation_sum_kj_m2"] = float(group["radiation_kj_m2"].fillna(0.0).sum()) if row["radiation_kj_m2_valid_hours"] > 0 else np.nan
        row["station_observed_fraction_mean"] = float(
            np.nanmean([row[f"{col}_observed_fraction"] for col in VAR_ALIASES])
        )
        rows.append(row)
    station_monthly = pd.DataFrame(rows)
    station_meta = pd.DataFrame(metas.values()).sort_values("station_code").reset_index(drop=True)
    return station_monthly, station_meta


def build_municipal_monthly(
    station_monthly: pd.DataFrame,
    station_meta: pd.DataFrame,
    centroids: pd.DataFrame,
) -> pd.DataFrame:
    """Constroi a etapa `build municipal monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inmet_automatic_station_observations.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    meta = station_meta.copy()
    months = station_monthly[["ano", "mes"]].drop_duplicates().sort_values(["ano", "mes"])
    value_cols = [
        "precip_total_mm",
        "temp_mean_c",
        "rh_mean_pct",
        "wind_mean_ms",
        "gust_max_ms",
        "radiation_sum_kj_m2",
    ]
    rows: list[dict[str, object]] = []
    for _, mrow in months.iterrows():
        year = int(mrow["ano"])
        month = int(mrow["mes"])
        sm = station_monthly[(station_monthly["ano"] == year) & (station_monthly["mes"] == month)].merge(
            meta, on="station_code", how="left"
        )
        for _, muni in centroids.iterrows():
            base = {
                "geocodigo": str(muni["geocodigo"]),
                "municipio_ibge": muni["municipio_ibge"],
                "uf": muni["uf"],
                "ano": year,
                "mes": month,
            }
            if sm.empty:
                base.update(
                    {
                        "inmet_station_count_any": 0,
                        "inmet_nearest_station_km": np.nan,
                        "inmet_max_station_km": np.nan,
                        "inmet_observed_fraction_mean": np.nan,
                    }
                )
                for col in value_cols:
                    base[f"inmet_{col}_idw"] = np.nan
                    base[f"inmet_{col}_station_count"] = 0
                rows.append(base)
                continue
            distances = sm.apply(
                lambda r: haversine_km(float(muni["latitude"]), float(muni["longitude"]), float(r["latitude"]), float(r["longitude"])),
                axis=1,
            )
            sm = sm.assign(distance_km=distances)
            base["inmet_station_count_any"] = int(len(sm))
            base["inmet_nearest_station_km"] = float(sm["distance_km"].min())
            base["inmet_max_station_km"] = float(sm["distance_km"].max())
            base["inmet_observed_fraction_mean"] = float(sm["station_observed_fraction_mean"].mean())
            fraction_floors = {
                "precip_total_mm": ("precip_mm_observed_fraction", MIN_FRACTION_SUM_VARS),
                "radiation_sum_kj_m2": ("radiation_kj_m2_observed_fraction", MIN_FRACTION_SUM_VARS),
                "temp_mean_c": ("temp_c_observed_fraction", MIN_FRACTION_MEAN_VARS),
                "rh_mean_pct": ("rh_pct_observed_fraction", MIN_FRACTION_MEAN_VARS),
                "wind_mean_ms": ("wind_ms_observed_fraction", MIN_FRACTION_MEAN_VARS),
                "gust_max_ms": ("gust_ms_observed_fraction", MIN_FRACTION_MEAN_VARS),
            }
            for col in value_cols:
                fraction_col, floor = fraction_floors[col]
                valid = sm[sm[col].notna() & (sm[fraction_col] >= floor)].copy()
                if valid.empty:
                    base[f"inmet_{col}_idw"] = np.nan
                    base[f"inmet_{col}_station_count"] = 0
                    continue
                weights = 1.0 / np.square(valid["distance_km"].to_numpy(dtype=float) + 5.0)
                values = valid[col].to_numpy(dtype=float)
                base[f"inmet_{col}_idw"] = float(np.average(values, weights=weights))
                base[f"inmet_{col}_station_count"] = int(len(valid))
            rows.append(base)
    return pd.DataFrame(rows).sort_values(["geocodigo", "ano", "mes"]).reset_index(drop=True)


def main() -> int:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_inmet_automatic_station_observations.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    centroids = load_target_centroids()

    discovery_zip = download_year_zip(DISCOVERY_YEAR)
    selected_stations = discover_stations(discovery_zip, centroids)
    station_codes = {s.station_code for s in selected_stations}

    zip_records = []
    raw_paths: list[Path] = []
    for year in YEARS:
        year_zip = download_year_zip(year)
        extracted = extract_selected_station_csvs(year_zip, year, station_codes)
        zip_records.append(
            {
                "year": year,
                "url": BASE_URL.format(year=year),
                "zip_cache_path": str(year_zip.relative_to(PROJECT_ROOT)),
                "zip_sha256": sha256_file(year_zip),
                "extracted_station_files": len(extracted),
            }
        )
        raw_paths.extend(extracted)

    station_monthly, station_meta = aggregate_station_monthly(raw_paths)
    selected_df = pd.DataFrame([s.__dict__ for s in selected_stations]).sort_values("station_code")
    station_meta = station_meta.merge(
        selected_df[["station_code", "min_target_distance_km", "discovery_entry"]],
        on="station_code",
        how="left",
    )
    municipal_monthly = build_municipal_monthly(station_monthly, station_meta, centroids)

    station_meta_path = OUT_DIR / "stations.csv"
    selected_path = OUT_DIR / "selected_stations.csv"
    station_monthly_path = OUT_DIR / "station_monthly_observed.csv"
    municipal_path = OUT_DIR / "municipal_monthly_station_features.csv"
    station_meta.to_csv(station_meta_path, index=False)
    selected_df.to_csv(selected_path, index=False)
    station_monthly.to_csv(station_monthly_path, index=False)
    municipal_monthly.to_csv(municipal_path, index=False)

    manifest = {
        "snapshot_name": "inmet_automatic_station_observed_v1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "source_name": "INMET",
        "dataset_name": "Dados Historicos Anuais - Estacoes Automaticas",
        "official_url": OFFICIAL_URL,
        "download_url_template": BASE_URL,
        "role": "observed_surface_weather_validation_and_lagged_features",
        "license": "Dados publicos INMET/portal oficial",
        "temporal_resolution_raw": "hourly",
        "temporal_resolution_outputs": "monthly",
        "spatial_resolution": "automatic weather station; municipal IDW interpolation",
        "timezone": "UTC in raw Hora UTC",
        "coverage_years": YEARS,
        "target_municipalities": int(centroids["geocodigo"].nunique()),
        "selected_station_count": int(len(selected_stations)),
        "station_selection_rule": f"stations in {sorted(TARGET_STATES)} from {DISCOVERY_YEAR} official zip with min target distance <= {MAX_STATION_DISTANCE_KM} km",
        "max_station_distance_km": MAX_STATION_DISTANCE_KM,
        "available_at_rule": "Monthly observed station features are used only with lag/rolling strictly before the forecast month; raw observations are historical official INMET annual files retrieved after observation.",
        "variables": {
            "precip_total_mm": "monthly sum of hourly precipitation",
            "temp_mean_c": "monthly mean dry-bulb temperature",
            "rh_mean_pct": "monthly mean relative humidity",
            "wind_mean_ms": "monthly mean wind speed",
            "gust_max_ms": "monthly max gust",
            "radiation_sum_kj_m2": "monthly sum of global radiation",
        },
        "quality_rules": [
            "preserve raw official station CSVs extracted from annual zips",
            "record annual zip URL and sha256",
            f"accumulated variables (precip, radiation) require observed fraction >= {MIN_FRACTION_SUM_VARS}; mean variables >= {MIN_FRACTION_MEAN_VARS}",
            "record station distance and observed fraction metadata",
            "municipal features must be lagged before experiments; same-month observed values are not valid predictors",
            "do not use unverified availability-only snapshot as weather observation",
        ],
        "annual_zips": zip_records,
        "outputs": {
            "stations.csv": {"sha256": sha256_file(station_meta_path), "rows": int(len(station_meta))},
            "selected_stations.csv": {"sha256": sha256_file(selected_path), "rows": int(len(selected_df))},
            "station_monthly_observed.csv": {"sha256": sha256_file(station_monthly_path), "rows": int(len(station_monthly))},
            "municipal_monthly_station_features.csv": {"sha256": sha256_file(municipal_path), "rows": int(len(municipal_monthly))},
        },
    }
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "snapshot": manifest["snapshot_name"],
                "selected_stations": len(selected_stations),
                "station_monthly_rows": len(station_monthly),
                "municipal_rows": len(municipal_monthly),
                "manifest": str(manifest_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

