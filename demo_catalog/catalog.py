from datarepo.core import Catalog, ModuleDatabase

from . import tables

DEMO_CATALOG = Catalog({"public_science": ModuleDatabase(tables)}, package_name="demo_catalog")
