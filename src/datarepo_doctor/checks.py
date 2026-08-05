from __future__ import annotations

from datarepo_doctor.models import (
    AccessMethod,
    FilterClause,
    ObjectStoreProfile,
    ProbeSpec,
    SchemaField,
)

DELTA_COLUMNS = ("product_id", "product_name", "price", "category")
DELTA_SCHEMA = (
    SchemaField(name="product_id", type="string"),
    SchemaField(name="product_name", type="string"),
    SchemaField(name="price", type="int64"),
    SchemaField(name="category", type="string"),
)
DELTA_PRODUCT_IDS = ["00001", "00002", "00003", "00004", "00005"]

PUDL_COLUMNS = ("code", "label", "fuel_group_eia", "fuel_phase", "description")
PUDL_SCHEMA = (
    SchemaField(name="code", type="string"),
    SchemaField(name="label", type="string"),
    SchemaField(name="fuel_group_eia", type="string"),
    SchemaField(name="fuel_phase", type="string", nullable=True),
    SchemaField(name="description", type="string"),
)
PUDL_CODES = ["GEO", "NG", "NUC", "SUN", "WND"]

RNA_COLUMNS = ("upi", "taxid", "ac")
RNA_SCHEMA = (
    SchemaField(name="upi", type="string"),
    SchemaField(name="taxid", type="int64"),
    SchemaField(name="ac", type="string"),
)

PUBLIC_ENVIRONMENT = "public_internet"
PUDL_URI = "s3://pudl.catalyst.coop/v2024.11.0/core_eia__codes_energy_sources.parquet"

PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec(
        check_id="aws-delta-products-sdk",
        display_name="AWS Products / Delta",
        description="Bounded native Delta retrieval from an official public AWS tutorial table.",
        physical_source="Delta Lake / public Amazon S3",
        source_owner="Amazon Web Services",
        source_uri="s3://aws-bigdata-blog/artifacts/delta-lake-crawler/sample_delta_table",
        source_version="Delta version 6",
        source_license="AWS public tutorial artifact",
        source_documentation_url=(
            "https://aws.amazon.com/blogs/big-data/"
            "introducing-native-delta-lake-table-support-with-aws-glue-crawlers/"
        ),
        catalog="demo_catalog.catalog:DEMO_CATALOG",
        database="public_science",
        table="products",
        access_method=AccessMethod.PYTHON_SDK,
        filters=(FilterClause(column="product_id", operator="in", value=DELTA_PRODUCT_IDS),),
        selected_columns=DELTA_COLUMNS,
        sort_columns=("product_id",),
        expected_schema=DELTA_SCHEMA,
        expected_row_count=5,
        expected_sha256="83360bb58ce36a0a69a24d47393c26ccb1c87e45eba2d5a1d95d857785107de6",
        timeout_seconds=45,
        phase_offset_minutes=0,
        environment=PUBLIC_ENVIRONMENT,
        object_store_profile=ObjectStoreProfile.PUBLIC_AWS_UNSIGNED,
        object_store_region="us-east-1",
        query_description=(
            "Select four declared columns for five fixed public product identifiers "
            "[redacted]."
        ),
        display_result_rows=True,
        spec_version="2",
    ),
    ProbeSpec(
        check_id="pudl-energy-parquet-sdk",
        display_name="PUDL Energy Sources / Parquet",
        description="Bounded native Parquet retrieval from a versioned public energy dataset.",
        physical_source="Parquet / public Amazon S3",
        source_owner="Catalyst Cooperative",
        source_uri=PUDL_URI,
        source_version="PUDL v2024.11.0",
        source_license="CC-BY-4.0",
        source_documentation_url="https://docs.catalyst.coop/pudl/en/v2026.4.0/data_access.html",
        catalog="demo_catalog.catalog:DEMO_CATALOG",
        database="public_science",
        table="energy_sources",
        access_method=AccessMethod.PYTHON_SDK,
        filters=(FilterClause(column="code", operator="in", value=PUDL_CODES),),
        selected_columns=PUDL_COLUMNS,
        sort_columns=("code",),
        expected_schema=PUDL_SCHEMA,
        expected_row_count=5,
        expected_sha256="ec8d33633540375014e541acd8d61a3cb3249bfba33dc45d4a1b9428635136e1",
        timeout_seconds=45,
        phase_offset_minutes=5,
        environment=PUBLIC_ENVIRONMENT,
        object_store_profile=ObjectStoreProfile.PUBLIC_AWS_UNSIGNED,
        object_store_region="us-west-2",
        query_description="Select five declared columns for five fixed EIA energy codes [redacted].",
        display_result_rows=True,
        spec_version="2",
    ),
    ProbeSpec(
        check_id="rnacentral-xrefs-function",
        display_name="RNAcentral Cross-references / Function",
        description="Bounded biological lookup through a DataRepo function table and public PostgreSQL.",
        physical_source="PostgreSQL / EMBL-EBI RNAcentral",
        source_owner="RNAcentral / EMBL-EBI",
        source_uri="postgresql://hh-pgsql-public.ebi.ac.uk:5432/pfmegrnargs",
        source_version="Current RNAcentral public release",
        source_license="CC0 (RNAcentral v20+)",
        source_documentation_url="https://rnacentral.org/help/public-database",
        catalog="demo_catalog.catalog:DEMO_CATALOG",
        database="public_science",
        table="rna_xrefs",
        access_method=AccessMethod.PYTHON_SDK,
        arguments={
            "accession_a": "OTTHUMT00000106564.1",
            "accession_b": "OTTHUMT00000416802.1",
        },
        selected_columns=RNA_COLUMNS,
        sort_columns=("ac",),
        expected_schema=RNA_SCHEMA,
        expected_row_count=2,
        expected_sha256="80bbbb3333e53ef8b1ac80fbe3b7aec6e447452f7ebee676d0b919f7778d828a",
        timeout_seconds=30,
        phase_offset_minutes=10,
        environment=PUBLIC_ENVIRONMENT,
        query_description="Resolve two fixed archived external RNA accessions [redacted].",
        display_result_rows=True,
        spec_version="2",
    ),
    ProbeSpec(
        check_id="pudl-energy-roapi-http",
        display_name="PUDL Energy Sources / ROAPI",
        description="The same bounded PUDL slice retrieved through the generated read-only HTTP API.",
        physical_source="Parquet / public Amazon S3 via ROAPI",
        source_owner="Catalyst Cooperative",
        source_uri=PUDL_URI,
        source_version="PUDL v2024.11.0",
        source_license="CC-BY-4.0",
        source_documentation_url="https://docs.catalyst.coop/pudl/en/v2026.4.0/data_access.html",
        catalog="demo_catalog.catalog:DEMO_CATALOG",
        database="public_science",
        table="energy_sources",
        access_method=AccessMethod.ROAPI_HTTP,
        filters=(FilterClause(column="code", operator="in", value=PUDL_CODES),),
        selected_columns=PUDL_COLUMNS,
        sort_columns=("code",),
        expected_schema=PUDL_SCHEMA,
        expected_row_count=5,
        expected_sha256="ec8d33633540375014e541acd8d61a3cb3249bfba33dc45d4a1b9428635136e1",
        timeout_seconds=30,
        phase_offset_minutes=15,
        environment=PUBLIC_ENVIRONMENT,
        query_description="HTTP SQL selection for five fixed EIA energy codes [redacted].",
        display_result_rows=True,
        spec_version="2",
    ),
)

_BY_ID = {probe.check_id: probe for probe in PROBES}


def get_probe(check_id: str) -> ProbeSpec:
    try:
        return _BY_ID[check_id]
    except KeyError as exc:
        raise KeyError(f"Unknown check: {check_id}") from exc
