from datarepo.core import Catalog, ModuleDatabase

from . import local_fixture_tables

LOCAL_FIXTURE_CATALOG = Catalog(
    {"tpch": ModuleDatabase(local_fixture_tables)},
    package_name="demo_catalog.local_fixtures",
)
