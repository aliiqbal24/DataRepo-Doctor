from datarepo_doctor.domain.models import (
    AccessMethod,
    FilterClause,
    ObjectStoreProfile,
    ProbeSpec,
    SchemaField,
)

PART_COLUMNS = ("p_partkey", "p_name", "p_brand", "p_retailprice")
PART_SCHEMA = (
    SchemaField(name="p_partkey", type="int64"),
    SchemaField(name="p_name", type="string"),
    SchemaField(name="p_brand", type="string"),
    SchemaField(name="p_retailprice", type="decimal"),
)
ORDER_COLUMNS = ("o_orderkey", "o_custkey", "o_orderstatus", "o_totalprice", "o_orderdate")
ORDER_SCHEMA = (
    SchemaField(name="o_orderkey", type="int64"),
    SchemaField(name="o_custkey", type="int64"),
    SchemaField(name="o_orderstatus", type="string"),
    SchemaField(name="o_totalprice", type="decimal"),
    SchemaField(name="o_orderdate", type="date"),
)
SUPPLIER_COLUMNS = ("s_suppkey", "s_name", "s_nationkey", "s_acctbal")
SUPPLIER_SCHEMA = (
    SchemaField(name="s_suppkey", type="int64"),
    SchemaField(name="s_name", type="string"),
    SchemaField(name="s_nationkey", type="int64"),
    SchemaField(name="s_acctbal", type="decimal"),
)

LOCAL_PROBES = (
    ProbeSpec(
        check_id="fixture-delta-part",
        display_name="Fixture Part / Delta",
        description="Controlled native Delta integration fixture.",
        physical_source="Delta Lake / MinIO fixture",
        catalog="demo_catalog.local_fixture_catalog:LOCAL_FIXTURE_CATALOG",
        database="tpch",
        table="part",
        access_method=AccessMethod.PYTHON_SDK,
        filters=(FilterClause(column="p_partkey", operator="in", value=[1, 2, 3, 4, 5]),),
        selected_columns=PART_COLUMNS,
        sort_columns=("p_partkey",),
        expected_schema=PART_SCHEMA,
        expected_row_count=5,
        expected_sha256="1489c551b5d646725a51c80555f818a421638fccdedb131087c587d09a05d338",
        timeout_seconds=30,
        phase_offset_minutes=0,
        object_store_profile=ObjectStoreProfile.LOCAL_MINIO,
        query_description="Controlled bounded Delta fixture query.",
    ),
    ProbeSpec(
        check_id="fixture-parquet-orders",
        display_name="Fixture Orders / Parquet",
        description="Controlled native Parquet integration fixture.",
        physical_source="Parquet / MinIO fixture",
        catalog="demo_catalog.local_fixture_catalog:LOCAL_FIXTURE_CATALOG",
        database="tpch",
        table="orders",
        access_method=AccessMethod.PYTHON_SDK,
        filters=(
            FilterClause(column="o_orderstatus", operator="=", value="O"),
            FilterClause(column="o_orderkey", operator="<=", value=6),
        ),
        selected_columns=ORDER_COLUMNS,
        sort_columns=("o_orderkey",),
        expected_schema=ORDER_SCHEMA,
        expected_row_count=6,
        expected_sha256="466b0332f589944e7765e00ba522f6e3eff6055fac5be27e00e5ca21c9e467a2",
        timeout_seconds=30,
        phase_offset_minutes=5,
        object_store_profile=ObjectStoreProfile.LOCAL_MINIO,
        query_description="Controlled bounded Parquet fixture query.",
    ),
    ProbeSpec(
        check_id="fixture-postgres-supplier",
        display_name="Fixture Supplier / Function",
        description="Controlled PostgreSQL function-table integration fixture.",
        physical_source="PostgreSQL fixture",
        catalog="demo_catalog.local_fixture_catalog:LOCAL_FIXTURE_CATALOG",
        database="tpch",
        table="supplier",
        access_method=AccessMethod.PYTHON_SDK,
        arguments={"min_suppkey": 1, "max_suppkey": 4},
        selected_columns=SUPPLIER_COLUMNS,
        sort_columns=("s_suppkey",),
        expected_schema=SUPPLIER_SCHEMA,
        expected_row_count=4,
        expected_sha256="b13456f17019e92c88c46cd62a514dcdba6363d4a57b354b06da96f80ba4b4e9",
        timeout_seconds=20,
        phase_offset_minutes=10,
        query_description="Controlled bounded PostgreSQL fixture query.",
    ),
)
