"""Extended service tests for new features: serialization, auto_load, short_query, caching."""

import os

os.environ["KUMO_LOG_LEVEL"] = "ERROR"
os.environ["KUMO_API_KEY"] = "test-key-123"

import importlib
import config
importlib.reload(config)

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from services import (
    _auto_load,
    _serialize_prediction,
    _short_query,
    _warm_caches,
    load_dataset,
    run_prediction,
    _load_status,
    model_store,
    graph_store,
    raw_data_store,
)


def _clean_stores():
    model_store.clear()
    graph_store.clear()
    raw_data_store.clear()
    _load_status.update(ready=False, dataset="", error="", api_key_configured=True)


class TestShortQuery:
    def test_short_query_under_80(self):
        assert _short_query("PREDICT x FOR y") == "PREDICT x FOR y"

    def test_short_query_over_80(self):
        long_q = "PREDICT " + "x" * 100 + " FOR y"
        result = _short_query(long_q)
        assert len(result) == 83
        assert result.endswith("...")

    def test_short_query_empty(self):
        assert _short_query("") == ""

    def test_short_query_exactly_80(self):
        q = "P" * 80
        assert _short_query(q) == q


class TestSerializePrediction:
    def test_dataframe(self):
        df = pd.DataFrame({"a": [1, 2]})
        assert _serialize_prediction(df) == [{"a": 1}, {"a": 2}]

    def test_result_with_prediction_attr(self):
        mock = MagicMock()
        mock.prediction = pd.DataFrame({"x": [42]})
        assert _serialize_prediction(mock) == [{"x": 42}]

    def test_unexpected_type(self):
        assert _serialize_prediction("just a string") == "just a string"

    def test_none(self):
        assert _serialize_prediction(None) == "None"


class TestAutoLoad:
    def test_auto_load_no_api_key(self, monkeypatch):
        monkeypatch.setattr("services.settings.kumo_api_key", "")
        _auto_load()
        assert _load_status["error"] != ""
        assert "KUMO_API_KEY" in _load_status["error"].upper() or ".env" in _load_status["error"]

    def test_auto_load_key_configured(self):
        _clean_stores()
        # Simulate settings having a key
        with patch("services.settings.kumo_api_key", "real-key"):
            with patch("services._init_api") as mock_init:
                with patch("services.load_dataset") as mock_load:
                    mock_load.return_value = {"status": "loaded"}
                    _auto_load()
        assert _load_status["ready"] is True
        assert _load_status["dataset"] == "online_shopping"

    def test_auto_load_failure_clears_status(self, monkeypatch):
        monkeypatch.setattr("services.settings.kumo_api_key", "real-key")
        with patch("services._init_api", side_effect=Exception("API init failed")):
            _auto_load()
        assert _load_status["ready"] is False
        assert "init failed" in _load_status["error"].lower()


class TestCacheWarming:
    def test_warm_caches_called_on_load(self, monkeypatch):
        _clean_stores()
        monkeypatch.setattr("services.settings.kumo_api_key", "real-key")
        monkeypatch.setattr("services.settings.auto_load_dataset", "test_ds")
        from services import _warm_caches
        calls = []
        monkeypatch.setattr("services.cache_set", lambda key, val, ttl: calls.append((key, ttl)))
        monkeypatch.setattr("services.cache_cleanup", lambda: 0)
        _warm_caches("test_ds", MagicMock(), {})

        assert any("graph:test_ds" in c[0] for c in calls)
        # templates should also be cached
        assert any("templates" in c[0] for c in calls)

    def test_warm_caches_does_not_crash_on_error(self, monkeypatch):
        def bad_set(*args, **kwargs):
            raise RuntimeError("oops")
        monkeypatch.setattr("services.cache_set", bad_set)
        monkeypatch.setattr("services.cache_cleanup", lambda: 0)
        # Should not raise
        _warm_caches("test_ds", MagicMock(), {})
