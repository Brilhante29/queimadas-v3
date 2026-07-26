import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Flame,
  TrendingUp,
  AlertTriangle,
  MapPin,
  BarChart3,
  Calendar,
  Activity,
  ShieldAlert,
  Loader2,
} from "lucide-react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  AreaChart,
  Area,
  Cell,
} from "recharts";
import {
  fetchChampionSummary,
  fetchMonthlySeries,
  fetchMunicipioRanking,
  fetchEnso,
  fetchHealth,
  predict,
  type ChampionSummary,
  type MonthlyPoint,
  type MunicipioWape,
  type EnsoPoint,
  type HealthStatus,
  type PredictionResult,
} from "@/lib/firecast-api";

const GATE_LABEL: Record<string, string> = {
  PASS: "bg-emerald-100 text-emerald-700 border-emerald-300",
  PARTIAL: "bg-amber-100 text-amber-700 border-amber-300",
  FAIL: "bg-red-100 text-red-700 border-red-300",
  UNKNOWN: "bg-slate-100 text-slate-500 border-slate-300",
};

function ApiUnavailable({ detail }: { detail: string }) {
  return (
    <Card className="border-red-200 bg-red-50/50">
      <CardContent className="p-5 flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
        <div>
          <p className="text-sm font-semibold text-red-700">
            Sem dado real disponível para este painel
          </p>
          <p className="text-xs text-red-600 mt-1">
            A API respondeu com erro (fail-closed): nenhum número foi
            inventado no lugar. Detalhe: {detail}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export default function Home() {
  const [activeTab, setActiveTab] = useState("dashboard");

  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [summary, setSummary] = useState<ChampionSummary | null>(null);
  const [monthly, setMonthly] = useState<MonthlyPoint[] | null>(null);
  const [ranking, setRanking] = useState<MunicipioWape[] | null>(null);
  const [enso, setEnso] = useState<EnsoPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      fetchHealth(),
      fetchChampionSummary(),
      fetchMonthlySeries(),
      fetchMunicipioRanking(),
      fetchEnso(),
    ]).then(([h, s, m, r, e]) => {
      if (h.status === "fulfilled") setHealth(h.value);
      if (s.status === "fulfilled") setSummary(s.value);
      if (m.status === "fulfilled") setMonthly(m.value);
      if (r.status === "fulfilled") setRanking(r.value);
      if (e.status === "fulfilled") setEnso(e.value);
      const firstError = [h, s, m, r, e].find((x) => x.status === "rejected") as
        | PromiseRejectedResult
        | undefined;
      if (firstError) setError(String(firstError.reason));
      setLoading(false);
    });
  }, []);

  const ensoRecent = enso?.filter((e) => e.ano >= 2015) ?? [];

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-orange-500 to-red-600 rounded-xl flex items-center justify-center shadow-lg">
                <Flame className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                  FireCast
                </h1>
                <p className="text-xs text-slate-500">
                  Previsão de Focos de Queimada — champion:{" "}
                  {health?.model_name ?? summary?.model_name ?? "carregando..."}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <Calendar className="w-4 h-4" />
                <span>Backtest real 2023-2024</span>
              </div>
              <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 border border-red-200 rounded-full">
                <AlertTriangle className="w-4 h-4 text-red-500" />
                <span className="text-xs font-semibold text-red-700">
                  NÃO APROVADO PARA PRODUÇÃO
                </span>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {loading && (
          <div className="flex items-center gap-2 text-slate-500 text-sm mb-4">
            <Loader2 className="w-4 h-4 animate-spin" /> Carregando evidência real da API...
          </div>
        )}
        {error && !loading && (
          <div className="mb-4">
            <ApiUnavailable detail={error} />
          </div>
        )}

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-6 bg-white border border-slate-200">
            <TabsTrigger value="dashboard" className="data-[state=active]:bg-orange-50 data-[state=active]:text-orange-700">
              <BarChart3 className="w-4 h-4 mr-2" />
              Dashboard
            </TabsTrigger>
            <TabsTrigger value="predict" className="data-[state=active]:bg-orange-50 data-[state=active]:text-orange-700">
              <TrendingUp className="w-4 h-4 mr-2" />
              Previsão ao vivo
            </TabsTrigger>
            <TabsTrigger value="ranking" className="data-[state=active]:bg-orange-50 data-[state=active]:text-orange-700">
              <MapPin className="w-4 h-4 mr-2" />
              Erro por município
            </TabsTrigger>
            <TabsTrigger value="enso" className="data-[state=active]:bg-orange-50 data-[state=active]:text-orange-700">
              <Activity className="w-4 h-4 mr-2" />
              ENSO (real)
            </TabsTrigger>
          </TabsList>

          {/* Dashboard Tab */}
          <TabsContent value="dashboard" className="space-y-6">
            {summary ? (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <Card className="border-slate-200">
                    <CardContent className="p-5">
                      <p className="text-sm text-slate-500 mb-1">WAPE geral (real)</p>
                      <p className="text-2xl font-bold text-slate-900">{(summary.all_wape * 100).toFixed(1)}%</p>
                      <p className="text-xs text-slate-400 mt-1">walk-forward 2023-2024, 24 cortes</p>
                    </CardContent>
                  </Card>
                  <Card className="border-slate-200">
                    <CardContent className="p-5">
                      <p className="text-sm text-slate-500 mb-1">WAPE out-nov (real)</p>
                      <p className="text-2xl font-bold text-slate-900">{(summary.outnov_wape * 100).toFixed(1)}%</p>
                      <p className="text-xs text-slate-400 mt-1">meses críticos out+nov</p>
                    </CardContent>
                  </Card>
                  <Card className="border-slate-200">
                    <CardContent className="p-5">
                      <p className="text-sm text-slate-500 mb-1">Cobertura IC90 G5 final</p>
                      <p className="text-2xl font-bold text-slate-900">{(summary.g5_coverage_overall * 100).toFixed(1)}%</p>
                      <p className="text-xs text-slate-400 mt-1">
                        alvo {summary.coverage_acceptable_range[0] * 100}-{summary.coverage_acceptable_range[1] * 100}% (G5 = {summary.gates.G5})
                      </p>
                    </CardContent>
                  </Card>
                  <Card className="border-red-200 bg-red-50/40">
                    <CardContent className="p-5">
                      <p className="text-sm text-slate-500 mb-1">Status</p>
                      <p className="text-lg font-bold text-red-700">NÃO APROVADO</p>
                      <p className="text-xs text-slate-400 mt-1">
                        {Object.entries(summary.gates)
                          .filter(([, status]) => status === "FAIL")
                          .map(([gate]) => gate)
                          .join(", ")} reprovados
                      </p>
                    </CardContent>
                  </Card>
                </div>

                <div className="grid grid-cols-1 gap-2 sm:grid-cols-4">
                  {Object.entries(summary.gates).map(([gate, status]) => (
                    <div
                      key={gate}
                      className={`rounded-lg border px-3 py-2 text-xs font-semibold flex items-center justify-between ${GATE_LABEL[status] ?? GATE_LABEL.UNKNOWN}`}
                    >
                      <span>{gate}</span>
                      <span>{status}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : !loading && <ApiUnavailable detail="resumo do champion indisponível" />}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <Card className="border-slate-200">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                    <Flame className="w-4 h-4 text-orange-500" />
                    Focos observados vs previstos — backtest real (24 cortes 2023-2024)
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {monthly ? (
                    <ResponsiveContainer width="100%" height={280}>
                      <AreaChart data={monthly}>
                        <defs>
                          <linearGradient id="colorFire" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                          </linearGradient>
                          <linearGradient id="colorPrev" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                            <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="cut" tick={{ fontSize: 10 }} interval={2} />
                        <YAxis tick={{ fontSize: 12 }} />
                        <Tooltip contentStyle={{ backgroundColor: "white", border: "1px solid #e2e8f0", borderRadius: "8px", fontSize: "12px" }} />
                        <Legend wrapperStyle={{ fontSize: "12px" }} />
                        <Area type="monotone" dataKey="y_sum" name="Observado" stroke="#f97316" fillOpacity={1} fill="url(#colorFire)" strokeWidth={2} />
                        <Area type="monotone" dataKey="pred_sum" name="Previsto" stroke="#3b82f6" fillOpacity={1} fill="url(#colorPrev)" strokeWidth={2} strokeDasharray="5 5" />
                      </AreaChart>
                    </ResponsiveContainer>
                  ) : !loading && <ApiUnavailable detail="série mensal indisponível" />}
                </CardContent>
              </Card>

              <Card className="border-slate-200">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-semibold text-slate-700 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-purple-500" />
                    WAPE real por corte mensal
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {monthly ? (
                    <ResponsiveContainer width="100%" height={280}>
                      <LineChart data={monthly}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                        <XAxis dataKey="cut" tick={{ fontSize: 10 }} interval={2} />
                        <YAxis tick={{ fontSize: 12 }} />
                        <Tooltip contentStyle={{ backgroundColor: "white", border: "1px solid #e2e8f0", borderRadius: "8px", fontSize: "12px" }} />
                        <Line type="monotone" dataKey="wape" name="WAPE" stroke="#8b5cf6" strokeWidth={2} dot={{ fill: "#8b5cf6", r: 3 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : !loading && <ApiUnavailable detail="série mensal indisponível" />}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* Previsão ao vivo Tab (substitui os cenários fabricados 2026-2027) */}
          <TabsContent value="predict" className="space-y-6">
            <Card className="border-amber-200 bg-amber-50/40">
              <CardContent className="p-5">
                <p className="text-sm font-semibold text-amber-800">
                  Não existe cenário 2026-2027 aprovado
                </p>
                <p className="text-xs text-amber-700 mt-1">
                  O FireCast não gera previsão futura fora do protocolo validado
                  (G2/G3/G5 reprovados). O que você pode fazer aqui é chamar a
                  API real do champion para um município e mês específico — a
                  mesma chamada que a API expõe em produção interna, fail-closed.
                </p>
              </CardContent>
            </Card>
            <LivePredictCard municipios={ranking} />
          </TabsContent>

          {/* Ranking Tab — WAPE real, não "risco futuro" */}
          <TabsContent value="ranking" className="space-y-6">
            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle className="text-lg">Erro (WAPE) real por município</CardTitle>
                <CardDescription>
                  Backtest walk-forward 2023-2024 — do pior para o melhor. Não é
                  uma previsão de risco futuro.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {ranking ? (
                  <div className="space-y-2">
                    {ranking.slice(0, 15).map((m) => (
                      <div
                        key={m.geocodigo}
                        className="flex items-center gap-4 p-3 rounded-lg border border-slate-100 hover:border-slate-300 transition-all"
                      >
                        <div className="flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-medium text-slate-900">{m.municipio_ibge}</span>
                            <span className="text-xs text-slate-400">geocódigo {m.geocodigo}</span>
                          </div>
                          <div className="mt-1 flex items-center gap-2">
                            <div className="flex-1 bg-slate-100 rounded-full h-2 overflow-hidden">
                              <div
                                className="h-full bg-gradient-to-r from-orange-400 to-red-500 rounded-full"
                                style={{ width: `${Math.min(100, (m.wape / 3) * 100)}%` }}
                              />
                            </div>
                            <span className="text-xs text-slate-500 w-16 text-right">
                              WAPE {m.wape.toFixed(2)}
                            </span>
                          </div>
                        </div>
                        <div className="text-right text-xs text-slate-500">
                          volume real: {m.volume_real.toFixed(0)}
                        </div>
                        <span
                          className={`px-2 py-1 text-xs font-semibold rounded-full border ${
                            m.flag_regressao
                              ? "bg-red-100 text-red-800 border-red-300"
                              : "bg-emerald-100 text-emerald-700 border-emerald-300"
                          }`}
                        >
                          {m.flag_regressao ? "regressão material" : "ok"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : !loading && <ApiUnavailable detail="ranking por município indisponível" />}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ENSO Tab — dado real NOAA/CPC, sem futuro fabricado */}
          <TabsContent value="enso" className="space-y-6">
            <Card className="border-slate-200">
              <CardHeader>
                <CardTitle className="text-sm font-semibold text-slate-700">
                  Índice Niño 3.4 — anomalia real (NOAA/CPC, ao vivo, desde 2015)
                </CardTitle>
                <CardDescription>
                  Corrigido nesta sessão: o ingestor tinha um bug que usava uma
                  tabela fabricada e a coluna errada (TSM absoluta em vez da
                  anomalia). Estes valores vêm da série real publicada pelo NOAA.
                </CardDescription>
              </CardHeader>
              <CardContent>
                {enso ? (
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={ensoRecent}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis
                        dataKey={(d: EnsoPoint) => `${d.ano}-${String(d.mes).padStart(2, "0")}`}
                        tick={{ fontSize: 9 }}
                        interval={5}
                      />
                      <YAxis tick={{ fontSize: 12 }} />
                      <Tooltip contentStyle={{ backgroundColor: "white", border: "1px solid #e2e8f0", borderRadius: "8px", fontSize: "12px" }} />
                      <Bar dataKey="nino34_anomaly" name="Anomalia Niño 3.4 (°C)">
                        {ensoRecent.map((point, i) => (
                          <Cell
                            key={i}
                            fill={
                              point.enso_regime === "el_nino"
                                ? "#f97316"
                                : point.enso_regime === "la_nina"
                                ? "#3b82f6"
                                : "#94a3b8"
                            }
                          />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : !loading && <ApiUnavailable detail="série ENSO indisponível" />}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>

      <footer className="border-t border-slate-200 bg-white mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between text-xs text-slate-400 flex-wrap gap-2">
            <div>FireCast — release candidate interno, NÃO aprovado para produção</div>
            <div className="flex items-center gap-4">
              <span>Modelo: {summary?.model_name ?? "climatology_municipal"} (baseline real)</span>
              <span>Dados: INPE, Open-Meteo/ERA5, NOAA/CPC</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

function LivePredictCard({ municipios }: { municipios: MunicipioWape[] | null }) {
  const [geocodigo, setGeocodigo] = useState<number | null>(null);
  const [mes, setMes] = useState(10);
  const [ano] = useState(2026);
  const [result, setResult] = useState<PredictionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [predictError, setPredictError] = useState<string | null>(null);

  const options = municipios ?? [];

  async function runPredict() {
    if (!geocodigo) return;
    setBusy(true);
    setPredictError(null);
    setResult(null);
    try {
      const r = await predict(geocodigo, ano, mes);
      setResult(r);
    } catch (e) {
      setPredictError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-slate-200">
      <CardHeader>
        <CardTitle className="text-sm font-semibold text-slate-700">
          Chamar /v1/predict de verdade
        </CardTitle>
        <CardDescription>
          Município e mês reais; o valor volta exatamente do artefato champion
          servido pela API (fail-closed, hash verificado).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-slate-500 block mb-1">Município</label>
            <Select onValueChange={(v) => setGeocodigo(Number(v))}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder="Selecione..." />
              </SelectTrigger>
              <SelectContent>
                {options.map((m) => (
                  <SelectItem key={m.geocodigo} value={String(m.geocodigo)}>
                    {m.municipio_ibge}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1">Mês</label>
            <Select value={String(mes)} onValueChange={(v) => setMes(Number(v))}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                  <SelectItem key={m} value={String(m)}>
                    {m.toString().padStart(2, "0")}/2026
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={runPredict} disabled={!geocodigo || busy}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
            Chamar API
          </Button>
        </div>

        {predictError && <ApiUnavailable detail={predictError} />}

        {result && (
          <div className="rounded-lg border border-slate-200 p-4 bg-slate-50">
            <div className="text-2xl font-bold text-slate-900">
              {result.y_pred.toFixed(2)} focos previstos
            </div>
            <div className="text-xs text-slate-500 mt-1">
              intervalo p90: [{result.interval_p90_low.toFixed(2)}, {result.interval_p90_high.toFixed(2)}]
            </div>
            <div className="text-xs text-slate-400 mt-2">
              modelo {result.model_name} · hash {result.artifact_sha256.slice(0, 12)}... · {result.production_status}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
