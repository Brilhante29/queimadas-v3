# Integração FireCast (IA) ↔ Monitor Queimadas Cariri Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plug FireCast (this repo, `queimadas-v3`) into the existing Monitor Queimadas Cariri back-end and front-end as the real IA data source, replacing the mock the dashboard currently falls back to.

**Architecture:** FireCast gains one read-only endpoint that serves its already-validated backtest, filtered per municipality. The NestJS back-end gains a thin HTTP client, a static city→IBGE-geocode map, and a use-case that reuses the already-existing `RegisterFiresPredictionsUseCase` to persist what it fetches, exposed as a manual sync endpoint (no cron yet). The React front-end just unblocks two already-written, already-commented spots that were waiting for real data.

**Tech Stack:** FireCast: Python 3.10, FastAPI, pandas, pytest. Back-End: NestJS 10, TypeScript, Prisma, Zod, vitest, `@nestjs/axios`. Front-End: React 19, TypeScript, Vite, `echarts-for-react`.

## Global Constraints

- Never claim tests pass without running them (FireCast `CLAUDE.md`, this session's established practice).
- FireCast changes must not touch the model, gates, or training — read-only view over already-frozen backtest evidence (`docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md`).
- No `@Cron` automatic sync yet — manual endpoint only (explicit user decision).
- No code duplicated into `LISA-Repo/Monitor-Queimadas-Cariri-IA` — `queimadas-v3` is the IA (explicit user decision).
- No direct commits to `main`/`develop` on ANY of the three repos, including `queimadas-v3` — branch `feat/integracao-firecast-ia` + PR everywhere (explicit user decision, confirmed after the spec was written: "branch separada a ser analisada" applies to all three, not just the two LISA-Repo repos).
- No infrastructure deploy, no `docker-compose.test.yaml` containers spun up without separate authorization.

---

## File Structure

```
queimadas-v3 (this repo, already local at
C:\Users\Guilherme\Desktop\queimadas\firecast_entrega_limpa_20260715\firecast)
├── src/production/serving_api.py         [MODIFY] new service method + route
├── tests/test_serving_api.py             [MODIFY] new tests
└── README.md                             [MODIFY] endpoint list

Monitor-Queimadas-Cariri-Back-End (clone to
C:\Users\Guilherme\Desktop\queimadas\Monitor-Queimadas-Cariri-Back-End)
├── src/infra/env/env.ts                                          [MODIFY]
├── .env.example                                                  [MODIFY]
├── src/infra/firecast/city-geocode-map.ts                        [CREATE]
├── src/infra/firecast/city-geocode-map.spec.ts                   [CREATE]
├── src/infra/firecast/firecast-client.ts                         [CREATE]
├── src/infra/firecast/firecast.module.ts                         [CREATE]
├── src/domain/fires-predictions/application/use-cases/fires-predictions/
│   sync-fires-predictions-from-firecast.ts                       [CREATE]
├── src/domain/fires-predictions/application/use-cases/tests/
│   sync-fires-predictions-from-firecast.spec.ts                  [CREATE]
├── test/firecast/in-memory-firecast-client.ts                    [CREATE]
├── src/infra/http/controllers/fires-prediction/
│   sync-fires-predictions-from-firecast.controller.ts             [CREATE]
└── src/infra/http/http.module.ts                                 [MODIFY]

Queimadas-Cariri-Front (clone to
C:\Users\Guilherme\Desktop\queimadas\Queimadas-Cariri-Front)
├── src/pages/DashboardQueimadas/index.tsx                        [MODIFY]
└── src/components/Echarts/index.tsx                              [MODIFY]
```

---

## Task 1: FireCast — `champion_municipio_monthly_series` service method + route

**Files:**
- Modify: `src/production/serving_api.py` (this repo, already local)
- Test: `tests/test_serving_api.py`

**Interfaces:**
- Produces: `FireCastServingService.champion_municipio_monthly_series(self, geocodigo: int, ano: int | None = None) -> list[dict[str, Any]]` — raises `ValueError` if `geocodigo` has no rows for the champion model in `BACKTEST_PREDICTIONS_PATH`.
- Produces: route `GET /v1/champion/municipio_monthly_series?geocodigo=<int>&ano=<int, optional>` — 200 with the list on success, 422 if `geocodigo` unknown, 503 if the backtest file is missing (same fail-closed pattern as every other endpoint in this file).

- [ ] **Step 1: Create the working branch**

```bash
cd "C:/Users/Guilherme/Desktop/queimadas/firecast_entrega_limpa_20260715/firecast"
git checkout main
git pull origin main
git checkout -b feat/integracao-firecast-ia
```

- [ ] **Step 2: Write the failing tests**

Open `tests/test_serving_api.py` and add these two tests right after
`test_serving_api_champion_monthly_series_has_24_real_cuts` (which ends at
line 87):

```python
def test_serving_api_champion_municipio_monthly_series_returns_24_real_cuts_for_abaiara():
    """Verifica o comportamento `test serving api champion municipio monthly series returns 24 real cuts for abaiara`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/municipio_monthly_series", params={"geocodigo": 2300101})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 24
    assert {"mes", "ano", "y_sum", "pred_sum"} <= body[0].keys()
    assert all(row["ano"] in (2023, 2024) for row in body)


def test_serving_api_champion_municipio_monthly_series_filters_by_year():
    """Verifica o comportamento `test serving api champion municipio monthly series filters by year`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get(
        "/v1/champion/municipio_monthly_series",
        params={"geocodigo": 2300101, "ano": 2024},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 12
    assert {row["mes"] for row in body} == set(range(1, 13))


def test_serving_api_champion_municipio_monthly_series_fails_closed_for_unknown_geocodigo():
    """Verifica o comportamento `test serving api champion municipio monthly series fails closed for unknown geocodigo`.

    O teste protege uma garantia publica da entrega, evitando regressao silenciosa em dados, metricas, API, container ou XAI."""
    client = TestClient(create_app())

    response = client.get("/v1/champion/municipio_monthly_series", params={"geocodigo": 9999999})

    assert response.status_code == 422
    assert "9999999" in response.json()["detail"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=. pytest tests/test_serving_api.py -k municipio_monthly_series -v`
Expected: FAIL — `AttributeError` or 404 (route does not exist yet).

- [ ] **Step 4: Implement the service method**

In `src/production/serving_api.py`, insert this method into
`FireCastServingService`, immediately after `champion_monthly_series` (which
ends at line 231, right before `def champion_municipio_ranking`):

```python
    def champion_municipio_monthly_series(self, geocodigo: int, ano: int | None = None) -> list[dict[str, Any]]:
        """Executa a etapa `champion municipio monthly series` do fluxo FireCast.

        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        preds = pd.read_csv(_require_file(BACKTEST_PREDICTIONS_PATH))
        preds = preds[(preds["model"] == CHAMPION_MODEL_NAME) & (preds["geocodigo"] == geocodigo)].copy()
        if ano is not None:
            preds = preds[preds["ano"] == ano]
        if preds.empty:
            raise ValueError(f"Nenhuma evidencia de backtest para geocodigo={geocodigo} ano={ano}")
        rows = []
        for (row_ano, mes), group in preds.groupby(["ano", "mes"], sort=True):
            rows.append(
                {
                    "geocodigo": geocodigo,
                    "ano": int(row_ano),
                    "mes": int(mes),
                    "y_sum": float(group["fire_count"].sum()),
                    "pred_sum": float(group["y_pred"].sum()),
                    "n": int(len(group)),
                }
            )
        return rows
```

- [ ] **Step 5: Wire the route**

In `src/production/serving_api.py`, insert this route inside `create_app`,
immediately after the `champion_monthly_series` route (which ends at line
331, right before `@app.get("/v1/champion/municipio_ranking")`):

```python
    @app.get("/v1/champion/municipio_monthly_series")
    def champion_municipio_monthly_series(geocodigo: int, ano: int | None = None) -> list[dict[str, Any]]:
        """Executa a etapa `champion municipio monthly series` do fluxo FireCast.

        A funcao faz parte de `src/production/serving_api.py` e deve preservar rastreabilidade, determinismo e separacao entre treino, avaliacao e serving."""
        try:
            return service.champion_municipio_monthly_series(geocodigo, ano)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=. pytest tests/test_serving_api.py -k municipio_monthly_series -v`
Expected: 3 passed.

- [ ] **Step 7: Run the full suite**

Run: `PYTHONPATH=. pytest tests -q`
Expected: all tests pass (61 previously + 3 new = 64 passed). If shapely/pyproj are missing in the environment, `pip install shapely pyproj` first (optional geo deps, not a code problem).

- [ ] **Step 8: Update README endpoint list**

In `README.md`, find the "Endpoints principais" list (currently ending with
`GET /v1/climate/enso`) and add a line right after `GET /v1/champion/municipio_ranking`:

```markdown
- `GET /v1/champion/municipio_monthly_series?geocodigo=<int>&ano=<int?>`
```

- [ ] **Step 9: Commit**

```bash
git add src/production/serving_api.py tests/test_serving_api.py README.md
git commit -m "feat: add per-municipality monthly series endpoint

Filters the already-validated backtest (predictions_2023_2024.csv) by
geocodigo/ano — read-only, no model or gate change. Feeds the Monitor
Queimadas Cariri back-end sync use-case (see docs/superpowers/specs/
2026-07-26-cariri-ia-integration-design.md)."
```

- [ ] **Step 10: Push the branch**

```bash
AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" push -u origin feat/integracao-firecast-ia
```

The PR against `main` is opened in Task 9 (Step 0 there), alongside the
Back-End and Front-End PRs.

---

## Task 2: Back-End — clone repo, create branch, add `FIRECAST_API_BASE_URL` env var

**Files:**
- Modify: `src/infra/env/env.ts`
- Modify: `.env.example`

**Interfaces:**
- Produces: `envSchema` gains optional key `FIRECAST_API_BASE_URL` (string URL, default `http://localhost:8000`) — consumed by Task 4's `FirecastClient`.

- [ ] **Step 1: Clone the repo and create the working branch**

```bash
cd "C:/Users/Guilherme/Desktop/queimadas"
AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" clone https://github.com/LISA-Repo/Monitor-Queimadas-Cariri-Back-End.git
cd Monitor-Queimadas-Cariri-Back-End
git checkout -b feat/integracao-firecast-ia
```

- [ ] **Step 2: Install dependencies**

```bash
npm install
```

Expected: installs without error (Node/npm already available per prior
session tool use).

- [ ] **Step 3: Add the env var to the schema**

In `src/infra/env/env.ts`, the schema currently ends with:

```typescript
  FRONTEND_RESET_PASS_URL: z.string().url(),
});
```

Change it to:

```typescript
  FRONTEND_RESET_PASS_URL: z.string().url(),
  FIRECAST_API_BASE_URL: z.string().url().optional().default('http://localhost:8000'),
});
```

- [ ] **Step 4: Document it in `.env.example`**

In `.env.example`, add a new line at the end:

```
FIRECAST_API_BASE_URL="http://localhost:8000"
```

- [ ] **Step 5: Verify the project still builds**

Run: `npm run build`
Expected: exits 0 (no TypeScript errors — this is an additive, optional schema field).

- [ ] **Step 6: Commit**

```bash
git add src/infra/env/env.ts .env.example
git commit -m "feat: add FIRECAST_API_BASE_URL env var

Optional, defaults to http://localhost:8000. Prepares the config surface
for the FireCast (IA) sync client — no behavior change yet."
```

---

## Task 3: Back-End — city → IBGE geocode map

**Files:**
- Create: `src/infra/firecast/city-geocode-map.ts`
- Test: `src/infra/firecast/city-geocode-map.spec.ts`

**Interfaces:**
- Produces: `CARIRI_CITY_GEOCODE_MAP: Record<string, number>` (29 entries, normalized-lowercase-no-accent key → IBGE geocode).
- Produces: `normalizeCityName(name: string): string`.
- Produces: `resolveGeocodigo(cityName: string): number | undefined`.
- Consumed by: Task 5 (`SyncFiresPredictionsFromFirecastUseCase`).

- [ ] **Step 1: Write the failing test**

Create `src/infra/firecast/city-geocode-map.spec.ts`:

```typescript
import { resolveGeocodigo, normalizeCityName, CARIRI_CITY_GEOCODE_MAP } from './city-geocode-map';

describe('city-geocode-map', () => {
  it('has exactly 29 cities', () => {
    expect(Object.keys(CARIRI_CITY_GEOCODE_MAP)).toHaveLength(29);
  });

  it('resolves a plain name', () => {
    expect(resolveGeocodigo('Crato')).toBe(2304202);
  });

  it('resolves case-insensitively and accent-insensitively', () => {
    expect(resolveGeocodigo('juazeiro do norte')).toBe(2307304);
    expect(resolveGeocodigo('JUAZEIRO DO NORTE')).toBe(2307304);
  });

  it('resolves names with accents present in the source data', () => {
    expect(resolveGeocodigo('Caririaçu')).toBe(2303204);
  });

  it('returns undefined for an unknown city', () => {
    expect(resolveGeocodigo('Fortaleza')).toBeUndefined();
  });

  it('normalizes accents and case the same way callers expect', () => {
    expect(normalizeCityName('Antonina Do Norte')).toBe('antonina do norte');
    expect(normalizeCityName('Santana Do Cariri')).toBe('santana do cariri');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- city-geocode-map`
Expected: FAIL — `Cannot find module './city-geocode-map'`.

- [ ] **Step 3: Implement the map**

Create `src/infra/firecast/city-geocode-map.ts`:

```typescript
/**
 * Static name -> IBGE geocode map for the 29 municipalities the front-end
 * dashboard already lists (Cariri cearense region). Cross-checked exactly
 * by name against queimadas-v3's data/reference/ibge_municipios_CE_PE_PI.json
 * (29/29 matched, no ambiguity) — see
 * docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md in that
 * repo for the full derivation.
 */
export const CARIRI_CITY_GEOCODE_MAP: Record<string, number> = {
  'abaiara': 2300101,
  'altaneira': 2300606,
  'antonina do norte': 2300804,
  'araripe': 2301307,
  'assare': 2301604,
  'aurora': 2301703,
  'baixio': 2301802,
  'barbalha': 2301901,
  'barro': 2302008,
  'brejo santo': 2302503,
  'campos sales': 2302701,
  'caririacu': 2303204,
  'crato': 2304202,
  'farias brito': 2304301,
  'granjeiro': 2304806,
  'ipaumirim': 2305704,
  'jardim': 2307106,
  'jati': 2307205,
  'juazeiro do norte': 2307304,
  'lavras da mangabeira': 2307502,
  'mauriti': 2308104,
  'milagres': 2308302,
  'nova olinda': 2309201,
  'porteiras': 2311108,
  'potengi': 2311207,
  'salitre': 2311959,
  'santana do cariri': 2312106,
  'tarrafas': 2313252,
  'umari': 2313708,
};

export function normalizeCityName(name: string): string {
  return name
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
    .toLowerCase();
}

export function resolveGeocodigo(cityName: string): number | undefined {
  return CARIRI_CITY_GEOCODE_MAP[normalizeCityName(cityName)];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- city-geocode-map`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/infra/firecast/city-geocode-map.ts src/infra/firecast/city-geocode-map.spec.ts
git commit -m "feat: add Cariri city name -> IBGE geocode static map

29/29 cities cross-checked by name against queimadas-v3's IBGE reference
data. Resolves the mismatch between how City.name is stored here (plain
string) and how the IA identifies municipalities (IBGE geocode)."
```

---

## Task 4: Back-End — `FirecastClient` + module

**Files:**
- Create: `src/infra/firecast/firecast-client.ts`
- Create: `src/infra/firecast/firecast.module.ts`

**Interfaces:**
- Consumes: `EnvService.get('FIRECAST_API_BASE_URL')` (pattern already used by `WEATHER_API_BASE_URL` elsewhere in this codebase — check `src/infra/env/env.service.ts` for the exact method name before writing this file; it is a thin wrapper around the validated `envSchema` from Task 2).
- Produces: `FirecastClient.getMunicipioMonthlySeries(geocodigo: number, ano?: number): Promise<FirecastMonthlySeriesEntry[]>`.
- Produces: `interface FirecastMonthlySeriesEntry { geocodigo: number; ano: number; mes: number; y_sum: number; pred_sum: number; n: number }`.
- Consumed by: Task 5 (`SyncFiresPredictionsFromFirecastUseCase`).

- [ ] **Step 1: Confirm the EnvService read pattern**

Run: `grep -n "WEATHER_API_BASE_URL" -r src/`

This shows the exact getter (e.g. `this.envService.get('WEATHER_API_BASE_URL')`
or `this.configService.get(...)`) used by an existing external-API
integration. Use the same pattern below — do not invent a different one.

- [ ] **Step 2: Implement the client**

Create `src/infra/firecast/firecast-client.ts` (adjust the env-read line per
Step 1's finding if it differs from the assumed `EnvService.get` pattern):

```typescript
import { HttpService } from '@nestjs/axios';
import { Injectable, Logger } from '@nestjs/common';
import { firstValueFrom, catchError } from 'rxjs';
import { AxiosError } from 'axios';
import { EnvService } from '@/infra/env/env.service';

export interface FirecastMonthlySeriesEntry {
  geocodigo: number;
  ano: number;
  mes: number;
  y_sum: number;
  pred_sum: number;
  n: number;
}

@Injectable()
export class FirecastClient {
  private readonly logger = new Logger(FirecastClient.name);

  constructor(
    private readonly httpService: HttpService,
    private readonly envService: EnvService,
  ) {}

  async getMunicipioMonthlySeries(
    geocodigo: number,
    ano?: number,
  ): Promise<FirecastMonthlySeriesEntry[]> {
    const baseUrl = this.envService.get('FIRECAST_API_BASE_URL');
    const { data } = await firstValueFrom(
      this.httpService
        .get<FirecastMonthlySeriesEntry[]>(
          `${baseUrl}/v1/champion/municipio_monthly_series`,
          { params: ano ? { geocodigo, ano } : { geocodigo } },
        )
        .pipe(
          catchError((error: AxiosError) => {
            this.logger.error(
              `FireCast request failed for geocodigo=${geocodigo} ano=${ano}: ${error.message}`,
            );
            throw error;
          }),
        ),
    );
    return data;
  }
}
```

- [ ] **Step 3: Create the module**

Create `src/infra/firecast/firecast.module.ts`:

```typescript
import { Module } from '@nestjs/common';
import { HttpModule } from '@nestjs/axios';
import { EnvModule } from '@/infra/env/env.module';
import { FirecastClient } from './firecast-client';

@Module({
  imports: [HttpModule, EnvModule],
  providers: [FirecastClient],
  exports: [FirecastClient],
})
export class FirecastModule {}
```

- [ ] **Step 4: Verify it compiles**

Run: `npm run build`
Expected: exits 0. If `EnvService.get` doesn't exist with that signature,
fix `firecast-client.ts` to match what Step 1 found, then rerun.

- [ ] **Step 5: Commit**

```bash
git add src/infra/firecast/firecast-client.ts src/infra/firecast/firecast.module.ts
git commit -m "feat: add FirecastClient to call the IA's monthly-series endpoint

Thin HttpService wrapper, same shape as other external integrations in
this codebase. No caller wired yet (Task 5)."
```

---

## Task 5: Back-End — `SyncFiresPredictionsFromFirecastUseCase`

**Files:**
- Create: `src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts`
- Create: `test/firecast/in-memory-firecast-client.ts`
- Test: `src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts`

**Interfaces:**
- Consumes: `CityRepository.findAll(): Promise<City[]>` (existing), `City.create({name}, id?)` (existing), `resolveGeocodigo(cityName: string): number | undefined` (Task 3), `FirecastClient.getMunicipioMonthlySeries(geocodigo, ano?)` (Task 4), `FiresPredictionsWithMonthData.create({city, occurredTotal, predictionTotal, monthDataProps, year?}, id?)` (existing), `RegisterFiresPredictionsUseCase.execute(entries: FiresPredictionsWithMonthData[])` (existing).
- Produces: `SyncFiresPredictionsFromFirecastUseCase.execute({ ano }: { ano: number }): Promise<Either<Error, { syncedCities: number; skippedCities: string[] }>>`.
- Consumed by: Task 7 (controller).

- [ ] **Step 1: Create the in-memory fake client for tests**

Create `test/firecast/in-memory-firecast-client.ts`:

```typescript
import { FirecastMonthlySeriesEntry } from '@/infra/firecast/firecast-client';

export class InMemoryFirecastClient {
  public seriesByGeocodigo = new Map<number, FirecastMonthlySeriesEntry[]>();
  public calls: Array<{ geocodigo: number; ano?: number }> = [];

  async getMunicipioMonthlySeries(
    geocodigo: number,
    ano?: number,
  ): Promise<FirecastMonthlySeriesEntry[]> {
    this.calls.push({ geocodigo, ano });
    const rows = this.seriesByGeocodigo.get(geocodigo) ?? [];
    return ano ? rows.filter((r) => r.ano === ano) : rows;
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts`:

```typescript
import { SyncFiresPredictionsFromFirecastUseCase } from '../fires-predictions/sync-fires-predictions-from-firecast';
import { InMemoryFiresPredictionsRepository } from 'test/repositories/in-memory-fires-predictions-repository';
import { InMemoryFirecastClient } from 'test/firecast/in-memory-firecast-client';
import { City } from '@/domain/cities/enterprise/entities/city';

class FakeCityRepository {
  public cities: City[] = [];
  async findAll(): Promise<City[]> {
    return this.cities;
  }
  async saveMany(entries: City[]): Promise<City[]> {
    this.cities.push(...entries);
    return this.cities;
  }
}

function makeMonthRow(ano: number, mes: number, y = 1, pred = 2) {
  return { geocodigo: 2304202, ano, mes, y_sum: y, pred_sum: pred, n: 1 };
}

describe('SyncFiresPredictionsFromFirecastUseCase', () => {
  it('syncs a known city and persists via the existing register use-case', async () => {
    const cityRepository = new FakeCityRepository();
    cityRepository.cities = [City.create({ name: 'Crato' })];
    const firesPredictionsRepository = new InMemoryFiresPredictionsRepository();
    const firecastClient = new InMemoryFirecastClient();
    firecastClient.seriesByGeocodigo.set(
      2304202,
      Array.from({ length: 12 }, (_, i) => makeMonthRow(2026, i + 1, i, i + 1)),
    );

    const sut = new SyncFiresPredictionsFromFirecastUseCase(
      firecastClient as any,
      cityRepository as any,
      firesPredictionsRepository,
    );

    const result = await sut.execute({ ano: 2026 });

    expect(result.isRight()).toBe(true);
    if (result.isRight()) {
      expect(result.value.syncedCities).toBe(1);
      expect(result.value.skippedCities).toEqual([]);
    }
    expect(firecastClient.calls).toEqual([{ geocodigo: 2304202, ano: 2026 }]);
  });

  it('skips a city that is not in the geocode map', async () => {
    const cityRepository = new FakeCityRepository();
    cityRepository.cities = [City.create({ name: 'Cidade Desconhecida' })];
    const firesPredictionsRepository = new InMemoryFiresPredictionsRepository();
    const firecastClient = new InMemoryFirecastClient();

    const sut = new SyncFiresPredictionsFromFirecastUseCase(
      firecastClient as any,
      cityRepository as any,
      firesPredictionsRepository,
    );

    const result = await sut.execute({ ano: 2026 });

    expect(result.isRight()).toBe(true);
    if (result.isRight()) {
      expect(result.value.syncedCities).toBe(0);
      expect(result.value.skippedCities).toEqual(['Cidade Desconhecida']);
    }
    expect(firecastClient.calls).toEqual([]);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm run test -- sync-fires-predictions-from-firecast`
Expected: FAIL — module not found.

- [ ] **Step 4: Implement the use-case**

Create `src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts`:

```typescript
import { Injectable } from '@nestjs/common';
import { Either, left, right } from '@/core/either';
import { City } from '@/domain/cities/enterprise/entities/city';
import { CityRepository } from '@/domain/cities/application/repositories/city-repository';
import { FiresPredictionsRepository } from '@/domain/fires-predictions/application/repositories/fires-predictions-repository';
import { FiresPredictionsWithMonthData } from '@/domain/fires-predictions/enterprise/entities/fires-prediction-with-month-data';
import { resolveGeocodigo } from '@/infra/firecast/city-geocode-map';
import { FirecastClient } from '@/infra/firecast/firecast-client';

type SyncFiresPredictionsFromFirecastUseCaseResponse = Either<
  Error,
  { syncedCities: number; skippedCities: string[] }
>;

@Injectable()
export class SyncFiresPredictionsFromFirecastUseCase {
  constructor(
    private readonly firecastClient: FirecastClient,
    private readonly cityRepository: CityRepository,
    private readonly firesPredictionsRepository: FiresPredictionsRepository,
  ) {}

  async execute({
    ano,
  }: {
    ano: number;
  }): Promise<SyncFiresPredictionsFromFirecastUseCaseResponse> {
    const cities = await this.cityRepository.findAll();
    const skippedCities: string[] = [];
    const entries: FiresPredictionsWithMonthData[] = [];

    for (const city of cities) {
      const geocodigo = resolveGeocodigo(city.name);
      if (!geocodigo) {
        skippedCities.push(city.name);
        continue;
      }

      const series = await this.firecastClient.getMunicipioMonthlySeries(geocodigo, ano);
      if (series.length === 0) {
        skippedCities.push(city.name);
        continue;
      }

      const sorted = [...series].sort((a, b) => a.mes - b.mes);
      const occurredTotal = sorted.reduce((acc, row) => acc + row.y_sum, 0);
      const predictionTotal = sorted.reduce((acc, row) => acc + row.pred_sum, 0);

      entries.push(
        FiresPredictionsWithMonthData.create({
          city: City.create({ name: city.name }, city.id),
          occurredTotal,
          predictionTotal,
          year: ano,
          monthDataProps: sorted.map((row) => ({
            fireOccurrences: row.y_sum,
            firesPredicted: row.pred_sum,
          })),
        }),
      );
    }

    if (entries.length > 0) {
      const saved = await this.firesPredictionsRepository.saveMany(entries);
      if (!saved) {
        return left(new Error('Falha ao salvar previsoes sincronizadas da IA'));
      }
    }

    return right({ syncedCities: entries.length, skippedCities });
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- sync-fires-predictions-from-firecast`
Expected: 2 passed. If `InMemoryFiresPredictionsRepository.saveMany` requires
city IDs to already exist (check `test/repositories/in-memory-fires-predictions-repository.ts`
if this fails) — adjust the `FakeCityRepository` fixture in the test, not
the use-case.

- [ ] **Step 6: Commit**

```bash
git add src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts \
        src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts \
        test/firecast/in-memory-firecast-client.ts
git commit -m "feat: add SyncFiresPredictionsFromFirecastUseCase

Reuses the existing fires-predictions repository directly (saveMany) —
no duplication of the register/validation logic. Skips cities that
aren't in the Cariri geocode map or that the IA has no data for, and
reports them back instead of failing the whole sync."
```

---

## Task 6: Back-End — manual sync controller + module registration

**Files:**
- Create: `src/infra/http/controllers/fires-prediction/sync-fires-predictions-from-firecast.controller.ts`
- Modify: `src/infra/http/http.module.ts`

**Interfaces:**
- Consumes: `SyncFiresPredictionsFromFirecastUseCase.execute({ano})` (Task 5), `FirecastModule` (Task 4).
- Produces: `POST /predictions/sync-from-ia?ano=<int>` — 201 with `{syncedCities, skippedCities}` on success, 400 if `ano` missing/invalid.

- [ ] **Step 1: Implement the controller**

Create `src/infra/http/controllers/fires-prediction/sync-fires-predictions-from-firecast.controller.ts`:

```typescript
import {
  Controller,
  HttpCode,
  HttpStatus,
  Post,
  Query,
  UsePipes,
} from '@nestjs/common';
import { z } from 'zod';
import { Public } from '@/infra/auth/decorators/public';
import { ApiOperation, ApiQuery, ApiTags } from '@nestjs/swagger';
import { ZodValidationPipe } from '../../pipes/zod-validation-pipe';
import { SyncFiresPredictionsFromFirecastUseCase } from '@/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast';

const syncFiresPredictionsQuerySchema = z.object({
  ano: z.coerce.number().int().min(2000).max(2100),
});

type SyncFiresPredictionsQuerySchema = z.infer<typeof syncFiresPredictionsQuerySchema>;

@ApiTags('predictions')
@Controller('predictions/sync-from-ia')
@Public()
export class SyncFiresPredictionsFromFirecastController {
  constructor(private readonly useCase: SyncFiresPredictionsFromFirecastUseCase) {}

  @Post()
  @HttpCode(HttpStatus.CREATED)
  @UsePipes(new ZodValidationPipe(syncFiresPredictionsQuerySchema))
  @ApiOperation({
    summary:
      'Manually pull the current monthly prediction series from the IA (FireCast) for every mapped city and persist it',
  })
  @ApiQuery({ name: 'ano', required: true, example: 2026 })
  async handle(@Query() query: SyncFiresPredictionsQuerySchema) {
    const result = await this.useCase.execute({ ano: query.ano });
    if (result.isLeft()) {
      throw new Error(result.value.message);
    }
    return result.value;
  }
}
```

- [ ] **Step 2: Register the controller and providers in `http.module.ts`**

Run: `grep -n "CreateFiresPredictionsController\|RegisterFiresPredictionsUseCase" src/infra/http/http.module.ts`

This confirms the exact `imports`/`controllers`/`providers` array names to
edit. Then, in `src/infra/http/http.module.ts`:

1. Add two imports near the other `fires-prediction` imports:

```typescript
import { SyncFiresPredictionsFromFirecastController } from './controllers/fires-prediction/sync-fires-predictions-from-firecast.controller';
import { SyncFiresPredictionsFromFirecastUseCase } from '@/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast';
import { FirecastModule } from '@/infra/firecast/firecast.module';
```

2. Add `FirecastModule` to the `@Module({ imports: [...] })` array (alongside
   `DatabaseModule` and the other existing imports).
3. Add `SyncFiresPredictionsFromFirecastController` to the `controllers` array.
4. Add `SyncFiresPredictionsFromFirecastUseCase` to the `providers` array.

- [ ] **Step 3: Verify it compiles and unit tests still pass**

Run: `npm run build && npm run test`
Expected: build exits 0, all unit tests pass (previous count + 8 new: 6 from
Task 3, 2 from Task 5 — do not run `npm run test:e2e`, it needs Docker
containers per Global Constraints).

- [ ] **Step 4: Commit**

```bash
git add src/infra/http/controllers/fires-prediction/sync-fires-predictions-from-firecast.controller.ts \
        src/infra/http/http.module.ts
git commit -m "feat: expose POST /predictions/sync-from-ia

Manual trigger for now (no @Cron — see spec's 'Fora de escopo'). Same
@Public() pattern as the other /predictions endpoints. Swap the manual
call for a @Cron in scheduler.module.ts once a real IA host exists."
```

- [ ] **Step 5: Push the branch and open the PR**

```bash
AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" push -u origin feat/integracao-firecast-ia
```

Then open the PR (see Task 8 for the combined PR-opening step covering both
Back-End and Front-End — or open it now via the GitHub API with body
pointing at `docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md`
in `queimadas-v3`).

---

## Task 7: Front-End — clone repo, create branch, unblock the dashboard fetch

**Files:**
- Modify: `src/pages/DashboardQueimadas/index.tsx`

**Interfaces:**
- Consumes: `PaginatedPredictionData`, `PredictionData` (already defined in `src/pages/DashboardQueimadas/interfaces/fires-data.ts` — do not redefine).
- Produces: `predictionData` state now typed `PredictionData[] | null` (was `PredictionMockData[] | null`), populated from the real `/predictions` response instead of `predictionDataMock`.

- [ ] **Step 1: Clone the repo and create the working branch**

```bash
cd "C:/Users/Guilherme/Desktop/queimadas"
AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" clone https://github.com/LISA-Repo/Queimadas-Cariri-Front.git
cd Queimadas-Cariri-Front
git checkout develop
git checkout -b feat/integracao-firecast-ia
npm install
```

- [ ] **Step 2: Update the imports**

In `src/pages/DashboardQueimadas/index.tsx`, the current import block has:

```typescript
import { predictionDataMock, PredictionMockData } from "./mocks/prediciton/cities";
import { CityAverages, cityAverages } from "./averages/averages";
```

and:

```typescript
import { cityCodes, FireWarning, FireWeatherData, PaginatedFireWarnings } from "./interfaces/fires-data"
```

Change the second one to also import the prediction types:

```typescript
import { cityCodes, FireWarning, FireWeatherData, PaginatedFireWarnings, PaginatedPredictionData, PredictionData } from "./interfaces/fires-data"
```

Leave the `predictionDataMock` import in place for now (still referenced
elsewhere is unlikely, but removing unused imports is a separate, unrelated
cleanup — out of scope here per the spec's "fora de escopo").

- [ ] **Step 3: Retype the state**

Find:

```typescript
  const [predictionData, setPredictionData] = useState<PredictionMockData[] | null>(null);
```

Replace with:

```typescript
  const [predictionData, setPredictionData] = useState<PredictionData[] | null>(null);
```

Find:

```typescript
  const [predictionInformation, setPredictionInformation] = useState<PredictionMockData[]>([]);
```

Replace with:

```typescript
  const [predictionInformation, setPredictionInformation] = useState<PredictionData[]>([]);
```

- [ ] **Step 4: Use the real fetch response instead of the mock**

Find this block inside the first `useEffect`:

```typescript
        const fireWeatherData: FireWeatherData[] = await fireWeatherResponse.json();
        //const predictionDataResponse: PaginatedPredictionData = await predictionResponse.json();
        const predictionDataResponse: PredictionMockData[] = predictionDataMock;

        setFireWeatherData(fireWeatherData);
        // console.log("Dados do clima:", fireWeatherData);
        // console.log("Dados de previsão:", predictionDataResponse);
        setPredictionData(predictionDataResponse);
```

Replace with:

```typescript
        const fireWeatherData: FireWeatherData[] = await fireWeatherResponse.json();
        const predictionDataResponse: PaginatedPredictionData = await predictionResponse.json();

        setFireWeatherData(fireWeatherData);
        setPredictionData(predictionDataResponse.data);
```

- [ ] **Step 5: Typecheck and build**

Run: `npm run build`
Expected: exits 0. `updateCityData`'s `.filter(item => item.city...)` and
`.occurredTotal`/`.predictionTotal` reducers already match `PredictionData`'s
shape exactly (see `interfaces/fires-data.ts`) — no further changes should
be needed there. If TypeScript complains about `predictionInformation[0]`
being passed where `PredictionMockData` is still expected, that is Task 8
(the `Echats` component's prop type) — leave it for that task, do not widen
types here to paper over it.

- [ ] **Step 6: Commit**

```bash
git add src/pages/DashboardQueimadas/index.tsx
git commit -m "feat: use the real /predictions response instead of the mock

The fetch was already there — it just discarded the response and used
predictionDataMock. Wires it through to the already-typed PredictionData
shape, which matches the back-end's FiresPredictionPresenter exactly."
```

---

## Task 8: Front-End — unblock the real chart series in `Echats`

**Files:**
- Modify: `src/components/Echarts/index.tsx`

**Interfaces:**
- Consumes: `PredictionData` (from `pages/DashboardQueimadas/interfaces/fires-data`, not `PredictionMockData` — prop type changes).
- Produces: chart renders real `firesPredicted`/`fireOccurrences` per month for the selected city+year instead of hardcoded arrays.

- [ ] **Step 1: Fix the prop type**

Find:

```typescript
import { PredictionMockData } from "pages/DashboardQueimadas/mocks/prediciton/cities";
import { FireWeatherData } from "pages/DashboardQueimadas/interfaces/fires-data";
```

Replace with:

```typescript
import { FireWeatherData, PredictionData } from "pages/DashboardQueimadas/interfaces/fires-data";
```

Find:

```typescript
const Echats: React.FC<{ obj: FireWeatherData, predictionObj: PredictionMockData, warningFire: boolean }> = ({ obj, predictionObj, warningFire }) => {
```

Replace with:

```typescript
const Echats: React.FC<{ obj: FireWeatherData, predictionObj: PredictionData | undefined, warningFire: boolean }> = ({ obj, predictionObj, warningFire }) => {
```

(`predictionObj` becomes explicitly optional — `predictionInformation[0]` is
`undefined` before the city filter finds a match or before the fetch
resolves.)

- [ ] **Step 2: Religar as duas séries reais, corrigindo o nome de campo**

Find the "Previstos" series:

```typescript
      {
        name: 'Previstos ',
        type: 'line',
        // data: predictionObj?.monthData.map((data) => data.firesPredicted),
        data: [35, 8, 4, 6, 4, 7, 14, 50, 85, 233, 293, 257],


        markPoint: {
```

Replace with:

```typescript
      {
        name: 'Previstos ',
        type: 'line',
        data: predictionObj?.monthData.map((data) => data.firesPredicted) ?? [],
        markPoint: {
```

Find the "Ocorridos 2025" series (the one whose comment already uses
`.firesOccurred` — the wrong field name; the real interface calls it
`fireOccurrences`, see `interfaces/fires-data.ts`):

```typescript
      {
        name: 'Ocorridos 2025',
        type: 'line',
        // data: predictionObj?.monthData.slice(0, date.getMonth() + 1).map((data) => data.firesOccurred),
        data: [32, 17, 2, 3, 5, 10, 20, 29, 64, 248, 331,180],
```

Replace with:

```typescript
      {
        name: 'Ocorridos 2025',
        type: 'line',
        data: predictionObj?.monthData.slice(0, date.getMonth() + 1).map((data) => data.fireOccurrences) ?? [],
```

Leave the "Ocorridos 2024" and "Ocorridos 2026" series exactly as they are
(hardcoded, still commented data lines) — wiring multi-year series is out of
scope per the spec (the back-end returns one record per city+year; deciding
how to fetch/merge three years into one chart call is a product decision,
not made here).

- [ ] **Step 3: Typecheck and build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 4: Commit**

```bash
git add src/components/Echarts/index.tsx
git commit -m "fix: wire real prediction data into the Previstos/Ocorridos series

Also fixes a latent field-name bug: the commented-out line used
data.firesOccurred (mock-only field), the real API contract is
fireOccurrences (see MonthData in interfaces/fires-data.ts). The
2024/2026 hardcoded series are left as-is — multi-year series needs a
product decision on how the back-end should serve them, out of scope."
```

- [ ] **Step 5: Push the branch**

```bash
AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" push -u origin feat/integracao-firecast-ia
```

---

## Task 9: Open Pull Requests on all three repos

**Files:** none (GitHub API calls only)

- [ ] **Step 1: Open the queimadas-v3 PR**

```bash
cd "C:/Users/Guilherme/Desktop/queimadas/firecast_entrega_limpa_20260715/firecast"
curl -s -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Brilhante29/queimadas-v3/pulls \
  -d '{
    "title": "feat: endpoint de serie mensal por municipio (para integracao Cariri)",
    "head": "feat/integracao-firecast-ia",
    "base": "main",
    "body": "Adiciona GET /v1/champion/municipio_monthly_series, leitura pura do backtest ja validado (predictions_2023_2024.csv), filtrado por geocodigo/ano. Sem mudanca de modelo ou gate. Alimenta o sync manual do Monitor Queimadas Cariri Back-End. Design completo em docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md."
  }'
```

- [ ] **Step 2: Open the Back-End PR**

```bash
curl -s -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/LISA-Repo/Monitor-Queimadas-Cariri-Back-End/pulls \
  -d '{
    "title": "feat: integrar IA (FireCast/queimadas-v3) via sync manual",
    "head": "feat/integracao-firecast-ia",
    "base": "main",
    "body": "Adiciona FirecastClient + mapa de 29 cidades (Cariri -> geocodigo IBGE) + SyncFiresPredictionsFromFirecastUseCase + POST /predictions/sync-from-ia. Reusa o RegisterFiresPredictionsUseCase/fires-predictions domain ja existente, sem duplicar logica. Sem cron (disparo manual ate existir host real da IA). Design completo em docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md no repo queimadas-v3."
  }'
```

(If the sandbox blocks direct `curl`, use the Python `urllib.request` pattern
established earlier in this session instead — same headers, same JSON body.)

- [ ] **Step 3: Open the Front-End PR**

```bash
curl -s -X POST \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/LISA-Repo/Queimadas-Cariri-Front/pulls \
  -d '{
    "title": "feat: consumir dados reais de previsao da IA no DashboardQueimadas",
    "head": "feat/integracao-firecast-ia",
    "base": "develop",
    "body": "Destrava o fetch de /predictions que ja existia (estava descartando a resposta e usando predictionDataMock) e religa as series reais no grafico Echats, corrigindo um bug latente de nome de campo (fireOccurrences, nao firesOccurred). Depende do PR do back-end para popular dados reais via POST /predictions/sync-from-ia. Design completo em docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md no repo queimadas-v3."
  }'
```

- [ ] **Step 4: Report all three PR URLs back to the user**

Print the `html_url` field from each of the three API responses.

---

## Self-Review Notes

- **Spec coverage:** FireCast endpoint (Task 1), Back-End env var/client/map/use-case/controller (Tasks 2-6), Front-End dashboard fetch + chart wiring (Tasks 7-8), PRs instead of direct commits (Task 9). Cron and IA deployment are explicitly out of scope per the spec and not tasked here.
- **Type consistency:** `FirecastMonthlySeriesEntry` (Task 4) fields (`geocodigo, ano, mes, y_sum, pred_sum, n`) match exactly what Task 1's Python endpoint returns and what Task 5's use-case reads (`row.mes`, `row.y_sum`, `row.pred_sum`). `resolveGeocodigo`/`normalizeCityName` (Task 3) are the only accessors Task 5 uses — no duplicate normalization logic introduced. Front-end `PredictionData`/`MonthData` (Tasks 7-8) are the pre-existing real interfaces, not redefined.
- **Uncertainty flagged inline:** Task 4 Step 1 and Task 6 Step 2 both instruct running a `grep` first to confirm the exact `EnvService`/module-array patterns before writing code, rather than assuming — this codebase wasn't fully clonable during planning (private repo, explored via GitHub API/content-search only).
