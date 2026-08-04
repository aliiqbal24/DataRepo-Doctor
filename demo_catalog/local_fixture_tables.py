"""Controlled source tables used only by integration and fault-injection tests."""

from __future__ import annotations

import os
from decimal import Decimal

import polars as pl
import psycopg
import pyarrow as pa
from datarepo.core import (
    DeltalakeTable,
    Filter,
    NlkDataFrame,
    ParquetTable,
    Partition,
    PartitioningScheme,
    table,
)

_bucket = os.environ.get("DOCTOR_S3_BUCKET", "datarepo-demo")

part = DeltalakeTable(
    name="part",
    uri=f"s3://{_bucket}/tpch/part",
    schema=pa.schema(
        [
            ("p_partkey", pa.int64()),
            ("p_name", pa.string()),
            ("p_brand", pa.string()),
            ("p_retailprice", pa.decimal128(12, 2)),
        ]
    ),
    docs_filters=[Filter("p_partkey", "in", [1, 2, 3, 4, 5])],
    docs_columns=["p_partkey", "p_name", "p_brand", "p_retailprice"],
    unique_columns=["p_partkey"],
    description="Controlled Delta Lake fixture in MinIO.",
)

orders = ParquetTable(
    name="orders",
    uri=f"s3://{_bucket}/tpch/orders",
    partitioning=[Partition("o_orderstatus", pl.String)],
    partitioning_scheme=PartitioningScheme.HIVE,
    parquet_file_name="df.parquet",
    docs_filters=[Filter("o_orderstatus", "=", "O")],
    docs_columns=["o_orderkey", "o_custkey", "o_orderstatus", "o_totalprice", "o_orderdate"],
    description="Controlled Hive-partitioned Parquet fixture in MinIO.",
)


@table(  # type: ignore[untyped-decorator]
    docs_args={"min_suppkey": 1, "max_suppkey": 4},
    data_input="Controlled read-only PostgreSQL fixture",
)
def supplier(min_suppkey: int, max_suppkey: int) -> NlkDataFrame:
    with psycopg.connect(os.environ["DOCTOR_POSTGRES_DSN"]) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        rows = connection.execute(
            """SELECT s_suppkey, s_name, s_nationkey, s_acctbal
                   FROM supplier
                  WHERE s_suppkey BETWEEN %s AND %s
                  ORDER BY s_suppkey""",
            (min_suppkey, max_suppkey),
        ).fetchall()
    return pl.LazyFrame(
        {
            "s_suppkey": [int(row[0]) for row in rows],
            "s_name": [str(row[1]) for row in rows],
            "s_nationkey": [int(row[2]) for row in rows],
            "s_acctbal": [Decimal(row[3]) for row in rows],
        }
    )
