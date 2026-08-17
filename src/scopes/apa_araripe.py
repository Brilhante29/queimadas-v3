"""Escopo oficial da APA Chapada do Araripe, derivado por intersecao espacial.

Por que derivar em vez de listar
--------------------------------
O decreto federal de 04/08/1997 que cria a APA **nao enumera municipios**. O
Art. 3 delimita a unidade por memorial descritivo (curva de nivel de 500 m e
640 m, coordenadas UTM, cartas SUDENE/DSG 1:100.000). A pagina oficial do
ICMBio para a UC tambem nao publica lista de municipios. Consequencia: toda
"lista de N municipios" em circulacao (33, 36, 38) e uma *interpretacao*
derivada do poligono, e as interpretacoes divergem entre si.

Ver ``outputs/apa_araripe/audit/source_research_findings.md`` para a evidencia
primaria (texto do decreto, pagina do ICMBio, divergencia entre fontes).

Definicao operacional adotada
-----------------------------
Escopo = municipios cuja area de intersecao poligonal com o limite oficial da
APA e **maior que zero**. Municipio que apenas encosta na fronteira (intersecao
de area nula) nao entra.

- Poligono da APA: camada oficial ``ICMBio:limiteucsfederais_a``, servida pelo
  geoserver da INDE (Infraestrutura Nacional de Dados Espaciais).
- Malha municipal: API oficial de malhas do IBGE, CE/PE/PI.
- Area medida em projecao equivalente (Albers America do Sul), nunca em graus.

O N **nao e fixado a priori** -- e o resultado da intersecao.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCOPE_CSV = PROJECT_ROOT / "data" / "reference" / "apa_chapada_araripe.csv"
CACHE_DIR = PROJECT_ROOT / "cache" / "apa_araripe_scope"
REPORT_PATH = PROJECT_ROOT / "outputs" / "apa_araripe" / "audit" / "scope_derivation_report.md"

INDE_WFS = "https://geoservicos.inde.gov.br/geoserver/wfs"
UC_LAYER = "ICMBio:limiteucsfederais_a"
IBGE_MALHAS = "https://servicodados.ibge.gov.br/api/v3/malhas/estados"

# Codigos IBGE das UFs de interesse
UF_CODES = {"CE": 23, "PE": 26, "PI": 22}

# Projecao equivalente (equal-area) para America do Sul. Area medida em graus
# (EPSG:4674/4326) seria fisicamente errada; o proprio ICMBio calcula area em
# Albers (campo `areahaalb` da camada oficial).
ALBERS_SA = (
    "+proj=aea +lat_1=-5 +lat_2=-42 +lat_0=-32 +lon_0=-60 "
    "+x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs"
)

MEMBERSHIP_RULE = "area_intersect_apa_km2 > 0"
UA = {"User-Agent": "FireCast APA Araripe scope derivation"}


def _http_get(url: str, timeout: int = 300) -> bytes:
    """Executa a etapa `http get` do fluxo FireCast.

    A funcao faz parte de `src/scopes/apa_araripe.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving.

    A API de malhas do IBGE responde comprimida mesmo sem `Accept-Encoding`,
    entao a descompressao e feita aqui -- caso contrario o GeoJSON chega como
    bytes binarios e o leitor falha com "not recognized as being in a
    supported file format"."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()

    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        import gzip

        raw = gzip.decompress(raw)
    elif encoding == "deflate":
        import zlib

        raw = zlib.decompress(raw)
    return raw


def _cached(name: str, url: str, force: bool = False) -> tuple[bytes, str]:
    """Executa a etapa `cached` do fluxo FireCast.

    Baixa com escrita atomica (.tmp -> rename) e devolve (conteudo, sha256).
    Arquivo parcialmente baixado nunca e tratado como valido."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / name
    if path.exists() and not force:
        raw = path.read_bytes()
        return raw, hashlib.sha256(raw).hexdigest()

    raw = _http_get(url)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return raw, hashlib.sha256(raw).hexdigest()


def fetch_apa_polygon(force: bool = False) -> tuple[gpd.GeoDataFrame, dict]:
    """Executa a etapa `fetch apa polygon` do fluxo FireCast.

    Busca o poligono oficial da APA Chapada do Araripe na camada federal do
    ICMBio publicada pela INDE. Falha fechada se a consulta nao devolver
    exatamente uma UC do tipo APA com Araripe no nome."""
    params = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": UC_LAYER,
            "outputFormat": "application/json",
            "CQL_FILTER": "nomeuc ILIKE '%ARARIPE%'",
        }
    )
    url = f"{INDE_WFS}?{params}"
    raw, sha = _cached("icmbio_ucs_araripe.geojson", url, force=force)
    gdf = gpd.read_file(raw if isinstance(raw, str) else __import__("io").BytesIO(raw))

    # A consulta casa tambem a FLONA Araripe-Apodi, que o proprio decreto
    # EXCLUI da APA. Selecionar explicitamente a APA.
    apa = gdf[gdf["nomeuc"].str.contains("PROTECAO AMBIENTAL|PROTEÇÃO AMBIENTAL", case=False, na=False)]
    if len(apa) != 1:
        names = gdf["nomeuc"].tolist()
        raise ValueError(
            f"Esperava exatamente 1 APA com 'ARARIPE' no nome, encontrei {len(apa)}. "
            f"UCs retornadas: {names}"
        )

    meta = {
        "layer": UC_LAYER,
        "wfs": INDE_WFS,
        "cql": "nomeuc ILIKE '%ARARIPE%'",
        "sha256": sha,
        "bytes": len(raw),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "nomeuc": apa.iloc[0]["nomeuc"],
        "cnuc": apa.iloc[0].get("cnuc"),
        "criacaoano": apa.iloc[0].get("criacaoano"),
        "criacaoato": apa.iloc[0].get("criacaoato"),
        "esferaadm": apa.iloc[0].get("esferaadm"),
        "areahaalb_icmbio": apa.iloc[0].get("areahaalb"),
        "source_crs": str(gdf.crs),
        "other_araripe_ucs_excluded": gdf[~gdf.index.isin(apa.index)]["nomeuc"].tolist(),
    }
    return apa, meta


def fetch_municipal_mesh(force: bool = False) -> tuple[gpd.GeoDataFrame, dict]:
    """Executa a etapa `fetch municipal mesh` do fluxo FireCast.

    Baixa a malha municipal oficial do IBGE para CE, PE e PI."""
    frames = []
    provenance = {}
    for uf, code in UF_CODES.items():
        url = (
            f"{IBGE_MALHAS}/{code}?formato=application/vnd.geo+json"
            f"&intrarregiao=municipio&qualidade=maxima"
        )
        raw, sha = _cached(f"ibge_malha_{uf}.geojson", url, force=force)
        gdf = gpd.read_file(__import__("io").BytesIO(raw))
        gdf["uf"] = uf
        frames.append(gdf)
        provenance[uf] = {"url": url, "sha256": sha, "bytes": len(raw), "n_features": len(gdf)}

    mesh = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    # A API do IBGE devolve o geocodigo em `codarea`
    if "codarea" not in mesh.columns:
        raise ValueError(f"malha IBGE sem coluna 'codarea'; colunas: {list(mesh.columns)}")
    mesh["geocodigo"] = mesh["codarea"].astype(int)
    return mesh, provenance


def derive_scope(force: bool = False) -> tuple[pd.DataFrame, dict]:
    """Executa a etapa `derive scope` do fluxo FireCast.

    Intersecta o poligono oficial da APA com a malha municipal do IBGE e
    devolve o escopo derivado. O N e resultado, nunca premissa."""
    apa, apa_meta = fetch_apa_polygon(force=force)
    mesh, mesh_prov = fetch_municipal_mesh(force=force)

    # Reprojetar para projecao equivalente ANTES de medir area.
    apa_m = apa.to_crs(ALBERS_SA)
    mesh_m = mesh.to_crs(ALBERS_SA)

    repaired = {"apa": 0, "mesh": 0}
    if not apa_m.geometry.is_valid.all():
        repaired["apa"] = int((~apa_m.geometry.is_valid).sum())
        apa_m["geometry"] = apa_m.geometry.buffer(0)
    invalid_mesh = ~mesh_m.geometry.is_valid
    if invalid_mesh.any():
        repaired["mesh"] = int(invalid_mesh.sum())
        mesh_m.loc[invalid_mesh, "geometry"] = mesh_m.loc[invalid_mesh, "geometry"].buffer(0)

    apa_geom = apa_m.geometry.union_all()

    rows = []
    for _, mun in mesh_m.iterrows():
        inter = mun.geometry.intersection(apa_geom)
        if inter.is_empty:
            continue
        area_int_km2 = inter.area / 1e6
        if area_int_km2 <= 0:
            continue
        area_mun_km2 = mun.geometry.area / 1e6
        rows.append(
            {
                "geocodigo": int(mun["geocodigo"]),
                "uf": mun["uf"],
                "area_municipal_km2": round(area_mun_km2, 6),
                "area_intersect_apa_km2": round(area_int_km2, 6),
                "pct_area_municipal_na_apa": round(100.0 * area_int_km2 / area_mun_km2, 4),
            }
        )

    scope = pd.DataFrame(rows).sort_values("pct_area_municipal_na_apa", ascending=False)

    # Nome canonico vem da referencia IBGE do repo (geocodigo e a chave).
    ref_path = PROJECT_ROOT / "data" / "reference" / "ibge_municipios_CE_PE_PI.json"
    ref = json.loads(ref_path.read_text(encoding="utf-8"))
    name_by_geo = {m["geocodigo"]: m["nome"] for m in ref}
    unknown = [g for g in scope["geocodigo"] if g not in name_by_geo]
    if unknown:
        raise ValueError(f"geocodigos fora da referencia IBGE do repo (falha fechada): {unknown}")
    scope.insert(1, "municipio", scope["geocodigo"].map(name_by_geo))

    apa_area_km2 = apa_geom.area / 1e6
    meta = {
        "rule": MEMBERSHIP_RULE,
        "crs_area": ALBERS_SA,
        "apa": apa_meta,
        "ibge_mesh": mesh_prov,
        "geometries_repaired": repaired,
        "apa_area_km2_computed": round(apa_area_km2, 3),
        "n_total": len(scope),
        "n_by_uf": scope["uf"].value_counts().to_dict(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return scope, meta


def write_scope(force: bool = False) -> tuple[pd.DataFrame, dict]:
    """Executa a etapa `write scope` do fluxo FireCast.

    Persiste o CSV canonico do escopo com proveniencia completa."""
    scope, meta = derive_scope(force=force)
    out = scope.copy()
    out["source_boundary"] = f"{INDE_WFS}?typeNames={UC_LAYER}"
    out["source_boundary_version"] = meta["apa"].get("criacaoato") or "n/a"
    out["boundary_sha256"] = meta["apa"]["sha256"]
    out["ibge_mesh_version"] = "IBGE API v3 malhas (qualidade=maxima)"
    out["rule"] = MEMBERSHIP_RULE
    SCOPE_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(SCOPE_CSV, index=False, encoding="utf-8")
    return out, meta


def load_apa_scope() -> pd.DataFrame:
    """Carrega a etapa `load apa scope` do fluxo FireCast.

    Le o escopo canonico ja derivado. Falha fechada se o CSV nao existir --
    nunca deriva silenciosamente na hora de treinar."""
    if not SCOPE_CSV.exists():
        raise FileNotFoundError(
            f"Escopo APA ausente: {SCOPE_CSV}. Rode `python -m src.scopes.apa_araripe` "
            "para deriva-lo a partir das fontes oficiais."
        )
    return pd.read_csv(SCOPE_CSV)


def apa_geocodes() -> set[int]:
    """Carrega a etapa `apa geocodes` do fluxo FireCast."""
    return set(load_apa_scope()["geocodigo"].astype(int).tolist())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Deriva o escopo da APA Chapada do Araripe")
    parser.add_argument("--force", action="store_true", help="ignora cache e rebaixa as fontes")
    args = parser.parse_args()

    scope, meta = write_scope(force=args.force)
    print(json.dumps({"n_total": meta["n_total"], "n_by_uf": meta["n_by_uf"]}, indent=2))
    print(f"escopo -> {SCOPE_CSV}")
    (CACHE_DIR / "derivation_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
