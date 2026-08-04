from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import boto3
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from deltalake import write_deltalake
from psycopg import sql

from datarepo_doctor.domain.canonical import result_sha256
from datarepo_doctor.registry.probes import PROBES
from demo_catalog.fixtures import ORDER_ROWS, PART_ROWS, SUPPLIER_ROWS


def _root_s3() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ["DOCTOR_S3_ENDPOINT"],
        aws_access_key_id=os.environ["MINIO_ROOT_USER"],
        aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        region_name=os.getenv("DOCTOR_S3_REGION", "us-east-1"),
    )


def _clear_prefix(client: Any, bucket: str, prefix: str) -> None:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects})


def _seed_objects() -> None:
    bucket = os.getenv("DOCTOR_S3_BUCKET", "datarepo-demo")
    endpoint = os.environ["DOCTOR_S3_ENDPOINT"]
    client = _root_s3()
    bucket_names = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    if bucket not in bucket_names:
        client.create_bucket(Bucket=bucket)
    _clear_prefix(client, bucket, "tpch/")

    part_schema = pa.schema(
        [
            ("p_partkey", pa.int64()),
            ("p_name", pa.string()),
            ("p_brand", pa.string()),
            ("p_retailprice", pa.decimal128(12, 2)),
        ]
    )
    part_table = pa.Table.from_pylist(PART_ROWS, schema=part_schema)
    storage = {
        "AWS_ACCESS_KEY_ID": os.environ["MINIO_ROOT_USER"],
        "AWS_SECRET_ACCESS_KEY": os.environ["MINIO_ROOT_PASSWORD"],
        "AWS_ENDPOINT_URL": endpoint,
        "AWS_REGION": os.getenv("DOCTOR_S3_REGION", "us-east-1"),
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }
    write_deltalake(f"s3://{bucket}/tpch/part", part_table, mode="overwrite", storage_options=storage)

    order_schema = pa.schema(
        [
            ("o_orderkey", pa.int64()),
            ("o_custkey", pa.int64()),
            ("o_totalprice", pa.decimal128(12, 2)),
            ("o_orderdate", pa.date32()),
        ]
    )
    for status in ("O", "F"):
        rows = [
            {key: value for key, value in row.items() if key != "o_orderstatus"}
            for row in ORDER_ROWS
            if row["o_orderstatus"] == status
        ]
        sink = pa.BufferOutputStream()
        pq.write_table(pa.Table.from_pylist(rows, schema=order_schema), sink)
        client.put_object(
            Bucket=bucket,
            Key=f"tpch/orders/o_orderstatus={status}/df.parquet",
            Body=sink.getvalue().to_pybytes(),
        )


def _seed_postgres() -> None:
    password = os.environ["DOCTOR_POSTGRES_PASSWORD"]
    admin_dsn = (
        "postgresql://postgres:" + os.environ["POSTGRES_ADMIN_PASSWORD"] + "@postgres:5432/datarepo_demo"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname='doctor_reader'").fetchone()
        if exists:
            connection.execute(
                sql.SQL("ALTER ROLE doctor_reader WITH LOGIN PASSWORD {}").format(sql.Literal(password))
            )
        else:
            connection.execute(
                sql.SQL("CREATE ROLE doctor_reader LOGIN PASSWORD {}").format(sql.Literal(password))
            )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS supplier (
                   s_suppkey BIGINT PRIMARY KEY,
                   s_name TEXT NOT NULL,
                   s_nationkey BIGINT NOT NULL,
                   s_acctbal NUMERIC(12,2) NOT NULL
               )"""
        )
        connection.execute("TRUNCATE supplier")
        with connection.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO supplier VALUES (%s, %s, %s, %s)",
                [tuple(row.values()) for row in SUPPLIER_ROWS],
            )
        connection.execute("REVOKE ALL ON supplier FROM PUBLIC")
        connection.execute("GRANT CONNECT ON DATABASE datarepo_demo TO doctor_reader")
        connection.execute("GRANT USAGE ON SCHEMA public TO doctor_reader")
        connection.execute("GRANT SELECT ON supplier TO doctor_reader")
        connection.execute("ALTER ROLE doctor_reader SET default_transaction_read_only = on")


def _expected_rows(check_id: str) -> list[dict[str, object]]:
    if check_id == "delta-part-sdk":
        return PART_ROWS[:5]
    if check_id == "postgres-supplier-function":
        return SUPPLIER_ROWS[:4]
    rows = [
        row
        for row in ORDER_ROWS
        if row["o_orderstatus"] == "O" and cast(int, row["o_orderkey"]) <= 6
    ]
    return cast(list[dict[str, object]], rows)


def _write_generated_contracts() -> None:
    output = Path(os.getenv("ROAPI_CONFIG_PATH", "infra/generated/roapi.yaml"))
    output.parent.mkdir(parents=True, exist_ok=True)

    # data-repository 0.0.2 provides export_to_roapi_tables, while its README's
    # generate_config example is not present in the published wheel.
    from datarepo.export.roapi import export_to_roapi_tables

    from demo_catalog.catalog import DEMO_CATALOG

    tables = export_to_roapi_tables(DEMO_CATALOG)
    output.write_text(
        yaml.safe_dump(
            {"addr": {"http": "0.0.0.0:8080"}, "tables": tables},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    expectations: dict[str, dict[str, object]] = {}
    for spec in PROBES:
        rows = [
            {column: row[column] for column in spec.selected_columns} for row in _expected_rows(spec.check_id)
        ]
        actual = result_sha256(rows, spec)
        if actual != spec.expected_sha256:
            raise RuntimeError(f"Checked-in fingerprint is stale for {spec.check_id}")
        expectations[spec.check_id] = {"row_count": len(rows), "sha256": actual}
    output.with_name("expectations.json").write_text(
        json.dumps(expectations, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    _seed_objects()
    _seed_postgres()
    _write_generated_contracts()
    print("Seed complete: MinIO, PostgreSQL, ROAPI config, and fingerprints are ready.")


if __name__ == "__main__":
    main()
