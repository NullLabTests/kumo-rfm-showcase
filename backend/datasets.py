"""Dataset definitions, loaders, and graph builders.

Each dataset is described by a :class:`DatasetDef` with its S3 root, table
names, file format, foreign-key links, and any special column handling.
This module owns all knowledge about dataset structure so that
:mod:`services` and :mod:`routes` stay dataset-agnostic.

Usage::

    from datasets import DATASETS, load_dataset_data, build_graph

    df_dict = load_dataset_data("steam")
    graph = build_graph("steam", df_dict)
"""

from __future__ import annotations

import gc as _gc
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

os_data = __import__("os")
os_data.environ["KUMO_LOG_LEVEL"] = "ERROR"
from kumoai.experimental.rfm import LocalGraph  # noqa: E402

from exceptions import DatasetNotFound
from logger import log
from settings import settings


# ─── Data classes ────────────────────────────────────────────────────


@dataclass
class LinkDef:
    """A foreign-key link between two tables.

    :param src: Source table name
    :param fkey: Foreign-key column in *src*
    :param dst: Destination table name
    """

    src: str
    fkey: str
    dst: str


@dataclass
class PKOverride:
    """Override the auto-detected primary key for a table.

    :param table: Table name
    :param pk: Primary-key column name
    """

    table: str
    pk: str


@dataclass
class TimeColumnOverride:
    """Override the auto-detected time column for a table.

    :param table: Table name
    :param col: Time-column name
    """

    table: str
    col: str


@dataclass
class DatasetDef:
    """Describes a dataset: where to find it, its structure, and how to load it.

    :param id_: Unique dataset identifier (e.g. ``"online_shopping"``)
    :param name: Human-readable name
    :param description: Short description
    :param root: S3 or filesystem root path
    :param tables: Ordered list of table names
    :param format: File format — ``"parquet"`` or ``"csv"``
    :param links: Foreign-key relationships to create in the graph
    :param pk_overrides: Tables whose primary key differs from auto-detection
    :param time_overrides: Tables whose time column needs explicit setting
    :param column_fixes: Optional callable to fix column types after loading
    """

    id_: str
    name: str
    description: str
    root: str
    tables: list[str]
    format: str = "parquet"
    links: list[LinkDef] = field(default_factory=list)
    pk_overrides: list[PKOverride] = field(default_factory=list)
    time_overrides: list[TimeColumnOverride] = field(default_factory=list)
    column_fixes: Callable[[dict[str, pd.DataFrame]], None] | None = None


# ─── Dataset definitions ────────────────────────────────────────────

S3_ROOT = "s3://kumo-sdk-public/rfm-datasets"


def _fix_steam_columns(df_dict: dict[str, pd.DataFrame]) -> None:
    """Cast Steam columns to correct dtypes."""
    games = df_dict.get("games")
    if games is not None:
        for col in ("win", "mac", "linux", "steam_deck"):
            if col in games.columns:
                games[col] = games[col].astype(bool)
    reviews = df_dict.get("reviews")
    if reviews is not None and "is_recommended" in reviews.columns:
        reviews["is_recommended"] = reviews["is_recommended"].astype(int)


DATASETS: dict[str, DatasetDef] = {
    "online_shopping": DatasetDef(
        id_="online_shopping",
        name="Online Shopping",
        description="Users, items, orders — e-commerce",
        root=f"{S3_ROOT}/online-shopping",
        tables=["users", "items", "orders"],
        format="parquet",
        links=[
            LinkDef("orders", "user_id", "users"),
            LinkDef("orders", "item_id", "items"),
        ],
    ),
    "ecom": DatasetDef(
        id_="ecom",
        name="E-Commerce w/ Returns",
        description="Users, items, orders, returns — fashion retail",
        root=f"{S3_ROOT}/ecom",
        tables=["users", "items", "orders", "returns"],
        format="parquet",
        links=[
            LinkDef("orders", "user_id", "users"),
            LinkDef("orders", "item_id", "items"),
            LinkDef("returns", "order_id", "orders"),
        ],
    ),
    "steam": DatasetDef(
        id_="steam",
        name="Steam Gaming",
        description="Users, games, reviews — gaming platform",
        root=f"{S3_ROOT}/steam_game_sample",
        tables=["users", "games", "reviews"],
        format="csv",
        links=[
            LinkDef("reviews", "user_id", "users"),
            LinkDef("reviews", "app_id", "games"),
        ],
        pk_overrides=[
            PKOverride("users", "user_id"),
            PKOverride("games", "app_id"),
            PKOverride("reviews", "review_id"),
        ],
        time_overrides=[
            TimeColumnOverride("reviews", "date"),
        ],
        column_fixes=_fix_steam_columns,
    ),
}


# ─── Memory optimization ────────────────────────────────────────────


def _downcast(df: pd.DataFrame) -> pd.DataFrame:
    if not settings.dataframe_downcast:
        return df
    for col in df.select_dtypes(include=[np.number]).columns:
        ctype = df[col].dtype
        if ctype == "float64":
            df[col] = pd.to_numeric(df[col], downcast="float")
        elif ctype == "int64":
            df[col] = pd.to_numeric(df[col], downcast="integer")
    return df


def _optimize_memory(df_dict: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    for name, df in df_dict.items():
        before = df.memory_usage(deep=True).sum()
        df_dict[name] = _downcast(df)
        after = df_dict[name].memory_usage(deep=True).sum()
        saved = before - after
        if saved > 0:
            log.debug("  Memory: %s %.1f MB → %.1f MB (saved %.1f MB)", name, before / 1e6, after / 1e6, saved / 1e6)
    _gc.collect()
    return df_dict


# ─── Loaders ────────────────────────────────────────────────────────


def _load_parquet(root: str, tables: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        path = f"{root}/{t}.parquet"
        log.info("  Loading parquet: %s", path)
        result[t] = pd.read_parquet(path)
    return result


def _load_csv(root: str, tables: list[str], name_map: dict[str, str] | None = None) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        filename = (name_map or {}).get(t, t)
        path = f"{root}/{filename}.csv"
        log.info("  Loading csv: %s", path)
        result[t] = pd.read_csv(path)
    return result


def _load_json(root: str, tables: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        path = f"{root}/{t}.json"
        log.info("  Loading json: %s", path)
        result[t] = pd.read_json(path)
    return result


def _load_jsonl(root: str, tables: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        path = f"{root}/{t}.jsonl"
        log.info("  Loading jsonl: %s", path)
        result[t] = pd.read_json(path, lines=True)
    return result


def _load_excel(root: str, tables: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        path = f"{root}/{t}.xlsx"
        log.info("  Loading excel: %s", path)
        result[t] = pd.read_excel(path)
    return result


def _load_feather(root: str, tables: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        path = f"{root}/{t}.feather"
        log.info("  Loading feather: %s", path)
        result[t] = pd.read_feather(path)
    return result


def _load_pickle(root: str, tables: list[str]) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for t in tables:
        path = f"{root}/{t}.pkl"
        log.info("  Loading pickle: %s", path)
        result[t] = pd.read_pickle(path)
    return result


_CSV_NAME_MAP: dict[str, dict[str, str]] = {
    "steam": {"reviews": "recommendations"},
}

_LOADERS: dict[str, Callable] = {
    "parquet": _load_parquet,
    "csv": _load_csv,
    "json": _load_json,
    "jsonl": _load_jsonl,
    "xlsx": _load_excel,
    "xls": _load_excel,
    "feather": _load_feather,
    "pickle": _load_pickle,
    "pkl": _load_pickle,
}


def load_dataset_data(dataset_id: str) -> dict[str, pd.DataFrame]:
    """Load raw DataFrames for *dataset_id* from S3.

    :raises DatasetNotFound: If *dataset_id* is unknown.
    """
    spec = DATASETS.get(dataset_id)
    if spec is None:
        raise DatasetNotFound(f"Unknown dataset: {dataset_id}")

    loader = _LOADERS.get(spec.format)
    if loader is None:
        raise DatasetNotFound(f"Unsupported format: {spec.format}")

    if spec.format == "csv":
        name_map = _CSV_NAME_MAP.get(dataset_id)
        df_dict = loader(spec.root, spec.tables, name_map=name_map)
    else:
        df_dict = loader(spec.root, spec.tables)

    if spec.column_fixes:
        spec.column_fixes(df_dict)

    return _optimize_memory(df_dict)


# ─── Graph builder ──────────────────────────────────────────────────


def build_graph(dataset_id: str, df_dict: dict[str, pd.DataFrame]) -> LocalGraph:
    """Build a :class:`LocalGraph` from *df_dict* using *dataset_id*'s spec.

    :param dataset_id: Dataset identifier
    :param df_dict: DataFrames keyed by table name
    """
    spec = DATASETS.get(dataset_id)
    if spec is None:
        raise DatasetNotFound(f"Unknown dataset: {dataset_id}")

    graph = LocalGraph.from_data(df_dict, verbose=False, edges=[])

    for override in spec.pk_overrides:
        graph[override.table].primary_key = override.pk

    for override in spec.time_overrides:
        try:
            graph[override.table].time_column = override.col
        except Exception as exc:
            log.warning("Could not set time_column for %s.%s: %s", override.table, override.col, exc)

    for link in spec.links:
        _safe_link(graph, link.src, link.fkey, link.dst)

    return graph


def _safe_link(graph: LocalGraph, src: str, fkey: str, dst: str) -> None:
    """Create a FK link, ignoring duplicate-edge errors."""
    try:
        graph.link(src_table=src, fkey=fkey, dst_table=dst)
    except ValueError as e:
        if "already exists" not in str(e):
            raise


# ─── Info helpers ───────────────────────────────────────────────────


def make_tables_info(graph: LocalGraph, df_dict: dict[str, pd.DataFrame]) -> dict:
    """Build a serializable table-info dict from a graph + raw DataFrames."""
    info: dict = {}
    for name in sorted(graph.tables.keys()):
        tbl = graph[name]
        raw_df = df_dict.get(name, pd.DataFrame())
        info[name] = {
            "rows": len(raw_df),
            "columns": list(raw_df.columns) if not raw_df.empty else [],
            "primary_key": str(tbl.primary_key) if tbl.primary_key else None,
            "time_column": str(tbl.time_column) if tbl.time_column else None,
        }
    return info


def get_links(graph: LocalGraph) -> list[dict]:
    """Extract link metadata from the graph's internal ``_edges`` list."""
    raw = getattr(graph, "_edges", []) or []
    return [
        {"src_table": getattr(e, "src_table", ""), "fkey": getattr(e, "fkey", ""), "dst_table": getattr(e, "dst_table", "")}
        for e in raw
    ]
