"""Testes publicos do FireCast para tests/test_inmet_station_snapshot.py.

Validam contratos, metricas, grafo XAI, dados e comportamento fail-closed para que a entrega possa ser conferida por terceiros."""
import numpy as np
import pandas as pd

from src.data.ingest_inmet_automatic_station_observations import (
    build_municipal_monthly,
    find_column,
    parse_metadata,
    to_float,
)

HEAD_2024 = (
    "REGIAO;NE\n"
    "UF;CE\n"
    "ESTACAO;CRATEUS\n"
    "CODIGO (WMO);A342\n"
    "LATITUDE;-5,17\n"
    "LONGITUDE;-40,66\n"
    "ALTITUDE;296,82\n"
    "DATA DE FUNDACAO;17/08/07\n"
).encode("latin1")

HEAD_2014 = (
    "REGI\xc3O:;NE\n"
    "UF:;CE\n"
    "ESTA\xc7\xc3O:;FORTALEZA\n"
    "CODIGO (WMO):;A305\n"
    "LATITUDE:;-3,83222221\n"
    "LONGITUDE:;-38,53777777\n"
    "ALTITUDE:;26,45\n"
    "DATA DE FUNDA\xc7\xc3O (YYYY-MM-DD):;2003-02-18\n"
).encode("latin1")


def test_parse_metadata_handles_both_header_vintages():
    """Verifica o comportamento `test parse metadata handles both header vintages`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    new = parse_metadata(HEAD_2024, "new.csv", [(-5.2, -40.7)])
    old = parse_metadata(HEAD_2014, "old.csv", [(-3.8, -38.5)])
    assert new is not None and new.station_code == "A342" and new.uf == "CE"
    assert old is not None and old.station_code == "A305" and old.uf == "CE"
    assert abs(old.latitude - (-3.83222221)) < 1e-9
    assert new.min_target_distance_km < 20.0


def test_find_column_matches_both_column_vintages():
    """Verifica o comportamento `test find column matches both column vintages`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    cols_2014 = ["DATA (YYYY-MM-DD)", "HORA (UTC)", "PRECIPITA\xc7\xc3O TOTAL, HOR\xc1RIO (mm)"]
    cols_2024 = ["Data", "Hora UTC", "PRECIPITACAO TOTAL, HORARIO (mm)"]
    assert find_column(cols_2014, "Hora UTC") == "HORA (UTC)"
    assert find_column(cols_2024, "Hora UTC") == "Hora UTC"
    assert find_column(cols_2014, "PRECIPITACAO TOTAL") == "PRECIPITA\xc7\xc3O TOTAL, HOR\xc1RIO (mm)"


def test_to_float_handles_comma_decimal_and_sentinel():
    """Verifica o comportamento `test to float handles comma decimal and sentinel`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    series = pd.Series(["1009,1", "-9999", "", "27", None])
    out = to_float(series)
    assert out.iloc[0] == 1009.1
    assert np.isnan(out.iloc[1])
    assert np.isnan(out.iloc[2])
    assert out.iloc[3] == 27.0


def test_build_municipal_monthly_idw_weights_and_coverage():
    """Verifica o comportamento `test build municipal monthly idw weights and coverage`.
    
    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    station_monthly = pd.DataFrame(
        [
            {
                "station_code": "S1", "ano": 2024, "mes": 1,
                "precip_total_mm": 100.0, "temp_mean_c": 30.0, "rh_mean_pct": 60.0,
                "wind_mean_ms": 2.0, "gust_max_ms": 8.0, "radiation_sum_kj_m2": 1000.0,
                "precip_mm_observed_fraction": 1.0, "temp_c_observed_fraction": 1.0,
                "rh_pct_observed_fraction": 1.0, "wind_ms_observed_fraction": 1.0,
                "gust_ms_observed_fraction": 1.0, "radiation_kj_m2_observed_fraction": 1.0,
                "station_observed_fraction_mean": 1.0,
            },
            {
                "station_code": "S2", "ano": 2024, "mes": 1,
                "precip_total_mm": 0.0, "temp_mean_c": 34.0, "rh_mean_pct": 40.0,
                "wind_mean_ms": 3.0, "gust_max_ms": 10.0, "radiation_sum_kj_m2": 1400.0,
                "precip_mm_observed_fraction": 0.01, "temp_c_observed_fraction": 1.0,
                "rh_pct_observed_fraction": 1.0, "wind_ms_observed_fraction": 1.0,
                "gust_ms_observed_fraction": 1.0, "radiation_kj_m2_observed_fraction": 1.0,
                "station_observed_fraction_mean": 0.8,
            },
        ]
    )
    station_meta = pd.DataFrame(
        [
            {"station_code": "S1", "latitude": -5.0, "longitude": -40.0},
            {"station_code": "S2", "latitude": -6.0, "longitude": -41.0},
        ]
    )
    centroids = pd.DataFrame(
        [{"geocodigo": "2300000", "municipio_ibge": "Teste", "uf": "CE", "latitude": -5.0, "longitude": -40.0}]
    )

    out = build_municipal_monthly(station_monthly, station_meta, centroids)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["inmet_station_count_any"] == 2
    assert row["inmet_nearest_station_km"] < 1.0
    # S2 precip fails the observed-fraction floor, so precip uses S1 only.
    assert row["inmet_precip_total_mm_station_count"] == 1
    assert row["inmet_precip_total_mm_idw"] == 100.0
    # Temperature uses both stations, dominated by the co-located S1.
    assert row["inmet_temp_mean_c_station_count"] == 2
    assert 30.0 < row["inmet_temp_mean_c_idw"] < 31.0
