"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_era5_zonal_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.ingest_era5_snapshot import (  # noqa: E402
    DAILY_VARS,
    ENDPOINT,
    END_DATE,
    MAX_VARS,
    MIN_VARS,
    MODEL,
    START_DATE,
    SUM_VARS,
    aggregate_monthly,
)

WEIGHTS_DIR = PROJECT_ROOT / "data" / "snapshots" / "era5_grid_weights_v1"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "era5_zonal_openmeteo_v1"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
DEFAULT_PAUSE_SECONDS = 30.0
DEFAULT_JITTER_SECONDS = 10.0
MAX_ATTEMPTS = 8
# Circuit breaker: 429 repetido na MESMA célula não deve consumir os 8
# attempts genéricos até o fim (isso já levou a >20min presos numa única
# célula). Ao bater um dos limites abaixo, para o lote inteiro em vez de
# insistir — o cache por célula já existente torna isso seguro de retomar.
DEFAULT_MAX_429_ATTEMPTS = 4
DEFAULT_MAX_429_WAIT_TOTAL_SECONDS = 180.0


class RateLimitCircuitOpen(Exception):
    """Representa `RateLimitCircuitOpen` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/data/ingest_era5_zonal_snapshot.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    def __init__(self, lat: float, lon: float, attempts_429: int, total_wait_429: float) -> None:
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.lat = lat
        self.lon = lon
        self.attempts_429 = attempts_429
        self.total_wait_429 = total_wait_429
        super().__init__(
            f"circuit breaker aberto para célula ({lat}, {lon}): "
            f"{attempts_429} tentativas de 429, {total_wait_429:.0f}s de espera acumulada"
        )


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class GlobalRateLimiter:
    """Representa `GlobalRateLimiter` dentro do fluxo FireCast.
    
    A classe concentra dados ou comportamento usado por `src/data/ingest_era5_zonal_snapshot.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""

    def __init__(self, pause_seconds: float, jitter_seconds: float) -> None:
        """Executa a etapa `init` do fluxo FireCast.
        
        A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        self.pause_seconds = pause_seconds
        self.jitter_seconds = jitter_seconds
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait_for_slot(self) -> None:
        """Executa a etapa `wait for slot` do fluxo FireCast.
        
        A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        with self._lock:
            delay = max(0.0, self._next_allowed - time.monotonic())
            # Segura o lock ate liberar o slot; caso contrario threads podem
            # reservar horarios espacos, mas iniciar o GET quase juntas.
            while delay > 0:
                time.sleep(delay)
                delay = max(0.0, self._next_allowed - time.monotonic())
            jitter = random.uniform(0, self.jitter_seconds) if self.jitter_seconds > 0 else 0.0
            self._next_allowed = time.monotonic() + self.pause_seconds + jitter


def _retry_after_seconds(resp: requests.Response) -> float | None:
    """Executa a etapa `retry after seconds` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    header = resp.headers.get("Retry-After")
    if not header:
        return None
    try:
        return float(header)
    except ValueError:
        return None  # formato de data HTTP não suportado; cai no backoff normal


def fetch_daily_cell(
    lat: float,
    lon: float,
    *,
    timeout: int = 120,
    rate_limiter: GlobalRateLimiter | None = None,
    max_429_attempts: int | None = DEFAULT_MAX_429_ATTEMPTS,
    max_429_wait_total_seconds: float | None = DEFAULT_MAX_429_WAIT_TOTAL_SECONDS,
) -> pd.DataFrame:
    """Executa a etapa `fetch daily cell` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "daily": ",".join(DAILY_VARS),
        "models": MODEL,
        "timezone": "America/Fortaleza",
    }
    attempts_429 = 0
    wait_429_total = 0.0
    for attempt in range(MAX_ATTEMPTS):
        if rate_limiter is not None:
            rate_limiter.wait_for_slot()
        try:
            resp = requests.get(ENDPOINT, params=params, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            wait = min(300.0, 10 * (2**attempt)) + random.uniform(0, 5)
            print(f"    erro de rede em célula ({lat}, {lon}): {exc!r}, aguardando {wait:.0f}s...", flush=True)
            time.sleep(wait)
            continue

        if resp.status_code in RETRYABLE_STATUS:
            retry_after = _retry_after_seconds(resp) if resp.status_code == 429 else None
            wait = retry_after if retry_after is not None else min(300.0, 30 * (2**attempt)) + random.uniform(0, 10)
            source = "Retry-After" if retry_after is not None else "backoff exponencial"

            if resp.status_code == 429:
                attempts_429 += 1
                wait_429_total += wait
                breaker_by_attempts = max_429_attempts is not None and attempts_429 >= max_429_attempts
                breaker_by_wait = (
                    max_429_wait_total_seconds is not None and wait_429_total >= max_429_wait_total_seconds
                )
                if breaker_by_attempts or breaker_by_wait:
                    raise RateLimitCircuitOpen(lat, lon, attempts_429, wait_429_total)

            print(
                f"    {resp.status_code} em célula ({lat}, {lon}), aguardando {wait:.0f}s ({source})...",
                flush=True,
            )
            time.sleep(wait)
            continue

        resp.raise_for_status()
        data = resp.json()
        if "daily" not in data:
            raise ValueError(f"Resposta sem bloco daily para célula ({lat}, {lon}): {data}")
        df = pd.DataFrame(data["daily"])
        df["elevation"] = data.get("elevation")
        return df
    raise RuntimeError(f"Limite de tentativas excedido para célula ({lat}, {lon})")


def write_rate_limit_pause(out_dir: Path, exc: RateLimitCircuitOpen, cells_done: int, cells_total: int) -> Path:
    """Grava a etapa `write rate limit pause` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    payload = {
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "reason": str(exc),
        "cell_lat": exc.lat,
        "cell_lon": exc.lon,
        "attempts_429": exc.attempts_429,
        "wait_429_total_seconds": exc.total_wait_429,
        "cells_done_this_run": cells_done,
        "cells_total_expected": cells_total,
        "resume_hint": (
            "Rode o mesmo comando de novo mais tarde. Células já baixadas em "
            "daily_cells/ são reaproveitadas automaticamente; só a célula que "
            "abriu o circuito (e as seguintes ainda não tentadas) serão buscadas."
        ),
    }
    path = out_dir / "rate_limit_pause.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_grid_inputs(weights_dir: Path = WEIGHTS_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carrega a etapa `load grid inputs` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    cells = pd.read_csv(weights_dir / "era5_grid_cells.csv")
    weights = pd.read_csv(weights_dir / "era5_cell_weights.csv")
    required_cells = {"cell_id", "lat", "lon"}
    required_weights = {"geocodigo", "municipio_ibge", "cell_id", "area_weight"}
    missing_cells = required_cells - set(cells.columns)
    missing_weights = required_weights - set(weights.columns)
    if missing_cells or missing_weights:
        raise ValueError(f"Pesos ERA5 inválidos: cells sem {missing_cells}; weights sem {missing_weights}")
    return cells, weights


def fetch_or_load_cells(
    cells: pd.DataFrame,
    out_dir: Path,
    *,
    fetcher: Callable[[float, float], pd.DataFrame] = fetch_daily_cell,
    max_cells: int | None = None,
    max_new_cells: int | None = None,
    pause_seconds: float = 12.0,
    jitter_seconds: float = 0.0,
    workers: int = 1,
) -> list[dict]:
    """Executa a etapa `fetch or load cells` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    daily_dir = out_dir / "daily_cells"
    daily_dir.mkdir(parents=True, exist_ok=True)
    selected = cells.sort_values("cell_id").head(max_cells) if max_cells else cells.sort_values("cell_id")
    total = len(selected)
    records = selected.to_dict("records")
    cached_rows: list[dict] = []
    missing_cells: list[dict] = []
    for i, cell in enumerate(records, start=1):
        path = daily_dir / f"{cell['cell_id']}.csv"
        if path.exists():
            cached_rows.append(
                {
                    "cell_id": cell["cell_id"],
                    "lat": float(cell["lat"]),
                    "lon": float(cell["lon"]),
                    "path": str(path.relative_to(out_dir)),
                    "sha256": sha256_file(path),
                    "cached": True,
                }
            )
            print(f"  [{i}/{total}] {cell['cell_id']} cache", flush=True)
        else:
            missing_cells.append(cell)

    if max_new_cells is not None:
        missing_cells = missing_cells[:max_new_cells]

    # Rate limiter compartilhado entre todas as threads: bloqueia ANTES de cada
    # requisição (não dorme depois do download), então mesmo com workers>1 as
    # chamadas reais saem espaçadas por pause_seconds (+jitter), nunca em rajada.
    rate_limiter = GlobalRateLimiter(pause_seconds, jitter_seconds) if pause_seconds > 0 else None

    def download_one(cell: dict) -> dict:
        """Executa a etapa `download one` do fluxo FireCast.
        
        A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        path = daily_dir / f"{cell['cell_id']}.csv"
        if rate_limiter is not None:
            rate_limiter.wait_for_slot()
        daily = fetcher(float(cell["lat"]), float(cell["lon"]))
        missing = [v for v in ["precipitation_sum", "temperature_2m_max"] if v not in daily.columns]
        if missing:
            raise ValueError(f"{cell['cell_id']}: resposta sem {missing}")
        daily.to_csv(path, index=False)
        return {
            "cell_id": cell["cell_id"],
            "lat": float(cell["lat"]),
            "lon": float(cell["lon"]),
            "path": str(path.relative_to(out_dir)),
            "sha256": sha256_file(path),
            "cached": False,
        }

    downloaded_rows: list[dict] = []
    circuit_open: RateLimitCircuitOpen | None = None
    if workers <= 1:
        for offset, cell in enumerate(missing_cells, start=1):
            try:
                row = download_one(cell)
            except RateLimitCircuitOpen as exc:
                circuit_open = exc
                break
            downloaded_rows.append(row)
            print(f"  [new {offset}/{len(missing_cells)}] {cell['cell_id']} baixada", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(download_one, cell): cell for cell in missing_cells}
            for offset, future in enumerate(as_completed(futures), start=1):
                cell = futures[future]
                try:
                    row = future.result()
                except RateLimitCircuitOpen as exc:
                    circuit_open = exc
                    for pending in futures:
                        pending.cancel()
                    break
                downloaded_rows.append(row)
                print(f"  [new {offset}/{len(missing_cells)}] {cell['cell_id']} baixada", flush=True)

    rows = cached_rows + downloaded_rows
    if circuit_open is not None:
        pause_path = write_rate_limit_pause(out_dir, circuit_open, len(rows), len(cells))
        print(
            f"  PARADO (circuit breaker): {circuit_open}. Estado salvo em {pause_path}. "
            f"{len(rows)}/{len(cells)} células prontas — rode de novo mais tarde para continuar.",
            flush=True,
        )
    return sorted(rows, key=lambda row: row["cell_id"])


def aggregate_cells_monthly(cells: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    """Executa a etapa `aggregate cells monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    frames = []
    for cell in cells.sort_values("cell_id").to_dict("records"):
        path = out_dir / "daily_cells" / f"{cell['cell_id']}.csv"
        if not path.exists():
            continue
        monthly = aggregate_monthly(pd.read_csv(path), geocodigo=0).drop(columns=["geocodigo"])
        monthly.insert(0, "cell_id", cell["cell_id"])
        frames.append(monthly)
    if not frames:
        raise ValueError("Nenhuma célula ERA5 em cache para agregação mensal")
    return pd.concat(frames, ignore_index=True)


def zonal_weighted_monthly(cell_monthly: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `zonal weighted monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    merged = weights.merge(cell_monthly, on="cell_id", how="inner")
    if merged.empty:
        raise ValueError("Interseção vazia entre pesos municipais e células ERA5 baixadas")

    value_cols = [c for c in cell_monthly.columns if c not in {"cell_id", "ano", "mes"}]
    weighted_cols = []
    for col in value_cols:
        if col in {"days_total", "days_observed"}:
            continue
        out_col = f"{col}_zonal"
        merged[out_col] = merged[col] * merged["area_weight"]
        weighted_cols.append(out_col)

    grouped = merged.groupby(["geocodigo", "municipio_ibge", "ano", "mes"], as_index=False)
    out = grouped[weighted_cols].sum()
    coverage = grouped.agg(
        era5_cells_used=("cell_id", "nunique"),
        era5_weight_covered=("area_weight", "sum"),
        era5_days_observed_min=("days_observed", "min"),
        era5_days_total_min=("days_total", "min"),
    )
    out = out.merge(coverage, on=["geocodigo", "municipio_ibge", "ano", "mes"], how="left")
    return out.sort_values(["geocodigo", "ano", "mes"]).reset_index(drop=True)



def build_snapshot_report(
    out_dir: Path,
    cells: pd.DataFrame,
    weights: pd.DataFrame,
    zonal: pd.DataFrame | None = None,
) -> dict:
    """Constroi a etapa `build snapshot report` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    daily_dir = out_dir / "daily_cells"
    cached_ids = sorted(path.stem for path in daily_dir.glob("*.csv")) if daily_dir.exists() else []
    expected_ids = set(cells["cell_id"].astype(str))
    cached_expected = sorted(set(cached_ids) & expected_ids)
    missing_ids = sorted(expected_ids - set(cached_ids))
    report = {
        "snapshot_name": "era5_zonal_openmeteo_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_cells": int(len(expected_ids)),
        "cached_expected_cells": int(len(cached_expected)),
        "unexpected_cached_cells": int(len(set(cached_ids) - expected_ids)),
        "missing_cells": missing_ids,
        "is_complete": len(missing_ids) == 0,
        "municipalities_expected": int(weights["geocodigo"].nunique()),
        "weight_rows": int(len(weights)),
        "min_weight_sum_by_municipality": float(weights.groupby("geocodigo")["area_weight"].sum().min()),
        "max_weight_sum_by_municipality": float(weights.groupby("geocodigo")["area_weight"].sum().max()),
    }
    if zonal is not None and not zonal.empty:
        report.update(
            {
                "zonal_rows": int(len(zonal)),
                "zonal_municipalities": int(zonal["geocodigo"].nunique()),
                "period_min": f"{int(zonal['ano'].min())}-{int(zonal['mes'].min()):02d}",
                "period_max": f"{int(zonal['ano'].max())}-{int(zonal['mes'].max()):02d}",
                "min_weight_covered": float(zonal["era5_weight_covered"].min()),
                "median_weight_covered": float(zonal["era5_weight_covered"].median()),
                "min_cells_used": int(zonal["era5_cells_used"].min()),
                "max_cells_used": int(zonal["era5_cells_used"].max()),
                "min_days_observed": int(zonal["era5_days_observed_min"].min()),
            }
        )
    return report


def write_snapshot_report(out_dir: Path, report: dict) -> Path:
    """Grava a etapa `write snapshot report` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "coverage_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_manifest(out_dir: Path, cells_meta: list[dict], monthly_path: Path, zonal_path: Path, weights: pd.DataFrame) -> None:
    """Grava a etapa `write manifest` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    manifest = {
        "snapshot_name": "era5_zonal_openmeteo_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "climate_zonal_statistics",
        "endpoint": ENDPOINT,
        "model_fixed": MODEL,
        "official_url": "https://open-meteo.com/en/docs/historical-weather-api",
        "license": "Open-Meteo non-commercial / CC-BY 4.0",
        "period": [START_DATE, END_DATE],
        "daily_vars": DAILY_VARS,
        "spatial_method": "ERA5 0.25 degree cells intersecting IBGE municipal polygons, aggregated by area_weight",
        "available_at_rule": "ERA5 historical data has provider delay; model features must use conservative monthly lag >= 1 month.",
        "weights_snapshot": "era5_grid_weights_v1",
        "municipalities": int(weights["geocodigo"].nunique()),
        "cells_total": len(cells_meta),
        "daily_cell_files": cells_meta,
        "cell_monthly_sha256": sha256_file(monthly_path),
        "zonal_monthly_sha256": sha256_file(zonal_path),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def run(
    max_cells: int | None = None,
    max_new_cells: int | None = None,
    out_dir: Path = SNAPSHOT_DIR,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    jitter_seconds: float = DEFAULT_JITTER_SECONDS,
    workers: int = 1,
    weights_dir: Path = WEIGHTS_DIR,
    max_429_attempts: int | None = DEFAULT_MAX_429_ATTEMPTS,
    max_429_wait_total_seconds: float | None = DEFAULT_MAX_429_WAIT_TOTAL_SECONDS,
) -> pd.DataFrame:
    """Executa a etapa `run` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cells, weights = load_grid_inputs(weights_dir)
    fetcher = functools.partial(
        fetch_daily_cell,
        max_429_attempts=max_429_attempts,
        max_429_wait_total_seconds=max_429_wait_total_seconds,
    )
    cells_meta = fetch_or_load_cells(
        cells,
        out_dir,
        fetcher=fetcher,
        max_cells=max_cells,
        max_new_cells=max_new_cells,
        pause_seconds=pause_seconds,
        jitter_seconds=jitter_seconds,
        workers=workers,
    )
    cell_monthly = aggregate_cells_monthly(cells, out_dir)
    zonal = zonal_weighted_monthly(cell_monthly, weights)

    cell_monthly_path = out_dir / "era5_cell_monthly.csv"
    zonal_path = out_dir / "era5_zonal_monthly.csv"
    cell_monthly.to_csv(cell_monthly_path, index=False)
    zonal.to_csv(zonal_path, index=False)
    write_manifest(out_dir, cells_meta, cell_monthly_path, zonal_path, weights)
    report = build_snapshot_report(out_dir, cells, weights, zonal)
    report_path = write_snapshot_report(out_dir, report)
    print(f"OK: {len(zonal)} linhas zonais em {zonal_path}", flush=True)
    print(f"Relatório: {report_path} | completo={report['is_complete']} células={report['cached_expected_cells']}/{report['expected_cells']}", flush=True)
    return zonal


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_era5_zonal_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cells", type=int, default=None, help="smoke/incremental: limita número de células processadas")
    parser.add_argument("--out-dir", type=Path, default=SNAPSHOT_DIR)
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS, help="espaçamento mínimo entre requisições reais (padrão 30s; suba para 45-90s se ainda bater 429)")
    parser.add_argument("--jitter-seconds", type=float, default=DEFAULT_JITTER_SECONDS, help="jitter aleatório somado ao pause_seconds, para não bater em intervalo fixo (padrão 10s)")
    parser.add_argument("--max-new-cells", type=int, default=None, help="resume em lote: baixa no máximo N células ainda ausentes")
    parser.add_argument("--workers", type=int, default=1, help="downloads paralelos para células ausentes; o rate limiter global impede rajada mesmo com workers>1")
    parser.add_argument("--report-only", action="store_true", help="não baixa dados; escreve apenas coverage_report.json do cache atual")
    parser.add_argument("--weights-dir", type=Path, default=WEIGHTS_DIR, help="snapshot de pesos/cells a usar (ex.: era5_grid_weights_chapada_v1 para escopo reduzido)")
    parser.add_argument(
        "--max-429-attempts",
        type=int,
        default=DEFAULT_MAX_429_ATTEMPTS,
        help="circuit breaker: para o lote (não crasha) após N tentativas de 429 na MESMA célula (padrão 4)",
    )
    parser.add_argument(
        "--max-429-wait-total-seconds",
        type=float,
        default=DEFAULT_MAX_429_WAIT_TOTAL_SECONDS,
        help="circuit breaker: para o lote se a espera acumulada de 429 numa única célula passar disso (padrão 180s)",
    )
    args = parser.parse_args()
    if args.report_only:
        cells, weights = load_grid_inputs(args.weights_dir)
        zonal_path = args.out_dir / "era5_zonal_monthly.csv"
        zonal = pd.read_csv(zonal_path) if zonal_path.exists() else None
        report = build_snapshot_report(args.out_dir, cells, weights, zonal)
        path = write_snapshot_report(args.out_dir, report)
        print(json.dumps({"report": str(path), **report}, indent=2, ensure_ascii=False))
    else:
        run(
            max_cells=args.max_cells,
            max_new_cells=args.max_new_cells,
            out_dir=args.out_dir,
            pause_seconds=args.pause_seconds,
            jitter_seconds=args.jitter_seconds,
            workers=args.workers,
            weights_dir=args.weights_dir,
            max_429_attempts=args.max_429_attempts,
            max_429_wait_total_seconds=args.max_429_wait_total_seconds,
        )


if __name__ == "__main__":
    main()
