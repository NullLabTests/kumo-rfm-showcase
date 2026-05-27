import pytest

from exceptions import (
    ConfigurationError,
    DatasetLoadError,
    DatasetNotFound,
    GraphNotReady,
    InvalidQuery,
    ModelNotReady,
    PredictionError,
    ServiceError,
    TooManyRequests,
)


class TestExceptionHierarchy:
    def test_service_error_is_base(self):
        assert issubclass(ModelNotReady, ServiceError)
        assert issubclass(DatasetNotFound, ServiceError)
        assert issubclass(PredictionError, ServiceError)
        assert issubclass(TooManyRequests, ServiceError)
        assert issubclass(GraphNotReady, ServiceError)

    def test_service_error_default_status(self):
        assert ServiceError().status_code == 400

    def test_model_not_ready_status(self):
        assert ModelNotReady().status_code == 503

    def test_dataset_not_found_status(self):
        assert DatasetNotFound().status_code == 404

    def test_prediction_error_status(self):
        assert PredictionError().status_code == 400

    def test_too_many_requests_status(self):
        assert TooManyRequests().status_code == 429

    def test_graph_not_ready_status(self):
        assert GraphNotReady().status_code == 503

    def test_exception_message(self):
        exc = ModelNotReady("loading dataset")
        assert str(exc) == "loading dataset"
        assert exc.detail == "loading dataset"

    def test_exception_with_detail(self):
        exc = PredictionError("query failed", detail="syntax error at line 1")
        assert str(exc) == "query failed"
        assert exc.detail == "syntax error at line 1"

    def test_is_exception(self):
        with pytest.raises(ServiceError):
            raise ModelNotReady("test")

    def test_caught_as_exception(self):
        with pytest.raises(Exception):
            raise DatasetNotFound("missing")


class TestNewExceptions:
    def test_configuration_error(self):
        exc = ConfigurationError("No KUMO_API_KEY set")
        assert exc.status_code == 500
        assert exc.error_code == "CONFIGURATION_ERROR"
        assert str(exc) == "No KUMO_API_KEY set"

    def test_dataset_load_error(self):
        exc = DatasetLoadError("S3 connection failed")
        assert exc.status_code == 500
        assert exc.error_code == "DATASET_LOAD_ERROR"
        assert exc.detail == "S3 connection failed"

    def test_invalid_query(self):
        exc = InvalidQuery("Query too short")
        assert exc.status_code == 400
        assert exc.error_code == "INVALID_QUERY"
        assert str(exc) == "Query too short"

    def test_configuration_error_is_service_error(self):
        assert issubclass(ConfigurationError, ServiceError)

    def test_dataset_load_error_is_service_error(self):
        assert issubclass(DatasetLoadError, ServiceError)

    def test_invalid_query_is_service_error(self):
        assert issubclass(InvalidQuery, ServiceError)

    def test_all_exceptions_have_error_code(self):
        for exc_cls in [
            ServiceError, ModelNotReady, DatasetNotFound, DatasetLoadError,
            PredictionError, InvalidQuery, TooManyRequests, GraphNotReady,
            ConfigurationError,
        ]:
            assert hasattr(exc_cls, "error_code")
            assert exc_cls.error_code

    def test_all_exceptions_have_status_code(self):
        for exc_cls in [
            ServiceError, ModelNotReady, DatasetNotFound, DatasetLoadError,
            PredictionError, InvalidQuery, TooManyRequests, GraphNotReady,
            ConfigurationError,
        ]:
            assert hasattr(exc_cls, "status_code")
            assert exc_cls.status_code

    def test_service_error_no_detail_fallback(self):
        exc = PredictionError("Something bad")
        assert exc.detail == "Something bad"

    def test_graph_not_ready_error_code(self):
        assert GraphNotReady.error_code == "GRAPH_NOT_READY"

    def test_prediction_error_code(self):
        assert PredictionError.error_code == "PREDICTION_ERROR"
