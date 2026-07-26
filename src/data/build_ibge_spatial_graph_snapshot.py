"""Modulo publico do FireCast para ingestao, contratos e preparacao de bases reais.

Arquivo `src/data/build_ibge_spatial_graph_snapshot.py` mantem uma parte reproduzivel do pipeline, com contratos explicitos para dados reais, avaliacao temporal e manutencao do projeto."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MALHA = PROJECT_ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi.geojson"
TARGET = PROJECT_ROOT / "data" / "snapshots" / "inpe_local_v2" / "inpe_monthly_merged.csv"
OUT_DIR = PROJECT_ROOT / "data" / "snapshots" / "ibge_spatial_graph_v1"
AREA_CRS = "EPSG:5880"


def sha256_file(path: Path) -> str:
    """Executa a etapa `sha256 file` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_ibge_spatial_graph_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_target_geometries() -> list[dict[str, object]]:
    """Carrega a etapa `load target geometries` do fluxo FireCast.
    
    A funcao faz parte de `src/data/build_ibge_spatial_graph_snapshot.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
    target_codes = set(pd.read_csv(TARGET)["geocodigo"].drop_duplicates().astype(int).tolist())
    raw = json.loads(MALHA.read_text(encoding="utf-8"))
    transformer = Transformer.from_crs("EPSG:4326", AREA_CRS, always_xy=True)
    records: list[dict[str, object]] = []
    for feature in raw.get("features", []):
        props = feature.get("properties", {})
        geocodigo = int(props["geocodigo"])
        if geocodigo not in target_codes:
            continue
        geom = transform(transformer.transform, shape(feature["geometry"]))
        records.append(
            {
                "geocodigo": geocodigo,
                "municipio_ibge": props["municipio_ibge"],
                "uf": props["uf"],
                "geometry": geom,
            }
        )
    if len(records) != len(target_codes):
        found = {int(r["geocodigo"]) for r in records}
        missing = sorted(target_codes - found)
        raise ValueError(f"IBGE malha does not cover every target municipality: {missing[:10]}")
    return records


def main() -> None:
    """Executa o ponto de entrada de linha de comando.
    
    L? argumentos, chama as rotinas principais de `src/data/build_ibge_spatial_graph_snapshot.py` e retorna erro claro quando o contrato operacional nao e atendido."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records = load_target_geometries()
    centroids = [record["geometry"].centroid for record in records]
    nodes = pd.DataFrame(
        {
            "geocodigo": [int(record["geocodigo"]) for record in records],
            "municipio_ibge": [record["municipio_ibge"] for record in records],
            "uf": [record["uf"] for record in records],
            "area_km2": [record["geometry"].area / 1_000_000.0 for record in records],
            "perimeter_km": [record["geometry"].length / 1_000.0 for record in records],
            "centroid_x_m": [centroid.x for centroid in centroids],
            "centroid_y_m": [centroid.y for centroid in centroids],
        }
    )
    nodes["compactness_iso"] = (
        4.0 * 3.141592653589793 * nodes["area_km2"] / (nodes["perimeter_km"] ** 2)
    ).clip(lower=0.0, upper=1.0)

    edge_rows: list[dict[str, object]] = []
    for src in records:
        distances: list[tuple[int, dict[str, object], float, bool]] = []
        for dst in records:
            if int(src["geocodigo"]) == int(dst["geocodigo"]):
                continue
            distance_km = float(src["geometry"].distance(dst["geometry"]) / 1_000.0)
            touches = bool(src["geometry"].touches(dst["geometry"]) or src["geometry"].intersects(dst["geometry"]))
            distances.append((int(dst["geocodigo"]), dst, distance_km, touches))
        distances.sort(key=lambda item: (item[2], item[0]))
        for rank, (dst_code, dst, distance_km, touches) in enumerate(distances, start=1):
            edge_rows.append(
                {
                    "src_geocodigo": int(src["geocodigo"]),
                    "src_municipio": src["municipio_ibge"],
                    "src_uf": src["uf"],
                    "dst_geocodigo": dst_code,
                    "dst_municipio": dst["municipio_ibge"],
                    "dst_uf": dst["uf"],
                    "centroid_distance_km": distance_km,
                    "touches_border": touches,
                    "nearest_rank": rank,
                    "inverse_distance_weight": 1.0 / (distance_km + 1.0),
                }
            )
    edges = pd.DataFrame(edge_rows)
    nodes.to_csv(OUT_DIR / "nodes.csv", index=False)
    edges.to_csv(OUT_DIR / "edges.csv", index=False)

    border_degree = edges[edges["touches_border"]].groupby("src_geocodigo").size()
    nearest_3 = edges[edges["nearest_rank"] <= 3].groupby("src_geocodigo").size()
    if not nodes["geocodigo"].isin(nearest_3.index.astype(int)).all():
        raise ValueError("Every municipality must have at least three nearest-neighbor edges")

    manifest = {
        "snapshot_name": OUT_DIR.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": "static_spatial_graph_for_lagged_neighbor_fire_features",
        "source_geometry": str(MALHA.relative_to(PROJECT_ROOT)),
        "source_geometry_sha256": sha256_file(MALHA),
        "target_snapshot": str(TARGET.relative_to(PROJECT_ROOT)),
        "target_snapshot_sha256": sha256_file(TARGET),
        "crs_area_distance": AREA_CRS,
        "nodes": int(len(nodes)),
        "edges": int(len(edges)),
        "border_edges": int(edges["touches_border"].sum()),
        "min_border_degree": int(border_degree.min()) if len(border_degree) else 0,
        "min_nearest3_degree": int(nearest_3.min()) if len(nearest_3) else 0,
        "files": {
            "nodes.csv": {"sha256": sha256_file(OUT_DIR / "nodes.csv"), "rows": int(len(nodes))},
            "edges.csv": {"sha256": sha256_file(OUT_DIR / "edges.csv"), "rows": int(len(edges))},
        },
        "available_at_rule": "Static IBGE 2024 municipal geometry is only used for graph topology; all fire-pressure features derived on this graph must be shifted before each prediction cut.",
        "limitations": [
            "IBGE qualidade=minima geometry is adequate for graph/nearest-neighbor hypotheses but not final high-resolution distance-to-road/fuel statistics",
            "topology is static and does not encode vegetation, roads, or population by itself",
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"nodes": len(nodes), "edges": len(edges), "border_edges": int(edges["touches_border"].sum())}, indent=2))


if __name__ == "__main__":
    main()
