# Integração FireCast (IA) com Monitor Queimadas Cariri (Back-End + Front-End)

Status: aprovado para implementação (autonomia concedida pelo usuário: "tome todas as decisões com base no queimadas v3")
Repos envolvidos:
- `Brilhante29/queimadas-v3` (FireCast — a IA, público, este repo)
- `LISA-Repo/Monitor-Queimadas-Cariri-Back-End` (privado, NestJS + Prisma)
- `LISA-Repo/Queimadas-Cariri-Front` (privado, React + Vite)

## Contexto

O sistema "Monitor Queimadas Cariri" já tem back-end e front-end com o domínio
`fires-predictions` inteiramente modelado (entidades, use-cases, controllers
`POST/GET /predictions`) e uma tela de dashboard (`DashboardQueimadas`) que já
faz `fetch` real em `/predictions`, mas descarta a resposta e usa um mock
(`predictionDataMock`) — o componente de gráfico real (`components/Echarts`)
também já tem as séries de dado real **comentadas**, com fallback hardcoded.

Não existe hoje nenhum mecanismo que povoe `fires-predictions` com dado real
da IA. Esse é o único elo faltante: o resto do encanamento (rotas, tipos,
persistência, UI) já existe e está correto.

Decisão do usuário: `queimadas-v3` (este repo, já público, com CI e release de
dados) É a IA — não se duplica código para o repo vazio da org
`Monitor-Queimadas-Cariri-IA`. Integração agora é "preparar código" (client +
env var), sem cron automático e sem deploy real — o host da IA fica para
depois.

## Descoberta chave: mapeamento de cidades

O mock do front lista 29 cidades (Cariri cearense). Cruzadas com
`data/reference/ibge_municipios_CE_PE_PI.json` deste repo: **29/29 batem
exatamente por nome**, todas em CE, todas dentro da cobertura atual do
champion (Chapada do Araripe / CE-PE-PI). Lista completa com geocódigo IBGE
em `scripts/cariri_city_geocode_map.json` (gerado neste design, ver Anexo).

## Arquitetura

```
FireCast (queimadas-v3)                 Back-End (NestJS)                 Front-End (React)
─────────────────────────               ──────────────────                ──────────────────
GET /v1/champion/                        FirecastClient (HttpService)      DashboardQueimadas:
  municipio_monthly_series      <────    city-geocode-map.ts (29 entries)  destrava fetch real
  ?geocodigo=X&ano=Y                     SyncFiresPredictionsFromFirecast  já existente em
  (novo endpoint, lê                     UseCase (reusa RegisterFires-     /predictions
  backtest já validado,                  PredictionsUseCase existente)
  sem tocar em modelo/gate)              POST /predictions/sync-from-ia    Echarts: religa 2
                                          (novo, manual, @Public() —       linhas comentadas
                                          mesmo padrão dos endpoints        (fireOccurrences,
                                          existentes)                       corrige nome de
                                                                            campo divergente
                                                                            do mock)
```

Fluxo de dados: operador chama `POST /predictions/sync-from-ia?ano=2026` no
back → para cada cidade cadastrada (ou a partir do mapa estático se a tabela
`City` estiver vazia) resolve o geocódigo → chama o FireCast → monta
`FiresPredictionsWithMonthData` → grava via use-case já existente (que já
lida com auto-registro de cidades). Sem cron: disparo manual até haver host
real; trocar por `@Cron` no `SchedulerModule` é a única mudança necessária
depois.

## 1. FireCast (queimadas-v3) — novo endpoint de leitura

**Por que é seguro:** não cria predição nova, não muda modelo, não reduz
gate — filtra o backtest já congelado (`predictions_2023_2024.csv`,
`BACKTEST_PREDICTIONS_PATH`) por `geocodigo`/`ano`. Mesmo padrão fail-closed
dos endpoints existentes (503 se arquivo ausente).

- `FireCastServingService.champion_municipio_monthly_series(geocodigo: int, ano: int | None) -> list[dict]`
  — filtra por `geocodigo` (e por `ano` se informado), ordena por `mes`,
  retorna `[{mes, y_sum, pred_sum, wape, mae, n}]` (mesmo shape de
  `champion_monthly_series`, por município).
  - 404 (`ValueError` → HTTP 422/404) se o geocódigo não existir no dataset.
- `GET /v1/champion/municipio_monthly_series?geocodigo=<int>&ano=<int?>`
- Teste novo em `tests/test_serving_api.py`: sucesso com geocódigo real do
  Cariri presente no backtest, e erro para geocódigo inexistente.
- README: adicionar o endpoint à lista de endpoints principais.
- Suíte completa (`pytest tests -q`) roda localmente antes do commit.

## 2. Back-End — client HTTP + sync manual (branch, sem tocar em `main` direto)

Trabalho feito em clone local do repo, branch `feat/integracao-firecast-ia`,
`npm install && npm test` rodando de verdade antes do push, PR aberto (não
commit direto).

- `src/infra/env/env.ts`: `FIRECAST_API_BASE_URL: z.string().url().optional().default('http://localhost:8000')`
  — opcional para não quebrar ambientes existentes.
- `src/infra/firecast/city-geocode-map.ts`: mapa estático das 29 cidades
  (nome normalizado → geocódigo IBGE), função `resolveGeocodigo(cityName)`.
- `src/infra/firecast/firecast-client.ts`: client fino via `HttpService`
  (`@nestjs/axios`, já é dependência do projeto), método
  `getMunicipioMonthlySeries(geocodigo, ano)`.
- `src/infra/firecast/firecast.module.ts`: módulo novo (`HttpModule`,
  `EnvModule`), exporta o client.
- `src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts`:
  novo use-case — busca cidades (`CityRepository.findAll()`, com fallback
  para o mapa estático se vazio), resolve geocódigo, chama o client, monta
  `FiresPredictionsWithMonthData[]` e delega a
  `RegisterFiresPredictionsUseCase` já existente (reuso total — sem duplicar
  lógica de persistência/auto-registro de cidade).
- `src/infra/http/controllers/fires-prediction/sync-fires-predictions-from-firecast.controller.ts`:
  `POST /predictions/sync-from-ia?ano=<int>`, `@Public()` (mesmo padrão dos
  demais controllers de `predictions`).
- Registro em `http.module.ts` + `firecast.module.ts` importado onde
  necessário.
- `.env.example`: adicionar `FIRECAST_API_BASE_URL=http://localhost:8000`.
- Testes: spec do use-case com `InMemoryFiresPredictionsRepository` (já
  existe) + fake do `FirecastClient`; teste do mapa (29 entradas, valores
  exatos batendo com o Anexo). Sem teste e2e novo (endpoint simples, e2e já
  cobre o padrão via `create-fires-predictions.controller.e2e-spec.ts`).
- Sem `@Cron` — decisão explícita do usuário. Comentário no código apontando
  onde plugar depois (mesmo padrão de `scheduler.module.ts`).

## 3. Front-End — destravar o que já existe (branch, sem tocar em `develop` direto)

Trabalho feito em clone local, branch `feat/integracao-firecast-ia`,
`npm install && npm run build` (typecheck) rodando antes do push, PR aberto.

- `src/pages/DashboardQueimadas/index.tsx`: no `useEffect` de fetch inicial,
  trocar o mock por `await predictionResponse.json()` (já tipado como
  `PaginatedPredictionData` na própria linha comentada), `setPredictionData`
  recebe `.data`. Ajustar o tipo do state de `PredictionMockData[]` para
  `PredictionData[]` (interface real já existe em `interfaces/fires-data.ts`,
  já com formato idêntico ao presenter do back).
- `src/components/Echarts/index.tsx`: religar as duas séries reais
  (`predictionObj?.monthData.map(d => d.firesPredicted)` para "Previstos",
  `predictionObj?.monthData.map(d => d.fireOccurrences)` para "Ocorridos") —
  **corrigindo** o nome de campo (`fireOccurrences`, não `firesOccurred` como
  no mock) para bater com o contrato real do back. Mantém fallback local
  (array vazio) se `predictionObj` for `undefined`, para não quebrar o
  render antes do primeiro fetch resolver.
  - Fora de escopo: redesenhar para múltiplas séries por ano (2024/2025/2026
    simultâneas) — o back hoje retorna um registro por cidade+ano; suportar
    isso no gráfico é decisão de produto/UX que não cabe decidir sozinho
    aqui. As séries hardcoded de anos extras ficam como estão (comentadas
    para religar depois, se o produto quiser).
- Não mexe no componente órfão `EchartsPredictions` (não importado em
  nenhuma rota) — fora de escopo, não é deletado sem confirmação.
- `.env` do front já usa `VITE_BACK_END_URL` (não é `axios.create.ts`, que é
  código morto/não importado em lugar nenhum — fora de escopo tocar).

## Testes e verificação (obrigatório antes de qualquer push)

1. FireCast: `PYTHONPATH=. pytest tests -q` local, verde, antes de commit.
2. Back-End: clone, `npm install`, `npm run test` (vitest unit) local, verde,
   antes de commit. `test:e2e` não é rodado (exige containers Postgres/Redis
   via `docker-compose.test.yaml` — fora do que este ambiente provisiona sem
   autorização explícita para subir infraestrutura).
3. Front-End: clone, `npm install`, `npm run build` (`tsc -b && vite build`)
   local, verde, antes de commit.
4. Nenhum dos três repos recebe commit direto na branch padrão — todos via
   branch `feat/integracao-firecast-ia` + Pull Request, para revisão humana
   antes do merge (repos de equipe, não de uso exclusivo do agente).

## Fora de escopo (explicitamente adiado)

- Deploy real do FireCast em qualquer host acessível pelo back — decisão de
  infraestrutura/custo que exige confirmação separada.
- `@Cron` automático de sincronização — liga-se depois, trocando o
  disparo manual pelo mesmo padrão de `scheduler.module.ts`.
- Autenticação no endpoint `sync-from-ia` (hoje `@Public()`, seguindo o
  padrão já usado pelos outros endpoints de `predictions` — não é regressão,
  é o padrão existente).
- Redesenho do gráfico multi-ano no front.
- Cópia do código da IA para o repo vazio `Monitor-Queimadas-Cariri-IA` da
  org — decisão explícita do usuário de não duplicar.

## Anexo — mapa cidade → geocódigo IBGE (29 cidades, CE)

Gerado por cruzamento exato de nome contra
`data/reference/ibge_municipios_CE_PE_PI.json` deste repo (fonte de
verdade). 29/29 encontradas, nenhuma ambígua.

| Cidade | Geocódigo IBGE |
|---|---|
| Abaiara | 2300101 |
| Altaneira | 2300606 |
| Antonina Do Norte | 2300804 |
| Araripe | 2301307 |
| Assare | 2301604 |
| Aurora | 2301703 |
| Baixio | 2301802 |
| Barbalha | 2301901 |
| Barro | 2302008 |
| Brejo Santo | 2302503 |
| Campos Sales | 2302701 |
| Caririacu | 2303204 |
| Crato | 2304202 |
| Farias Brito | 2304301 |
| Granjeiro | 2304806 |
| Ipaumirim | 2305704 |
| Jardim | 2307106 |
| Jati | 2307205 |
| Juazeiro Do Norte | 2307304 |
| Lavras Da Mangabeira | 2307502 |
| Mauriti | 2308104 |
| Milagres | 2308302 |
| Nova Olinda | 2309201 |
| Porteiras | 2311108 |
| Potengi | 2311207 |
| Salitre | 2311959 |
| Santana Do Cariri | 2312106 |
| Tarrafas | 2313252 |
| Umari | 2313708 |
