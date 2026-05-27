"""Custom exception classes for structured error handling.

Each exception maps to a specific HTTP status code, an internal error code,
and a user-facing message. Used throughout the service layer and caught
in :func:`routes.handle_error` for consistent JSON error responses.

Usage::

    raise ModelNotReady("online_shopping")
    raise PredictionError("PQL query failed")
"""


class ServiceError(Exception):
    """Base exception for all service-layer errors."""

    status_code: int = 400
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "", detail: str = ""):
        super().__init__(message)
        self.detail = detail or message


class ModelNotReady(ServiceError):
    """Raised when the model/graph has not finished loading."""

    status_code = 503
    error_code = "MODEL_NOT_READY"


class DatasetNotFound(ServiceError):
    """Raised for unknown dataset identifiers."""

    status_code = 404
    error_code = "DATASET_NOT_FOUND"


class DatasetLoadError(ServiceError):
    """Raised when a dataset fails to load from S3 or disk."""

    status_code = 500
    error_code = "DATASET_LOAD_ERROR"


class PredictionError(ServiceError):
    """Raised when a PQL prediction fails (parse error, invalid table, etc.)."""

    status_code = 400
    error_code = "PREDICTION_ERROR"


class InvalidQuery(ServiceError):
    """Raised when the PQL query fails validation."""

    status_code = 400
    error_code = "INVALID_QUERY"


class TooManyRequests(ServiceError):
    """Raised when the KumoRFM live display limit is hit."""

    status_code = 429
    error_code = "TOO_MANY_REQUESTS"


class GraphNotReady(ServiceError):
    """Raised when graph data is requested before loading completes."""

    status_code = 503
    error_code = "GRAPH_NOT_READY"


class ConfigurationError(ServiceError):
    """Raised when the application is misconfigured (e.g. missing API key)."""

    status_code = 500
    error_code = "CONFIGURATION_ERROR"
