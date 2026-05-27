# KumoRFM Demo

A full-stack demo application showcasing **KumoRFM**'s predictive query capabilities on relational datasets. Built with FastAPI + vanilla JS SPA — single process, zero build step.

## Quick Start

```bash
# 1. Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

# 2. Configure API key (get one from https://kumo.ai)
echo "KUMO_API_KEY=eyJ..." > backend/.env

# 3. Run
python3 backend/main.py

# 4. Open
open http://localhost:8080
```

The server auto-loads `online_shopping` dataset on startup, then caches locally for near-instant restarts.  
Full test suite: `cd backend && python3 -m pytest tests/ -v` (112 tests).

## Screenshots

| | |
|---|---|
| ![Dashboard](media/dashboard.png) | ![Query Lab](media/query-lab.png) |
| **Dashboard** — dataset stats & quick actions | **Query Lab** — template grid & PQL editor |
| ![Data Explorer](media/data-explorer.png) | ![Query Results](media/query-results.png) |
| **Data Explorer** — schema browser & row preview | **Query Results** — prediction with chart |

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                    Browser (SPA)                            │
│  index.html ← app.css ← app.js                             │
│  Dashboard | Query Lab | Data Explorer | History            │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTP REST (JSON)
┌──────────────────────▼─────────────────────────────────────┐
│              FastAPI Server (:8080)                         │
│  ┌──────────┐ ┌──────────┐ ┌────────────────────────────┐ │
│  │ main.py  │ │routes.py │ │    services.py              │ │
│  │ lifespan,│→│ 9 routes │→│  stores, loaders,           │ │
│  │ cors,    │ │ caching  │ │  LocalGraph builder,        │ │
│  │ security,│ │ error    │ │  KumoRFM model mgmt,       │ │
│  │ static   │ │ handlers │ │  background thread         │ │
│  └──────────┘ └──────────┘ └──────────┬─────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────▼────────────────┐  │
│  │cache.py  │ │logger.py │ │   KumoRFM SDK              │  │
│  │tiered    │ │structured│ │   graph → model → predict  │  │
│  │memory+   │ │request   │ │   queries                   │  │
│  │disk      │ │timing    │ └────────────────────────────┘  │
│  └──────────┘ └──────────┘                                 │
│  ┌────────────┐ ┌──────────┐ ┌────────────┐               │
│  │settings.py │ │datasets  │ │exceptions  │               │
│  │Pydantic    │ │.py: 3    │ │.py: 8      │               │
│  │BaseSettings│ │datasets  │ │error codes │               │
│  └────────────┘ └──────────┘ └────────────┘               │
└────────────────────────────────────────────────────────────┘
```

## Configuration

All settings are configured via environment variables or `backend/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `KUMO_API_KEY` | `""` | KumoRFM API key (required) |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `AUTO_LOAD_DATASET` | `online_shopping` | Dataset to load on startup |
| `CACHE_GRAPH_TTL` | `300` | Graph schema cache (seconds) |
| `CACHE_TEMPLATES_TTL` | `3600` | PQL templates cache (seconds) |
| `CACHE_PREDICT_TTL` | `120` | Prediction result cache (seconds) |
| `CACHE_DISK_ENABLED` | `true` | Enable disk-persistent cache |
| `PREDICT_MAX_ENTITY_IDS` | `1000` | Max entity IDs per request |
| `PREDICT_MAX_QUERY_LENGTH` | `2000` | Max PQL query length |
| `DATAFRAME_DOWNCAST` | `true` | Downcast numeric columns on load |
| `DATASET_CACHE_DIR` | `~/.cache/kumodemo/datasets` | Local cache for S3 datasets (first load slow, subsequent instant) |

### Backend Modules

| Module | File | Role |
|--------|------|------|
| **settings** | `backend/settings.py` | Pydantic `BaseSettings` — all config in one place |
| **config** | `backend/config.py` | Backward-compat re-exports from settings |
| **models** | `backend/models.py` | Pydantic request schemas with validation |
| **services** | `backend/services.py` | Data loaders, stores, model mgmt, prediction orchestration |
| **routes** | `backend/routes.py` | 9 API endpoints with caching + structured error handling |
| **datasets** | `backend/datasets.py` | Dataset definitions, 8 file format loaders, graph builder |
| **cache** | `backend/cache.py` | Tiered (memory + disk) TTL cache with `@cached` decorator |
| **exceptions** | `backend/exceptions.py` | 8 error classes with status codes + error codes |
| **logger** | `backend/logger.py` | Structured logging with request ID, timing, component tags |

### Frontend Files

| File | Lines | Role |
|------|-------|------|
| `frontend/dist/index.html` | ~200 | SPA shell with 4 pages + shortcuts modal |
| `frontend/dist/app.css` | ~260 | Dark theme, gradients, animations, responsive |
| `frontend/dist/app.js` | ~1090 | SPA logic, charting, comparison mode, pagination, sorting |

## API Reference

### `GET /api/health`

Server health check.

```bash
curl http://localhost:8080/api/health
```

```json
{"status": "ok", "api_key_set": true, "ready": true, "dataset": "online_shopping"}
```

### `GET /api/status`

Dataset loading status — poll this while the background loader runs.

```bash
curl http://localhost:8080/api/status
```

```json
{"api_key_configured": true, "loaded": true, "dataset": "online_shopping", "error": ""}
```

### `GET /api/datasets`

List available datasets with metadata.

```bash
curl http://localhost:8080/api/datasets
```

### `POST /api/load-dataset`

Load a dataset asynchronously. Returns immediately; poll `/api/status`.

```bash
curl -X POST http://localhost:8080/api/load-dataset \
  -H 'Content-Type: application/json' \
  -d '{"dataset": "steam"}'
```

```json
{"status": "loading", "dataset": "steam"}
```

### `GET /api/graph`

Relational graph schema with column types and semantics. Cached 5 min per dataset.

```bash
curl http://localhost:8080/api/graph
```

### `GET /api/preview`

First 10 rows of every table in the loaded dataset.

```bash
curl http://localhost:8080/api/preview
```

### `GET /api/pql-templates`

7 pre-built PQL template queries with names and descriptions.

```bash
curl http://localhost:8080/api/pql-templates
```

### `GET /api/cache-stats`

Cache hit/miss statistics and TTL configuration.

```bash
curl http://localhost:8080/api/cache-stats
```

```json
{
  "stats": {"hits": 42, "misses": 7, "size": 15, "disk_size": 12},
  "ttl": {"graph": 300, "templates": 3600, "predict": 120}
}
```

### `POST /api/predict`

Execute a PQL predictive query.

```bash
curl -X POST http://localhost:8080/api/predict \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
    "run_mode": "fast",
    "explain": false
  }'
```

#### Parameters

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | required | PQL query starting with `PREDICT` (min 8, max 2000 chars) |
| `run_mode` | `"fast"`, `"normal"`, `"best"` | `"fast"` | Example count: 1K / 5K / 10K |
| `explain` | bool | `false` | Return NL summary + cohort analysis |
| `entity_ids` | list\|null | `null` | Override target entities (max 1000) |
| `anchor_time` | string\|null | `null` | ISO date to anchor prediction (e.g. `"2024-06-01"`) |
| `graph_id` | string | `"default"` | Graph identifier |

#### Response (basic)

```json
{
  "status": "ok",
  "result": {
    "prediction": [
      {"ENTITY": 42, "TARGET_PRED": 275.50}
    ]
  }
}
```

#### Response (explain mode)

```json
{
  "status": "ok",
  "result": {
    "summary": "User 42 is predicted to churn (score 0.87)...",
    "prediction": [{"ENTITY": 42, "TARGET_PRED": 0.87}],
    "cohorts": [
      {
        "table_name": "orders",
        "column_name": "price",
        "hop": 1,
        "cohorts": ["low", "medium", "high"],
        "populations": [120, 45, 12],
        "targets": [0.3, 0.6, 0.9]
      }
    ]
  }
}
```

#### Error Responses

| Status | Error Code | When |
|--------|-----------|------|
| 400 | `PREDICTION_ERROR` | Invalid PQL syntax, unknown table/column |
| 400 | `INVALID_QUERY` | Query validation failed |
| 404 | `DATASET_NOT_FOUND` | Unknown dataset ID |
| 429 | `TOO_MANY_REQUESTS` | Live display limit hit |
| 503 | `MODEL_NOT_READY` | Dataset still loading |

## PQL Query Examples

### 1. Demand Forecast — 30-day revenue for an item

```pql
PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42
```

### 2. Customer Churn — will a user go inactive?

```pql
PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id IN (42, 123)
```

### 3. Product Recommendation — top-10 items for a user

```pql
PREDICT LIST_DISTINCT(orders.item_id, 0, 30, days) RANK TOP 10 FOR users.user_id=123
```

### 4. Attribute Inference — predict a missing user attribute

```pql
PREDICT users.age FOR users.user_id=8
```

### 5. Return Prediction — will an order be returned?

```pql
PREDICT COUNT(returns.*, 0, 30, days) > 0 FOR orders.order_id=333
```

*Requires `ecom` dataset (has `returns` table).*

### 6. Review Sentiment — positive reviews forecast

```pql
PREDICT SUM(reviews.is_recommended, 0, 180, days) FOR users.user_id=11227231
```

*Requires `steam` dataset.*

### 7. Multiple Entity Forecast

```pql
PREDICT SUM(orders.price, 0, 30, days) FOR users.user_id IN (1, 5, 42, 99)
```

### 8. Churn Explanation (NL summary + cohorts)

```
POST /api/predict  {"query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id=42", "explain": true}
```

### 9. Cross-dataset: spend prediction on ecom

```pql
PREDICT SUM(orders.price, 0, 30, days) FOR users.user_id=42
```

*Available on `online_shopping` and `ecom` datasets.*

### 10. High-value user identification

```pql
PREDICT SUM(orders.price, 0, 90, days) > 500 FOR users.user_id IN (1, 5, 42, 99)
```

### PQL Syntax Reference

```
PREDICT <aggregation> [comparison] FOR <entity> [RANK TOP N]

Aggregations:
  SUM(table.column, lookback, horizon, unit)
  COUNT(table.*, lookback, horizon, unit)
  LIST_DISTINCT(table.column, lookback, horizon, unit)
  table.column  (direct attribute inference)

Comparisons (optional):
  = <value>
  > <value>
  < <value>
  IN (<v1>, <v2>, ...)

Entities:
  FOR table.column = <id>
  FOR table.column IN (<id1>, <id2>, ...)

Units: days, weeks, months
```

## Datasets

| Dataset | Tables | Total Rows | Format | Source |
|---------|--------|------------|--------|--------|
| `online_shopping` | users, items, orders | ~269K | parquet | Kumo public S3 |
| `ecom` | users, items, orders, returns | ~205K | parquet | Kumo public S3 |
| `steam` | users, games, reviews | ~2.3M | csv | Kumo public S3 (CSV) |

## Supported File Formats

The dataset loader supports 8 formats. To add a custom dataset, add a `DatasetDef` to `datasets.py`:

| Format | Loader | Extension |
|--------|--------|-----------|
| Parquet | `pd.read_parquet()` | `.parquet` |
| CSV | `pd.read_csv()` | `.csv` |
| JSON | `pd.read_json()` | `.json` |
| JSONL | `pd.read_json(lines=True)` | `.jsonl` |
| Excel | `pd.read_excel()` | `.xlsx`, `.xls` |
| Feather | `pd.read_feather()` | `.feather` |
| Pickle | `pd.read_pickle()` | `.pkl`, `.pickle` |

## Frontend Features

| Feature | Description |
|---------|-------------|
| **Dashboard** | Dataset stats, quick template buttons, inline PQL runner, recent queries |
| **Query Lab** | Template grid, PQL editor, entity IDs, run mode selector, comparison mode (A/B), sortable results, pagination |
| **Data Explorer** | Schema browser with column types/semantics, collapsible data preview (10 rows) |
| **Query History** | localStorage-persisted, re-run, delete individual entries, save entity IDs |
| **Comparison Mode** | Side-by-side query editors and results (A/B), independent charting per panel |
| **Charts** | Auto-generated bar or line chart for predictions with multiple data points |
| **Export** | Copy CSV/JSON to clipboard, download CSV/JSON file |
| **Cache Stats** | Dashboard shows cache hit/miss ratio via `/api/cache-stats` |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+Enter` | Run current query |
| `?` | Toggle help modal |
| `1–7` | Load template by number |
| `Ctrl+S` | Save query to history |
| `Ctrl+D` | Clear editor |
| `Ctrl+B` | Toggle comparison mode |
| `R` | Clear results (Query Lab) |
| `Esc` | Close modal |
| Click cell | Copy cell value to clipboard |

### Run Modes

| Mode | Examples | Use Case |
|------|----------|----------|
| **Fast** | 1,000 | Quick exploration |
| **Normal** | 5,000 | Balanced accuracy |
| **Best** | 10,000 | Production-grade |

## Caching

Three-tier caching with automatic promotion from disk → memory:

| Cache Key | TTL | Backend | Behavior |
|-----------|-----|---------|----------|
| `graph:{dataset}` | 5 min | Memory + Disk | Invalidated on dataset switch; pre-warmed after load |
| `templates` | 1 hour | Memory + Disk | Pre-warmed after dataset load |
| `predict:{query}:{mode}:...` | 2 min | Memory + Disk | Skipped for `explain: true` requests |
| Cache cleanup | 5 min | — | Background removal of expired entries |

Stats tracked: hits, misses, current size (memory + disk).

## Error Handling

All errors return a JSON body with a `detail` field. The `ServiceError` hierarchy maps to HTTP status codes:

| Exception | HTTP Status | Error Code | When |
|-----------|-------------|-----------|------|
| `ServiceError` (base) | 400 | `INTERNAL_ERROR` | Unexpected service error |
| `ModelNotReady` | 503 | `MODEL_NOT_READY` | Dataset still loading |
| `DatasetNotFound` | 404 | `DATASET_NOT_FOUND` | Unknown dataset ID |
| `DatasetLoadError` | 500 | `DATASET_LOAD_ERROR` | S3/filesystem load failure |
| `PredictionError` | 400 | `PREDICTION_ERROR` | PQL parse or execution failure |
| `InvalidQuery` | 400 | `INVALID_QUERY` | Validation failure |
| `TooManyRequests` | 429 | `TOO_MANY_REQUESTS` | KumoRFM live display limit |
| `GraphNotReady` | 503 | `GRAPH_NOT_READY` | Graph not yet built |
| `ConfigurationError` | 500 | `CONFIGURATION_ERROR` | Missing API key or misconfig |

## Development

```bash
# Install
pip install -r backend/requirements.txt

# Run all unit tests
cd backend && python3 -m pytest tests/ -v --tb=short -k "not integration"

# Run specific test file
python3 -m pytest tests/test_models.py -v

# Run integration tests (server must be running)
python3 backend/main.py &
python3 -m pytest tests/test_integration.py -v

# Server hot-reload
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

### Test Structure

| File | Type | Count | Description |
|------|------|-------|-------------|
| `test_models.py` | Unit | 8 | Pydantic request validation |
| `test_services.py` | Unit | 19 | Store accessors, loaders, prediction orchestration |
| `test_routes.py` | Route | 18 | FastAPI `TestClient` with `fake_services` mock layer |
| `test_integration.py` | E2E | 21 | Real server + KumoRFM API (skipped if unreachable) |
| `test_cache.py` | Unit | 10 | TTL, invalidation, prefix, decorator, stats |
| `test_exceptions.py` | Unit | 10 | Error class hierarchy, status codes, messages |
| `test_datasets.py` | Unit | 14 | Dataset defs, graph builder, safe_link, info helpers |
| **Total** | | **112** | |

## Deployment

```bash
# Docker Compose (recommended)
docker compose up --build

# Docker
docker build -t kumodemo .
docker run -p 8080:8080 -v $(pwd)/backend/.env:/app/backend/.env kumodemo

# Process manager (systemd / supervisord)
python3 backend/main.py
```

## Troubleshooting

**"No KUMO_API_KEY in .env"**
→ Create `backend/.env` with `KUMO_API_KEY=your_key_here` (or `docker compose run -e KUMO_API_KEY=...`)

**"Only one live display may be active at once"**
→ Consecutive predictions need ~2s gap. The frontend and integration tests handle this; rapid manual requests may trigger it.

**Server won't start — port in use**
→ Change port: `echo "PORT=8081" >> backend/.env`

**Disk cache errors**
→ The cache directory is at `/tmp/kumo_cache`. Ensure `/tmp` is writable or disable disk caching: `CACHE_DISK_ENABLED=false`

**Missing dependencies**
→ If `pydantic-settings` fails, install it: `pip install pydantic-settings`

## License

MIT
