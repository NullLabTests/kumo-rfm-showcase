"""Integration tests for API routes.
Uses fake_services.py to mock the service layer so tests run
without real kumoai SDK or S3 access."""

import os
from unittest.mock import MagicMock, PropertyMock

os.environ["KUMO_LOG_LEVEL"] = "ERROR"
os.environ["KUMO_API_KEY"] = "test-key-123"

import importlib
import config
importlib.reload(config)

import pandas as pd
import pytest
from fastapi.testclient import TestClient


# ─── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
    """Patch all services and routes functions before each test."""
    monkeypatch.setattr("main.settings.rate_limit_enabled", False)
    import tests.fake_services as fake
    import routes as routes_mod
    import services as svc_mod
    from cache import invalidate
    from main import _RATE_LIMIT_STORE
    invalidate()
    _RATE_LIMIT_STORE.clear()

    for attr_name in dir(fake):
        if attr_name.startswith("fake_"):
            real_name = attr_name.replace("fake_", "", 1)
            fake_fn = getattr(fake, attr_name)
            monkeypatch.setattr(svc_mod, real_name, fake_fn)
            if hasattr(routes_mod, real_name):
                monkeypatch.setattr(routes_mod, real_name, fake_fn)


@pytest.fixture
def client():
    from main import app
    with TestClient(app) as c:
        yield c


# ─── Status / Health ─────────────────────────────────────────────────

class TestStatus:
    def _check_security_headers(self, resp):
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-xss-protection") == "1; mode=block"

    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        self._check_security_headers(resp)
        data = resp.json()
        assert data["status"] == "ok"
        assert data["api_key_set"] is True
        assert data["ready"] is True
        assert data["dataset"] == "online_shopping"

    def test_status(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        self._check_security_headers(resp)
        data = resp.json()
        assert data["api_key_configured"] is True
        assert data["loaded"] is True
        assert data["dataset"] == "online_shopping"
        assert data["error"] == ""

    def test_status_no_key(self, client, monkeypatch):
        monkeypatch.setattr("tests.fake_services._api_key_set", False)
        monkeypatch.setattr("tests.fake_services.fake_get_load_status",
            lambda: {"ready": False, "dataset": "", "error": "No key", "api_key_configured": False})
        resp = client.get("/api/status")
        assert resp.status_code == 200
        self._check_security_headers(resp)
        data = resp.json()
        assert data["api_key_configured"] is False


# ─── Dataset management ─────────────────────────────────────────────

class TestDatasets:
    def test_list_datasets(self, client):
        resp = client.get("/api/datasets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["datasets"]) == 3
        ids = [d["id"] for d in data["datasets"]]
        assert "online_shopping" in ids
        assert "ecom" in ids
        assert "steam" in ids

    def test_load_dataset_already_loaded(self, client):
        resp = client.post("/api/load-dataset", json={"dataset": "online_shopping"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "already_loaded"
        assert data["dataset"] == "online_shopping"

    def test_load_dataset_new(self, client, monkeypatch):
        monkeypatch.setattr("tests.fake_services._dataset", "ecom")
        monkeypatch.setattr("tests.fake_services.fake_current_dataset", lambda: "ecom")
        monkeypatch.setattr("tests.fake_services.fake_is_ready", lambda: True)
        # Now requesting ecom should return "already_loaded"
        resp = client.post("/api/load-dataset", json={"dataset": "ecom"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_loaded"

    def test_load_dataset_triggers_async(self, client, monkeypatch):
        monkeypatch.setattr("tests.fake_services.fake_current_dataset", lambda: "online_shopping")
        called = []
        # routes.py does `from services import load_dataset_async`, so patch routes
        monkeypatch.setattr("routes.load_dataset_async", lambda ds: called.append(ds))
        resp = client.post("/api/load-dataset", json={"dataset": "steam"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "loading"
        assert resp.json()["dataset"] == "steam"
        assert "steam" in called


# ─── Graph / Schema ─────────────────────────────────────────────────

class TestGraph:
    def test_graph_info(self, client, monkeypatch):
        """Test /api/graph with a mocked graph that has tables."""
        from kumoai.experimental.rfm import LocalGraph
        df_dict = {
            "users": pd.DataFrame({"user_id": [1, 2], "age": [25, 30]}),
            "items": pd.DataFrame({"item_id": [10, 20], "price": [9.99, 19.99]}),
        }
        graph = LocalGraph.from_data(df_dict, verbose=False, edges=[])
        raw = {
            "users": pd.DataFrame({"user_id": [1, 2], "age": [25, 30]}),
            "items": pd.DataFrame({"item_id": [10, 20], "price": [9.99, 19.99]}),
        }
        monkeypatch.setattr("tests.fake_services._graph", graph)
        monkeypatch.setattr("tests.fake_services._raw_data", raw)
        monkeypatch.setattr("tests.fake_services.fake_get_raw_data", lambda gid="default": raw)

        resp = client.get("/api/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["graph_id"] == "default"
        assert "users" in data["tables"]
        assert "items" in data["tables"]
        assert data["tables"]["users"]["rows"] == 2
        assert "user_id" in data["tables"]["users"]["columns"]


# ─── Data Preview ───────────────────────────────────────────────────

class TestPreview:
    def test_preview_with_data(self, client, monkeypatch):
        """Test /api/preview with mocked graph and raw data."""
        from kumoai.experimental.rfm import LocalGraph
        df_dict = {
            "users": pd.DataFrame({"user_id": [1, 2], "age": [25, 30]}),
        }
        graph = LocalGraph.from_data(df_dict, verbose=False, edges=[])
        monkeypatch.setattr("tests.fake_services._graph", graph)
        monkeypatch.setattr("tests.fake_services._raw_data", df_dict)
        monkeypatch.setattr("tests.fake_services.fake_get_raw_data", lambda gid="default": df_dict)

        resp = client.get("/api/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data["tables"]
        assert len(data["tables"]["users"]["rows"]) == 2
        assert data["tables"]["users"]["columns"] == ["user_id", "age"]
        assert data["tables"]["users"]["total_rows"] == 2

    def test_preview_empty(self, client, monkeypatch):
        """Test /api/preview when no data is loaded."""
        from kumoai.experimental.rfm import LocalGraph
        df = pd.DataFrame({"a": [1]})
        graph = LocalGraph.from_data({"t": df}, verbose=False, edges=[])
        monkeypatch.setattr("tests.fake_services._graph", graph)
        monkeypatch.setattr("tests.fake_services._raw_data", {})
        monkeypatch.setattr("tests.fake_services.fake_get_raw_data", lambda gid="default": {})

        resp = client.get("/api/preview")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tables"]) == 0


# ─── Prediction ────────────────────────────────────────────────────

class TestPredict:
    def test_predict_simple(self, client):
        """Test basic predict without explain."""
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_result = MagicMock()
        mock_result.prediction = pd.DataFrame({"ENTITY": [42], "TARGET_PRED": [275.5]})
        mock_model.predict.return_value = mock_result

        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["result"]["prediction"][0]["TARGET_PRED"] == 275.5

    def test_predict_with_explain(self, client):
        """Test predict with explain=True."""
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)

        mock_prediction = pd.DataFrame({"ENTITY": [42], "TARGET_PRED": [275.5]})

        class MockDetails:
            cohorts = []

        class MockResult:
            summary = "Natural language explanation"
            prediction = mock_prediction
            details = MockDetails()

        mock_model.predict.return_value = MockResult()

        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id=42",
            "explain": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["result"]["summary"] == "Natural language explanation"
        assert data["result"]["prediction"][0]["TARGET_PRED"] == 275.5
        assert data["result"]["cohorts"] == []

    def test_predict_with_entity_ids(self, client):
        """Test predict with explicit entity_ids."""
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_result = MagicMock()
        mock_result.prediction = pd.DataFrame({"ENTITY": [1, 2, 3], "TARGET_PRED": [0.1, 0.2, 0.3]})
        mock_model.predict.return_value = mock_result

        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT x FOR y",
            "entity_ids": [1, 2, 3],
        })
        assert resp.status_code == 200
        assert len(resp.json()["result"]["prediction"]) == 3

    def test_predict_model_not_ready(self, client, monkeypatch):
        """Test predict when model is not loaded (is_ready returns False)."""
        monkeypatch.setattr("routes.is_ready", lambda: False)
        resp = client.post("/api/predict", json={"query": "PREDICT x FOR y"})
        assert resp.status_code == 503
        assert "not ready" in resp.json()["detail"]

    def test_predict_with_anchor_time(self, client):
        """Test predict with anchor_time."""
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_result = MagicMock()
        mock_result.prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [100.0]})
        mock_model.predict.return_value = mock_result

        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT x FOR y",
            "anchor_time": "2024-06-01",
        })
        assert resp.status_code == 200

    def test_predict_raw_dataframe(self, client):
        """Test predict returning a raw DataFrame (no .prediction attr)."""
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_model.predict.return_value = pd.DataFrame({"A": [1, 2], "B": [3, 4]})

        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={"query": "PREDICT x FOR y"})
        assert resp.status_code == 200
        assert len(resp.json()["result"]["prediction"]) == 2


# ─── PQL Templates ─────────────────────────────────────────────────

# ─── Cache Stats ─────────────────────────────────────────────────────

class TestCacheStats:
    def test_cache_stats_endpoint(self, client, monkeypatch):
        mock_stats = {
            "hits": 5,
            "misses": 3,
            "size": 2,
            "disk_size": 1048576,
            "warmed_keys": ["graph:ecom", "templates"],
        }
        monkeypatch.setattr("routes.cache_stats", lambda: mock_stats)
        resp = client.get("/api/cache-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["hits"] == 5
        assert data["stats"]["misses"] == 3
        assert data["stats"]["size"] == 2
        assert data["stats"]["disk_size"] == 1048576
        assert "warmed_keys" in data["stats"]
        assert "ttl" in data

    def test_cache_stats_defaults(self, client, monkeypatch):
        mock_stats = {"hits": 0, "misses": 0, "size": 0, "disk_size": 0, "warmed_keys": []}
        monkeypatch.setattr("routes.cache_stats", lambda: mock_stats)
        resp = client.get("/api/cache-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["hits"] == 0
        assert data["stats"]["misses"] == 0
        assert len(data["ttl"]) == 3


# ─── PQL Templates ─────────────────────────────────────────────────

class TestTemplates:
    def test_templates_returned(self, client):
        resp = client.get("/api/pql-templates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["templates"]) == 7
        assert data["templates"][0]["name"] == "Demand Forecast (30-day)"

    def test_templates_have_required_fields(self, client):
        resp = client.get("/api/pql-templates")
        templates = resp.json()["templates"]
        for t in templates:
            assert "name" in t
            assert "description" in t
            assert "query" in t
            assert t["query"].startswith("PREDICT")
