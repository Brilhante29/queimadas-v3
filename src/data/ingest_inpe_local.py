"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/ingest_inpe_local.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

import hashlib
import io
import json
import re
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2"

ZIP_SOURCES = {
    "inpe_bdq_aqua_ref": ["dados_INPE.zip", "dados_INPE_Monitor.zip"],
    "inpe_bdq_legacy": ["dados.zip"],
}

# preferência de fusão por frescor (ver docstring, correção 4)
MERGE_REF_UNTIL = pd.Period("2024-12", freq="M")

NAME_ALIASES = {
    "campo sales": "campos sales",
    "sao goncalo": "sao goncalo do amarante",
}

STATE_SUFFIX_RE = re.compile(r"\s+(ce|ceara)$")
YEAR_FILE_RE = re.compile(r"_(\d{4})_\d+\.csv$")


def normalize_name(name: str) -> str:
    """Executa a etapa `normalize name` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    s = unicodedata.normalize("NFKD", str(name))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("_", " ").replace("-", " ").replace("'", "")
    s = re.sub(r"\s+", " ", s).strip()
    s = STATE_SUFFIX_RE.sub("", s).strip()
    return NAME_ALIASES.get(s, s)


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ibge_lookup() -> dict:
    """Carrega a etapa `load ibge lookup` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    ref = REFERENCE_DIR / "ibge_municipios_CE_PE_PI.json"
    if not ref.exists():
        raise FileNotFoundError(
            f"Snapshot IBGE ausente: {ref}. Rodar a ingestão IBGE antes (fail closed)."
        )
    records = json.loads(ref.read_text(encoding="utf-8-sig"))
    lookup = {}
    for r in records:
        key = normalize_name(r["nome"])
        lookup[(key, r["uf"])] = (int(r["geocodigo"]), r["nome"], r["uf"])
    return lookup


UF_BY_STATE_NAME = {"ceara": "CE", "pernambuco": "PE", "piaui": "PI"}


def zip_export_period(zip_path: Path) -> pd.Period:
    """Executa a etapa `zip export period` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    with zipfile.ZipFile(zip_path) as zf:
        latest = max(i.date_time for i in zf.infolist() if i.filename.endswith(".csv"))
    return pd.Period(f"{latest[0]}-{latest[1]:02d}", freq="M")


def parse_format_a(text: str, source_file: str) -> pd.DataFrame:
    """Executa a etapa `parse format a` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    out = pd.DataFrame(
        {
            "event_time_utc": pd.to_datetime(df["Data / Hora"], utc=True, errors="coerce"),
            "satellite": df["Satélite"].astype(str).str.strip(),
            "state_name": df["Estado"].astype(str).str.strip(),
            "municipality_raw": df["Município"].astype(str).str.strip(),
            "bioma": df.get("Bioma"),
            "dias_sem_chuva": pd.to_numeric(df.get("N. Dias Sem Chuva"), errors="coerce"),
            "precipitacao": pd.to_numeric(df.get("Precipitação"), errors="coerce"),
            "risco_fogo": pd.to_numeric(df.get("Risco Fogo"), errors="coerce"),
            "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
            "lon": pd.to_numeric(df["Longitude"], errors="coerce"),
            "frp": pd.to_numeric(df.get("FRP"), errors="coerce"),
        }
    )
    out["source_file"] = source_file
    local = out["event_time_utc"].dt.tz_convert("Etc/GMT+3")
    out["ano"] = local.dt.year
    out["mes"] = local.dt.month
    out["event_date_local"] = local.dt.date.astype(str)
    return out


def parse_format_b(text: str, source_file: str) -> pd.DataFrame:
    """Executa a etapa `parse format b` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    dt = pd.to_datetime(df["DataHora"], dayfirst=True, errors="coerce")
    out = pd.DataFrame(
        {
            "event_time_utc": pd.NaT,
            "satellite": "UNKNOWN",
            "state_name": df["Estado"].astype(str).str.strip(),
            "municipality_raw": df["Municipio"].astype(str).str.strip(),
            "bioma": df.get("Bioma"),
            "dias_sem_chuva": pd.to_numeric(df.get("DiaSemChuva"), errors="coerce"),
            "precipitacao": pd.to_numeric(df.get("Precipitacao"), errors="coerce"),
            "risco_fogo": pd.to_numeric(df.get("RiscoFogo"), errors="coerce"),
            "lat": pd.to_numeric(df["Latitude"], errors="coerce"),
            "lon": pd.to_numeric(df["Longitude"], errors="coerce"),
            "frp": pd.to_numeric(df.get("FRP"), errors="coerce"),
        }
    )
    out["source_file"] = source_file
    out["ano"] = dt.dt.year
    out["mes"] = dt.dt.month
    out["event_date_local"] = dt.dt.date.astype(str)
    return out


def read_zip_events(zip_path: Path, parser) -> pd.DataFrame:
    """Carrega a etapa `read zip events` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    frames = []
    with zipfile.ZipFile(zip_path) as zf:
        for entry in zf.namelist():
            if not entry.lower().endswith(".csv"):
                continue
            raw = zf.read(entry)
            text = raw.decode("utf-8-sig", errors="replace")
            frames.append(parser(text, f"{zip_path.name}:{entry}"))
    if not frames:
        raise ValueError(f"Nenhum CSV encontrado em {zip_path}")
    return pd.concat(frames, ignore_index=True)


def map_geocode(events: pd.DataFrame, lookup: dict) -> pd.DataFrame:
    """Executa a etapa `map geocode` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    events = events.copy()
    events["mun_norm"] = events["municipality_raw"].map(normalize_name)
    events["uf"] = events["state_name"].map(lambda s: UF_BY_STATE_NAME.get(normalize_name(s)))
    if events["uf"].isna().any():
        bad = sorted(events.loc[events["uf"].isna(), "state_name"].unique())
        raise ValueError(f"Estados não mapeados (fail closed): {bad}")

    keys = list(zip(events["mun_norm"], events["uf"]))
    mapped = [lookup.get(k) for k in keys]
    missing = sorted({k for k, m in zip(keys, mapped) if m is None})
    if missing:
        raise ValueError(f"Municípios sem geocódigo IBGE (fail closed): {missing}")
    events["geocodigo"] = [m[0] for m in mapped]
    events["municipio_ibge"] = [m[1] for m in mapped]
    return events


def aggregate_monthly(events: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Executa a etapa `aggregate monthly` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    g = events.groupby(["geocodigo", "municipio_ibge", "uf", "ano", "mes"], as_index=False)
    monthly = g.agg(
        fire_count=("lat", "size"),
        frp_sum=("frp", "sum"),
        frp_mean=("frp", "mean"),
        frp_max=("frp", "max"),
        risco_fogo_mean=("risco_fogo", "mean"),
        dias_sem_chuva_mean=("dias_sem_chuva", "mean"),
    )
    monthly["source_name"] = source_name
    return monthly


def coverage_ref(events: pd.DataFrame, export_caps: dict) -> pd.DataFrame:
    """Executa a etapa `coverage ref` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    events = events.copy()
    events["zip_name"] = events["source_file"].str.split(":").str[0]
    events["file_year"] = events["source_file"].str.extract(YEAR_FILE_RE)[0].astype(float)
    events["period"] = pd.PeriodIndex.from_fields(year=events["ano"], month=events["mes"], freq="M")

    rows = []
    for (geo, mun, uf), g in events.groupby(["geocodigo", "municipio_ibge", "uf"]):
        zips = set(g["zip_name"])
        if "dados_INPE.zip" in zips:
            cap = export_caps["dados_INPE.zip"] - 1
            annual = g[g["zip_name"] == "dados_INPE.zip"]
            last_file_year = int(annual["file_year"].max())
            end = min(pd.Period(f"{last_file_year}-12", freq="M"), cap)
            # se também está no monitor (mais fresco), estender até o cap do monitor
            if "dados_INPE_Monitor.zip" in zips:
                end = max(end, export_caps["dados_INPE_Monitor.zip"] - 1)
            start = pd.Period("2003-01", freq="M")
        else:  # somente monitor
            cap = export_caps["dados_INPE_Monitor.zip"] - 1
            start = g["period"].min()
            end = min(g["period"].max(), cap)
        rows.append({"geocodigo": geo, "municipio_ibge": mun, "uf": uf,
                     "coverage_start": start, "coverage_end": end,
                     "total_events": len(g)})
    return pd.DataFrame(rows)


def coverage_legacy(events: pd.DataFrame, export_caps: dict) -> pd.DataFrame:
    """Executa a etapa `coverage legacy` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    events = events.copy()
    events["period"] = pd.PeriodIndex.from_fields(year=events["ano"], month=events["mes"], freq="M")
    cap = export_caps["dados.zip"] - 1
    cov = (
        events.groupby(["geocodigo", "municipio_ibge", "uf"], as_index=False)
        .agg(coverage_start=("period", "min"), coverage_end=("period", "max"),
             total_events=("lat", "size"))
    )
    cov["coverage_end"] = cov["coverage_end"].map(lambda p: min(p, cap))
    return cov


def fill_zero_months(monthly: pd.DataFrame, coverage: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Executa a etapa `fill zero months` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    rows = []
    for _, c in coverage.iterrows():
        # An event newer than the export cutoff does not establish a usable
        # coverage window. Keep it documented in coverage_report, but never
        # fabricate a reverse/empty monthly range for model input.
        if c["coverage_start"] > c["coverage_end"]:
            continue
        periods = pd.period_range(c["coverage_start"], c["coverage_end"], freq="M")
        rows.append(
            pd.DataFrame(
                {
                    "geocodigo": c["geocodigo"],
                    "municipio_ibge": c["municipio_ibge"],
                    "uf": c["uf"],
                    "ano": periods.year,
                    "mes": periods.month,
                }
            )
        )
    if not rows:
        empty = monthly.iloc[0:0].copy()
        empty["assumed_zero"] = pd.Series(dtype=bool)
        empty["source_name"] = source_name
        return empty
    grid = pd.concat(rows, ignore_index=True)
    merged = grid.merge(
        monthly.drop(columns=["source_name"]),
        on=["geocodigo", "municipio_ibge", "uf", "ano", "mes"],
        how="left",
    )
    merged["assumed_zero"] = merged["fire_count"].isna()
    merged["fire_count"] = merged["fire_count"].fillna(0).astype(int)
    merged["frp_sum"] = merged["frp_sum"].fillna(0.0)
    merged["source_name"] = source_name
    return merged


def flag_legacy_gaps(filled: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `flag legacy gaps` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    filled = filled.copy()
    filled["suspect_gap"] = False
    season = filled["mes"].isin([8, 9, 10, 11, 12])
    totals = (
        filled[season]
        .groupby(["geocodigo", "ano"])["fire_count"].sum()
        .unstack("ano")
    )
    for geo, row in totals.iterrows():
        years = [y for y in row.index if pd.notna(row.get(y))]
        for y in years:
            prev_v, next_v = row.get(y - 1), row.get(y + 1)
            if (
                row[y] == 0
                and pd.notna(prev_v) and prev_v > 0
                and pd.notna(next_v) and next_v > 0
            ):
                mask = (filled["geocodigo"] == geo) & (filled["ano"] == y) & season
                filled.loc[mask, "suspect_gap"] = True
    filled.loc[filled["suspect_gap"], "fire_count"] = np.nan
    return filled


def merge_sources(ref: pd.DataFrame, leg: pd.DataFrame) -> pd.DataFrame:
    """Executa a etapa `merge sources` do fluxo FireCast.
    
    A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    ref = ref.copy()
    leg = leg.copy()
    for df in (ref, leg):
        df["period"] = pd.PeriodIndex.from_fields(year=df["ano"], month=df["mes"], freq="M")

    early_pref, late_pref = [], []
    for df, name in ((ref, "ref"), (leg, "legacy")):
        early = df[df["period"] <= MERGE_REF_UNTIL]
        late = df[df["period"] > MERGE_REF_UNTIL]
        if name == "ref":
            early_pref.append(early)   # ref preferida até 2024-12
            late_fallback = late
        else:
            early_fallback = early
            late_pref.append(late)     # legado preferido de 2025-01 em diante

    def prefer(primary: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
        """Executa a etapa `prefer` do fluxo FireCast.
        
        A funcao faz parte de `src/data/ingest_inpe_local.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        keys = set(zip(primary["geocodigo"], primary["ano"], primary["mes"]))
        extra = fallback[
            ~fallback.apply(lambda r: (r["geocodigo"], r["ano"], r["mes"]) in keys, axis=1)
        ]
        return pd.concat([primary, extra], ignore_index=True)

    early = prefer(pd.concat(early_pref, ignore_index=True), early_fallback)
    late = prefer(pd.concat(late_pref, ignore_index=True), late_fallback)
    merged = pd.concat([early, late], ignore_index=True)
    merged = merged.rename(columns={"source_name": "target_source"})
    merged = merged.sort_values(["geocodigo", "ano", "mes"]).reset_index(drop=True)
    return merged.drop(columns=["period"])


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/ingest_inpe_local.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    retrieved_at = datetime.now(timezone.utc).isoformat()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    lookup = load_ibge_lookup()

    export_caps = {}
    for zips in ZIP_SOURCES.values():
        for zn in zips:
            export_caps[zn] = zip_export_period(REPO_ROOT / zn)

    manifest = {
        "snapshot_name": "inpe_local_v2",
        "created_at": retrieved_at,
        "role": "target",
        "official_url": "https://data.inpe.br/queimadas/portal/dados-abertos/",
        "license": "dados abertos INPE",
        "export_dates_from_zip_timestamps": {k: str(v) for k, v in export_caps.items()},
        "available_at_rule": (
            "cobertura de cada fonte limitada ao mes anterior ao export do zip; "
            "zeros presumidos apenas dentro da janela comprovada"
        ),
        "merge_rule": (
            f"meses <= {MERGE_REF_UNTIL} preferem inpe_bdq_aqua_ref; "
            "meses posteriores preferem inpe_bdq_legacy (export mais fresco); "
            "fallback para a outra fonte"
        ),
        "timezone_rule": "mes atribuido em horario local America/Fortaleza (UTC-3 fixo)",
        "deduplication_rule": "drop_duplicates(event_date/time, lat, lon, satellite) por fonte",
        "keys": ["geocodigo", "ano", "mes", "source_name"],
        "sources": {},
    }

    per_source = {}
    all_coverage = []

    for source_name, zip_names in ZIP_SOURCES.items():
        frames = []
        zip_meta = []
        for zip_name in zip_names:
            zip_path = REPO_ROOT / zip_name
            if not zip_path.exists():
                raise FileNotFoundError(f"Snapshot bruto ausente: {zip_path} (fail closed)")
            parser = parse_format_a if source_name == "inpe_bdq_aqua_ref" else parse_format_b
            df = read_zip_events(zip_path, parser)
            zip_meta.append({"file": zip_name, "sha256": sha256_file(zip_path), "rows": int(len(df))})
            frames.append(df)
        events = pd.concat(frames, ignore_index=True)

        n_before = len(events)
        bad_dates = events["ano"].isna().sum()
        if bad_dates:
            raise ValueError(f"{source_name}: {bad_dates} eventos com data inválida (fail closed)")
        dedup_cols = ["event_date_local", "lat", "lon", "satellite"]
        if source_name == "inpe_bdq_aqua_ref":
            dedup_cols = ["event_time_utc", "lat", "lon", "satellite"]
        events = events.drop_duplicates(subset=dedup_cols)

        events = map_geocode(events, lookup)
        monthly = aggregate_monthly(events, source_name)

        if source_name == "inpe_bdq_aqua_ref":
            cov = coverage_ref(events, export_caps)
        else:
            cov = coverage_legacy(events, export_caps)

        cov["coverage_valid"] = cov["coverage_start"] <= cov["coverage_end"]
        cov["exclusion_reason"] = np.where(
            cov["coverage_valid"],
            "",
            "first_observation_after_export_cutoff",
        )

        filled = fill_zero_months(monthly, cov, source_name)
        filled = flag_legacy_gaps(filled)

        per_source[source_name] = filled
        cov = cov.copy()
        cov["source_name"] = source_name
        cov["coverage_start"] = cov["coverage_start"].astype(str)
        cov["coverage_end"] = cov["coverage_end"].astype(str)
        all_coverage.append(cov)

        manifest["sources"][source_name] = {
            "zips": zip_meta,
            "events_raw": int(n_before),
            "events_deduplicated": int(len(events)),
            "duplicates_removed": int(n_before - len(events)),
            "satellites": sorted(events["satellite"].unique().tolist()),
            "sensor_note": (
                "AQUA_M-T (satelite de referencia INPE)"
                if source_name == "inpe_bdq_aqua_ref"
                else "sensor NAO informado no formato legado; validado via overlap_validation.csv"
            ),
            "municipalities": int(events["geocodigo"].nunique()),
            "municipalities_with_valid_coverage": int(cov.loc[cov["coverage_valid"], "geocodigo"].nunique()),
            "suspect_gap_months": int(filled["suspect_gap"].sum()),
        }

    monthly_all = pd.concat(per_source.values(), ignore_index=True)
    coverage_all = pd.concat(all_coverage, ignore_index=True)
    merged = merge_sources(per_source["inpe_bdq_aqua_ref"], per_source["inpe_bdq_legacy"])
    excluded = coverage_all.loc[
        ~coverage_all["coverage_valid"],
        ["geocodigo", "municipio_ibge", "uf", "source_name", "exclusion_reason"],
    ].drop_duplicates()
    manifest["excluded_municipalities"] = excluded.to_dict("records")

    # validação cruzada nos meses em que ambas cobrem (fire_count não-NaN)
    ref_m = per_source["inpe_bdq_aqua_ref"].dropna(subset=["fire_count"])
    leg_m = per_source["inpe_bdq_legacy"].dropna(subset=["fire_count"])
    common = set(ref_m["geocodigo"]).intersection(leg_m["geocodigo"])
    overlap_rows = []
    for geo in sorted(common):
        a = ref_m[ref_m["geocodigo"] == geo][["ano", "mes", "fire_count"]]
        b = leg_m[leg_m["geocodigo"] == geo][["ano", "mes", "fire_count"]]
        m = a.merge(b, on=["ano", "mes"], suffixes=("_ref", "_legacy"))
        if len(m) == 0:
            continue
        corr = m["fire_count_ref"].corr(m["fire_count_legacy"]) if len(m) > 2 else np.nan
        overlap_rows.append({
            "geocodigo": geo,
            "months_overlap": len(m),
            "exact_match_share": float((m["fire_count_ref"] == m["fire_count_legacy"]).mean()),
            "corr": float(corr) if pd.notna(corr) else None,
            "ref_total": int(m["fire_count_ref"].sum()),
            "legacy_total": int(m["fire_count_legacy"].sum()),
        })
    overlap = pd.DataFrame(overlap_rows)

    monthly_all.to_csv(SNAPSHOT_DIR / "inpe_monthly.csv", index=False)
    merged.to_csv(SNAPSHOT_DIR / "inpe_monthly_merged.csv", index=False)
    coverage_all.to_csv(SNAPSHOT_DIR / "coverage_report.csv", index=False)
    overlap.to_csv(SNAPSHOT_DIR / "overlap_validation.csv", index=False)

    manifest["outputs"] = {}
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for out_name in ["inpe_monthly.csv", "inpe_monthly_merged.csv"]:
        manifest["outputs"][out_name] = {"sha256": sha256_file(SNAPSHOT_DIR / out_name)}
    manifest["outputs"]["inpe_monthly.csv"]["rows"] = int(len(monthly_all))
    manifest["outputs"]["inpe_monthly_merged.csv"]["rows"] = int(len(merged))
    (SNAPSHOT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"OK snapshot {SNAPSHOT_DIR}")
    print(f"  linhas mensais (por fonte): {len(monthly_all)}")
    print(f"  linhas mensais (merged):    {len(merged)}")
    print(f"  municipios: {merged['geocodigo'].nunique()}")
    for src, meta in manifest["sources"].items():
        print(f"  {src}: {meta['events_deduplicated']} eventos, {meta['municipalities']} municipios, "
              f"suspect_gap_months={meta['suspect_gap_months']}")
    if len(overlap):
        print("  validacao cruzada (meses validos em ambas):")
        print(overlap.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
