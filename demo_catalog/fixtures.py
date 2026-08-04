from datetime import date
from decimal import Decimal

PART_ROWS = [
    {
        "p_partkey": i,
        "p_name": f"Part #{i}",
        "p_brand": f"Brand#{(i % 3) + 1}",
        "p_retailprice": Decimal(f"{100 + i}.25"),
    }
    for i in range(1, 9)
]

ORDER_ROWS = [
    {
        "o_orderkey": i,
        "o_custkey": 100 + i,
        "o_orderstatus": "O" if i <= 6 else "F",
        "o_totalprice": Decimal(f"{200 + i * 11}.50"),
        "o_orderdate": date(2026, 1, i),
    }
    for i in range(1, 11)
]

SUPPLIER_ROWS = [
    {
        "s_suppkey": i,
        "s_name": f"Supplier #{i}",
        "s_nationkey": i % 3,
        "s_acctbal": Decimal(f"{1000 + i * 17}.00"),
    }
    for i in range(1, 7)
]
