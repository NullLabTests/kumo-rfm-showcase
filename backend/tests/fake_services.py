"""Fake implementations of services.py functions for route testing.
Each function is named as `fake_<original_name>` and monkeypatched into
the services module by conftest.py."""

from unittest.mock import MagicMock


# Shared state for fake services
_ready = True
_dataset = "online_shopping"
_error = ""
_api_key_set = True
_model = MagicMock()
_graph = MagicMock()
_raw_data = {}


def fake_get_load_status():
    return {
        "ready": _ready,
        "dataset": _dataset,
        "error": _error,
        "api_key_configured": _api_key_set,
    }


def fake_get_model(gid="default"):
    return _model


def fake_get_graph(gid="default"):
    return _graph


def fake_get_raw_data(gid="default"):
    return _raw_data


def fake_is_ready():
    return _ready


def fake_current_dataset():
    return _dataset


def fake_load_dataset_async(dataset):
    pass


def fake_load_dataset(dataset):
    return {
        "status": "loaded",
        "dataset": dataset,
        "graph_id": "default",
        "tables": {
            "users": {"rows": 1000, "columns": ["user_id", "age"], "primary_key": "user_id", "time_column": None},
            "items": {"rows": 500, "columns": ["item_id", "price"], "primary_key": "item_id", "time_column": None},
        },
        "graph_metadata": {
            "table_count": 2,
            "tables": ["users", "items"],
            "links": [{"src_table": "orders", "fkey": "user_id", "dst_table": "users"}],
        },
    }


def fake_cache_stats():
    return {
        "hits": 5,
        "misses": 3,
        "size": 2,
        "disk_size": 1048576,
        "warmed_keys": ["graph:ecom", "templates"],
    }
