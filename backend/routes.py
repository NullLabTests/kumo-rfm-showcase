import pandas as pd
from fastapi import APIRouter, HTTPException

from models import PredictRequest, LoadDataRequest
from services import (
    _TEMPLATE_CACHE,
    _build_graph_info_for_warm,
    current_dataset,
    get_graph,
    get_load_status,
    get_raw_data,
    is_ready,
    load_dataset_async,
    run_prediction,
)
from cache import get as cache_get, set as cache_set, invalidate as cache_invalidate, stats as cache_stats
from datasets import DATASETS
from exceptions import ServiceError
from logger import log
from settings import settings

router = APIRouter(prefix="/api")


def _handle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ServiceError):
        log.warning("Service error [%s]: %s", exc.error_code, exc.detail)
        return HTTPException(status_code=exc.status_code, detail=exc.detail)
    log.error("Unhandled error: %s", str(exc))
    return HTTPException(status_code=500, detail="Internal server error")


@router.get("/status")
def status():
    s = get_load_status()
    return {
        "api_key_configured": bool(s.get("api_key_configured", False)),
        "loaded": s["ready"],
        "dataset": s["dataset"],
        "error": s["error"],
    }


@router.get("/health")
def health():
    s = get_load_status()
    return {
        "status": "ok",
        "api_key_set": bool(s.get("api_key_configured", False)),
        "ready": s["ready"],
        "dataset": s["dataset"],
    }


@router.post("/load-dataset")
def handle_load_dataset(req: LoadDataRequest):
    if current_dataset() == req.dataset and is_ready():
        return {"status": "already_loaded", "dataset": req.dataset}
    cache_invalidate("graph:")
    cache_invalidate("templates:")
    load_dataset_async(req.dataset)
    return {"status": "loading", "dataset": req.dataset}


@router.get("/datasets")
def list_datasets():
    return {
        "datasets": [
            {
                "id": ds.id_,
                "name": ds.name,
                "description": ds.description,
                "tables": ds.tables,
            }
            for ds in DATASETS.values()
        ]
    }


@router.get("/graph")
def get_graph_info():
    ds = current_dataset()
    cache_key = f"graph:{ds}"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        graph = get_graph()
        raw = get_raw_data()
        result = _build_graph_info_for_warm(graph, raw)
        cache_set(cache_key, result, settings.cache_graph_ttl)
        return result
    except Exception as exc:
        raise _handle_error(exc)


@router.get("/preview")
def table_preview():
    try:
        raw = get_raw_data()
        graph = get_graph()
        preview = {}
        for name in sorted(graph.tables.keys()):
            df = raw.get(name)
            if df is not None and not df.empty:
                preview[name] = {
                    "rows": df.head(10).to_dict(orient="records"),
                    "columns": list(df.columns),
                    "total_rows": len(df),
                }
        return {"tables": preview}
    except Exception as exc:
        raise _handle_error(exc)


@router.post("/predict")
def predict(req: PredictRequest):
    if not is_ready():
        raise HTTPException(503, "Dataset not ready — still loading")

    cache_key = f"predict:{req.query}:{req.run_mode}:{req.explain}:{req.anchor_time}:{req.entity_ids}"
    if not req.explain:
        cached = cache_get(cache_key)
        if cached is not None:
            log.info("Predict cache HIT  %s", _short_query(req.query))
            return cached

    try:
        result = run_prediction(
            query=req.query,
            run_mode=req.run_mode,
            explain=req.explain,
            anchor_time=req.anchor_time,
            entity_ids=req.entity_ids,
            graph_id=req.graph_id,
        )
        body = {"status": "ok", "result": result}
        if not req.explain:
            cache_set(cache_key, body, settings.cache_predict_ttl)
            log.info("Predict cache MISS %s", _short_query(req.query))
        return body
    except Exception as exc:
        raise _handle_error(exc)


def _short_query(q: str) -> str:
    return q[:80] + "..." if len(q) > 80 else q


@router.get("/pql-templates")
def pql_templates():
    cached = cache_get("templates")
    if cached is not None:
        return cached
    result = {"templates": _TEMPLATE_CACHE}
    cache_set("templates", result, settings.cache_templates_ttl)
    return result


@router.get("/cache-stats")
def cache_status():
    return {
        "stats": cache_stats(),
        "ttl": {
            "graph": settings.cache_graph_ttl,
            "templates": settings.cache_templates_ttl,
            "predict": settings.cache_predict_ttl,
        },
    }
