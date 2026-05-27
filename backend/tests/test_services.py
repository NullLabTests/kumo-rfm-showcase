"""Unit tests for services.py and datasets.py helpers.

Tests helpers with real LocalGraph instances from tiny DataFrames to
avoid external API calls.
"""

import os
from unittest.mock import MagicMock, PropertyMock, patch

os.environ["KUMO_LOG_LEVEL"] = "ERROR"
os.environ["KUMO_API_KEY"] = "test-key-123"

import pandas as pd

import importlib
import config
importlib.reload(config)

from services import (
    get_load_status,
    get_model,
    get_graph,
    get_raw_data,
    is_ready,
    current_dataset,
    load_dataset,
    run_prediction,
    _load_status,
    model_store,
    graph_store,
    raw_data_store,
)
from exceptions import ModelNotReady


def _clean_stores():
    model_store.clear()
    graph_store.clear()
    raw_data_store.clear()
    _load_status.update(ready=False, dataset="", error="", api_key_configured=True)


# ─── Store accessors ────────────────────────────────────────────────
class TestStoreAccessors:
    def setup_method(self):
        _clean_stores()

    def test_get_load_status_defaults(self):
        s = get_load_status()
        assert s["ready"] is False
        assert s["dataset"] == ""
        assert s["error"] == ""

    def test_get_model_not_ready(self):
        import pytest
        with pytest.raises(ModelNotReady):
            get_model()

    def test_get_graph_not_ready(self):
        import pytest
        with pytest.raises(ModelNotReady):
            get_graph()

    def test_get_raw_data_empty(self):
        assert get_raw_data() == {}

    def test_is_ready_defaults(self):
        assert is_ready() is False

    def test_current_dataset_defaults(self):
        assert current_dataset() == ""

    def test_store_and_retrieve(self):
        model_store["default"] = "fake-model"
        graph_store["default"] = "fake-graph"
        raw_data_store["default"] = {"t": "fake-df"}
        assert get_model() == "fake-model"
        assert get_graph() == "fake-graph"
        assert get_raw_data() == {"t": "fake-df"}


# ─── load_dataset ────────────────────────────────────────────────────
class TestLoadDataset:
    def setup_method(self):
        _clean_stores()

    def test_unknown_dataset_raises(self):
        import pytest
        from exceptions import DatasetNotFound
        with pytest.raises(DatasetNotFound):
            load_dataset("nonexistent")


# ─── run_prediction ──────────────────────────────────────────────────
class TestRunPrediction:
    def setup_method(self):
        _clean_stores()
        # Set up a mock model in the store
        self.mock_model = MagicMock()
        model_store["default"] = self.mock_model
        _load_status.update(ready=True, dataset="test")

    def _make_result(self, pred_df=None):
        result = MagicMock()
        if pred_df is not None:
            result.prediction = pred_df
        else:
            result.prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [100.0]})
        return result

    def test_rejects_when_not_ready(self):
        _clean_stores()
        import pytest
        with pytest.raises(ModelNotReady):
            run_prediction("SELECT 1")

    def test_simple_prediction(self):
        result = self._make_result()
        self.mock_model.predict.return_value = result

        resp = run_prediction("PREDICT x FOR y")
        assert "prediction" in resp
        assert resp["prediction"][0]["ENTITY"] == 1
        assert resp["prediction"][0]["TARGET_PRED"] == 100.0
        self.mock_model.predict.assert_called_once()

    def test_prediction_with_explain(self):
        mock_result = MagicMock()
        mock_result.summary = "This is an explanation"
        mock_result.prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [0.5]})
        mock_result.details = MagicMock()
        mock_result.details.cohorts = []
        self.mock_model.predict.return_value = mock_result

        resp = run_prediction("PREDICT x FOR y", explain=True)
        assert resp["summary"] == "This is an explanation"
        assert resp["prediction"][0]["TARGET_PRED"] == 0.5
        assert resp["cohorts"] == []

    def test_prediction_with_explain_cohorts(self):
        mock_cohort = MagicMock()
        mock_cohort.table_name = "orders"
        mock_cohort.column_name = "price"
        mock_cohort.hop = 1
        mock_cohort.cohorts = [1.0, 2.0]
        mock_cohort.populations = [10, 20]
        mock_cohort.targets = [0.1, 0.2]

        mock_result = MagicMock()
        mock_result.summary = "Cohort explanation"
        mock_result.prediction = pd.DataFrame({"ENTITY": [1], "TARGET_PRED": [0.5]})
        mock_result.details = MagicMock()
        mock_result.details.cohorts = [mock_cohort]
        self.mock_model.predict.return_value = mock_result

        resp = run_prediction("PREDICT x FOR y", explain=True)
        assert len(resp["cohorts"]) == 1
        assert resp["cohorts"][0]["table_name"] == "orders"
        assert resp["cohorts"][0]["hop"] == 1

    def test_prediction_with_anchor_time(self):
        result = self._make_result()
        self.mock_model.predict.return_value = result

        run_prediction("PREDICT x FOR y", anchor_time="2024-06-01")
        call_kwargs = self.mock_model.predict.call_args[1]
        assert "anchor_time" in call_kwargs
        assert str(call_kwargs["anchor_time"])[:10] == "2024-06-01"

    def test_prediction_with_entity_ids(self):
        result = self._make_result(pd.DataFrame({"ENTITY": [1, 2], "TARGET_PRED": [0.5, 0.8]}))
        self.mock_model.predict.return_value = result

        run_prediction("PREDICT x FOR y", entity_ids=[1, 2])
        call_kwargs = self.mock_model.predict.call_args[1]
        assert call_kwargs.get("indices") == [1, 2]

    def test_prediction_run_mode(self):
        result = self._make_result()
        self.mock_model.predict.return_value = result

        run_prediction("PREDICT x FOR y", run_mode="best")
        call_kwargs = self.mock_model.predict.call_args[1]
        assert call_kwargs.get("run_mode") == "best"

    def test_prediction_serializes_raw_dataframe(self):
        raw_df = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
        self.mock_model.predict.return_value = raw_df

        resp = run_prediction("PREDICT x FOR y")
        assert resp["prediction"] == [{"A": 1, "B": 3}, {"A": 2, "B": 4}]

    def test_prediction_syntax_error(self):
        self.mock_model.predict.side_effect = ValueError("Failed to parse query")

        import pytest
        from exceptions import PredictionError
        with pytest.raises(PredictionError, match="Invalid PQL syntax"):
            run_prediction("BAD QUERY")

    def test_prediction_table_error(self):
        self.mock_model.predict.side_effect = ValueError("Table 'returns' does not exist")

        import pytest
        from exceptions import PredictionError
        with pytest.raises(PredictionError, match="Invalid table or column"):
            run_prediction("PREDICT COUNT(returns.*) FOR x")

    def test_prediction_live_display_error(self):
        self.mock_model.predict.side_effect = RuntimeError("Only one live display may be active at once")

        import pytest
        from exceptions import TooManyRequests
        with pytest.raises(TooManyRequests):
            run_prediction("PREDICT x FOR y")

    def test_prediction_generic_error(self):
        self.mock_model.predict.side_effect = RuntimeError("Something went wrong")

        import pytest
        from exceptions import PredictionError
        with pytest.raises(PredictionError, match="Prediction failed"):
            run_prediction("PREDICT x FOR y")
