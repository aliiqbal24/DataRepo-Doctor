# DataRepo Doctor — SWE Interview Preparation

Use this as a spoken narrative, not as something to recite word for word. The strongest version sounds natural and follows a chain of reasoning: problem, constraints, ownership, design, hard decision, verification, result, limitation, reflection.

This project is a portfolio-quality MVP. Do not describe it as a production system with active users, adoption, uptime, or business savings. Those facts were not measured. The concrete result is a working, tested monitor over four real retrieval paths.

## First: be exact about ownership

Only claim work you can personally defend at the code and design level.

If you directly designed, implemented, reviewed, and tested the project, say:

> I owned the MVP end to end: requirements, architecture, DataRepo integration, execution model, persistence, dashboard, tests, Docker setup, and documentation.

If you used AI coding tools substantially, the honest and still strong version is:

> I drove the product requirements, architecture, tradeoffs, iterative simplification, and acceptance testing. I used an AI coding assistant to accelerate implementation, then inspected, tested, and revised the resulting code until I could explain and defend the complete system.

An interviewer cares less about whether every character was typed manually than whether you made the decisions, found flaws, verified behavior, and understand the result. Never imply solo implementation if that is not accurate.

---

## The 30-second version

> I built DataRepo Doctor, a synthetic retrieval monitor for scientists and data-platform owners who need to know whether a real DataRepo query works right now—not merely whether a storage service responds to a ping. I owned the MVP architecture and verification. It uses DataRepo, FastAPI, isolated Python worker processes, SQLite, and a small HTML/JavaScript dashboard. The interesting challenge was proving complete correctness while preventing a hung third-party query from blocking every later check. I solved that with bounded deterministic queries, schema/count/SHA-256 validation, and one fresh subprocess per probe. The result is four real access-path checks that run sequentially against public S3, PostgreSQL, and ROAPI sources and recover cleanly after timeouts and worker crashes.

Do not open with a technology list. The first two sentences should establish the user, problem, and value.

---

## The 2-minute version

> The problem was that a storage ping, catalog import, or one-row smoke test could report healthy even when the actual user-facing DataRepo query path was broken, incomplete, unauthorized, or returning changed data. Scientists and data-platform owners needed a direct answer to: “Can this representative reader retrieve the entire expected bounded result right now, and how long does that successful query take?”
>
> The main constraints were that the checks had to use real supported access paths, retrieve complete results, use one read-only logical identity, execute locally and sequentially, survive hangs, avoid storing history, and keep latency separate from health. I also wanted a small system that I could explain, so I avoided Redis, Celery, WebSockets, React, and distributed workers.
>
> I owned the MVP design, DataRepo catalog integration, probe execution model, scheduling and persistence behavior, API/dashboard, test strategy, Docker environment, and simplification work. I built four checks: DataRepo Python SDK to a Delta table on public S3, the SDK to Parquet on public S3, the SDK to a Python function table backed by public PostgreSQL, and HTTP to ROAPI using a configuration exported from the DataRepo catalog.
>
> The hardest decision was a simple in-process query versus subprocess isolation. In-process code was smaller, but a native library or network call that ignored cancellation could permanently strand the only FIFO worker. I chose one spawned process per probe because the parent can enforce a hard timeout, kill and reap the child, save an unhealthy outcome, and continue to the next job.
>
> I verified it with 35 unit tests and 14 real integration and fault-injection scenarios, plus Ruff, strict mypy, JavaScript syntax checking, Docker image builds, live API checks, and an on-demand ROAPI run. The concrete result is a one-command local application whose four default checks can become healthy only after the complete bounded result passes schema, exact row-count, and deterministic fingerprint validation.
>
> The biggest limitation is that it is deliberately a single-process, single-worker monitor for one reader profile and four representative queries. It does not prove all data, users, permissions, freshness, or scientific validity. If I rebuilt it, I would keep the bounded end-to-end probes and process isolation, disable returned-row display by default, add authentication before any shared deployment, and add durable queue or multi-worker behavior only after scale justified it.

---

## The 10-minute technical deep dive

### 1. Problem and value

DataRepo exists to give users a consistent Python catalog and table interface over heterogeneous data sources. That abstraction is useful, but it creates a monitoring question: a source service may be reachable while the supported DataRepo retrieval path is broken.

A ping is insufficient because it does not prove:

- the catalog can import;
- the table can resolve;
- the representative credentials are accepted;
- filters and selected columns work;
- the query fully materializes;
- the HTTP response fully decodes; or
- the result is complete and unchanged.

DataRepo Doctor therefore performs synthetic transactions. Each check resembles a small real read a scientist could make. It asks one narrow operational question and does not pretend to monitor freshness, scientific quality, distributions, duplicates, or every possible query.

### 2. Constraints

The design constraints shaped almost every choice:

- One logical read-only identity named `doctor_reader`.
- Real DataRepo Python and ROAPI retrieval paths.
- Deterministically bounded filters or function arguments.
- Explicit selected columns and sort keys.
- Full materialization before success.
- Binary health: healthy or unhealthy.
- Latency is descriptive; it never changes health.
- One global FIFO worker.
- A hard timeout that cannot block subsequent jobs.
- Manual and scheduled work use the same queue.
- Only the latest result and schedule state persist.
- Local, understandable deployment with no distributed infrastructure.

This is why the system intentionally does not contain Redis, Celery, Kafka, Kubernetes, Prometheus, WebSockets, history charts, latency thresholds, or alerting.

### 3. Architecture to draw from memory

```text
Browser (HTML + JavaScript)
        |
        | GET checks / POST run / PATCH schedule
        v
FastAPI process -------------------------> SQLite
        |                            schedules + latest outcome
        |
        +--> recurring scheduler
        |          |
        +----------v
             FIFO asyncio queue
                    |
                    | one job globally
                    v
          parent process executor
                    |
                    | spawn one child + hard timeout
                    v
              isolated probe
               /          \
      DataRepo Python      ROAPI HTTP
       SDK query             query
          |                    |
    S3 / PostgreSQL      Parquet on S3
               \          /
                materialize
                    |
        schema + count + SHA-256
                    |
             safe outcome only
```

The production-style Compose deployment runs the FastAPI app, a one-shot configuration service that exports the DataRepo table into ROAPI configuration, and ROAPI. MinIO and local PostgreSQL are in the `test` profile only; the normal dashboard uses live public data.

### 4. Real sources and retrieval paths

There are four default checks:

1. **AWS Delta products:** DataRepo Python SDK → native `DeltalakeTable` → an AWS public S3 tutorial table. It selects four columns for five fixed product IDs.
2. **PUDL energy-source Parquet:** DataRepo Python SDK → native `ParquetTable` → a versioned Catalyst Cooperative public S3 file. It selects five fixed energy codes.
3. **RNAcentral cross-references:** DataRepo Python SDK → DataRepo `@table` Python function → parameterized PostgreSQL query against EMBL-EBI's public reader database. It resolves two fixed accession values.
4. **PUDL through ROAPI:** HTTP SQL request → ROAPI table exported from the DataRepo catalog → the same public Parquet file.

The DataRepo calls are real. The Python path imports the catalog, calls `catalog.db(database)`, calls `database.table(...)` with DataRepo filters or function arguments and selected columns, then calls `.collect()` and converts the complete result to rows. The monitor does not bypass DataRepo by reading S3 or PostgreSQL directly.

The PostgreSQL source access lives inside the DataRepo function table. It uses a parameterized `WHERE ac = ANY(%s)` query, explicitly requests a read-only transaction, and returns a Polars lazy frame to DataRepo.

ROAPI is slightly different: DataRepo defines the exportable table and generates the ROAPI table configuration, while the monitored runtime access path is the HTTP API itself. That distinction is worth stating clearly.

### 5. Walk one manual request end to end

Use this sequence if asked to draw or narrate a request:

1. The user clicks **Check now**. Browser JavaScript sends `POST /api/checks/{check_id}/run`.
2. FastAPI passes the ID to the queue. The registry is the allowlist: an unknown ID returns 404. There is no user-supplied SQL or generic query language.
3. The queue checks whether that same check is already queued or running. If so, it returns the existing state instead of creating a duplicate.
4. The single FIFO worker marks the job running and calls the process executor on a background thread so the asyncio event loop remains responsive.
5. The executor uses Python's `spawn` multiprocessing context, sends a serialized `ProbeSpec` to a fresh child, and waits only until the configured hard timeout.
6. Inside the child, timing starts immediately before the query call. For Python it covers `database.table(...).collect()`; for ROAPI it covers `httpx.post(...)` until the complete response is returned. Catalog setup, row conversion/JSON decoding, validation, and SQLite writes are excluded.
7. The child validates the materialized rows: exact column order and types, exact row count, deterministic sorting, canonical serialization, and SHA-256 comparison.
8. On success, the child returns a JSON `ProbeOutcome` with healthy status and the one query-latency value. On failure, it returns no latency and one safe failure mode.
9. If the child hangs, the parent kills and reaps it and produces `timeout`. If it exits without a valid outcome, the parent records `worker_crash`.
10. The parent upserts the latest outcome into SQLite, marks the job idle in a `finally` block, calls `task_done()`, and advances to the next FIFO job.
11. The browser polls `GET /api/checks` every two seconds and redraws the status. Running is shown separately while the last completed health remains visible.

Scheduled execution enters at step 3 through the same queue. Manual execution does not change `next_run_at`, so it does not reset scheduled cadence.

### 6. Input validation and trust boundaries

There are two kinds of input:

- **Internal probe specifications:** Pydantic rejects unbounded probes, empty or duplicate selected columns, invalid sort keys, schema/column mismatch, invalid hashes, unsafe timeouts, and obvious secrets. Probe definitions are Python code reviewed with the catalog, not arbitrary user queries.
- **Dashboard operations:** the run endpoint accepts only a known check ID. The schedule endpoint accepts `enabled` and an interval from 5 to 10,080 minutes. Pydantic and repository checks reject invalid values.

The child receives one serialized spec and credentials through environment variables. The parent receives a serialized outcome—not a DataFrame, traceback, or raw HTTP body.

The current public demo probes explicitly opt in to displaying and persisting their tiny returned rows. New probes default to not doing so. For private scientific data, I would keep rows inside the child, return only count/hash/status, and remove row display entirely.

### 7. Authentication versus authorization

Authentication answers “who is this?” Authorization answers “what may this identity do?”

`doctor_reader` is a logical source identity, not a dashboard login:

- Public AWS S3 objects use unsigned reads, so there is no source authentication.
- RNAcentral uses a public reader credential supplied by environment variable.
- Controlled integration fixtures create read-only MinIO and PostgreSQL credentials and grant only object reads or SQL `SELECT`.
- Secrets are absent from probe definitions, SQLite, API responses, and persisted error details.

The dashboard itself currently has no authentication. That is acceptable only for local use. It is the first security issue I would address before exposing the app on a shared network.

### 8. Why complete bounded validation works

Every probe defines:

- filters or function arguments;
- selected columns in fixed order;
- deterministic sort columns;
- expected schema and nullability;
- exact expected row count; and
- expected SHA-256.

The canonical format sorts rows and serializes values with explicit type tags. It handles nulls, integers, strings, booleans, decimals, finite floats, dates, and UTC-normalized timestamps. Column order is part of the contract.

Schema alone would miss missing or changed rows. Count alone would miss changed values. Hash alone without deterministic serialization would be unstable across ordering and representation differences. Together, the checks make “healthy” mean the complete known slice arrived correctly.

SHA-256 collision resistance is far beyond what this use case requires, but the fingerprint is not being used as an authentication mechanism. It is a compact deterministic equality check.

### 9. Persistence and query patterns

SQLite was chosen because there is one local app process, one writer, tiny state, and no need for a network database. Python's built-in `sqlite3` module avoids an ORM dependency.

There are exactly two tables:

- `check_schedule`: primary key `check_id`, interval, phase offset, next run, enabled flag, update time.
- `latest_probe_run`: primary key `check_id`, serialized safe outcome, checked time.

Important operations are point lookups/upserts by `check_id` and full scans of four rows for the dashboard. The primary-key indexes are sufficient; adding secondary indexes would not help at this scale. There is deliberately no history table.

Existing outcomes written by the earlier, more detailed model remain readable. The loader removes obsolete timing/stage fields and maps old failure categories into the five current modes. That compatibility path is unit tested.

### 10. API boundaries and error behavior

The public backend surface is intentionally small:

- `GET /api/checks`: specs safe for display, latest outcome, schedule, and queue state.
- `POST /api/checks/{id}/run`: enqueue or return the existing queued/running state; HTTP 202.
- `PATCH /api/checks/{id}/schedule`: update enabled/interval settings.
- `GET /api/healthz`: process liveness only.

`healthz` does not claim that any catalog is healthy. This separation prevents an orchestrator liveness probe from restarting a healthy app merely because an external dataset is unavailable.

Failures collapse into five operational categories:

- `connection_error`
- `query_error`
- `validation_error`
- `timeout`
- `worker_crash`

Validation summaries still distinguish schema, count, and fingerprint failures. Error details are sanitized: URLs, DSNs, credential-like assignments, quoted values, long tokens, multiple lines, and tracebacks are not exposed. For unsafe unknown third-party messages, only the exception class is retained.

### 11. Scheduling and concurrency

Every check defaults to 60 minutes. Stable registry order gives initial offsets of 0, 5, 10, and 15 minutes. Overrides and `next_run_at` persist.

The scheduler checks for due work once per second but enqueues at most one overdue check per tick, which prevents a restart herd. Manual and scheduled jobs share the same deduplicating queue. Global concurrency is intentionally one because the MVP is measuring representative access, not load-testing shared public services.

The key concurrency boundary is that the queue lives in one FastAPI process. The deployment therefore uses one Uvicorn worker. Multiple Uvicorn workers would create independent queues and schedulers, violating global concurrency and deduplication.

### 12. Hardest problems and real engineering decisions

#### Decision 1: real query versus ping

A ping is cheap but answers the wrong question. Complete bounded retrieval mirrors the user path, controls cost, and enables exact validation.

#### Decision 2: subprocess versus thread

A thread is simpler, but Python cannot safely kill an arbitrary blocked thread and cancellation may not interrupt native I/O. A subprocess adds startup cost but gives the parent a reliable kill/reap boundary. Recovery mattered more for an hourly monitor.

#### Decision 3: sequential versus concurrent

Concurrency shortens a cycle but can load public services and distort representative latency. I chose one FIFO worker; larger scale would use explicit per-source limits.

#### Decision 4: public sources versus only fixtures

Fixtures are deterministic but not realistic; public data is realistic but mutable. Default checks use public sources, while MinIO/PostgreSQL fixtures make integration and fault tests repeatable.

#### Decision 5: detailed diagnostics versus explainability

The first version had timing phases, failure stages, many modes, and SQLAlchemy. I reduced it to one latency, five modes, and built-in SQLite, removing 105 net lines without weakening health guarantees.

#### Actual integration issue: published package behavior

The public `data-repository==0.0.2` wheel did not expose the README's `generate_config` example as expected. Instead of inventing an API or forking the library, I inspected the installed public package and used its real `export_to_roapi_tables` function to generate the ROAPI table configuration. I documented the deviation and left DataRepo unmodified.

#### Actual upgrade bug caught before release

Removing timing and stage fields made older JSON outcomes incompatible with Pydantic's `extra="forbid"`. A deployment with an existing SQLite volume could fail while reading its latest results. I added a compatibility loader that strips removed fields and maps old modes, then added a regression test. This is a useful example of considering persisted data when simplifying models.

### 13. Verification and defensible results

The measured verification from the final simplification pass was:

- **33 unit tests passed:** specs, canonicalization, validation, failure classification, FIFO/deduplication, schedules/restarts, persistence compatibility, API safety, and UI serving.
- **14 integration/fault tests passed:** real Delta, Parquet, PostgreSQL function-table, and ROAPI paths plus validation, unreachable-dependency, timeout, and crash failures.
- Ruff, strict mypy, JavaScript syntax, and production/test Docker builds passed.
- The upgraded app loaded its existing SQLite volume with four healthy latest outcomes.
- One live on-demand ROAPI run completed healthy with a measured latency of **560.649 ms** in that single run.

Be precise with the last number: it was one observed end-to-end query measurement, not an average, percentile, benchmark, SLO, or guarantee. If asked for general latency, say it varies with the public network and source; show the dashboard rather than inventing a representative average.

The result is four real checks with expected sizes 5, 5, 2, and 5 rows; a FIFO worker that survives timeout/crash; persistent editable hourly schedules staggered five minutes apart; and binary health plus successful latency in one dashboard.

There are no measured end users, adoption numbers, cost savings, or production-uptime claims.

### 14. Limitations and reflection

Limitations: one local process and in-memory queue, one logical reader, four probes, no history/alerts/durable jobs/dashboard authentication, mutable public contracts, demo row display, and no centralized observability.

I would keep end-to-end bounded queries, exact validation, latency-independent health, process isolation, shared manual/scheduled execution, and latest-only state. I would remove private row display, add dashboard authentication, keep ROAPI internal, add safe structured telemetry, and introduce durable work or controlled parallelism only when measured requirements justified them.

---

## Fast follow-up answers

| Question | Strong short answer |
|---|---|
| Why not check S3/PostgreSQL directly? | That proves the source, not the supported DataRepo path. The monitor imports the catalog, resolves the table, applies DataRepo parameters, and fully materializes it. |
| Why not `.limit(1)`? | One row can succeed while later partitions, pages, or decoding fail. It cannot prove completeness. |
| Why does latency not affect health? | Health means complete and correct. Latency is separate; a threshold would add an arbitrary policy and degraded state. |
| Why no latency on timeout? | The query never completed, so no successful query latency exists. Partial elapsed time would be misleading. |
| Why a SHA-256 instead of expected rows? | It is a compact equality contract. Canonicalization makes it stable across ordering and representations. |
| Why SQLite and no ORM? | One local writer and two tiny tables do not justify a network database or ORM. `check_id` primary keys cover the query patterns. |
| Why plain JavaScript? | The UI polls one endpoint and performs two mutations. React and a Node build added more machinery than value. |
| Two simultaneous clicks? | The first queues the check; the second receives its existing queued/running state. Different checks remain FIFO and sequential. |
| Restart during a query? | The in-flight job is lost; latest completed state and schedules remain. Overdue schedules restore gradually, but manual queued work is not durable. |
| Does ROAPI invoke DataRepo per request? | DataRepo defines and exports the table configuration; ROAPI performs the runtime HTTP retrieval. The other checks exercise DataRepo's Python runtime. |
| Is the dashboard authenticated? | No; it is local-only. Shared deployment requires authenticated TLS, mutation authorization, internal-only ROAPI, and CSRF protection where applicable. |

---

## If usage grew by 100×

The single FIFO worker would bottleneck before SQLite. At 400 checks, 30–45 second runs could create hours of queue delay; process startup and repeated catalog import would be secondary costs. I would first measure queue wait and per-source duration, then add a few source-limited worker slots, preserve deduplication, make the queue durable only if restart loss mattered, and move SQLite to PostgreSQL only when multiple processes needed coordinated writes. I would not jump directly to Kafka or Kubernetes.

---

## First security investigation

The first issue is the unauthenticated mutation surface. FastAPI binds to `0.0.0.0`, and Compose publishes the app and ROAPI ports. On a shared network, someone could trigger reads, change schedules, or view displayed rows. I would confirm exposure, add authenticated TLS, authorize mutations separately, make ROAPI internal-only, disable row display, review logs for secret leakage, and use a secret manager. Environment variables and spec validation help, but they are not a complete production security model.

---

## How to diagnose a production failure

1. Check `/api/healthz` for app liveness, but do not confuse that with data health.
2. Inspect `/api/checks`: completed health, job state, timestamp, and safe mode.
3. For `connection_error`, test DNS/network from the app container and inspect the dependency.
4. For `query_error`, reproduce the exact bounded path under `doctor_reader` and confirm DataRepo/ROAPI versions.
5. For `validation_error`, inspect schema, controlled actual count, source version, and reviewed fingerprint; never blindly accept the observed hash.
6. For timeout/crash, inspect resource pressure and exit behavior, then confirm the next queued check completed. Restore the dependency or contract and rerun.

---

## Final rehearsal checklist

Be able to deliver the short opening, draw the architecture, walk one request, name all four real paths, define the latency boundary, explain schema/count/hash, describe both SQLite tables, defend subprocess + FIFO choices, tell both real bug stories, state measured results carefully, and admit the authentication, durability, scale, history, and user-adoption limitations.

The closing sentence to remember is:

> The project is intentionally narrow: it does not prove that every dataset or user is healthy. It proves that four representative, complete, bounded retrievals work through the same DataRepo-supported paths users rely on, and it does so in a way that remains truthful under changed data, dependency failures, timeouts, and worker crashes.
