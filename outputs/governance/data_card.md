# FireCast - Data Card

Atualizado em 2026-07-13. Complementa o model card em `outputs/champion_climatology_regional_intensity12/model_card.md`.

## Alvos

| Uso | Fonte | Snapshot | Regra |
|---|---|---|---|
| Treino/validacao congelados | INPE Programa Queimadas / BDQueimadas, referencia AQUA_M-T historica | `data/snapshots/inpe_local_v2/` | Usar apenas meses disponiveis no corte; gaps suspeitos ficam ausentes, nunca zero fabricado. |
| Scoring 2025/2026 e shadow | INPE publico event-level | `data/snapshots/inpe_monthly_public_v3/` | Filtrar `satellite == AQUA_M-T` para comparabilidade; nao usar 2025/2026 para selecionar parametros. |
| Eventos para auditoria | INPE event points | `data/snapshots/inpe_event_points_v1/` | Agregar somente como auditoria ou features defasadas; target-month nao entra como feature. |

Chave canonica: `geocodigo` IBGE. Nomes normalizados nunca sao chave primaria de uniao.

## Fontes auxiliares reais

| Fonte | Snapshot | Status |
|---|---|---|
| FIRMS MODIS_SP | `firms_modis_sp_ce_v1` | Real NASA FIRMS SP; usado em EXP-15, REJECT para G3. |
| FIRMS VIIRS_SNPP_SP | `firms_viirs_snpp_sp_ce_v1` | Real NASA FIRMS SP; usado em EXP-16, REJECT para G3. |
| FIRMS VIIRS_NOAA20_SP | `firms_viirs_noaa20_sp_ce_v1` | Real NASA FIRMS SP; usado em EXP-17, REJECT para G3. |
| FIRMS multi-sensor | `firms_multi_sensor_ce_v1` | Fonte de auditoria/feature defasada; usado em EXP-18/19, REJECT para G3. |
| Grafo espacial IBGE | `ibge_spatial_graph_v1` | Topologia municipal oficial; usado em EXP-20, REJECT para G3. |
| Populacao IBGE/SIDRA | `ibge_population_estimates_v1` | Pressao humana as-of; usado em EXP-21, REJECT para G3. |
| Area agricola IBGE/PAM | `ibge_pam_crop_area_v1` | Fuel/uso agricola anual as-of; usado em EXP-23, REJECT para G3. |
| INMET observado | `inmet_automatic_station_observed_v1` | Meteorologia real de estacoes; usado em EXP-24, REJECT para G3. |
| ERA5 centroide | `era5_openmeteo_v1` | Usado em EXP-03/04; rejeitado como feature promocional. |
| ERA5 zonal Chapada | `era5_grid_weights_chapada_v1` + `cache/era5_zonal_chapada/` | Usado em EXP-05/06; rejeitado como feature promocional. |
| ENSO Nino 3.4 | `enso_cpc_v1` | NOAA/CPC real; usado em EXP-09; mantido como contexto. |
| Malha municipal IBGE | `ibge_malha_municipal_2024` | Geometria para centroides, pesos zonais, grafo e auditorias. |

## Fontes nao aprovadas para promocao

| Fonte | Motivo |
|---|---|
| `nasa_monthly_enriched_unverified` | Sem `source/retrieved_at/available_at`; uso so exploratorio. |
| `inmet_station_availability_unverified` | Disponibilidade por estacao/mes, nao leituras meteorologicas. |
| NDVI CSV local | Sem QA MODIS, sem `available_at`, sem image IDs; EXP-22 invalido para promocao. |
| MOD13Q1 oficial | Candidato futuro; requer credencial, QA, image IDs e `available_at`. |
| MapBiomas | Candidato futuro; requer download/contrato de uso e manifestos verificaveis. |

## Disponibilidade temporal as-of

Toda feature usada em experimento respeita `shift(1)`, publicacao anterior ao corte ou eventos estritamente anteriores ao mes previsto. O mes previsto nunca entra como feature. Populacao/area usam ano publicado antes do ano previsto. 2025/2026 sao janelas de realidade scoring-only.

## Validacao automatizada

`./firecast data-check` (`scripts/check_data_ingestors.py`) valida snapshots, manifestos, credenciais hardcoded e caminhos ambiguos. Estado atual: 20 snapshots e 26 ingestores OK.

Checklist de ingestao: `checklist/firecast-data-pipeline/references/ingestion-checklist.md`.
