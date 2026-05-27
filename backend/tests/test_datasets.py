import pytest


def test_downcast_enabled(monkeypatch):
    monkeypatch.setattr("datasets.settings.dataframe_downcast", True)
    from datasets import _downcast
    import pandas as pd
    df = pd.DataFrame({"a": [1, 2, 3], "b": [1000000, 2000000, 3000000]})
    df["a"] = df["a"].astype("int64")
    result = _downcast(df)
    assert result["a"].dtype.itemsize <= 4


def test_downcast_float_conversion(monkeypatch):
    monkeypatch.setattr("datasets.settings.dataframe_downcast", True)
    from datasets import _downcast
    import pandas as pd
    df = pd.DataFrame({"a": [1.5, 2.5, 3.5]})
    df["a"] = df["a"].astype("float64")
    result = _downcast(df)
    assert result["a"].dtype.itemsize <= 4


def test_downcast_disabled(monkeypatch):
    monkeypatch.setattr("datasets.settings.dataframe_downcast", False)
    from datasets import _downcast
    import pandas as pd
    df = pd.DataFrame({"a": [1, 2, 3]})
    df["a"] = df["a"].astype("int64")
    result = _downcast(df)
    assert result["a"].dtype.name == "int64"


def test_optimize_memory_calls_downcast(monkeypatch):
    monkeypatch.setattr("datasets.settings.dataframe_downcast", True)
    from datasets import _optimize_memory
    import pandas as pd
    df = pd.DataFrame({"a": range(100), "b": [1.0] * 100})
    df["a"] = df["a"].astype("int64")
    df["b"] = df["b"].astype("float64")
    result = _optimize_memory({"t": df})
    assert result["t"]["a"].dtype.itemsize <= 4
    assert result["t"]["b"].dtype.itemsize <= 4


def test_optimize_memory_reduces_size(monkeypatch):
    monkeypatch.setattr("datasets.settings.dataframe_downcast", True)
    from datasets import _optimize_memory
    import pandas as pd
    import numpy as np
    df = pd.DataFrame({"a": np.arange(1000, dtype="int64"), "b": np.arange(1000, dtype="float64")})
    before = df.memory_usage(deep=True).sum()
    result = _optimize_memory({"t": df})
    after = result["t"].memory_usage(deep=True).sum()
    assert after < before


def test_optimize_memory_includes_gc_call(monkeypatch):
    calls = []
    monkeypatch.setattr("datasets._gc.collect", lambda: calls.append(1))
    monkeypatch.setattr("datasets.settings.dataframe_downcast", False)
    from datasets import _optimize_memory
    import pandas as pd
    df = pd.DataFrame({"a": [1]})
    _optimize_memory({"t": df})
    assert len(calls) == 1


def test_load_parquet(tmp_path, monkeypatch):
    import pandas as pd
    root = tmp_path / "parquet_data"
    root.mkdir()
    pd.DataFrame({"x": [1, 2]}).to_parquet(root / "t1.parquet")
    from datasets import _load_parquet
    result = _load_parquet(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 2


def test_load_csv(tmp_path):
    import pandas as pd
    root = tmp_path / "csv_data"
    root.mkdir()
    pd.DataFrame({"x": [1, 2]}).to_csv(root / "t1.csv", index=False)
    from datasets import _load_csv
    result = _load_csv(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 2


def test_load_json(tmp_path):
    import pandas as pd
    root = tmp_path / "json_data"
    root.mkdir()
    pd.DataFrame({"a": [1, 2]}).to_json(root / "t1.json", orient="records")
    from datasets import _load_json
    result = _load_json(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 2


def test_load_jsonl(tmp_path):
    root = tmp_path / "jsonl_data"
    root.mkdir()
    (root / "t1.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
    from datasets import _load_jsonl
    result = _load_jsonl(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 2


def test_load_excel(tmp_path):
    pytest.importorskip("openpyxl")
    import pandas as pd
    root = tmp_path / "xlsx_data"
    root.mkdir()
    pd.DataFrame({"x": [1, 2]}).to_excel(root / "t1.xlsx", index=False)
    from datasets import _load_excel
    result = _load_excel(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 2


def test_load_feather(tmp_path):
    import pandas as pd
    root = tmp_path / "feather_data"
    root.mkdir()
    pd.DataFrame({"x": [1, 2, 3]}).to_feather(root / "t1.feather")
    from datasets import _load_feather
    result = _load_feather(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 3


def test_load_pickle(tmp_path):
    import pandas as pd
    root = tmp_path / "pkl_data"
    root.mkdir()
    pd.DataFrame({"x": [1, 2, 3, 4]}).to_pickle(root / "t1.pkl")
    from datasets import _load_pickle
    result = _load_pickle(str(root), ["t1"])
    assert "t1" in result
    assert len(result["t1"]) == 4


def test_load_dataset_data_unknown():
    from datasets import load_dataset_data
    from exceptions import DatasetNotFound
    with pytest.raises(DatasetNotFound):
        load_dataset_data("nonexistent_dataset")
