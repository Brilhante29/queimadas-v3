# Data Handoff

The fire-count target comes from INPE, not INMET.

- `data/snapshots/inpe_local_v2/inpe_monthly_merged.csv`: historical training target.
- `data/snapshots/inpe_monthly_public_v3/events_target_region.csv`: public event-level scoring target for 2025/2026; filter `satelite == "AQUA_M-T"` before comparing with the model target.
- `data/snapshots/inpe_monthly_public_v3/monthly_target_region.csv`: monthly aggregation for the same public target region.
- `data/snapshots/inmet_automatic_station_observed_v1/municipal_monthly_station_features.csv`: INMET-derived weather/station features and validation context.

INMET is included because it explains/validates local weather conditions, but it is sparse relative to the municipalities. The fire label remains INPE.

## Complete Base Inventory

All 20 snapshot directories are included in this package. Use `docs/ALL_BASES.md` for the human-readable list and `data/ALL_BASES_MANIFEST.json` for the machine-readable manifest. Raw received files are preserved under `data/raw_external_bases/`.
