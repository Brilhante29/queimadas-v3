// Cliente para a API real do FireCast (src/production/serving_api.py).
// Todos os endpoints aqui refletem evidência já validada (walk-forward real
// 2023-2024, gates G0-G7). Nada aqui gera número quando o backend não tiver
// artefato: os fetchers propagam o erro para a UI mostrar "indisponível" em
// vez de inventar dado, seguindo a mesma regra fail-closed do backend.

export const API_BASE = import.meta.env.VITE_FIRECAST_API_BASE ?? "http://localhost:8000";

export interface HealthStatus {
  status: string;
  model_name: string;
  artifact_sha256: string;
  artifact_status: string;
  production_status: string;
}

export interface ChampionSummary {
  model_name: string;
  protocol: string;
  all_wape: number;
  all_mae: number;
  outnov_wape: number;
  outnov_mae: number;
  g5_protocol: string;
  g5_coverage_overall: number;
  g5_coverage_dry_season: number;
  g5_coverage_target: number;
  coverage_test_2024_overall: number;
  coverage_test_2024_dry_season: number;
  coverage_acceptable_range: [number, number];
  gates: Record<string, string>;
  production_status: string;
}

export interface MonthlyPoint {
  cut: string;
  ano: number;
  mes: number;
  y_sum: number;
  pred_sum: number;
  wape: number;
  mae: number;
  n: number;
}

export interface MunicipioWape {
  geocodigo: number;
  municipio_ibge: string;
  n: number;
  volume_real: number;
  wape: number;
  mae: number;
  flag_regressao: boolean;
}

export interface EnsoPoint {
  ano: number;
  mes: number;
  nino34_anomaly: number;
  enso_regime: "el_nino" | "la_nina" | "neutral";
}

export interface PredictionResult {
  geocodigo: number;
  ano: number;
  mes: number;
  y_pred: number;
  interval_p90_low: number;
  interval_p90_high: number;
  model_name: string;
  artifact_sha256: string;
  served_at: string;
  production_status: string;
  regional_intensity_ratio?: number;
  regional_intensity_ratio_period?: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${path} -> HTTP ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const fetchHealth = () => getJson<HealthStatus>("/health");
export const fetchChampionSummary = () => getJson<ChampionSummary>("/v1/champion/summary");
export const fetchMonthlySeries = () => getJson<MonthlyPoint[]>("/v1/champion/monthly_series");
export const fetchMunicipioRanking = () => getJson<MunicipioWape[]>("/v1/champion/municipio_ranking");
export const fetchEnso = () => getJson<EnsoPoint[]>("/v1/climate/enso");

export async function predict(geocodigo: number, ano: number, mes: number): Promise<PredictionResult> {
  const res = await fetch(`${API_BASE}/v1/predict`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ geocodigo, ano, mes }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`/v1/predict -> HTTP ${res.status}: ${detail}`);
  }
  return res.json() as Promise<PredictionResult>;
}
