"""Dashboard Streamlit para demonstrar o FireCast e seu XAI verificavel.

A aplicacao apresenta metricas congeladas, comparacao real versus predito,
robustez por municipio e o grafo XAI do modelo champion. O Ollama e usado
apenas como narrador local: a previsao vem do artefato glass-box e qualquer
narrativa gerada por LLM passa pelo verificador numerico antes de aparecer como
validada.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.production.champion_climatology import ChampionClimatologyModel  # noqa: E402
from src.production.llm_xai import (  # noqa: E402
    NarrativeValidationError,
    build_verified_xai_response,
    verify_narrative_against_packet,
)

MODEL_PATH = ROOT / "outputs" / "champion_climatology_regional_intensity12" / "model.json"
SUMMARY_PATH = ROOT / "outputs" / "public_results_summary.json"
REALITY_PATH = ROOT / "outputs" / "exp27_reality_volume_2025_2026" / "monthly_reality_comparison.csv"
BACKTEST_PATH = ROOT / "outputs" / "exp10_dynamic_regional_intensity" / "predictions_2023_2024.csv"
MUNICIPIO_PATH = ROOT / "outputs" / "g4_spatial_robustness_exp10_2023_2024" / "by_municipio.csv"
ATTRIBUTES_PATH = ROOT / "data" / "snapshots" / "ibge_malha_municipal_2024" / "municipios_ce_pe_pi_attributes.csv"
BASES_PATH = ROOT / "data" / "ALL_BASES_MANIFEST.json"
G3_PATH = ROOT / "outputs" / "exp26_g3_contract_v2_evaluation" / "contract_v2_report.json"
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

NODE_POSITIONS = {
    "request": (0.0, 1.1),
    "target_history": (0.0, -1.1),
    "artifact": (1.25, 0.0),
    "municipal_climatology": (2.45, 1.1),
    "regional_intensity_window": (2.45, -1.1),
    "exact_equation": (4.0, 0.0),
    "prediction": (5.55, 0.75),
    "interval": (5.55, -0.75),
    "numeric_guard": (7.05, 0.0),
}

NODE_COLORS = {
    "input": "#56CCF2",
    "data_source": "#7BD88F",
    "model": "#F2C94C",
    "feature": "#A78BFA",
    "operation": "#F2994A",
    "output": "#EB5757",
    "uncertainty": "#2D9CDB",
    "verification": "#27AE60",
}


def page_config() -> None:
    """Configura pagina, tema e estilos visuais do dashboard."""
    st.set_page_config(
        page_title="FireCast | IA de queimadas",
        page_icon="??",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        :root { color-scheme: dark; }
        .stApp {
            background:
              radial-gradient(circle at 18% 4%, rgba(242, 153, 74, 0.16), transparent 26rem),
              linear-gradient(135deg, #071016 0%, #0D1720 45%, #12151B 100%);
        }
        .block-container { padding-top: 1.4rem; padding-bottom: 2.2rem; }
        [data-testid="stSidebar"] { background: #091018; border-right: 1px solid rgba(255,255,255,0.08); }
        .hero {
            padding: 1.25rem 1.35rem;
            border: 1px solid rgba(255,255,255,0.10);
            background: linear-gradient(135deg, rgba(255,255,255,0.08), rgba(255,255,255,0.025));
            border-radius: 8px;
        }
        .hero h1 { margin: 0; font-size: 2.15rem; letter-spacing: 0; }
        .hero p { margin: 0.45rem 0 0 0; color: rgba(255,255,255,0.74); max-width: 72rem; }
        .badge-row { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .8rem; }
        .badge {
            border: 1px solid rgba(255,255,255,0.16);
            border-radius: 999px;
            padding: .28rem .55rem;
            font-size: .78rem;
            color: rgba(255,255,255,0.82);
            background: rgba(255,255,255,0.055);
        }
        .metric-card {
            border: 1px solid rgba(255,255,255,0.10);
            border-radius: 8px;
            background: rgba(255,255,255,0.055);
            padding: .85rem .95rem;
            min-height: 7rem;
        }
        .metric-card .label { color: rgba(255,255,255,0.63); font-size: .78rem; }
        .metric-card .value { color: white; font-size: 1.55rem; font-weight: 700; margin-top: .2rem; }
        .metric-card .note { color: rgba(255,255,255,0.58); font-size: .75rem; margin-top: .35rem; }
        .section-title { margin-top: .25rem; margin-bottom: .35rem; font-size: 1.1rem; font-weight: 700; }
        div[data-testid="stMetric"] { border: 1px solid rgba(255,255,255,0.09); border-radius: 8px; padding: .65rem .75rem; background: rgba(255,255,255,0.045); }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner=False)
def read_json(path: str) -> dict[str, Any]:
    """Le um JSON versionado do pacote e retorna seu conteudo."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def read_csv(path: str) -> pd.DataFrame:
    """Le uma tabela CSV versionada e preserva os nomes de colunas originais."""
    return pd.read_csv(path)


@st.cache_resource(show_spinner=False)
def load_model(path: str) -> ChampionClimatologyModel:
    """Carrega o artefato champion com validacao de hash fail-closed."""
    return ChampionClimatologyModel.load(Path(path))


def format_number(value: float, digits: int = 2) -> str:
    """Formata numero no padrao visual usado nos cards da aplicacao."""
    return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def percentage(value: float) -> str:
    """Converte proporcao em percentual legivel para metricas de qualidade."""
    return f"{100.0 * float(value):.1f}%".replace(".", ",")


def municipality_options(model: ChampionClimatologyModel) -> list[dict[str, Any]]:
    """Extrai municipios unicos disponiveis no artefato champion."""
    seen: dict[int, dict[str, Any]] = {}
    for row in model.artifact["climatology"]:
        geocodigo = int(row["geocodigo"])
        seen.setdefault(
            geocodigo,
            {
                "geocodigo": geocodigo,
                "municipio": str(row.get("municipio_ibge", geocodigo)),
                "uf": str(row.get("uf", "")),
            },
        )
    return sorted(seen.values(), key=lambda item: (item["uf"], item["municipio"]))


def plot_real_vs_pred(df: pd.DataFrame, scenario: str, title: str) -> go.Figure:
    """Desenha grafico mensal com linhas de observado e predito."""
    data = df[df["scenario"] == scenario].copy()
    data["periodo"] = pd.to_datetime(dict(year=data["ano"], month=data["mes"], day=1))
    long_df = data.melt(
        id_vars=["periodo", "ano", "mes", "wape"],
        value_vars=["actual", "pred"],
        var_name="serie",
        value_name="focos",
    )
    long_df["serie"] = long_df["serie"].map({"actual": "observado", "pred": "predito"})
    fig = px.line(
        long_df,
        x="periodo",
        y="focos",
        color="serie",
        markers=True,
        color_discrete_map={"observado": "#7BD88F", "predito": "#F2994A"},
        title=title,
    )
    fig.update_traces(line=dict(width=3), marker=dict(size=8))
    fig.update_layout(
        height=430,
        legend_title_text="",
        xaxis_title="mes",
        yaxis_title="focos mensais",
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.035)",
        margin=dict(l=20, r=20, t=55, b=30),
    )
    return fig


def build_backtest_monthly(backtest: pd.DataFrame) -> pd.DataFrame:
    """Agrega o backtest do champion por mes para visualizacao."""
    champion = backtest[backtest["model"] == "climatology_regional_intensity12"].copy()
    monthly = champion.groupby(["ano", "mes"], as_index=False).agg(actual=("fire_count", "sum"), pred=("y_pred", "sum"))
    monthly["scenario"] = "backtest_2023_2024"
    monthly["abs_error"] = (monthly["actual"] - monthly["pred"]).abs()
    monthly["wape"] = monthly["abs_error"] / monthly["actual"].replace(0, pd.NA)
    return monthly


def plot_error_bars(df: pd.DataFrame, scenario: str) -> go.Figure:
    """Mostra onde a diferenca absoluta entre real e predito foi maior."""
    data = df[df["scenario"] == scenario].copy()
    data["periodo"] = data["ano"].astype(str) + "-" + data["mes"].astype(str).str.zfill(2)
    fig = px.bar(
        data,
        x="periodo",
        y="abs_error",
        color="abs_error",
        color_continuous_scale=["#1B9AAA", "#F2C94C", "#EB5757"],
        title="Erro absoluto por mes",
    )
    fig.update_layout(
        height=350,
        xaxis_title="periodo",
        yaxis_title="|observado - predito|",
        coloraxis_showscale=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.035)",
        margin=dict(l=20, r=20, t=55, b=30),
    )
    return fig


def plot_municipality_ranking(municipio: pd.DataFrame) -> go.Figure:
    """Renderiza ranking municipal para auditoria dos maiores erros relativos."""
    data = municipio.sort_values("wape", ascending=False).head(15).copy()
    fig = px.bar(
        data,
        x="wape",
        y="municipio_ibge",
        orientation="h",
        color="volume_real",
        color_continuous_scale=["#7BD88F", "#F2C94C", "#EB5757"],
        title="Municipios mais dificeis no backtest 2023-2024",
        hover_data=["geocodigo", "volume_real", "mae", "flag_regressao"],
    )
    fig.update_layout(
        height=520,
        yaxis={"categoryorder": "total ascending"},
        xaxis_title="WAPE municipal",
        yaxis_title="",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.035)",
        margin=dict(l=20, r=20, t=55, b=30),
    )
    return fig


def plot_municipality_map(municipio: pd.DataFrame, attributes: pd.DataFrame | None) -> go.Figure | None:
    """Cria mapa pontual de robustez quando os centroides estao disponiveis."""
    if attributes is None or not {"geocodigo", "centroid_lon", "centroid_lat"} <= set(attributes.columns):
        return None
    data = municipio.merge(attributes[["geocodigo", "centroid_lon", "centroid_lat"]], on="geocodigo", how="left")
    data = data.dropna(subset=["centroid_lon", "centroid_lat"]).copy()
    if data.empty:
        return None
    fig = px.scatter_geo(
        data,
        lon="centroid_lon",
        lat="centroid_lat",
        size="volume_real",
        color="wape",
        hover_name="municipio_ibge",
        hover_data={"geocodigo": True, "volume_real": True, "mae": ":.3f", "wape": ":.3f"},
        color_continuous_scale=["#7BD88F", "#F2C94C", "#EB5757"],
        title="Mapa de erro e volume por municipio",
    )
    fig.update_geos(
        fitbounds="locations",
        visible=False,
        projection_type="mercator",
        bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(
        height=520,
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=55, b=10),
    )
    return fig


def plot_xai_graph(graph: dict[str, Any]) -> go.Figure:
    """Converte o grafo XAI dirigido em figura Plotly interativa."""
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    annotations: list[dict[str, Any]] = []
    for edge in graph["edges"]:
        x0, y0 = NODE_POSITIONS[edge["source"]]
        x1, y1 = NODE_POSITIONS[edge["target"]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        annotations.append(
            {
                "x": (x0 + x1) / 2,
                "y": (y0 + y1) / 2,
                "text": edge.get("label", ""),
                "showarrow": False,
                "font": {"size": 10, "color": "rgba(255,255,255,0.62)"},
                "bgcolor": "rgba(7,16,22,0.75)",
                "borderpad": 2,
            }
        )
    node_x = []
    node_y = []
    labels = []
    colors = []
    hover = []
    for node in graph["nodes"]:
        x, y = NODE_POSITIONS[node["id"]]
        node_x.append(x)
        node_y.append(y)
        value = node.get("value", "")
        labels.append(f"<b>{node['label']}</b><br>{value}")
        colors.append(NODE_COLORS.get(node.get("type"), "#FFFFFF"))
        hover.append(json.dumps(node.get("details", {}), ensure_ascii=False, indent=2))

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=2, color="rgba(255,255,255,0.28)"),
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            marker=dict(size=36, color=colors, line=dict(color="rgba(255,255,255,0.75)", width=1.2)),
            text=labels,
            textposition="bottom center",
            textfont=dict(size=12, color="white"),
            hovertext=hover,
            hovertemplate="<pre>%{hovertext}</pre><extra></extra>",
        )
    )
    fig.update_layout(
        height=560,
        annotations=annotations,
        showlegend=False,
        xaxis=dict(visible=False, range=(-0.45, 7.55)),
        yaxis=dict(visible=False, range=(-1.65, 1.65)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.025)",
        margin=dict(l=10, r=10, t=15, b=15),
    )
    return fig


def call_ollama(prompt: str, model_name: str, base_url: str) -> str:
    """Chama o Ollama local pelo endpoint `/api/generate` com streaming desativado."""
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 220},
    }
    response = requests.post(f"{base_url.rstrip('/')}/api/generate", json=payload, timeout=90)
    response.raise_for_status()
    data = response.json()
    text = str(data.get("response", "")).strip()
    if not text:
        raise RuntimeError("Ollama respondeu sem texto narrativo.")
    return text


def verified_ollama_narrative(response: dict[str, Any], model_name: str, base_url: str) -> tuple[str, dict[str, Any]]:
    """Gera narrativa via Ollama e valida cada numero contra o pacote XAI."""
    prompt = (
        response["llm_contract"]["grounding_prompt"]
        + "\nEscreva uma explicacao executiva em portugues, objetiva, sem novos numeros, "
        + "sem recalcular a previsao e deixando claro que o LLM so narrou fatos verificados."
    )
    narrative = call_ollama(prompt, model_name=model_name, base_url=base_url)
    verification = verify_narrative_against_packet(response["xai_packet"], narrative)
    return narrative, verification


def render_metric_card(label: str, value: str, note: str) -> None:
    """Renderiza card visual para metricas principais da entrega."""
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="label">{label}</div>
          <div class="value">{value}</div>
          <div class="note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_hero(summary: dict[str, Any]) -> None:
    """Renderiza cabecalho executivo com status e escopo do modelo."""
    st.markdown(
        f"""
        <div class="hero">
          <h1>FireCast: previs?o operacional de focos de queimadas</h1>
          <p>{summary['scope']} ? champion <b>{summary['champion']}</b>. A vitrine combina avalia??o real vs predita, robustez municipal, bases rastreadas e XAI com grafo verific?vel.</p>
          <div class="badge-row">
            <span class="badge">Champion glass-box</span>
            <span class="badge">LLM n?o toca na previs?o</span>
            <span class="badge">Ollama local em Docker</span>
            <span class="badge">Narrativa fail-closed</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overview(summary: dict[str, Any], g3: dict[str, Any], bases: dict[str, Any], reality: pd.DataFrame) -> None:
    """Renderiza a primeira aba com decisao, metricas e contexto cientifico."""
    metrics = summary["metrics"]
    cols = st.columns(4)
    with cols[0]:
        render_metric_card(
            "WAPE walk-forward",
            format_number(metrics["extended_walk_forward_wape"], 4),
            f"baseline {format_number(metrics['extended_walk_forward_baseline_wape'], 4)}",
        )
    with cols[1]:
        render_metric_card(
            "Erro absoluto 2025",
            format_number(metrics["reality_2025_absolute_error"], 1),
            f"real {metrics['reality_2025_actual_aqua_mt']} ? predito {format_number(metrics['reality_2025_predicted'], 1)}",
        )
    with cols[2]:
        render_metric_card(
            "Cobertura IC95",
            percentage(metrics["g5_ic95_overall_coverage"]),
            f"seca {percentage(metrics['g5_ic95_dry_coverage'])} ? chuva {percentage(metrics['g5_ic95_wet_coverage'])}",
        )
    with cols[3]:
        render_metric_card(
            "Bases empacotadas",
            str(bases["snapshot_count"] + len(bases["raw_external_bases"])),
            f"{bases['snapshot_count']} snapshots + {len(bases['raw_external_bases'])} bases brutas",
        )

    st.markdown('<div class="section-title">Contrato G3 v2</div>', unsafe_allow_html=True)
    champion = g3["metrics"]["climatology_regional_intensity12"]
    gate_rows = [
        {"escopo": "Ceara", "metrica": "WAPE mensal agregado", "valor": champion["ceara"]["wape_scope_month"], "limite": g3["contract"]["ceara"]["wape_scope_month_max"]},
        {"escopo": "Ceara", "metrica": "WAPE sazonal", "valor": champion["ceara"]["wape_scope_season"], "limite": g3["contract"]["ceara"]["wape_scope_season_max"]},
        {"escopo": "Chapada", "metrica": "WAPE sazonal", "valor": champion["chapada_araripe"]["wape_scope_season"], "limite": g3["contract"]["chapada_araripe"]["wape_scope_season_max"]},
        {"escopo": "Ceara", "metrica": "Recall@10", "valor": champion["ceara"]["recall10"], "limite": g3["contract"]["ceara"]["recall10_min"]},
    ]
    gate_df = pd.DataFrame(gate_rows)
    gate_df["status"] = ["PASS" if row.valor <= row.limite or "Recall" in row.metrica and row.valor >= row.limite else "REVER" for row in gate_df.itertuples()]
    st.dataframe(gate_df, use_container_width=True, hide_index=True)
    st.plotly_chart(plot_real_vs_pred(reality, "public_aqua_full_31", "Teste de realidade 2025-2026: observado vs predito"), use_container_width=True)


def render_real_vs_pred(reality: pd.DataFrame, backtest: pd.DataFrame) -> None:
    """Renderiza analise detalhada de real versus predito por periodo."""
    scenario_labels = {
        "public_aqua_full_31": "Realidade publica AQUA-MT completa",
        "v2_partial_observed_rows": "Linhas observadas parciais do alvo interno",
    }
    scenario = st.selectbox(
        "Cenario de realidade",
        options=list(scenario_labels),
        format_func=lambda value: scenario_labels[value],
    )
    top = st.columns([2, 1])
    with top[0]:
        st.plotly_chart(plot_real_vs_pred(reality, scenario, scenario_labels[scenario]), use_container_width=True)
    with top[1]:
        st.plotly_chart(plot_error_bars(reality, scenario), use_container_width=True)

    st.markdown('<div class="section-title">Backtest congelado 2023-2024</div>', unsafe_allow_html=True)
    monthly = build_backtest_monthly(backtest)
    st.plotly_chart(plot_real_vs_pred(monthly, "backtest_2023_2024", "Backtest champion: 2023-2024"), use_container_width=True)
    with st.expander("Tabela mensal auditavel"):
        st.dataframe(reality.sort_values(["scenario", "ano", "mes"]), use_container_width=True, hide_index=True)


def render_municipal_tab(municipio: pd.DataFrame, attributes: pd.DataFrame | None) -> None:
    """Renderiza a auditoria espacial e municipal do modelo."""
    cols = st.columns([1.15, 1])
    with cols[0]:
        st.plotly_chart(plot_municipality_ranking(municipio), use_container_width=True)
    with cols[1]:
        map_fig = plot_municipality_map(municipio, attributes)
        if map_fig is None:
            st.info("Centroides municipais nao encontrados no pacote; exibindo somente ranking tabular.")
        else:
            st.plotly_chart(map_fig, use_container_width=True)
    st.markdown('<div class="section-title">Tabela de robustez municipal</div>', unsafe_allow_html=True)
    st.dataframe(
        municipio.sort_values(["flag_regressao", "wape"], ascending=[False, False]),
        use_container_width=True,
        hide_index=True,
    )


def render_xai_tab(
    model: ChampionClimatologyModel,
    municipio: dict[str, Any],
    ano: int,
    mes: int,
    ollama_model: str,
    ollama_url: str,
) -> None:
    """Renderiza predi??o pontual, grafo XAI e narrativa verificada via Ollama."""
    response = build_verified_xai_response(model, geocodigo=municipio["geocodigo"], ano=ano, mes=mes)
    packet = response["xai_packet"]
    pred = packet["prediction"]
    attr = packet["exact_attribution"]
    intensity = packet["regional_intensity_evidence"]

    metric_cols = st.columns(4)
    metric_cols[0].metric("Predi??o", format_number(pred["y_pred"], 3), "focos mensais")
    metric_cols[1].metric("Base municipal", format_number(attr["base_climatology"], 3), "climatologia mes-municipio")
    metric_cols[2].metric("Fator regional", format_number(attr["regional_intensity_ratio"], 4), intensity["forecast_period_used"])
    metric_cols[3].metric("Intervalo p90", f"{format_number(pred['interval_p90_low'], 2)} a {format_number(pred['interval_p90_high'], 2)}", "erro empirico")

    st.plotly_chart(plot_xai_graph(response["xai_graph"]), use_container_width=True)

    narrative_cols = st.columns([1.2, 1])
    with narrative_cols[0]:
        st.markdown('<div class="section-title">Narrativa deterministica verificada</div>', unsafe_allow_html=True)
        st.success(response["llm_narrative"]["text"])
        if st.button("Gerar narrativa com Ollama local e validar", type="primary", use_container_width=True):
            try:
                with st.spinner("Chamando Ollama local e conferindo os numeros..."):
                    llm_text, verification = verified_ollama_narrative(response, model_name=ollama_model, base_url=ollama_url)
                st.success(llm_text)
                st.caption(f"Narrativa verificada por {verification['verifier']} ? tokens numericos checados: {verification['checked_numeric_tokens']}")
            except requests.RequestException as exc:
                st.warning(
                    "Ollama local nao respondeu. Suba o servico com Docker Compose e puxe o modelo antes de testar a narracao LLM. "
                    f"Detalhe: {exc}"
                )
            except NarrativeValidationError as exc:
                st.error(f"Narrativa rejeitada pelo guard numerico: {exc}")
            except Exception as exc:  # pragma: no cover - caminho operacional exibido ao usuario
                st.error(f"Falha operacional ao gerar narrativa: {exc}")
    with narrative_cols[1]:
        st.markdown('<div class="section-title">Contrato LLM</div>', unsafe_allow_html=True)
        st.json(packet["llm_xai_contract"], expanded=True)

    with st.expander("Mermaid do grafo XAI"):
        st.code(response["xai_graph"]["mermaid"], language="mermaid")
    with st.expander("Pacote XAI completo"):
        st.json(packet, expanded=False)


def render_bases_tab(bases: dict[str, Any], summary: dict[str, Any]) -> None:
    """Renderiza inventario das bases e comandos de operacao."""
    st.markdown('<div class="section-title">Manifesto de bases incluidas</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(bases["snapshots"]), use_container_width=True, hide_index=True)
    st.markdown('<div class="section-title">Bases brutas externas preservadas</div>', unsafe_allow_html=True)
    st.dataframe(pd.DataFrame(bases["raw_external_bases"]), use_container_width=True, hide_index=True)
    st.markdown('<div class="section-title">Como rodar a vitrine com Ollama</div>', unsafe_allow_html=True)
    st.code(
        "docker compose --profile ui up -d ollama\n"
        "docker compose --profile ui run --rm ollama-pull\n"
        "docker compose --profile ui up streamlit\n",
        language="bash",
    )
    st.info(summary["data_handoff"]["important_note"])


def main() -> None:
    """Executa a aplicacao Streamlit do FireCast."""
    page_config()
    model = load_model(str(MODEL_PATH))
    summary = read_json(str(SUMMARY_PATH))
    g3 = read_json(str(G3_PATH))
    bases = read_json(str(BASES_PATH))
    reality = read_csv(str(REALITY_PATH))
    backtest = read_csv(str(BACKTEST_PATH))
    municipio = read_csv(str(MUNICIPIO_PATH))
    attributes = read_csv(str(ATTRIBUTES_PATH)) if ATTRIBUTES_PATH.exists() else None

    options = municipality_options(model)
    st.sidebar.title("FireCast")
    st.sidebar.caption("Demo de predicao, realidade e XAI verificavel")
    selected_label = st.sidebar.selectbox(
        "Municipio para explicacao XAI",
        options=[f"{item['municipio']} ({item['uf']}) ? {item['geocodigo']}" for item in options],
        index=0,
    )
    selected_index = [f"{item['municipio']} ({item['uf']}) ? {item['geocodigo']}" for item in options].index(selected_label)
    selected_municipio = options[selected_index]
    ano = st.sidebar.number_input("Ano da previsao", min_value=2025, max_value=2035, value=2026, step=1)
    mes = st.sidebar.slider("Mes", min_value=1, max_value=12, value=10)
    ollama_url = st.sidebar.text_input("URL do Ollama", value=DEFAULT_OLLAMA_URL)
    ollama_model = st.sidebar.text_input("Modelo Ollama", value=DEFAULT_OLLAMA_MODEL)
    st.sidebar.caption("O modelo local so narra fatos; a predicao segue travada no artefato.")

    render_hero(summary)
    tabs = st.tabs(["Resumo", "Real vs predito", "Municipios", "XAI + Ollama", "Bases e operacao"])
    with tabs[0]:
        render_overview(summary, g3, bases, reality)
    with tabs[1]:
        render_real_vs_pred(reality, backtest)
    with tabs[2]:
        render_municipal_tab(municipio, attributes)
    with tabs[3]:
        render_xai_tab(
            model,
            selected_municipio,
            int(ano),
            int(mes),
            ollama_model=ollama_model,
            ollama_url=ollama_url,
        )
    with tabs[4]:
        render_bases_tab(bases, summary)


if __name__ == "__main__":
    main()
