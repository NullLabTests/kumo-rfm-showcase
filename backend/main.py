import os
import io
import base64
import json
import traceback
from typing import Optional
from contextlib import asynccontextmanager

import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

os.environ["KUMO_LOG_LEVEL"] = "ERROR"
import kumoai.experimental.rfm as rfm
import kumoai as kumo

from config import KUMO_API_KEY

model_store = {}
graph_store = {}
raw_data_store = {}


class InitRequest(BaseModel):
    api_key: str


class GraphFromDataRequest(BaseModel):
    tables: dict
    infer_metadata: bool = True
    graph_id: str = "default"


class GraphLinkRequest(BaseModel):
    graph_id: str = "default"
    src_table: str
    fkey: str
    dst_table: str


class PredictRequest(BaseModel):
    query: str
    graph_id: str = "default"
    entity_ids: Optional[list] = None
    anchor_time: Optional[str] = None
    run_mode: str = "fast"
    explain: bool = False
    max_pq_iterations: Optional[int] = None
    num_neighbors: Optional[list] = None


class LoadDataRequest(BaseModel):
    dataset: str  # "ecom", "online_shopping", "uci_retail", "steam"
    graph_id: str = "default"


class AddTableRequest(BaseModel):
    graph_id: str = "default"
    table_name: str
    data: list
    columns: list
    primary_key: Optional[str] = None
    time_column: Optional[str] = None


class EvaluateRequest(BaseModel):
    query: str
    graph_id: str = "default"
    anchor_time: Optional[str] = None
    run_mode: str = "fast"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if KUMO_API_KEY:
        rfm.init(api_key=KUMO_API_KEY)
    yield


app = FastAPI(title="KumoRFM Demo API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_model(graph_id: str = "default"):
    if graph_id not in model_store:
        raise HTTPException(404, f"Model for graph '{graph_id}' not found. Create a graph first.")
    return model_store[graph_id]


def get_graph(graph_id: str = "default"):
    if graph_id not in graph_store:
        raise HTTPException(404, f"Graph '{graph_id}' not found. Create a graph first.")
    return graph_store[graph_id]


@app.get("/api/health")
def health():
    return {"status": "ok", "api_key_set": bool(KUMO_API_KEY)}


_api_key = KUMO_API_KEY


@app.post("/api/init")
def init_kumo(req: InitRequest):
    try:
        key = req.api_key or _api_key
        if not key:
            raise HTTPException(400, "API key required")
        try:
            rfm.init(api_key=key)
        except Exception:
            pass  # Already initialized, which is fine
        return {"status": "initialized"}
    except Exception as e:
        raise HTTPException(400, str(e))


def _init_kumo_api():
    try:
        rfm.init(api_key=KUMO_API_KEY if KUMO_API_KEY else _api_key)
    except Exception:
        pass  # Already initialized


def _safe_link(graph, src, fkey, dst):
    """Link tables, skipping if already exists."""
    try:
        graph.link(src_table=src, fkey=fkey, dst_table=dst)
    except ValueError as e:
        if "already exists" in str(e):
            pass
        else:
            raise


@app.post("/api/load-dataset")
def load_dataset(req: LoadDataRequest):
    try:
        _init_kumo_api()

        datasets = {
            "ecom": "s3://kumo-sdk-public/rfm-datasets/ecom",
            "online_shopping": "s3://kumo-sdk-public/rfm-datasets/online-shopping",
            "steam": "s3://kumo-sdk-public/rfm-datasets/steam_game_sample",
        }
        root = datasets.get(req.dataset)
        if not root:
            raise HTTPException(400, f"Unknown dataset: {req.dataset}")

        if req.dataset == "ecom":
            df_dict = {
                "users": pd.read_parquet(f"{root}/users.parquet"),
                "items": pd.read_parquet(f"{root}/items.parquet"),
                "orders": pd.read_parquet(f"{root}/orders.parquet"),
                "returns": pd.read_parquet(f"{root}/returns.parquet"),
            }
            graph = rfm.LocalGraph.from_data(df_dict, verbose=False, edges=[])
            _safe_link(graph, "orders", "user_id", "users")
            _safe_link(graph, "orders", "item_id", "items")
            _safe_link(graph, "returns", "order_id", "orders")

        elif req.dataset == "online_shopping":
            df_dict = {
                "users": pd.read_parquet(f"{root}/users.parquet"),
                "items": pd.read_parquet(f"{root}/items.parquet"),
                "orders": pd.read_parquet(f"{root}/orders.parquet"),
            }
            graph = rfm.LocalGraph.from_data(df_dict, verbose=False, edges=[])
            _safe_link(graph, "orders", "user_id", "users")
            _safe_link(graph, "orders", "item_id", "items")

        elif req.dataset == "steam":
            df_dict = {
                "users": pd.read_csv(f"{root}/users.csv"),
                "games": pd.read_csv(f"{root}/games.csv"),
                "reviews": pd.read_csv(f"{root}/recommendations.csv"),
            }
            df_dict["reviews"]["is_recommended"] = df_dict["reviews"]["is_recommended"].astype(int)
            graph = rfm.LocalGraph.from_data(df_dict, verbose=False, edges=[])
            _safe_link(graph, "reviews", "user_id", "users")
            _safe_link(graph, "reviews", "app_id", "games")

        raw_data_store[req.graph_id] = df_dict
        graph_store[req.graph_id] = graph
        model = rfm.KumoRFM(graph, verbose=False)
        model_store[req.graph_id] = model

        tables_info = {}
        for name in sorted(graph.tables.keys()):
            tbl = graph[name]
            raw_df = df_dict.get(name, pd.DataFrame())
            tables_info[name] = {
                "rows": len(raw_df),
                "columns": list(raw_df.columns) if not raw_df.empty else [],
                "primary_key": tbl.primary_key,
                "time_column": tbl.time_column,
            }

        return {
            "status": "loaded",
            "dataset": req.dataset,
            "graph_id": req.graph_id,
            "tables": tables_info,
            "graph_metadata": {
                "table_count": len(graph.tables),
                "tables": list(graph.tables.keys()),
                "links": list(graph._links) if hasattr(graph, '_links') else [],
            },
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(400, f"Failed to load dataset: {str(e)}")


@app.post("/api/graph/add-table")
def add_table(req: AddTableRequest):
    try:
        df = pd.DataFrame(req.data, columns=req.columns)
        tbl = rfm.LocalTable(
            df,
            name=req.table_name,
            primary_key=req.primary_key,
            time_column=req.time_column,
        )
        graph = get_graph(req.graph_id)
        graph.add_table(tbl)
        model_store.pop(req.graph_id, None)
        m = rfm.KumoRFM(graph, verbose=False)
        model_store[req.graph_id] = m
        return {"status": "table_added", "table": req.table_name, "rows": len(df)}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/graph/link")
def link_tables(req: GraphLinkRequest):
    try:
        graph = get_graph(req.graph_id)
        graph.link(src_table=req.src_table, fkey=req.fkey, dst_table=req.dst_table)
        model_store.pop(req.graph_id, None)
        m = rfm.KumoRFM(graph, verbose=False)
        model_store[req.graph_id] = m
        return {"status": "linked", "src": req.src_table, "fkey": req.fkey, "dst": req.dst_table}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/graph/{graph_id}")
def get_graph_info(graph_id: str = "default"):
    graph = get_graph(graph_id)
    raw_df = raw_data_store.get(graph_id, {})
    tables_info = {}
    for name in sorted(graph.tables.keys()):
        tbl = graph[name]
        df = raw_df.get(name, pd.DataFrame())
        cols_info = {}
        for col_name in (df.columns if not df.empty else []):
            col = tbl[col_name]
            cols_info[col_name] = {
                "dtype": str(df[col_name].dtype),
                "stype": str(col.stype) if hasattr(col, 'stype') else "unknown",
            }
        tables_info[name] = {
            "rows": len(df),
            "columns": cols_info,
            "primary_key": tbl.primary_key,
            "time_column": tbl.time_column,
        }

    links = []
    if hasattr(graph, '_links'):
        for l in graph._links:
            links.append({"src_table": l[0], "fkey": l[1], "dst_table": l[2]})

    return {
        "graph_id": graph_id,
        "tables": tables_info,
        "links": links,
    }


@app.post("/api/predict")
def predict(req: PredictRequest):
    try:
        model = get_model(req.graph_id)

        query = req.query
        kwargs = {
            "run_mode": req.run_mode,
        }

        if req.anchor_time:
            kwargs["anchor_time"] = pd.Timestamp(req.anchor_time)
        if req.max_pq_iterations is not None:
            kwargs["max_pq_iterations"] = req.max_pq_iterations
        if req.num_neighbors is not None:
            kwargs["num_neighbors"] = req.num_neighbors

        if req.entity_ids:
            kwargs["indices"] = req.entity_ids

        if req.explain:
            kwargs["explain"] = True
            result = model.predict(query, **kwargs)
            pred_df = result.prediction
            explanation_data = {
                "summary": result.summary,
                "prediction": pred_df.to_dict(orient="records"),
            }
            if hasattr(result, 'details') and result.details:
                if hasattr(result.details, 'cohorts'):
                    cohorts_list = []
                    for c in result.details.cohorts:
                        cohorts_list.append({
                            "table_name": c.table_name,
                            "column_name": c.column_name,
                            "hop": c.hop,
                            "cohorts": c.cohorts,
                            "populations": c.populations,
                            "targets": c.targets,
                        })
                    explanation_data["cohorts"] = cohorts_list
            return {"status": "ok", "result": explanation_data}
        else:
            result = model.predict(query, **kwargs)
            if isinstance(result, pd.DataFrame):
                return {"status": "ok", "result": {"prediction": result.to_dict(orient="records")}}
            elif hasattr(result, 'prediction'):
                return {"status": "ok", "result": {"prediction": result.prediction.to_dict(orient="records")}}
            else:
                return {"status": "ok", "result": {"prediction": str(result)}}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(400, f"Prediction failed: {str(e)}")


@app.post("/api/evaluate")
def evaluate_query(req: EvaluateRequest):
    try:
        model = get_model(req.graph_id)
        kwargs = {"run_mode": req.run_mode}
        if req.anchor_time:
            kwargs["anchor_time"] = pd.Timestamp(req.anchor_time)
        metrics = model.evaluate(req.query, **kwargs)
        return {"status": "ok", "metrics": metrics}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/predict/batch")
def predict_batch(req: PredictRequest):
    try:
        model = get_model(req.graph_id)
        kwargs = {
            "run_mode": req.run_mode,
        }
        if req.anchor_time:
            kwargs["anchor_time"] = pd.Timestamp(req.anchor_time)

        if req.entity_ids:
            with model.batch_mode(batch_size="max", num_retries=1):
                result = model.predict(req.query, indices=req.entity_ids, **kwargs)
        else:
            with model.batch_mode(batch_size="max", num_retries=1):
                result = model.predict(req.query, **kwargs)

        if isinstance(result, pd.DataFrame):
            return {"status": "ok", "result": {"prediction": result.to_dict(orient="records")}}
        return {"status": "ok", "result": {"prediction": result.prediction.to_dict(orient="records")}}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/pql-templates")
def pql_templates():
    return {
        "templates": [
            {
                "name": "Demand Forecast (30-day)",
                "description": "Predict total revenue for an item in the next 30 days",
                "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
                "entity_table": "items",
                "entity_column": "item_id",
            },
            {
                "name": "Customer Churn Prediction",
                "description": "Predict if a user will place zero orders in the next 90 days",
                "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id IN (42, 123)",
                "entity_table": "users",
                "entity_column": "user_id",
            },
            {
                "name": "Product Recommendation",
                "description": "Predict top-10 items a user will buy in the next 30 days",
                "query": "PREDICT LIST_DISTINCT(orders.item_id, 0, 30, days) RANK TOP 10 FOR users.user_id=123",
                "entity_table": "users",
                "entity_column": "user_id",
            },
            {
                "name": "Attribute Inference",
                "description": "Predict a missing user attribute (age)",
                "query": "PREDICT users.age FOR users.user_id=8",
                "entity_table": "users",
                "entity_column": "user_id",
            },
            {
                "name": "Return Prediction",
                "description": "Predict if an order will have a return in the next 30 days",
                "query": "PREDICT COUNT(returns.*, 0, 30, days) > 0 FOR orders.order_id=333",
                "entity_table": "orders",
                "entity_column": "order_id",
            },
            {
                "name": "Sales Forecast (7-day)",
                "description": "Predict scaled sales amount for next 7 days",
                "query": "PREDICT SUM(daily_item.daily_amount_scaled, 0, 7, days) FOR EACH item.item_id",
                "entity_table": "item",
                "entity_column": "item_id",
            },
            {
                "name": "Positive Reviews Forecast",
                "description": "Predict sum of positive reviews for a user in next 6 months",
                "query": "PREDICT SUM(reviews.is_recommended, 0, 180, days) FOR users.user_id=11227231",
                "entity_table": "users",
                "entity_column": "user_id",
            },
            {
                "name": "Game Review Count (filtered)",
                "description": "Predict count of positive reviews for a game in next 30 days",
                "query": "PREDICT COUNT(reviews.* WHERE reviews.is_recommended=1, 0, 30, days) FOR games.app_id=263460",
                "entity_table": "games",
                "entity_column": "app_id",
            },
        ]
    }


@app.get("/api/datasets")
def list_datasets():
    return {
        "datasets": [
            {
                "id": "online_shopping",
                "name": "Online Shopping (E-Commerce)",
                "description": "Users, items, and orders for an e-commerce platform",
                "tables": ["users", "items", "orders"],
                "size": "Small (~10K rows)",
            },
            {
                "id": "ecom",
                "name": "E-Commerce with Returns (H&M)",
                "description": "Users, items, orders, and returns for fashion e-commerce",
                "tables": ["users", "items", "orders", "returns"],
                "size": "Small (~10K rows)",
            },
            {
                "id": "steam",
                "name": "Steam Gaming Platform",
                "description": "Users, games, and reviews from Steam",
                "tables": ["users", "games", "reviews"],
                "size": "Small (~50K rows)",
            },
        ]
    }


@app.post("/api/reset")
def reset_graph(graph_id: str = "default"):
    graph_store.pop(graph_id, None)
    model_store.pop(graph_id, None)
    return {"status": "reset"}


try:
    dist_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
    if os.path.isdir(dist_dir):
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")
except Exception:
    pass


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)
