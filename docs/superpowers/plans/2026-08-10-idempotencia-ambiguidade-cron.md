# Idempotência, Ambiguidade e Cron Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three gaps the user flagged as unacceptable in the Cariri IA integration: (1) the sync is not idempotent (re-running duplicates every city), (2) a `0` in the monthly chart is ambiguous (real zero vs. unsynced month), (3) the sync is manual-only, no cron.

**Architecture:** A Prisma migration adds a `(cityId, year)` unique constraint and a `hasData` flag on month rows. The repository's `saveMany` becomes a real upsert instead of a `createMany` whose `skipDuplicates` never fires (no unique key existed to skip on). The FireCast→use-case→entity→mapper→presenter chain carries `hasData` end to end so the front-end can render a genuine gap instead of a fabricated zero. A new `@Cron` job runs the sync automatically, following this codebase's existing `cronJobs/*.service.ts` pattern exactly.

**Tech Stack:** NestJS 10, Prisma 6, PostgreSQL, vitest. React/TypeScript/Vite front-end for the last task.

## Global Constraints

- Continue on the existing branch `feat/integracao-firecast-ia` in `Monitor-Queimadas-Cariri-Back-End` (already has 3 open PRs against it — this is more commits on the same branch, not a new one) and in `Queimadas-Cariri-Front` for Task 14.
- Generate the Prisma migration against a REAL Postgres (via `npm run docker:up:dev`, already configured in `.docker/docker-compose.dev.yaml`) using `npx prisma migrate dev` — never hand-write migration SQL.
- `RegisterFiresPredictionsUseCase` is used by other callers besides the FireCast sync (e.g. `CreateFiresPredictionsController`) — the upsert behavior must not change what those callers observe when they're creating genuinely new predictions (no existing `(cityId, year)` row).
- Never claim tests pass without running them.
- No direct commits to `main`/`develop`/`feat/integracao-firecast-ia`'s PR base without going through the same branch+PR flow already established.

---

## File Structure

```
Monitor-Queimadas-Cariri-Back-End (already cloned at
C:\Users\Guilherme\Desktop\queimadas\Monitor-Queimadas-Cariri-Back-End, branch feat/integracao-firecast-ia)
├── prisma/schema.prisma                                          [MODIFY] +@@unique, +hasData
├── prisma/migrations/<timestamp>_.../migration.sql                [CREATE, by prisma migrate dev]
├── src/infra/database/prisma/repositories/
│   prisma-fires-prediction-repository.ts                          [MODIFY] saveMany -> upsert
├── src/infra/database/prisma/repositories/tests/
│   prisma-fires-prediction-repository.e2e-spec.ts                 [CREATE or MODIFY, e2e idempotency test]
├── src/infra/firecast/firecast-client.ts                          [MODIFY] +cobertura_completa field
├── src/domain/fires-predictions/enterprise/entities/
│   fires-predictions-month-data.ts                                [MODIFY] +hasData
├── src/domain/fires-predictions/enterprise/entities/
│   fires-prediction-with-month-data.ts                            [MODIFY] +hasData passthrough
├── src/infra/database/prisma/mappers/prisma-month-data-mapper.ts  [MODIFY] +hasData
├── src/domain/fires-predictions/application/use-cases/fires-predictions/
│   sync-fires-predictions-from-firecast.ts                        [MODIFY] +hasData per padded slot
├── src/domain/fires-predictions/application/use-cases/tests/
│   sync-fires-predictions-from-firecast.spec.ts                   [MODIFY] +hasData assertions
├── src/infra/http/presenters/fires-prediction-presenter.ts        [MODIFY] +hasData in JSON
├── src/infra/scheduler/cronJobs/firecast-sync-cron.service.ts     [CREATE]
└── src/infra/scheduler/scheduler.module.ts                       [MODIFY] register cron + FirecastModule

Queimadas-Cariri-Front (already cloned at
C:\Users\Guilherme\Desktop\queimadas\Queimadas-Cariri-Front, branch feat/integracao-firecast-ia)
├── src/pages/DashboardQueimadas/interfaces/fires-data.ts          [MODIFY] MonthData +hasData
└── src/components/Echarts/index.tsx                               [MODIFY] null for !hasData
```

---

## Task 10: Prisma migration — unique constraint + hasData column, generated for real

**Files:**
- Modify: `prisma/schema.prisma`
- Create: `prisma/migrations/<timestamp>_add_fires_predictions_unique_and_month_hasdata/migration.sql` (generated, not hand-written)

**Interfaces:**
- Produces: `FiresPredictions` gains `@@unique([cityId, year])` (Prisma will name the constraint `cityId_year` by default — confirm the generated name in the migration SQL, later tasks reference it).
- Produces: `FiresPredictionsMonthData` gains `hasData Boolean @default(true)`.

- [ ] **Step 1: Edit the schema**

In `prisma/schema.prisma`, find `model FiresPredictions` (currently ends with `@@map("fire_predictions")` right before the closing `}`):

```prisma
model FiresPredictions {
  id                        String                      @id @default(uuid())
  cityId                    String
  city                      City                        @relation(fields: [cityId], references: [id])
  predictionTotal           Int
  occurredTotal             Int
  year                      Int
  month                     Int
  created_at                DateTime                    @default(now())
  FiresPredictionsMonthData FiresPredictionsMonthData[]

  @@unique([cityId, year])
  @@map("fire_predictions")
}
```

(Only the `@@unique([cityId, year])` line is new.)

Find `model FiresPredictionsMonthData`:

```prisma
model FiresPredictionsMonthData {
  id              String           @id @default(uuid())
  predictionId    String
  month           Int
  created_at      DateTime         @default(now())
  fireOccurrences Int
  firesPredicted  Int
  hasData         Boolean          @default(true)
  prediction      FiresPredictions @relation(fields: [predictionId], references: [id])

  @@map("fire_predictions_month_data")
}
```

(Only the `hasData Boolean @default(true)` line is new.)

- [ ] **Step 2: Start a real local Postgres**

```bash
cd C:/Users/Guilherme/Desktop/queimadas/Monitor-Queimadas-Cariri-Back-End
npm run docker:up:dev
```

Wait a few seconds for Postgres to accept connections (the container is `burned-database`, port `5433` per `.docker/docker-compose.dev.yaml`).

- [ ] **Step 3: Point Prisma at it**

Check whether a `.env` file already exists in this repo (it's gitignored, so it may or may not be present from prior work). If it doesn't have a working `DATABASE_URL`, create/update `.env` (NOT `.env.example`) with:

```
DATABASE_URL="postgresql://burned:burned@localhost:5433/burned_db?schema=public"
```

(Matches `.docker/docker-compose.dev.yaml`'s `POSTGRES_USER=burned`, `POSTGRES_PASSWORD=burned`, `POSTGRES_DB=burned_db`, port `5433`.)

- [ ] **Step 4: Generate the migration for real**

```bash
npx prisma migrate dev --name add_fires_predictions_unique_and_month_hasdata
```

This applies all pending migrations (including any from before this branch) to the fresh dev database and generates a new migration file for the two schema changes. Read the generated `migration.sql` under `prisma/migrations/<new-timestamp>_add_fires_predictions_unique_and_month_hasdata/` to confirm it contains an `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE ("cityId", "year")` (or equivalent) and an `ALTER TABLE ... ADD COLUMN "hasData" BOOLEAN NOT NULL DEFAULT true`. Note the exact constraint name Prisma generated (needed by Task 11).

- [ ] **Step 5: Confirm the Prisma client regenerates cleanly**

```bash
npx prisma generate
npm run build
```

Expected: both exit 0. `npm run build` failing here would mean the schema change broke a type somewhere already consuming the client — investigate before proceeding, don't paper over it.

- [ ] **Step 6: Commit**

```bash
git add prisma/schema.prisma prisma/migrations/
git commit -m "feat: add unique(cityId, year) and month-level hasData flag

Prepares the schema for real upsert-based idempotency (Task 11) and for
distinguishing a genuine zero-fires month from an unsynced one (Task 12).
Migration generated for real against a local dev Postgres via
npx prisma migrate dev, not hand-written."
```

Do NOT push yet — Task 11 lands on the same commit sequence before the next push.

---

## Task 11: Real idempotency — `saveMany` becomes an upsert by `(cityId, year)`

**Files:**
- Modify: `src/infra/database/prisma/repositories/prisma-fires-prediction-repository.ts`
- Test: `src/infra/database/prisma/repositories/tests/prisma-fires-prediction-repository.e2e-spec.ts` (create if it doesn't exist; check first — an e2e test for this repository may already exist under a similar path, search `find src -iname "*fires-prediction-repository*spec*"` before creating a duplicate)

**Interfaces:**
- Consumes: the `@@unique([cityId, year])` constraint from Task 10 (exact constraint name confirmed in that task's migration SQL).
- Produces: `PrismaFiresPredictionsRepository.saveMany(entities: FiresPredictionsWithMonthData[]): Promise<FiresPredictionsAndMonthData[] | null>` — same signature, new behavior: re-running with the same `(cityId, year)` pair updates the existing row (totals + month data replaced) instead of silently trying to insert a duplicate.

- [ ] **Step 1: Read the current `saveMany` and confirm the constraint name**

```bash
cd C:/Users/Guilherme/Desktop/queimadas/Monitor-Queimadas-Cariri-Back-End
cat src/infra/database/prisma/repositories/prisma-fires-prediction-repository.ts
grep -n "UNIQUE" prisma/migrations/*/migration.sql | tail -3
```

The current implementation does one bulk `createMany({ data, skipDuplicates: true })` for all entities, then a separate `createMany` for all their month data — `skipDuplicates` has never fired because no unique constraint existed on the business key (only on `id`, which is always a fresh UUID). Confirm this reading matches what you see before changing it.

- [ ] **Step 2: Write the failing e2e test**

Find whether `src/infra/database/prisma/repositories/tests/` (or a similar existing path — check `find src -iname "*.e2e-spec.ts" | xargs grep -l FiresPredictions` for the real location before creating a new file) already has an e2e spec exercising `PrismaFiresPredictionsRepository`. This repo's e2e tests run against a real database (`npm run test:e2e`, which does `docker:up:test` + migrate + vitest). If no existing spec file covers this repository, create `src/infra/database/prisma/repositories/tests/prisma-fires-prediction-repository.e2e-spec.ts` following the existing e2e spec conventions in this codebase (check e.g. `create-fires-predictions.controller.e2e-spec.ts` for the exact setup/teardown pattern — module bootstrap, Prisma cleanup between tests) and add:

```typescript
it('upserts instead of duplicating when saveMany is called twice for the same city and year', async () => {
  // Arrange: create a city via the real CityRepository the test module provides
  const cityRepository = /* resolve from the testing module, same pattern as sibling e2e specs */;
  const [city] = await cityRepository.saveMany([City.create({ name: 'Crato Teste Idempotencia' })]);

  const firstRun = FiresPredictionsWithMonthData.create({
    city: City.create({ name: city.name }, city.id),
    occurredTotal: 10,
    predictionTotal: 20,
    year: 2023,
    createdAt: new Date(2023, 0, 1),
    monthDataProps: Array.from({ length: 12 }, () => ({
      fireOccurrences: 1,
      firesPredicted: 2,
      hasData: true,
    })),
  });

  const repository = /* resolve PrismaFiresPredictionsRepository from the testing module */;
  await repository.saveMany([firstRun]);

  const secondRun = FiresPredictionsWithMonthData.create({
    city: City.create({ name: city.name }, city.id),
    occurredTotal: 99,
    predictionTotal: 199,
    year: 2023,
    createdAt: new Date(2023, 0, 1),
    monthDataProps: Array.from({ length: 12 }, () => ({
      fireOccurrences: 9,
      firesPredicted: 19,
      hasData: true,
    })),
  });

  await repository.saveMany([secondRun]);

  const all = await repository.findByCity(city.name);
  expect(all).toHaveLength(1); // not 2 — the second run updated, didn't duplicate
  expect(all![0].occurredTotal).toBe(99); // reflects the latest sync, not the first
});
```

Adjust the exact test-module bootstrap and cleanup boilerplate to match this codebase's real e2e conventions — read a sibling e2e spec file first and mirror its structure precisely rather than inventing new setup code.

- [ ] **Step 2b: Run test to verify it fails**

```bash
npm run docker:up:test
sleep 5
npx dotenv -e .env.test -- npm run prisma:migrate:dev
npx vitest run --config ./vitest.config.e2e.ts -t "upserts instead of duplicating"
```

Expected: FAIL — `all` has length 2 (or the unique constraint throws a raw Prisma error), not 1.

- [ ] **Step 3: Rewrite `saveMany` as a real upsert**

Replace the body of `saveMany` in `src/infra/database/prisma/repositories/prisma-fires-prediction-repository.ts`:

```typescript
  async saveMany(
    entities: FiresPredictionsWithMonthData[],
  ): Promise<FiresPredictionsAndMonthData[] | null> {
    if (!entities || entities.length <= 0) {
      return null;
    }

    try {
      const savedIds: string[] = [];

      for (const entity of entities) {
        const firesPredictionData = PrismaFiresPredictionsMapper.toPrisma(
          entity.firesPredictions,
        );

        const upserted = await this.prisma.$transaction(async (tx) => {
          const saved = await tx.firesPredictions.upsert({
            where: {
              cityId_year: {
                cityId: firesPredictionData.cityId,
                year: firesPredictionData.year,
              },
            },
            create: firesPredictionData,
            update: {
              predictionTotal: firesPredictionData.predictionTotal,
              occurredTotal: firesPredictionData.occurredTotal,
              month: firesPredictionData.month,
              created_at: firesPredictionData.created_at,
            },
          });

          // Month data has no natural per-month unique key exposed here, and
          // a sync always supplies a full 12-slot series (see the use-case's
          // padding) — replacing the set atomically is simpler and safer
          // than diffing 12 rows by month number, and avoids ever leaving
          // stale month rows from a smaller previous series behind.
          await tx.firesPredictionsMonthData.deleteMany({
            where: { predictionId: saved.id },
          });
          await tx.firesPredictionsMonthData.createMany({
            data: entity.monthData.map((monthData) => ({
              ...PrismaMonthDataMapper.toPrisma(monthData),
              predictionId: saved.id,
            })),
          });

          return saved;
        });

        savedIds.push(upserted.id);
      }

      const createdFiresPredictions =
        await this.prisma.firesPredictions.findMany({
          where: { id: { in: savedIds } },
          include: {
            city: true,
            FiresPredictionsMonthData: true,
          },
        });

      return createdFiresPredictions.map((entry) => ({
        firesPrediction: PrismaFiresPredictionsMapper.toDomain(entry),
        monthData: entry.FiresPredictionsMonthData.map((data) =>
          PrismaMonthDataMapper.toDomain(data),
        ),
      }));
    } catch (error) {
      console.error('Error during transaction:', error);
      throw new Error('Error creating entries');
    }
  }
```

If Step 1's grep found the generated unique constraint has a different auto-generated name than `cityId_year` (Prisma's default naming is `<field1>_<field2>` for composite `@@unique`, but confirm against the actual migration SQL/generated client types — TypeScript will fail to compile with the wrong key name, which is a reliable signal), use the real name instead.

- [ ] **Step 4: Run test to verify it passes**

Same command as Step 2b. Expected: PASS.

- [ ] **Step 5: Run the full e2e and unit suites**

```bash
npx vitest run --config ./vitest.config.e2e.ts
npm run test
npm run build
```

Expected: all pass, 0 TypeScript errors. Pay particular attention to `create-fires-predictions.controller.e2e-spec.ts` (or wherever `RegisterFiresPredictionsUseCase`/`saveMany` is already exercised) — confirm the changed upsert behavior doesn't break an existing "create a fresh prediction" test case (it shouldn't: a genuinely new `(cityId, year)` pair takes the `create` branch of the upsert, identical in effect to the old `createMany`).

- [ ] **Step 6: Commit**

```bash
git add src/infra/database/prisma/repositories/prisma-fires-prediction-repository.ts \
        src/infra/database/prisma/repositories/tests/
git commit -m "fix: make saveMany idempotent via real upsert on (cityId, year)

createMany's skipDuplicates never fired -- no unique constraint existed
on the business key, only on the always-fresh id. Re-running a sync for
the same city+year now updates the existing row (totals + month data
replaced atomically) instead of inserting a duplicate."
```

---

## Task 12: Propagate `hasData` end to end (FireCast -> client -> use-case -> entity -> mapper -> presenter)

**Files:**
- Modify: `src/infra/firecast/firecast-client.ts`
- Modify: `src/domain/fires-predictions/enterprise/entities/fires-predictions-month-data.ts`
- Modify: `src/domain/fires-predictions/enterprise/entities/fires-prediction-with-month-data.ts`
- Modify: `src/infra/database/prisma/mappers/prisma-month-data-mapper.ts`
- Modify: `src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts`
- Modify: `src/infra/http/presenters/fires-prediction-presenter.ts`
- Test: `src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts`

**Interfaces:**
- Consumes: `hasData Boolean @default(true)` column from Task 10; FireCast's `GET /v1/champion/municipio_monthly_series` already returns `cobertura_completa` per row (queimadas-v3, already shipped) — this task's `FirecastMonthlySeriesEntry` interface just needs to declare it, it isn't otherwise used here (the use-case derives its own per-month `hasData` from whether FireCast returned a row for that month at all, which is a more precise, per-month signal than the year-level `cobertura_completa`).
- Produces: `FiresPredictionPresenter.toHTTP(...)`'s `monthData` array items each carry `hasData: boolean`.

- [ ] **Step 1: Add the field to `FirecastMonthlySeriesEntry`**

In `src/infra/firecast/firecast-client.ts`, find:

```typescript
export interface FirecastMonthlySeriesEntry {
  geocodigo: number;
  ano: number;
  mes: number;
  y_sum: number;
  pred_sum: number;
  n: number;
}
```

Add `cobertura_completa: boolean;` as a new field (matches the JSON key FireCast's endpoint already returns — see `docs/superpowers/specs/2026-07-26-cariri-ia-integration-design.md` in `queimadas-v3` for the field's origin).

- [ ] **Step 2: Add `hasData` to the `FiresPredictionsMonthData` entity**

In `src/domain/fires-predictions/enterprise/entities/fires-predictions-month-data.ts`, add to the `FiresPredictionsMonthDataProps` interface:

```typescript
export interface FiresPredictionsMonthDataProps {
  month: number;
  fireOccurrences: number;
  firesPredicted: number;
  hasData: boolean;
  createdAt: Date;
  FiresPrediction?: FiresPredictions;
}
```

Add a getter/setter pair (matching the existing style for `fireOccurrences`/`firesPredicted`):

```typescript
  get hasData(): boolean {
    return this.props.hasData;
  }

  set hasData(hasData: boolean) {
    this.props.hasData = hasData;
  }
```

In the `static create(...)` method, `hasData` is required (not defaulted) except where existing callers don't pass it — check `Optional<FiresPredictionsMonthDataProps, 'createdAt' | 'month'>` (the current optional-fields list). To avoid breaking any other caller of `FiresPredictionsMonthData.create` that doesn't yet know about `hasData`, add `'hasData'` to that `Optional<...>` union too, and default it in `defaultProps`:

```typescript
  static create(
    props: Optional<FiresPredictionsMonthDataProps, 'createdAt' | 'month' | 'hasData'>,
    id?: UniqueEntityID,
  ) {
    const defaultProps: FiresPredictionsMonthDataProps = {
      ...props,
      createdAt: props.createdAt ?? new Date(),
      month: props.month ?? new Date().getMonth() + 1,
      hasData: props.hasData ?? true,
    };
    const instance = new FiresPredictionsMonthData(defaultProps, id);
    return instance;
  }
```

(Defaulting to `true` preserves old behavior for any caller that predates this field — e.g. the manually-created predictions via `CreateFiresPredictionsController`, which always represent real data.)

- [ ] **Step 3: Pass `hasData` through `FiresPredictionsWithMonthData`**

In `src/domain/fires-predictions/enterprise/entities/fires-prediction-with-month-data.ts`, find:

```typescript
type monthDataProps = {
  fireOccurrences: number;
  firesPredicted: number;
};
```

Add the field:

```typescript
type monthDataProps = {
  fireOccurrences: number;
  firesPredicted: number;
  hasData: boolean;
};
```

Find where `FiresPredictionsMonthData.create` is called inside the constructor:

```typescript
    this.monthData = props.monthDataProps.map((monthData, i) => {
      return FiresPredictionsMonthData.create({
        fireOccurrences: monthData.fireOccurrences,
        firesPredicted: monthData.firesPredicted,
        FiresPrediction: this._firesPredictions,
        month: i + 1,
      });
    });
```

Add `hasData: monthData.hasData,` to the object passed to `create`.

- [ ] **Step 4: Propagate through the Prisma mapper**

In `src/infra/database/prisma/mappers/prisma-month-data-mapper.ts`, add `hasData: raw.hasData,` to `toDomain`'s returned props, and `hasData: monthData.hasData,` to `toPrisma`'s returned object.

- [ ] **Step 5: Write the failing test for per-month `hasData`**

In `src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts`, extend the existing "month padding" test (the one seeded with non-contiguous months 5 and 8 — search for it) to also assert `hasData`:

```typescript
    // Real months (5 and 8) should carry hasData: true; every padded
    // (synthetic zero) month should carry hasData: false, so the
    // front-end can distinguish "genuinely zero" from "not synced".
    const byMonth = new Map(items.map((item) => [item.month, item]));
    expect(byMonth.get(5)!.hasData).toBe(true);
    expect(byMonth.get(8)!.hasData).toBe(true);
    expect(byMonth.get(1)!.hasData).toBe(false);
    expect(byMonth.get(12)!.hasData).toBe(false);
```

(Add this to the existing test body rather than creating a new test — it's extending the same scenario, not a new one. If the existing test's fixture/assertions don't match this description closely, adapt to the real current test rather than guessing blindly — read the file first.)

- [ ] **Step 5b: Run test to verify it fails**

```bash
npx vitest run src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts
```

Expected: FAIL — `hasData` is `undefined` on the entity today (property doesn't exist on the raw items being read, or the field flows through as `undefined`).

- [ ] **Step 6: Wire `hasData` into the padding logic**

In `src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts`, find:

```typescript
      const paddedMonthDataProps: Array<{
        fireOccurrences: number;
        firesPredicted: number;
      }> = Array.from({ length: 12 }, () => ({
        fireOccurrences: 0,
        firesPredicted: 0,
      }));
      for (const row of sorted) {
        paddedMonthDataProps[row.mes - 1] = {
          fireOccurrences: Math.round(row.y_sum),
          firesPredicted: Math.round(row.pred_sum),
        };
      }
```

Replace with:

```typescript
      const paddedMonthDataProps: Array<{
        fireOccurrences: number;
        firesPredicted: number;
        hasData: boolean;
      }> = Array.from({ length: 12 }, () => ({
        fireOccurrences: 0,
        firesPredicted: 0,
        hasData: false,
      }));
      for (const row of sorted) {
        paddedMonthDataProps[row.mes - 1] = {
          fireOccurrences: Math.round(row.y_sum),
          firesPredicted: Math.round(row.pred_sum),
          hasData: true,
        };
      }
```

- [ ] **Step 7: Run test to verify it passes**

Same command as Step 5b. Expected: PASS.

- [ ] **Step 8: Expose `hasData` in the presenter**

In `src/infra/http/presenters/fires-prediction-presenter.ts`, find:

```typescript
      monthData: FiresPredictionsAndMonthData.monthData.map((monthData) => {
        return {
          fireOccurrences: monthData.fireOccurrences,
          firesPredicted: monthData.firesPredicted,
          month: monthData.month,
        };
      }),
```

Add `hasData: monthData.hasData,` to the returned object.

- [ ] **Step 9: Run the full suite**

```bash
npm run test
npm run build
```

Expected: all pass, 0 TypeScript errors.

- [ ] **Step 10: Commit**

```bash
git add src/infra/firecast/firecast-client.ts \
        src/domain/fires-predictions/enterprise/entities/fires-predictions-month-data.ts \
        src/domain/fires-predictions/enterprise/entities/fires-prediction-with-month-data.ts \
        src/infra/database/prisma/mappers/prisma-month-data-mapper.ts \
        src/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast.ts \
        src/domain/fires-predictions/application/use-cases/tests/sync-fires-predictions-from-firecast.spec.ts \
        src/infra/http/presenters/fires-prediction-presenter.ts
git commit -m "feat: propagate hasData end to end, closing the zero-ambiguity gap

A padded (unsynced) month and a genuine zero-fires month were both
persisted and served as an indistinguishable 0. hasData: false now marks
padding explicitly, true marks a real FireCast row, all the way through
to the HTTP response's monthData[].hasData -- unblocks the front-end
fix (Task 14)."
```

---

## Task 13: Automatic sync via `@Cron`

**Files:**
- Create: `src/infra/scheduler/cronJobs/firecast-sync-cron.service.ts`
- Modify: `src/infra/scheduler/scheduler.module.ts`

**Interfaces:**
- Consumes: `SyncFiresPredictionsFromFirecastUseCase.execute({ano})` (existing), `FirecastModule` (existing, Task 4 of the prior plan).
- Produces: an automatic daily sync at 4am server time for the current calendar year.

- [ ] **Step 1: Create the cron service**

Read `src/infra/scheduler/cronJobs/average-fire-weather-cron.service.ts` first (already read during planning — this is the exact pattern to mirror: `Injectable`, a `Logger` named after the class, constructor-injected use-case, `@Cron(cronExpression, { name })` decorating a handler method that logs start/success/failure via the `Either` result).

Create `src/infra/scheduler/cronJobs/firecast-sync-cron.service.ts`:

```typescript
import { Injectable, Logger } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { SyncFiresPredictionsFromFirecastUseCase } from '@/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast';

@Injectable()
export class FirecastSyncCronService {
  private readonly logger = new Logger(FirecastSyncCronService.name);

  constructor(
    private readonly syncFiresPredictionsFromFirecastUseCase: SyncFiresPredictionsFromFirecastUseCase,
  ) {}

  // Daily at 4am -- after the fire-weather cron jobs (12pm, every 15min) so
  // it doesn't contend with them, and at an hour with negligible dashboard
  // traffic. Syncs the current calendar year; FireCast's backtest evidence
  // only grows forward in time as new months are ingested there, so
  // re-running the current year daily picks up new coverage automatically.
  // The (cityId, year) upsert from Task 11 makes this safe to run every
  // day without duplicating anything.
  @Cron('0 4 * * *', {
    name: 'syncFiresPredictionsFromFirecast',
  })
  async handleSyncFiresPredictionsFromFirecast() {
    const ano = new Date().getFullYear();
    this.logger.log(
      `Iniciando cron job: sincronizacao de previsoes da IA (FireCast) para o ano ${ano}.`,
    );

    const result = await this.syncFiresPredictionsFromFirecastUseCase.execute({
      ano,
    });

    if (result.isLeft()) {
      this.logger.error(
        `Cron job falhou: ${result.value.message}`,
        result.value.stack,
      );
    } else {
      this.logger.log(
        `Cron job concluido: ${result.value.syncedCities} cidades sincronizadas, ${result.value.skippedCities.length} ignoradas.`,
      );
    }
  }
}
```

- [ ] **Step 2: Register it in `SchedulerModule`**

In `src/infra/scheduler/scheduler.module.ts`, add the import:

```typescript
import { FirecastModule } from '@/infra/firecast/firecast.module';
import { SyncFiresPredictionsFromFirecastUseCase } from '@/domain/fires-predictions/application/use-cases/fires-predictions/sync-fires-predictions-from-firecast';
import { FirecastSyncCronService } from './cronJobs/firecast-sync-cron.service';
```

Add `FirecastModule` to the `@Module({ imports: [...] })` array (alongside `DatabaseModule`, `HttpModule`, `EnvModule`).

Add `SyncFiresPredictionsFromFirecastUseCase` and `FirecastSyncCronService` to the `providers` array.

`SyncFiresPredictionsFromFirecastUseCase` also needs a `CityRepository` and a `RegisterFiresPredictionsUseCase` provider resolvable in this module's DI graph (same as when it was wired into `http.module.ts`) — `DatabaseModule` (already imported) provides `CityRepository`; `RegisterFiresPredictionsUseCase` needs to be added to `providers` here too if it isn't already resolvable through an imported module. Check by running the build (next step) — a DI resolution failure surfaces at Nest bootstrap, not at `tsc` compile time, so also start the app locally (`npm run start:dev`, watch the startup log for a `Nest can't resolve dependencies` error, then stop it) rather than relying on `npm run build` alone for this specific check.

- [ ] **Step 3: Verify build, tests, and DI resolution**

```bash
npm run build
npm run test
npm run start:dev
```

Let `start:dev` run long enough to see either a successful "Nest application successfully started" log or a DI resolution error; then stop it (Ctrl+C equivalent — kill the process). If DI fails, add whatever provider is missing (most likely `RegisterFiresPredictionsUseCase`, and transitively `FiresPredictionsRepository`'s Prisma binding — check how `http.module.ts` resolves the same use-case and mirror it) and re-verify.

- [ ] **Step 4: Commit**

```bash
git add src/infra/scheduler/cronJobs/firecast-sync-cron.service.ts src/infra/scheduler/scheduler.module.ts
git commit -m "feat: add daily automatic FireCast sync cron

Runs at 4am for the current year, following the exact pattern of the
existing fire-weather cron jobs. Safe to run daily without duplicating
data thanks to the (cityId, year) upsert (previous commit)."
```

- [ ] **Step 5: Push the whole branch**

```bash
AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" push origin feat/integracao-firecast-ia
```

This pushes Tasks 10-13's commits together (already-open PRs #6 and #13 pick up the new commits automatically).

---

## Task 14: Front-End — render a genuine gap instead of a fabricated zero

**Files:**
- Modify: `src/pages/DashboardQueimadas/interfaces/fires-data.ts`
- Modify: `src/components/Echarts/index.tsx`

**Interfaces:**
- Consumes: `monthData[].hasData: boolean`, now present in the real `/predictions` API response (Task 12, Back-End).
- Produces: the `'Ocorridos'` series (and, if reused for the same purpose, `'Previstos '`) renders `null` for months where `hasData` is `false`, which ECharts renders as a visual gap in the line instead of a point at zero.

- [ ] **Step 1: Add `hasData` to the front-end's `MonthData` interface**

In `src/pages/DashboardQueimadas/interfaces/fires-data.ts`, find:

```typescript
export interface MonthData {
  fireOccurrences: number;
  firesPredicted: number;
  month: number;
}
```

Add `hasData: boolean;`.

- [ ] **Step 2: Use it in the chart**

In `src/components/Echarts/index.tsx`, find the two real series (added in the prior plan's Task 8, then fixed further in the whole-branch-review fix commit):

```typescript
        data: predictionObj?.monthData.map((data) => data.firesPredicted) ?? [],
```

and

```typescript
        data: predictionObj?.monthData.map((data) => data.fireOccurrences) ?? [],
```

Replace both with a version that maps to `null` when `hasData` is `false` — ECharts natively renders a `null` value in a `line` series' `data` array as a gap (no point, connective line breaks) rather than plotting it at zero:

```typescript
        data: predictionObj?.monthData.map((data) => data.hasData ? data.firesPredicted : null) ?? [],
```

```typescript
        data: predictionObj?.monthData.map((data) => data.hasData ? data.fireOccurrences : null) ?? [],
```

(`firesPredicted` is FireCast's own model output, which the FireCast API always returns a real number for whenever `hasData` is true for that month — apply the same `hasData` gating to both series for consistency, since a month with no real observed data also has no real backtest prediction context for that specific month slot.)

Find the ambiguity comment added in the prior fix (search for `NOTA: um valor 0 em monthData`) and update/remove it — the ambiguity it described is now resolved, so either delete the comment or replace it with a note that `hasData` now disambiguates this, e.g.:

```typescript
// hasData distingue "sem queimadas" (0, hasData=true) de "mes sem
// sincronizacao" (renderizado como gap na linha, hasData=false) -- ver
// Task 12 do plano docs/superpowers/plans/2026-08-10-idempotencia-ambiguidade-cron.md
// no repo queimadas-v3 / Monitor-Queimadas-Cariri-IA.
```

- [ ] **Step 3: Typecheck**

```bash
cd C:/Users/Guilherme/Desktop/queimadas/Queimadas-Cariri-Front
npm run build
```

Expected: 0 TypeScript errors.

- [ ] **Step 4: Commit and push**

```bash
git add src/pages/DashboardQueimadas/interfaces/fires-data.ts src/components/Echarts/index.tsx
git commit -m "fix: render a real gap instead of a fabricated zero for unsynced months

monthData now carries hasData (back-end Task 12). A month with
hasData=false maps to null in the chart series, which ECharts renders
as a gap in the line -- resolves the ambiguity between 'genuinely zero
fires' and 'this month was never synced', flagged in the prior
whole-branch review."

AUTH=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)
git -c http.extraheader="AUTHORIZATION: basic $AUTH" push origin feat/integracao-firecast-ia
```

---

## Self-Review Notes

- **Spec coverage:** idempotency (Tasks 10-11), ambiguity (Tasks 10, 12, 14), cron (Task 13). All three of the user's explicit complaints are addressed.
- **Type consistency:** `hasData: boolean` is threaded through the same name at every layer (`FirecastMonthlySeriesEntry.cobertura_completa` is intentionally NOT the same field — the use-case derives a more precise per-month `hasData` from whether a row exists for that month, not from the year-level `cobertura_completa` flag; this is called out explicitly in Task 12 so an implementer doesn't conflate the two).
- **Real migration, not hand-written SQL:** Task 10 is explicit about using a real local Postgres via the repo's own `docker:up:dev` script and `npx prisma migrate dev`, per this session's established practice of never fabricating what a real command would produce.
- **Idempotency doesn't regress existing callers:** Task 11 explicitly calls out that `RegisterFiresPredictionsUseCase` is shared with `CreateFiresPredictionsController`, and that the upsert's `create` branch is behaviorally identical to the old path for any genuinely-new `(cityId, year)` pair — only a real re-sync (same city, same year) takes the new `update` branch.
