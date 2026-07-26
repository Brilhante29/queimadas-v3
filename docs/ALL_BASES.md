# Todas as Bases Incluidas

Esta entrega inclui todos os diretorios de snapshot presentes no projeto e tambem os arquivos brutos externos preservados na raiz do workspace.

Inclusao nao significa promocao automatica para producao. Bases com `unverified` no nome estao no pacote para auditoria e exploracao, mas precisam de revisao de contrato antes de sustentar qualquer claim de modelo.

## Snapshots

| Snapshot | Status | Arquivos | MB | Manifesto |
|---|---|---:|---:|---|
| `data/snapshots/enso_cpc_v1` | snapshot versionado | 2 | 0.017 | `True` |
| `data/snapshots/era5_grid_weights_cariri_central_v1` | snapshot versionado | 3 | 0.005 | `True` |
| `data/snapshots/era5_grid_weights_chapada_v1` | snapshot versionado | 3 | 0.013 | `True` |
| `data/snapshots/era5_grid_weights_v1` | snapshot versionado | 4 | 0.027 | `True` |
| `data/snapshots/era5_openmeteo_v1` | snapshot versionado | 15 | 11.016 | `True` |
| `data/snapshots/firms_modis_sp_ce_v1` | snapshot versionado | 5 | 24.756 | `True` |
| `data/snapshots/firms_multi_sensor_ce_v1` | snapshot versionado | 2 | 0.799 | `True` |
| `data/snapshots/firms_viirs_noaa20_sp_ce_v1` | snapshot versionado | 5 | 75.295 | `True` |
| `data/snapshots/firms_viirs_snpp_sp_ce_v1` | snapshot versionado | 5 | 108.321 | `True` |
| `data/snapshots/ibge_malha_municipal_2024` | snapshot versionado | 7 | 0.709 | `True` |
| `data/snapshots/ibge_pam_crop_area_v1` | snapshot versionado | 25 | 6.404 | `True` |
| `data/snapshots/ibge_population_estimates_v1` | snapshot versionado | 5 | 0.143 | `True` |
| `data/snapshots/ibge_spatial_graph_v1` | snapshot versionado | 3 | 0.167 | `True` |
| `data/snapshots/inmet_automatic_station_observed_v1` | snapshot versionado | 370 | 251.845 | `True` |
| `data/snapshots/inmet_station_availability_unverified` | nao verificado/exploratorio | 18 | 0.057 | `True` |
| `data/snapshots/inpe_event_points_v1` | snapshot versionado | 3 | 5.439 | `True` |
| `data/snapshots/inpe_local_v1` | snapshot versionado | 4 | 0.632 | `True` |
| `data/snapshots/inpe_local_v2` | snapshot versionado | 5 | 1.337 | `True` |
| `data/snapshots/inpe_monthly_public_v3` | snapshot versionado | 22 | 678.108 | `True` |
| `data/snapshots/nasa_monthly_enriched_unverified` | nao verificado/exploratorio | 18 | 0.109 | `True` |

## Bases Brutas Externas

| Arquivo | Status | MB |
|---|---|---:|
| `data/raw_external_bases/availability.zip` | base bruta preservada | 0.017 |
| `data/raw_external_bases/dados.zip` | base bruta preservada | 0.075 |
| `data/raw_external_bases/dados_INPE.zip` | base bruta preservada | 0.357 |
| `data/raw_external_bases/dados_INPE_Monitor.zip` | base bruta preservada | 0.027 |
| `data/raw_external_bases/dados_mensais_enriquecidos_nasa.zip` | base bruta preservada | 0.039 |
| `data/raw_external_bases/NDVI_Ceara_Municipios_Mensal_FINAL.csv` | base bruta preservada | 6.183 |

## Leitura Operacional

- INPE e a fonte do alvo de focos de queimadas.
- INMET e contexto meteorologico/estacoes; nao e alvo de queimadas.
- FIRMS e camada independente de auditoria e comparacao de sensores.
- ERA5/Open-Meteo, ENSO, IBGE, populacao e PAM sao camadas de contexto ou features candidatas, sempre respeitando regras as-of.
