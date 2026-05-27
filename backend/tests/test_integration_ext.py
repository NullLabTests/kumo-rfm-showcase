"""Extended integration tests covering cache interaction, explain mode, error scenarios."""

import os

os.environ["KUMO_LOG_LEVEL"] = "ERROR"
os.environ["KUMO_API_KEY"] = "test-key-123"

import importlib
import config
importlib.reload(config)

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def patch_services(monkeypatch):
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


class TestIntegratedPrediction:
    def test_predict_with_all_params(self, client):
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_result = MagicMock()
        mock_result.prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [0.95]})
        mock_model.predict.return_value = mock_result
        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT x FOR y",
            "graph_id": "default",
            "entity_ids": [1],
            "anchor_time": "2024-06-01",
            "run_mode": "best",
            "explain": False,
        })
        assert resp.status_code == 200
        assert resp.json()["result"]["prediction"][0]["TARGET_PRED"] == 0.95

    def test_same_prediction_cached(self, client):
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_result = MagicMock()
        mock_result.prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [100.0]})
        mock_model.predict.return_value = mock_result
        import tests.fake_services as fake
        fake._model = mock_model

        resp1 = client.post("/api/predict", json={"query": "PREDICT x FOR y"})
        assert resp1.status_code == 200

        # Second identical request hits cache, model.predict still called once by routes
        resp2 = client.post("/api/predict", json={"query": "PREDICT x FOR y"})
        assert resp2.status_code == 200
        assert resp2.json()["result"]["prediction"][0]["TARGET_PRED"] == 100.0

    def test_predict_with_graph_id(self, client):
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        mock_model.predict.return_value = MagicMock(prediction=pd.DataFrame({"E": [1], "P": [0.5]}))
        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT x FOR y",
            "graph_id": "default",
        })
        assert resp.status_code == 200


class TestExplainMode:
    def test_explain_with_summary(self, client):
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)

        class MockDetails:
            cohorts = []

        class MockResult:
            summary = "User is predicted to churn because..."
            prediction = pd.DataFrame({"ENTITY": [42], "TARGET_PRED": [0.8]})
            details = MockDetails()

        mock_model.predict.return_value = MockResult()
        import tests.fake_services as fake
        fake._model = mock_model

        resp = client.post("/api/predict", json={
            "query": "PREDICT COUNT(orders.*, 0, 90, days)=0 FOR users.user_id=42",
            "explain": True,
        })
        assert resp.status_code == 200
        data = resp.json()["result"]
        assert data["summary"] == "User is predicted to churn because..."
        assert len(data["prediction"]) == 1

    def test_explain_with_cohorts(self, client):
        from kumoai.experimental.rfm import KumoRFM
        mock_model = MagicMock(spec=KumoRFM)
        import tests.fake_services as fake
        fake._model = mock_model

        mock_cohort = MagicMock()
        mock_cohort.table_name = "orders"
        mock_cohort.column_name = "price"
        mock_cohort.hop = 1
        mock_cohort.cohorts = [10.0, 20.0]
        mock_cohort.populations = [50, 100]
        mock_cohort.targets = [0.1, 0.2]

        class MockDetails:
            cohorts = [mock_cohort]

        class MockResult:
            summary = "Explanation with cohorts"
            prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [0.5]})
            details = MockDetails()

        mock_model.predict.return_value = MockResult()
        resp = client.post("/api/predict", json={
            "query": "PREDICT SUM(orders.price, 0, 30, days) FOR items.item_id=42",
            "explain": True,
        })
        assert resp.status_code == 200
        data = resp.json()["result"]
        assert len(data["cohorts"]) == 1
        assert data["cohorts"][0]["table_name"] == "orders"
        assert data["cohorts"][0]["hop"] == 1
        assert data["cohorts"][0]["cohorts"] == [10.0, 20.0]


class TestErrorResponses:
    def test_predict_invalid_query_too_short(self, client):
        resp = client.post("/api/predict", json={"query": "SHORT"})
        assert resp.status_code == 422

    def test_predict_invalid_run_mode(self, client):
        resp = client.post("/api/predict", json={
            "query": "PREDICT x FOR y",
            "run_mode": "invalid",
        })
        assert resp.status_code == 422

    def test_predict_invalid_anchor_time(self, client):
        resp = client.post("/api/predict", json={
            "query": "PREDICT x FOR y",
            "anchor_time": "not-a-date",
        })
        assert resp.status_code == 422

    def test_load_dataset_missing_field(self, client):
        resp = client.post("/api/load-dataset", json={})
        assert resp.status_code == 422

    def test_load_dataset_empty_string(self, client):
        resp = client.post("/api/load-dataset", json={"dataset": ""})
        assert resp.status_code == 422


class TestHealthAndStatus:
    def test_health_returns_status(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        assert data["status"] == "ok"

    def test_status_after_auto_load(self, client):
        resp = client.get("/api/status")
        data = resp.json()
        assert "api_key_configured" in data
        assert "loaded" in data
        assert "dataset" in data


class TestCacheEndpoints:
    def test_cache_stats_endpoint_success(self, client):
        resp = client.get("/api/cache-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "hits" in data["stats"]
        assert "misses" in data["stats"]
        assert "size" in data["stats"]

    def test_cache_stats_returns_numbers(self, client):
        resp = client.get("/api/cache-stats")
        data = resp.json()
        assert isinstance(data["stats"]["hits"], int)
        assert isinstance(data["stats"]["misses"], int)
        assert isinstance(data["stats"]["size"], int)
