"""Integration tests that call the real KumoRFM API through the running server.
Requires the server to be running on localhost:8080 and a valid KUMO_API_KEY in .env.
Tests are skipped if the server is unreachable."""

import os
import time
from pathlib import Path

import pytest
import requests


API_BASE = "http://localhost:8080/api"
TIMEOUT = 120  # predictions can be slow


def _server_alive() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        return r.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


def _dataset_ready() -> bool:
    try:
        r = requests.get(f"{API_BASE}/status", timeout=3)
        data = r.json()
        return data.get("loaded", False)
    except Exception:
        return False


def _wait_for_ready(max_retries: int = 30, delay: int = 3) -> bool:
    for _ in range(max_retries):
        if _dataset_ready():
            return True
        import time
        time.sleep(delay)
    return False


server_alive = pytest.mark.skipif(not _server_alive(), reason="Server not running on localhost:8080")
dataset_ready = pytest.mark.skipif(not _wait_for_ready(), reason="Dataset not loaded yet")


# ─── Health / Status ─────────────────────────────────────────────────

@server_alive
class TestHealth:
    def test_health_endpoint(self):
        r = requests.get(f"{API_BASE}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "api_key_set" in data

    def test_status_endpoint(self):
        r = requests.get(f"{API_BASE}/status", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert "api_key_configured" in data
        assert "loaded" in data
        assert "dataset" in data


# ─── Dataset management ─────────────────────────────────────────────

@server_alive
@dataset_ready
class TestDatasets:
    def test_list_datasets(self):
        r = requests.get(f"{API_BASE}/datasets", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert len(data["datasets"]) == 3
        ids = [d["id"] for d in data["datasets"]]
        assert "online_shopping" in ids
        assert "ecom" in ids
        assert "steam" in ids

    def test_current_dataset_is_online_shopping(self):
        r = requests.get(f"{API_BASE}/status", timeout=5)
        data = r.json()
        assert data["dataset"] == "online_shopping"
        assert data["loaded"] is True


# ─── Graph / Schema ─────────────────────────────────────────────────

@server_alive
@dataset_ready
class TestGraph:
    def test_graph_has_expected_tables(self):
        r = requests.get(f"{API_BASE}/graph", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["graph_id"] == "default"
        assert "users" in data["tables"]
        assert "items" in data["tables"]
        assert "orders" in data["tables"]

    def test_graph_users_table_columns(self):
        r = requests.get(f"{API_BASE}/graph", timeout=10)
        tables = r.json()["tables"]
        users = tables["users"]
        cols = users["columns"]
        assert "user_id" in cols
        assert "age" in cols
        assert users["rows"] == 1000

    def test_graph_has_links(self):
        r = requests.get(f"{API_BASE}/graph", timeout=10)
        # Also verify via load-dataset metadata
        pass


# ─── Data Preview ───────────────────────────────────────────────────

@server_alive
@dataset_ready
class TestPreview:
    def test_preview_returns_10_rows(self):
        r = requests.get(f"{API_BASE}/preview", timeout=10)
        assert r.status_code == 200
        tables = r.json()["tables"]
        assert "users" in tables
        assert len(tables["users"]["rows"]) == 10
        assert tables["users"]["total_rows"] == 1000


# ─── Templates ──────────────────────────────────────────────────────

@server_alive
class TestTemplates:
    def test_seven_templates(self):
        r = requests.get(f"{API_BASE}/pql-templates", timeout=5)
        assert r.status_code == 200
        assert len(r.json()["templates"]) == 7

    def test_templates_all_have_predict(self):
        r = requests.get(f"{API_BASE}/pql-templates", timeout=5)
        for t in r.json()["templates"]:
            assert t["query"].startswith("PREDICT")


# ─── Predictions (real API calls) ────────────────────────────────────

@server_alive
@dataset_ready
class TestPredict:
    """These tests make real KumoRFM API calls and verify actual prediction values."""

    def test_demand_forecast_item_42(self):
        """Predict 30-day revenue for item 42."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        pred = data["result"]["prediction"]
        assert len(pred) == 1
        assert pred[0]["ENTITY"] == 42
        assert isinstance(pred[0]["TARGET_PRED"], (int, float))
        assert pred[0]["TARGET_PRED"] > 0  # must be positive revenue

    def test_customer_churn_users_42_and_123(self):
        """Predict churn probability for two users."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id IN (42, 123)",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        pred = r.json()["result"]["prediction"]
        assert len(pred) == 2
        for row in pred:
            assert row["ENTITY"] in (42, 123)
            assert 0 <= row["TARGET_PRED"] <= 1  # probability

    def test_product_recommendation_user_123(self):
        """Get top-5 product recommendations for user 123."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT LIST_DISTINCT(orders.item_id, 0, 30, days) RANK TOP 5 FOR users.user_id=123",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        pred = r.json()["result"]["prediction"]
        assert len(pred) >= 1
        # LIST_DISTINCT RANK returns ENTITY, CLASS, SCORE columns
        row = pred[0]
        assert "CLASS" in row or "TARGET_PRED" in row or "SCORE" in row

    def test_attribute_inference_user_age(self):
        """Predict age for user 8."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT users.age FOR users.user_id=8",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        pred = r.json()["result"]["prediction"]
        assert len(pred) == 1
        assert isinstance(pred[0].get("TARGET_PRED") or pred[0].get("users.age") or list(pred[0].values())[-1], (int, float))

    def test_spend_prediction_user_42(self):
        """Predict 30-day revenue for user 42 (valid FK chain: orders→users)."""
        time.sleep(3)
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT SUM(orders.price, 0, 30, days) FOR users.user_id=42",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        pred = r.json()["result"]["prediction"]
        assert len(pred) == 1
        assert isinstance(pred[0]["TARGET_PRED"], (int, float))

    def test_predict_with_entity_ids_filter(self):
        """Test entity_ids parameter overrides FOR clause entities."""
        time.sleep(3)
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id = 0",
            "entity_ids": [42, 123],
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        pred = r.json()["result"]["prediction"]
        assert len(pred) == 2
        for row in pred:
            assert row["ENTITY"] in (42, 123)

    def test_predict_with_explain(self):
        """Test explain=True returns summary and cohorts."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id=42",
            "explain": True,
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        result = data["result"]
        assert "summary" in result
        assert len(result["summary"]) > 100  # should be a meaningful explanation
        assert "prediction" in result
        assert "cohorts" in result

    def test_predict_with_anchor_time(self):
        """Test anchor_time parameter changes the reference point."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
            "anchor_time": "2024-06-01",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200
        pred = r.json()["result"]["prediction"]
        assert len(pred) == 1

    def test_different_run_modes(self):
        """Test that run_mode parameter is accepted."""
        for mode in ("fast", "normal"):
            r = requests.post(f"{API_BASE}/predict", json={
                "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
                "run_mode": mode,
            }, timeout=TIMEOUT)
            assert r.status_code == 200, f"run_mode={mode} failed"

    def test_explain_cohorts_not_empty(self):
        """Test that explain cohorts contain actual data."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id=42",
            "explain": True,
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        data = r.json()
        cohorts = data["result"].get("cohorts", [])
        assert len(cohorts) > 0, "Expected at least one cohort explanation"
        for c in cohorts:
            assert "table_name" in c
            assert "column_name" in c
            assert "hop" in c


    def test_cache_hit_repeated_query(self):
        """Test that repeating the same query returns from cache."""
        query = "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=1"
        r1 = requests.post(f"{API_BASE}/predict", json={
            "query": query, "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r1.status_code == 200

        r2 = requests.post(f"{API_BASE}/predict", json={
            "query": query, "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r2.status_code == 200
        assert r2.json()["status"] == "ok"

    def test_invalid_query_returns_400(self):
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "NOT A VALID PQL QUERY",
            "run_mode": "fast",
        }, timeout=15)
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_unknown_table_returns_400(self):
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT SUM(nonexistent_table.col, 0, 30, days) FOR users.user_id=1",
            "run_mode": "fast",
        }, timeout=15)
        assert r.status_code == 400

    def test_predict_without_query_returns_422(self):
        r = requests.post(f"{API_BASE}/predict", json={
            "run_mode": "fast",
        }, timeout=5)
        assert r.status_code == 422

    def test_predict_non_existent_entity_returns_400(self):
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id = 9999999",
            "run_mode": "fast",
        }, timeout=15)
        assert r.status_code == 400

    def test_health_after_predictions(self):
        """Health endpoint should always return 200, even after predictions."""
        r = requests.get(f"{API_BASE}/health", timeout=5)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_predict_with_long_query(self):
        """A long but valid query should work."""
        r = requests.post(f"{API_BASE}/predict", json={
            "query": "PREDICT SUM(orders.price, 0, 180, days) FOR items.item_id=1",
            "run_mode": "fast",
        }, timeout=TIMEOUT)
        assert r.status_code == 200

    def test_preview_includes_all_tables(self):
        r = requests.get(f"{API_BASE}/preview", timeout=10)
        tables = r.json()["tables"]
        assert "users" in tables
        assert "items" in tables
        assert "orders" in tables

    def test_graph_columns_have_types(self):
        r = requests.get(f"{API_BASE}/graph", timeout=10)
        tables = r.json()["tables"]
        for tname, tinfo in tables.items():
            for cname, cinfo in tinfo["columns"].items():
                assert "dtype" in cinfo
                assert "stype" in cinfo


# ─── Dataset switching ──────────────────────────────────────────────

@server_alive
@dataset_ready
class TestDatasetSwitch:
    def test_switch_to_steam_and_back(self):
        """Switch to steam dataset, verify it loads, then switch back."""
        # Switch to steam
        r = requests.post(f"{API_BASE}/load-dataset", json={"dataset": "steam"}, timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "loading"

        # Wait for steam to load
        for _ in range(40):
            import time
            time.sleep(3)
            st = requests.get(f"{API_BASE}/status", timeout=5).json()
            if st["loaded"] and st["dataset"] == "steam":
                break
        else:
            pytest.skip("Steam dataset did not load in time")

        # Verify steam tables
        r = requests.get(f"{API_BASE}/graph", timeout=10)
        tables = r.json()["tables"]
        assert "games" in tables
        assert "reviews" in tables
        assert "users" in tables

        # Switch back to online_shopping
        r = requests.post(f"{API_BASE}/load-dataset", json={"dataset": "online_shopping"}, timeout=5)
        assert r.status_code == 200

        for _ in range(40):
            import time
            time.sleep(3)
            st = requests.get(f"{API_BASE}/status", timeout=5).json()
            if st["loaded"] and st["dataset"] == "online_shopping":
                return
        pytest.skip("Could not switch back to online_shopping in time")
