"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_inpe_monthly_public_v3.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_inpe_local import load_ibge_lookup  # noqa: E402

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "inpe_monthly_public_v3"
RAW_DIR = SNAPSHOT_DIR / "raw"
BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil"
DEFAULT_MONTHS = [
    "202512",
    "202601",
    "202602",
    "202603",
    "202604",
    "202605",
    "202606",
    "202607",
]


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def month_label(month: str) -> str:
    """Executa a etapa `month label` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    return f"{month[:4]}-{month[4:]}"


def download_month(month: str, force: bool = False) -> Path:
    """Executa a etapa `download month` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = RAW_DIR / f"focos_mensal_br_{month}.csv"
    if out.exists() and not force:
        return out
    url = f"{BASE_URL}/focos_mensal_br_{month}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "FireCast scoring snapshot"})
    with urllib.request.urlopen(req, timeout=120) as resp, out.open("wb") as f:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return out


def parse_month(path: Path, target_geocodes: set[int]) -> pd.DataFrame:
    """Executa a etapa `parse month` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    keep_cols = [
        "id",
        "lat",
        "lon",
        "data_hora_gmt",
        "satelite",
        "municipio",
        "estado",
        "municipio_id",
        "numero_dias_sem_chuva",
        "precipitacao",
        "risco_fogo",
        "bioma",
        "frp",
    ]
    chunks = []
    for chunk in pd.read_csv(path, usecols=lambda c: c in keep_cols, chunksize=200_000):
        chunk.columns = [c.strip() for c in chunk.columns]
        chunk["municipio_id"] = pd.to_numeric(chunk["municipio_id"], errors="coerce").astype("Int64")
        chunk = chunk[chunk["municipio_id"].isin(target_geocodes)].copy()
        if chunk.empty:
            continue
        chunk["data_hora_gmt"] = pd.to_datetime(chunk["data_hora_gmt"], utc=True, errors="coerce")
        chunk = chunk.dropna(subset=["data_hora_gmt", "municipio_id"])
        chunk = chunk.drop_duplicates(subset=["id"])
        local = chunk["data_hora_gmt"].dt.tz_convert("Etc/GMT+3")
        chunk["ano"] = local.dt.year.astype(int)
        chunk["mes"] = local.dt.month.astype(int)
        chunk["geocodigo"] = chunk["municipio_id"].astype(int)
        for col in ["lat", "lon", "numero_dias_sem_chuva", "precipitacao", "risco_fogo", "frp"]:
            chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
        chunks.append(chunk)
    if not chunks:
        return pd.DataFrame(columns=keep_cols + ["ano", "mes", "geocodigo"])
    return pd.concat(chunks, ignore_index=True)


def aggregate(events: pd.DataFrame, lookup_by_code: dict[int, tuple[str, str]]) -> pd.DataFrame:
    """Executa a etapa `aggregate` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if events.empty:
        return pd.DataFrame()
    grouped = events.groupby(["geocodigo", "ano", "mes"], as_index=False)
    monthly = grouped.agg(
        fire_count=("id", "size"),
        frp_sum=("frp", "sum"),
        frp_mean=("frp", "mean"),
        frp_max=("frp", "max"),
        risco_fogo_mean=("risco_fogo", "mean"),
        dias_sem_chuva_mean=("numero_dias_sem_chuva", "mean"),
        precip_mean=("precipitacao", "mean"),
        lat_mean=("lat", "mean"),
        lon_mean=("lon", "mean"),
        n_satellites=("satelite", "nunique"),
    )
    monthly["municipio_ibge"] = monthly["geocodigo"].map(lambda g: lookup_by_code[int(g)][0])
    monthly["uf"] = monthly["geocodigo"].map(lambda g: lookup_by_code[int(g)][1])
    monthly["target_source"] = "inpe_monthly_public_v3"
    return monthly[
        [
            "geocodigo",
            "municipio_ibge",
            "uf",
            "ano",
            "mes",
            "fire_count",
            "frp_sum",
            "frp_mean",
            "frp_max",
            "risco_fogo_mean",
            "dias_sem_chuva_mean",
            "precip_mean",
            "lat_mean",
            "lon_mean",
            "n_satellites",
            "target_source",
        ]
    ].sort_values(["geocodigo", "ano", "mes"])


def period_bounds(monthly: pd.DataFrame) -> tuple[str | None, str | None]:
    """Executa a etapa `period bounds` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    if monthly.empty:
        return None, None
    periods = pd.PeriodIndex.from_fields(year=monthly["ano"], month=monthly["mes"], freq="M")
    return str(periods.min()), str(periods.max())

def build_snapshot(months: list[str], force: bool = False) -> dict:
    """Constroi a etapa `build snapshot` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_monthly_public_v3.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    lookup = load_ibge_lookup()
    lookup_by_code = {value[0]: (value[1], value[2]) for value in lookup.values()}
    target_geocodes = set(lookup_by_code)

    raw_meta = []
    frames = []
    for month in months:
        path = download_month(month, force=force)
        raw_meta.append(
            {
                "month_file": month,
                "period_label": month_label(month),
                "url": f"{BASE_URL}/focos_mensal_br_{month}.csv",
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
        frames.append(parse_month(path, target_geocodes))

    events = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    events = events.drop_duplicates(subset=["id"]).reset_index(drop=True)
    monthly = aggregate(events, lookup_by_code)

    events_path = SNAPSHOT_DIR / "events_target_region.csv"
    monthly_path = SNAPSHOT_DIR / "monthly_target_region.csv"
    events.to_csv(events_path, index=False)
    monthly.to_csv(monthly_path, index=False)
    min_period, max_period = period_bounds(monthly)

    manifest = {
        "snapshot_name": "inpe_monthly_public_v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "additive_target_scoring_only",
        "official_url": f"{BASE_URL}/",
        "license": "dados abertos INPE",
        "months_requested": months,
        "time_assignment": "data_hora_gmt converted to Etc/GMT+3 to match inpe_local_v2 local-month convention",
        "training_policy": "must not replace inpe_local_v2 for historical model selection; use only for delayed shadow scoring / reality tests",
        "deduplication_rule": "drop_duplicates(id) after filtering target geocodes",
        "caveats": [
            "Public monthly files may include a different satellite mix than the frozen v2 target; validate overlap before treating as identical target.",
            "Latest month can be incomplete in local-month convention because next-month early UTC hours are not yet available.",
        ],
        "raw_files": raw_meta,
        "metrics": {
            "events_target_region": int(len(events)),
            "monthly_rows": int(len(monthly)),
            "municipalities": int(monthly["geocodigo"].nunique()) if len(monthly) else 0,
            "min_period": min_period,
            "max_period": max_period,
        },
        "outputs": {
            "events_target_region.csv": {"sha256": sha256_file(events_path), "rows": int(len(events))},
            "monthly_target_region.csv": {"sha256": sha256_file(monthly_path), "rows": int(len(monthly))},
        },
    }
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_inpe_monthly_public_v3.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", nargs="*", default=DEFAULT_MONTHS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = build_snapshot(args.months, force=args.force)
    print(json.dumps(manifest["metrics"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

