"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_era5_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_inpe_local import load_ibge_lookup, normalize_name  # noqa: E402
from src.data.municipality_coords import MUNICIPIOS_CE  # noqa: E402

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "era5_openmeteo_v1"
TARGET_SNAPSHOT = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"

ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
MODEL = "era5"
START_DATE = "2002-01-01"
END_DATE = "2025-12-31"
DAILY_VARS = [
    "temperature_2m_mean", "temperature_2m_max", "temperature_2m_min",
    "relative_humidity_2m_mean",
    "vapour_pressure_deficit_max",
    "precipitation_sum",
    "et0_fao_evapotranspiration",
    "shortwave_radiation_sum",
    "wind_speed_10m_max",
    "soil_moisture_0_to_7cm_mean", "soil_moisture_7_to_28cm_mean",
    "soil_moisture_28_to_100cm_mean",
]

SUM_VARS = ["precipitation_sum", "rain_sum", "shortwave_radiation_sum", "et0_fao_evapotranspiration"]
MAX_VARS = ["temperature_2m_max", "vapour_pressure_deficit_max", "wind_speed_10m_max", "wind_gusts_10m_max"]
MIN_VARS = ["temperature_2m_min"]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def target_municipalities() -> pd.DataFrame:
    """Executa a etapa `target municipalities` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    tgt = pd.read_csv(TARGET_SNAPSHOT)
    munis = tgt[["geocodigo", "municipio_ibge", "uf"]].drop_duplicates()
    coords = {normalize_name(name): (lat, lon) for name, lat, lon in MUNICIPIOS_CE}
    rows = []
    missing = []
    for _, r in munis.iterrows():
        key = normalize_name(r["municipio_ibge"])
        if key not in coords:
            missing.append(r["municipio_ibge"])
            continue
        lat, lon = coords[key]
        rows.append({"geocodigo": r["geocodigo"], "municipio_ibge": r["municipio_ibge"],
                     "uf": r["uf"], "lat": lat, "lon": lon})
    if missing:
        raise ValueError(f"Municípios do alvo sem coordenada em municipality_coords (fail closed): {missing}")
    return pd.DataFrame(rows)


def fetch_daily(lat: float, lon: float) -> pd.DataFrame:
    """Executa a etapa `fetch daily` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "daily": ",".join(DAILY_VARS),
        "models": MODEL,
        "timezone": "America/Fortaleza",
    }
    for attempt in range(8):
        resp = requests.get(ENDPOINT, params=params, timeout=120)
        if resp.status_code == 429:
            wait = 45 * (attempt + 1)
            print(f"    429, aguardando {wait}s...", flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        data = resp.json()
        if "daily" not in data:
            raise ValueError(f"Resposta sem bloco daily: {data}")
        df = pd.DataFrame(data["daily"])
        df["elevation"] = data.get("elevation")
        return df
    raise RuntimeError("Limite de tentativas excedido (429 persistente)")


def aggregate_monthly(daily: pd.DataFrame, geocodigo: int) -> pd.DataFrame:
    """Executa a etapa `aggregate monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = daily.copy()
    df["time"] = pd.to_datetime(df["time"])
    df["ano"] = df["time"].dt.year
    df["mes"] = df["time"].dt.month

    agg = {}
    for c in DAILY_VARS:
        if c not in df.columns:
            continue
        if c in SUM_VARS:
            agg[c] = "sum"
        elif c in MAX_VARS:
            agg[c] = "max"
        elif c in MIN_VARS:
            agg[c] = "min"
        else:
            agg[c] = "mean"
    out = df.groupby(["ano", "mes"], as_index=False).agg(agg)

    # dias secos no mês e sequência máxima de dias secos
    df["dry_day"] = (df["precipitation_sum"].fillna(0) < 1.0).astype(int)

    def max_run(x):
        """Executa a etapa `max run` do fluxo FireCast.
        
        A funcao faz parte de `src/data/ingest_era5_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        best = run = 0
        for v in x:
            run = run + 1 if v else 0
            best = max(best, run)
        return best

    dry = df.groupby(["ano", "mes"])["dry_day"].agg(
        dry_days="sum", dry_spell_max=max_run
    ).reset_index()
    out = out.merge(dry, on=["ano", "mes"])

    # cobertura observada do mês (dias com dado de temperatura)
    covg = df.groupby(["ano", "mes"])["temperature_2m_mean"].agg(
        days_observed="count", days_total="size"
    ).reset_index()
    out = out.merge(covg, on=["ano", "mes"])
    out.insert(0, "geocodigo", geocodigo)
    return out


def fetch_one(r: dict) -> dict:
    """Executa a etapa `fetch one` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    raw_path = SNAPSHOT_DIR / "daily" / f"{r['geocodigo']}.csv"
    if not raw_path.exists():
        daily = fetch_daily(r["lat"], r["lon"])
        # variáveis podem faltar em cache antigo/novo; valida colunas mínimas
        missing = [v for v in ["precipitation_sum", "temperature_2m_max"] if v not in daily.columns]
        if missing:
            raise ValueError(f"{r['municipio_ibge']}: resposta sem {missing}")
        daily.to_csv(raw_path, index=False)
    return r


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_era5_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    (SNAPSHOT_DIR / "daily").mkdir(parents=True, exist_ok=True)
    munis = target_municipalities()
    print(f"Snapshot ERA5 para {len(munis)} municípios ({START_DATE} a {END_DATE}, model={MODEL})", flush=True)

    records = munis.to_dict("records")
    done = 0
    for r in records:
        cached = (SNAPSHOT_DIR / "daily" / f"{r['geocodigo']}.csv").exists()
        fetch_one(r)
        done += 1
        print(f"  [{done}/{len(records)}] {r['municipio_ibge']} ok", flush=True)
        if not cached:
            time.sleep(12)  # respeitar limite de unidades do tier gratuito

    monthly_all = []
    file_meta = []
    for r in records:
        raw_path = SNAPSHOT_DIR / "daily" / f"{r['geocodigo']}.csv"
        daily = pd.read_csv(raw_path)
        monthly_all.append(aggregate_monthly(daily, r["geocodigo"]))
        file_meta.append({
            "geocodigo": int(r["geocodigo"]),
            "municipio": r["municipio_ibge"],
            "lat": r["lat"], "lon": r["lon"],
            "sha256": sha256_file(raw_path),
            "rows": int(len(daily)),
        })

    monthly = pd.concat(monthly_all, ignore_index=True)
    monthly.to_csv(SNAPSHOT_DIR / "era5_monthly.csv", index=False)

    manifest = {
        "snapshot_name": "era5_openmeteo_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "climate",
        "endpoint": ENDPOINT,
        "model_fixed": MODEL,
        "official_url": "https://open-meteo.com/en/docs/historical-weather-api",
        "license": "Open-Meteo non-commercial / CC-BY 4.0",
        "period": [START_DATE, END_DATE],
        "daily_vars": DAILY_VARS,
        "spatial_method": "centroide municipal (limitacao documentada; zonal por poligono pendente)",
        "available_at_rule": "ERA5 tem atraso ~5 dias; para features usar somente lags >= 1 mes",
        "timezone": "America/Fortaleza",
        "files": file_meta,
        "monthly_rows": int(len(monthly)),
        "monthly_sha256": None,
    }
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest["monthly_sha256"] = sha256_file(SNAPSHOT_DIR / "era5_monthly.csv")
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # relatório de qualidade rápido
    nul = monthly[DAILY_VARS].isna().mean().sort_values(ascending=False)
    print("\nFração de NaN por variável (top 5):")
    print(nul.head(5).to_string())
    print(f"\nOK: {len(monthly)} linhas mensais em {SNAPSHOT_DIR / 'era5_monthly.csv'}")


if __name__ == "__main__":
    main()
