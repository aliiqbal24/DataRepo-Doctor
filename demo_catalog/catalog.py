from datarepo.core import Catalog, ModuleDatabase

from . import tables

DEMO_CATALOG = Catalog({"tpch": ModuleDatabase(tables)}, package_name="demo_catalog")
