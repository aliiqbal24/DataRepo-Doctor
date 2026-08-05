import sys
from types import SimpleNamespace

from datarepo_doctor import retrieval
from datarepo_doctor.checks import PROBES
from datarepo_doctor.models import ObjectStoreProfile


def _clock(events: list[str], values: tuple[int, int]):
    remaining = iter(values)

    def tick() -> int:
        events.append(f"clock_{sum(item.startswith('clock_') for item in events) + 1}")
        return next(remaining)

    return tick


def test_python_latency_starts_at_query_call_and_stops_at_collect(monkeypatch):
    events: list[str] = []
    row = {"product_id": "1", "product_name": "One", "price": 1, "category": "test"}

    class CollectedFrame:
        def to_dicts(self):
            events.append("to_dicts")
            return [row]

    class LazyFrame:
        def collect(self):
            events.append("collect")
            return CollectedFrame()

    class Database:
        def tables(self, *, show_deprecated):
            events.append("resolve_table")
            return ["products"]

        def table(self, name, **kwargs):
            events.append("query_call")
            return LazyFrame()

    class Catalog:
        def db(self, name):
            events.append("resolve_database")
            return Database()

    spec = PROBES[0].model_copy(
        update={
            "catalog": "fake.module:TEST_CATALOG",
            "object_store_profile": ObjectStoreProfile.NONE,
        }
    )
    catalog_module = SimpleNamespace(TEST_CATALOG=Catalog())
    monkeypatch.setitem(sys.modules, "fake.module", catalog_module)
    real_import_module = retrieval.importlib.import_module

    def import_module(name, package=None):
        if name == "fake.module":
            events.append("import_catalog")
        return real_import_module(name, package)

    monkeypatch.setattr(retrieval.importlib, "import_module", import_module)
    monkeypatch.setattr(retrieval, "perf_counter_ns", _clock(events, (1_000_000, 8_500_000)))

    result = retrieval._retrieve_with_python(spec)

    assert result.user_query_latency_ms == 7.5
    assert events == [
        "import_catalog",
        "resolve_database",
        "resolve_table",
        "clock_1",
        "query_call",
        "collect",
        "clock_2",
        "to_dicts",
    ]


def test_roapi_latency_starts_at_http_call_and_stops_at_response(monkeypatch):
    events: list[str] = []
    spec = PROBES[3]
    row = {
        "code": "GEO",
        "label": "Geothermal",
        "fuel_group_eia": "Other",
        "fuel_phase": None,
        "description": "test",
    }

    class Response:
        content = b"unused"

        def raise_for_status(self):
            events.append("raise_for_status")

    def build_sql(_spec):
        events.append("build_sql")
        return "SELECT bounded"

    def post(*args, **kwargs):
        events.append("http_call")
        return Response()

    def loads(_content):
        events.append("decode_json")
        return [row]

    monkeypatch.setenv("DOCTOR_ROAPI_URL", "http://roapi.test")
    monkeypatch.setattr(retrieval, "_build_sql", build_sql)
    monkeypatch.setattr(retrieval.httpx, "post", post)
    monkeypatch.setattr(retrieval.json, "loads", loads)
    monkeypatch.setattr(retrieval, "perf_counter_ns", _clock(events, (2_000_000, 11_250_000)))

    result = retrieval._retrieve_with_roapi(spec)

    assert result.user_query_latency_ms == 9.25
    assert events == [
        "build_sql",
        "clock_1",
        "http_call",
        "clock_2",
        "raise_for_status",
        "decode_json",
    ]
