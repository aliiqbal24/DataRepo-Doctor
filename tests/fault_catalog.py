from __future__ import annotations

import os
import time

import polars as pl
from datarepo.core import Catalog, ModuleDatabase, NlkDataFrame, table


@table
def hanging(lower: int, upper: int) -> NlkDataFrame:
    time.sleep(10)
    return pl.LazyFrame({"id": [lower]})


@table
def crashing(lower: int, upper: int) -> NlkDataFrame:
    os._exit(23)


@table
def succeeding(lower: int, upper: int) -> NlkDataFrame:
    return pl.LazyFrame({"id": list(range(lower, upper + 1))})


FAULT_CATALOG = Catalog({"faults": ModuleDatabase(__import__(__name__, fromlist=["*"]))})
