import pytest
from models import PredictRequest, LoadDataRequest


class TestPredictRequest:
    def test_defaults(self):
        r = PredictRequest(query="PREDICT x FOR y")
        assert r.query == "PREDICT x FOR y"
        assert r.graph_id == "default"
        assert r.entity_ids is None
        assert r.anchor_time is None
        assert r.run_mode == "fast"
        assert r.explain is False

    def test_all_fields(self):
        r = PredictRequest(
            query="PREDICT x FOR y",
            graph_id="my_graph",
            entity_ids=[1, 2, 3],
            anchor_time="2024-01-01",
            run_mode="best",
            explain=True,
        )
        assert r.query == "PREDICT x FOR y"
        assert r.graph_id == "my_graph"
        assert r.entity_ids == [1, 2, 3]
        assert r.anchor_time == "2024-01-01"
        assert r.run_mode == "best"
        assert r.explain is True

    def test_query_required(self):
        import pydantic
        try:
            PredictRequest()
            assert False, "Should have raised"
        except pydantic.ValidationError as e:
            assert "query" in str(e)

    def test_entity_ids_strings(self):
        r = PredictRequest(query="PREDICT x FOR y", entity_ids=["a", "b"])
        assert r.entity_ids == ["a", "b"]

    def test_graph_id_custom(self):
        r = PredictRequest(query="PREDICT x FOR y", graph_id="custom")
        assert r.graph_id == "custom"


class TestPredictValidation:
    def test_query_too_short(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            PredictRequest(query="PREDICT")

    def test_query_too_long(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            PredictRequest(query="PREDICT " + "x" * 2000)

    def test_query_must_start_with_predict_lowercase(self):
        import pydantic
        try:
            PredictRequest(query="select x FOR y")
            assert False
        except pydantic.ValidationError as e:
            assert "PREDICT" in str(e)

    def test_query_starts_with_predict_case_insensitive(self):
        r = PredictRequest(query="predict x FOR y")
        assert r.query == "predict x FOR y"

    def test_query_starts_with_predict_whitespace(self):
        r = PredictRequest(query="  PREDICT x FOR y  ")
        assert r.query == "PREDICT x FOR y"

    def test_invalid_run_mode(self):
        import pydantic
        try:
            PredictRequest(query="PREDICT x FOR y", run_mode="turbo")
            assert False
        except pydantic.ValidationError as e:
            assert "run_mode" in str(e)

    def test_entity_ids_max_1000(self):
        r = PredictRequest(query="PREDICT x FOR y", entity_ids=list(range(1000)))
        assert len(r.entity_ids) == 1000

    def test_entity_ids_exceeds_1000(self):
        import pydantic
        try:
            PredictRequest(query="PREDICT x FOR y", entity_ids=list(range(1001)))
            assert False
        except pydantic.ValidationError as e:
            assert "1000" in str(e)

    def test_anchor_time_iso_format(self):
        import pydantic
        try:
            PredictRequest(query="PREDICT x FOR y", anchor_time="not-a-date")
            assert False
        except pydantic.ValidationError as e:
            assert "anchor_time" in str(e)

    def test_anchor_time_valid(self):
        r = PredictRequest(query="PREDICT x FOR y", anchor_time="2024-06-01")
        assert r.anchor_time == "2024-06-01"

    def test_anchor_time_datetime_with_timezone(self):
        r = PredictRequest(query="PREDICT x FOR y", anchor_time="2024-06-01T12:00:00Z")
        assert r.anchor_time == "2024-06-01T12:00:00Z"

    def test_entity_ids_empty_list_allowed(self):
        r = PredictRequest(query="PREDICT x FOR y", entity_ids=[])
        assert r.entity_ids == []

    def test_explain_default_false(self):
        r = PredictRequest(query="PREDICT x FOR y")
        assert r.explain is False

    def test_explain_true(self):
        r = PredictRequest(query="PREDICT x FOR y", explain=True)
        assert r.explain is True

    def test_all_run_modes_accepted(self):
        for mode in ("fast", "normal", "best"):
            r = PredictRequest(query="PREDICT x FOR y", run_mode=mode)
            assert r.run_mode == mode


class TestLoadDataRequest:
    def test_defaults(self):
        r = LoadDataRequest(dataset="online_shopping")
        assert r.dataset == "online_shopping"
        assert r.graph_id == "default"

    def test_dataset_required(self):
        import pydantic
        try:
            LoadDataRequest()
            assert False, "Should have raised"
        except pydantic.ValidationError as e:
            assert "dataset" in str(e)

    def test_custom_graph_id(self):
        r = LoadDataRequest(dataset="steam", graph_id="g2")
        assert r.dataset == "steam"
        assert r.graph_id == "g2"
