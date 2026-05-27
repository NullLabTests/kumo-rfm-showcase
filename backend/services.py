from __future__ import annotations

import os
import threading as _threading
from typing import Any

import pandas as pd

os.environ["KUMO_LOG_LEVEL"] = "ERROR"
import kumoai.experimental.rfm as rfm  # noqa: E402

from settings import settings
from datasets import DATASETS, build_graph, get_links, load_dataset_data, make_tables_info
from exceptions import ConfigurationError, DatasetNotFound, ModelNotReady, PredictionError
from logger import log, set_component

set_component("svc")
from cache import cleanup as cache_cleanup, set as cache_set, stats as cache_stats

model_store: dict[str, rfm.KumoRFM] = {}
graph_store: dict[str, rfm.LocalGraph] = {}
raw_data_store: dict[str, dict[str, pd.DataFrame]] = {}
_load_lock = _threading.Lock()
_load_status: dict[str, Any] = {
    "ready": False,
    "dataset": "",
    "error": "",
    "api_key_configured": bool(settings.kumo_api_key),
}


def get_load_status() -> dict:
    with _load_lock:
        return dict(_load_status)


def _set_load_status(**kw: Any) -> None:
    with _load_lock:
        _load_status.update(kw)


def get_model(gid: str = "default") -> rfm.KumoRFM:
    with _load_lock:
        if gid not in model_store:
            raise ModelNotReady("Model not ready — dataset still loading")
        return model_store[gid]


def get_graph(gid: str = "default") -> rfm.LocalGraph:
    with _load_lock:
        if gid not in graph_store:
            raise ModelNotReady("Graph not ready — dataset still loading")
        return graph_store[gid]


def get_raw_data(gid: str = "default") -> dict[str, pd.DataFrame]:
    return raw_data_store.get(gid, {})


def is_ready() -> bool:
    return _load_status["ready"]


def current_dataset() -> str:
    return _load_status.get("dataset", "")


def _init_api() -> None:
    if not settings.kumo_api_key:
        raise ConfigurationError("KUMO_API_KEY is not configured")
    try:
        rfm.init(api_key=settings.kumo_api_key)
        log.info("KumoRFM API initialized")
    except Exception as exc:
        log.warning("rfm.init may already be initialized: %s", exc)


def load_dataset(dataset: str) -> dict:
    from datasets import DatasetNotFound as _DSNotFound

    spec = DATASETS.get(dataset)
    if spec is None:
        raise _DSNotFound(f"Unknown dataset: {dataset}")

    log.info("Loading dataset: %s from %s", dataset, spec.root)

    try:
        df_dict = load_dataset_data(dataset)
    except Exception as exc:
        log.exception("Failed to load data for %s: %s", dataset, exc)
        raise

    try:
        graph = build_graph(dataset, df_dict)
        model = rfm.KumoRFM(graph, verbose=False)
    except Exception as exc:
        log.exception("Failed to build graph/model for %s: %s", dataset, exc)
        raise

    graph_id = "default"
    with _load_lock:
        raw_data_store[graph_id] = df_dict
        graph_store[graph_id] = graph
        model_store[graph_id] = model

    rows_info = ", ".join(f"{k}({v.shape[0]} rows)" for k, v in df_dict.items())
    log.info("Loaded %s: %d tables, %s", dataset, len(graph.tables), rows_info)

    meta = {
        "status": "loaded",
        "dataset": dataset,
        "graph_id": graph_id,
        "tables": make_tables_info(graph, df_dict),
        "graph_metadata": {
            "table_count": len(graph.tables),
            "tables": list(graph.tables.keys()),
            "links": get_links(graph),
        },
    }

    _warm_caches(dataset, graph, df_dict)
    cleaned = cache_cleanup()
    if cleaned:
        log.debug("Cache cleanup: removed %d expired entries", cleaned)

    return meta


_TEMPLATE_CACHE = [
    {"name": "Demand Forecast (30-day)", "description": "Predict revenue an item generates in next 30 days",
     "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42"},
    {"name": "Customer Churn", "description": "Predict if a user will place zero orders in the next 90 days",
     "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id IN (42, 123)"},
    {"name": "Product Recommendation", "description": "Top-10 items a user will buy in the next 30 days",
     "query": "PREDICT LIST_DISTINCT(orders.item_id, 0, 30, days) RANK TOP 10 FOR users.user_id=123"},
    {"name": "Attribute Inference", "description": "Predict a missing user attribute (age)",
     "query": "PREDICT users.age FOR users.user_id=8"},
    {"name": "Return Prediction", "description": "Predict if an order will have a return in the next 30 days",
     "query": "PREDICT COUNT(returns.*, 0, 30, days) > 0 FOR orders.order_id=333"},
    {"name": "Positive Reviews Forecast", "description": "Predict sum of positive reviews for a user in 6 months",
     "query": "PREDICT SUM(reviews.is_recommended, 0, 180, days) FOR users.user_id=11227231"},
    {"name": "Explain Churn", "description": "Explain why a user is predicted to churn (NL summary + cohorts)",
     "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id=42"},
]


def _warm_caches(dataset: str, graph: rfm.LocalGraph, df_dict: dict[str, pd.DataFrame]) -> None:
    try:
        info = _build_graph_info_for_warm(graph, df_dict)
        cache_set(f"graph:{dataset}", info, settings.cache_graph_ttl)
        log.debug("Cache warmed: graph:%s", dataset)
    except Exception as exc:
        log.warning("Failed to warm graph cache: %s", exc)
    try:
        cache_set("templates", {"templates": _TEMPLATE_CACHE}, settings.cache_templates_ttl)
        log.debug("Cache warmed: templates")
    except Exception as exc:
        log.warning("Failed to warm template cache: %s", exc)


def _build_graph_info_for_warm(graph: rfm.LocalGraph, raw: dict[str, pd.DataFrame]) -> dict:
    info = {}
    for name in sorted(graph.tables.keys()):
        tbl = graph[name]
        df = raw.get(name, pd.DataFrame())
        cols = {}
        for c in (df.columns if not df.empty else []):
            col = tbl[c]
            cols[c] = {
                "dtype": str(df[c].dtype),
                "stype": str(col.stype) if hasattr(col, "stype") else "unknown",
            }
        info[name] = {
            "rows": len(df),
            "columns": cols,
            "primary_key": str(tbl.primary_key) if tbl.primary_key else None,
            "time_column": str(tbl.time_column) if tbl.time_column else None,
        }
    return {"graph_id": "default", "tables": info}


def _auto_load() -> None:
    _set_load_status(ready=False, dataset="", error="")
    if not settings.kumo_api_key:
        msg = "No KUMO_API_KEY in .env"
        _set_load_status(error=msg)
        log.error(msg)
        return
    try:
        _init_api()
        load_dataset(settings.auto_load_dataset)
        _set_load_status(ready=True, dataset=settings.auto_load_dataset)
        log.info("Auto-load complete: %s", settings.auto_load_dataset)
    except Exception as exc:
        _set_load_status(error=str(exc))
        log.exception("Auto-load failed: %s", exc)


def start_background_load() -> _threading.Thread:
    t = _threading.Thread(target=_auto_load, daemon=True)
    t.start()
    log.info("Background dataset loading started")
    return t


def load_dataset_async(dataset: str) -> None:
    def _bg(ds: str) -> None:
        _set_load_status(ready=False, dataset="", error="")
        try:
            _init_api()
            load_dataset(ds)
            _set_load_status(ready=True, dataset=ds)
            log.info("Async load complete: %s", ds)
        except Exception as exc:
            _set_load_status(error=str(exc))
            log.exception("Async load failed for %s: %s", ds, exc)

    t = _threading.Thread(target=_bg, args=(dataset,), daemon=True)
    t.start()
    log.info("Background dataset loading started: %s", dataset)


def run_prediction(
    query: str,
    run_mode: str = "fast",
    explain: bool = False,
    anchor_time: str | None = None,
    entity_ids: list | None = None,
    graph_id: str = "default",
) -> dict:
    model = get_model(graph_id)

    kwargs: dict[str, Any] = {"run_mode": run_mode}
    if anchor_time:
        try:
            kwargs["anchor_time"] = pd.Timestamp(anchor_time)
        except (ValueError, TypeError) as exc:
            raise PredictionError(f"Invalid anchor_time format: {exc}")
    if entity_ids is not None:
        kwargs["indices"] = entity_ids

    try:
        if explain:
            kwargs["explain"] = True
            log.info("Explaining query: %s", _short_query(query))
            result = model.predict(query, **kwargs)
            cohorts = _extract_cohorts(result)
            return {
                "summary": result.summary,
                "prediction": _serialize_prediction(result),
                "cohorts": cohorts,
            }

        log.info("Predicting: %s", _short_query(query))
        result = model.predict(query, **kwargs)
        return {"prediction": _serialize_prediction(result)}

    except PredictionError:
        raise
    except Exception as exc:
        msg = str(exc)
        if "does not exist" in msg.lower():
            raise PredictionError(f"Invalid table or column: {msg}")
        if "parse" in msg.lower() or "syntax" in msg.lower():
            raise PredictionError(f"Invalid PQL syntax: {msg}")
        if "live display" in msg.lower():
            from exceptions import TooManyRequests
            raise TooManyRequests("Too many concurrent prediction requests. Please wait and try again.")
        log.exception("Prediction failed: %s", msg)
        raise PredictionError(f"Prediction failed: {msg}")


def _short_query(q: str) -> str:
    return q[:80] + "..." if len(q) > 80 else q


def _extract_cohorts(result) -> list:
    if not hasattr(result, "details") or not result.details:
        return []
    if not hasattr(result.details, "cohorts"):
        return []
    try:
        return [
            {
                "table_name": getattr(c, "table_name", ""),
                "column_name": getattr(c, "column_name", ""),
                "hop": getattr(c, "hop", 0),
                "cohorts": getattr(c, "cohorts", []),
                "populations": getattr(c, "populations", []),
                "targets": getattr(c, "targets", []),
            }
            for c in result.details.cohorts
        ]
    except Exception as exc:
        log.warning("Failed to extract cohorts: %s", exc)
        return []


def _serialize_prediction(result):
    if isinstance(result, pd.DataFrame):
        return result.to_dict(orient="records")
    if hasattr(result, "prediction"):
        return result.prediction.to_dict(orient="records")
    log.warning("Unexpected prediction result type: %s", type(result).__name__)
    return str(result)
