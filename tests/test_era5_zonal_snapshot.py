"""Testes publicos do FireCast para tests/test_era5_zonal_snapshot.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import pandas as pd

from src.data.ingest_era5_zonal_snapshot import zonal_weighted_monthly


def test_zonal_weighted_monthly_uses_area_weights_and_coverage():
    """Verifica o comportamento `test zonal weighted monthly uses area weights and coverage`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    cell_monthly = pd.DataFrame(
        [
            {"cell_id": "a", "ano": 2024, "mes": 1, "precipitation_sum": 10.0, "temperature_2m_max": 30.0, "days_observed": 31, "days_total": 31},
            {"cell_id": "b", "ano": 2024, "mes": 1, "precipitation_sum": 30.0, "temperature_2m_max": 34.0, "days_observed": 30, "days_total": 31},
        ]
    )
    weights = pd.DataFrame(
        [
            {"geocodigo": 1, "municipio_ibge": "Teste", "cell_id": "a", "area_weight": 0.25},
            {"geocodigo": 1, "municipio_ibge": "Teste", "cell_id": "b", "area_weight": 0.75},
        ]
    )

    out = zonal_weighted_monthly(cell_monthly, weights)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["precipitation_sum_zonal"] == 25.0
    assert row["temperature_2m_max_zonal"] == 33.0
    assert row["era5_cells_used"] == 2
    assert row["era5_weight_covered"] == 1.0
    assert row["era5_days_observed_min"] == 30


def test_build_snapshot_report_tracks_missing_cells(tmp_path):
    """Verifica o comportamento `test build snapshot report tracks missing cells`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.data.ingest_era5_zonal_snapshot import build_snapshot_report, write_snapshot_report

    daily_dir = tmp_path / "daily_cells"
    daily_dir.mkdir()
    (daily_dir / "a.csv").write_text("time,temperature_2m_max\n2024-01-01,30\n", encoding="utf-8")
    cells = pd.DataFrame(
        [
            {"cell_id": "a", "lat": -7.0, "lon": -39.0},
            {"cell_id": "b", "lat": -7.25, "lon": -39.25},
        ]
    )
    weights = pd.DataFrame(
        [
            {"geocodigo": 1, "municipio_ibge": "Teste", "cell_id": "a", "area_weight": 0.4},
            {"geocodigo": 1, "municipio_ibge": "Teste", "cell_id": "b", "area_weight": 0.6},
        ]
    )

    report = build_snapshot_report(tmp_path, cells, weights)
    path = write_snapshot_report(tmp_path, report)

    assert report["expected_cells"] == 2
    assert report["cached_expected_cells"] == 1
    assert report["missing_cells"] == ["b"]
    assert not report["is_complete"]
    assert path.exists()


def test_fetch_or_load_cells_limits_new_downloads_but_keeps_resume_metadata(tmp_path):
    """Verifica o comportamento `test fetch or load cells limits new downloads but keeps resume metadata`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.data.ingest_era5_zonal_snapshot import fetch_or_load_cells

    cells = pd.DataFrame(
        [
            {"cell_id": "a", "lat": -7.0, "lon": -39.0},
            {"cell_id": "b", "lat": -7.25, "lon": -39.25},
            {"cell_id": "c", "lat": -7.5, "lon": -39.5},
        ]
    )
    calls = []

    def fake_fetcher(lat, lon):
        """Executa a etapa `fake fetcher` do fluxo FireCast.
        
        A funcao faz parte de `tests/test_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        calls.append((lat, lon))
        return pd.DataFrame(
            {"time": ["2024-01-01"], "precipitation_sum": [1.0], "temperature_2m_max": [30.0]}
        )

    rows = fetch_or_load_cells(
        cells,
        tmp_path,
        fetcher=fake_fetcher,
        max_new_cells=2,
        pause_seconds=0,
    )

    assert len(calls) == 2
    assert [row["cell_id"] for row in rows] == ["a", "b"]
    assert (tmp_path / "daily_cells" / "a.csv").exists()
    assert (tmp_path / "daily_cells" / "b.csv").exists()
    assert not (tmp_path / "daily_cells" / "c.csv").exists()


def test_fetch_or_load_cells_parallel_downloads(tmp_path):
    """Verifica o comportamento `test fetch or load cells parallel downloads`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    from src.data.ingest_era5_zonal_snapshot import fetch_or_load_cells

    cells = pd.DataFrame(
        [
            {"cell_id": "a", "lat": -7.0, "lon": -39.0},
            {"cell_id": "b", "lat": -7.25, "lon": -39.25},
        ]
    )

    def fake_fetcher(lat, lon):
        """Executa a etapa `fake fetcher` do fluxo FireCast.
        
        A funcao faz parte de `tests/test_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        return pd.DataFrame(
            {"time": ["2024-01-01"], "precipitation_sum": [1.0], "temperature_2m_max": [30.0]}
        )

    rows = fetch_or_load_cells(cells, tmp_path, fetcher=fake_fetcher, workers=2, pause_seconds=0)

    assert [row["cell_id"] for row in rows] == ["a", "b"]
    assert all(not row["cached"] for row in rows)


def test_fetch_or_load_cells_paces_parallel_workers_no_burst(tmp_path):
    """Verifica o comportamento `test fetch or load cells paces parallel workers no burst`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    import time

    from src.data.ingest_era5_zonal_snapshot import fetch_or_load_cells

    cells = pd.DataFrame(
        [
            {"cell_id": "a", "lat": -7.0, "lon": -39.0},
            {"cell_id": "b", "lat": -7.25, "lon": -39.25},
            {"cell_id": "c", "lat": -7.5, "lon": -39.5},
        ]
    )
    call_times: list[float] = []

    def fake_fetcher(lat, lon):
        """Executa a etapa `fake fetcher` do fluxo FireCast.
        
        A funcao faz parte de `tests/test_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        call_times.append(time.monotonic())
        return pd.DataFrame(
            {"time": ["2024-01-01"], "precipitation_sum": [1.0], "temperature_2m_max": [30.0]}
        )

    fetch_or_load_cells(
        cells, tmp_path, fetcher=fake_fetcher, workers=3, pause_seconds=0.2, jitter_seconds=0.0
    )

    assert len(call_times) == 3
    call_times.sort()
    gaps = [b - a for a, b in zip(call_times, call_times[1:])]
    assert all(gap >= 0.18 for gap in gaps), f"chamadas saíram em rajada: gaps={gaps}"


def test_fetch_daily_cell_opens_circuit_breaker_after_max_429_attempts(monkeypatch):
    """Verifica o comportamento `test fetch daily cell opens circuit breaker after max 429 attempts`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    import src.data.ingest_era5_zonal_snapshot as mod

    class FakeResp:
        """Representa `FakeResp` dentro do fluxo FireCast.
        
        A classe concentra dados ou comportamento usado por `tests/test_era5_zonal_snapshot.py` para manter o contrato claro entre ingestao, experimento, serving e auditoria."""
        status_code = 429
        headers: dict = {}

    calls = {"n": 0}

    def fake_get(*args, **kwargs):
        """Executa a etapa `fake get` do fluxo FireCast.
        
        A funcao faz parte de `tests/test_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)

    try:
        mod.fetch_daily_cell(-7.0, -39.0, max_429_attempts=2, max_429_wait_total_seconds=10_000)
        assert False, "deveria ter levantado RateLimitCircuitOpen"
    except mod.RateLimitCircuitOpen as exc:
        assert exc.attempts_429 == 2
    assert calls["n"] == 2


def test_fetch_or_load_cells_stops_batch_and_writes_pause_state_on_circuit_open(tmp_path):
    """Verifica o comportamento `test fetch or load cells stops batch and writes pause state on circuit open`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    import json

    from src.data.ingest_era5_zonal_snapshot import RateLimitCircuitOpen, fetch_or_load_cells

    cells = pd.DataFrame(
        [
            {"cell_id": "a", "lat": -7.0, "lon": -39.0},
            {"cell_id": "b", "lat": -7.25, "lon": -39.25},
            {"cell_id": "c", "lat": -7.5, "lon": -39.5},
        ]
    )

    def fake_fetcher(lat, lon):
        """Executa a etapa `fake fetcher` do fluxo FireCast.
        
        A funcao faz parte de `tests/test_era5_zonal_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        if lat == -7.25:
            raise RateLimitCircuitOpen(lat, lon, attempts_429=2, total_wait_429=90.0)
        return pd.DataFrame(
            {"time": ["2024-01-01"], "precipitation_sum": [1.0], "temperature_2m_max": [30.0]}
        )

    rows = fetch_or_load_cells(cells, tmp_path, fetcher=fake_fetcher, pause_seconds=0)

    assert [row["cell_id"] for row in rows] == ["a"]
    assert not (tmp_path / "daily_cells" / "c.csv").exists()
    pause_path = tmp_path / "rate_limit_pause.json"
    assert pause_path.exists()
    payload = json.loads(pause_path.read_text(encoding="utf-8"))
    assert payload["cell_lat"] == -7.25
    assert payload["attempts_429"] == 2
    assert payload["cells_done_this_run"] == 1
