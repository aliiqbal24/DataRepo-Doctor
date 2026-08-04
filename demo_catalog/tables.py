from __future__ import annotations

import os

import polars as pl
import psycopg
import pyarrow as pa
from datarepo.core import (
    DeltalakeTable,
    Filter,
    NlkDataFrame,
    ParquetTable,
    PartitioningScheme,
    table,
)

products = DeltalakeTable(
    name="products",
    uri="s3://aws-bigdata-blog/artifacts/delta-lake-crawler/sample_delta_table",
    schema=pa.schema(
        [
            ("product_id", pa.string()),
            ("product_name", pa.string()),
            ("price", pa.int64()),
            ("CURRENCY", pa.string()),
            ("category", pa.string()),
            ("updated_at", pa.float64()),
        ]
    ),
    docs_filters=[Filter("product_id", "in", ["00001", "00002", "00003", "00004", "00005"])],
    docs_columns=["product_id", "product_name", "price", "category"],
    unique_columns=["product_id"],
    description="Public Delta Lake product table maintained as an AWS Big Data Blog tutorial artifact.",
    table_metadata_args={
        "data_input": "Public AWS S3 Delta Lake tutorial table",
        "latency_info": "Live unsigned retrieval from Amazon S3",
    },
)


energy_sources = ParquetTable(
    name="energy_sources",
    uri="s3://pudl.catalyst.coop/v2024.11.0/core_eia__codes_energy_sources.parquet",
    partitioning=[],
    partitioning_scheme=PartitioningScheme.HIVE,
    docs_columns=["code", "label", "fuel_group_eia", "fuel_phase", "description"],
    description="Versioned public energy-source reference data from Catalyst Cooperative's PUDL project.",
    table_metadata_args={
        "data_input": "PUDL v2024.11.0 public Parquet release",
        "latency_info": "Live unsigned retrieval from the PUDL public S3 bucket",
    },
)


@table(  # type: ignore[untyped-decorator]
    docs_args={
        "accession_a": "OTTHUMT00000106564.1",
        "accession_b": "OTTHUMT00000416802.1",
    },
    data_input="RNAcentral public read-only PostgreSQL database",
    latency_info="Live query to EMBL-EBI public infrastructure",
)
def rna_xrefs(accession_a: str, accession_b: str) -> NlkDataFrame:
    """Resolve a bounded pair of archived external RNA accessions."""
    with psycopg.connect(os.environ["DOCTOR_RNACENTRAL_DSN"]) as connection:
        connection.execute("SET TRANSACTION READ ONLY")
        rows = connection.execute(
            """SELECT upi, taxid, ac
                   FROM xref
                  WHERE ac = ANY(%s)
                  ORDER BY ac""",
            ([accession_a, accession_b],),
        ).fetchall()
    return pl.LazyFrame(
        {
            "upi": [str(row[0]) for row in rows],
            "taxid": [int(row[1]) for row in rows],
            "ac": [str(row[2]) for row in rows],
        }
    )
