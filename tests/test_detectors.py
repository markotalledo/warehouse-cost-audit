from datetime import UTC, datetime, timedelta

from costaudit import detectors as d
from costaudit.model import Query


def test_polling_finds_the_three_dashboard_tiles(queries):
    f = d.polling(queries)
    assert len(f.evidence) == 3 and all(e["runs_per_day"] == 288 for e in f.evidence)


def test_small_loads_finds_the_per_minute_copy(queries):
    f = d.small_loads(queries)
    assert [e["runs_per_day"] for e in f.evidence] == [1440]


def test_unpruned_scans_finds_the_analyst_query_only(queries):
    f = d.unpruned_scans(queries)
    assert len(f.evidence) == 1 and "analytics.events" in f.evidence[0]["example"]


def test_spill_finds_the_one_heavy_model(queries):
    f = d.spill(queries)
    assert len(f.evidence) == 1 and "model_07" in f.evidence[0]["example"]


def test_queueing_points_at_the_overlapping_hour(queries):
    assert [e["hour_utc"] for e in d.queueing(queries).evidence] == ["13:00"]


def test_idle_hours_after_dbt_are_billed(queries, metering):
    f = d.idle_warehouses(metering, queries, credit_price=3.0)
    assert [e["warehouse"] for e in f.evidence] == ["TRANSFORM_WH"]


def test_kept_awake_carries_polling_cost_and_is_not_double_counted(queries, metering):
    findings = {f.key: f for f in d.run_all(queries, metering, credit_price=3.0)}
    awake = findings["kept_awake"]
    assert {e["warehouse"] for e in awake.evidence} == {"BI_WH", "LOAD_WH"}
    assert findings["polling"].monthly_saving_usd == 0 and findings["small_loads"].monthly_saving_usd == 0
    # BI_WH is not counted in the hours analysts used it.
    bi = next(e for e in awake.evidence if e["warehouse"] == "BI_WH")
    assert bi["hours_awake_only_for_this_per_day"] == 16.0


def test_a_well_behaved_workload_has_no_findings():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    quiet = [
        Query(
            str(i),
            "u",
            "W",
            "SELECT",
            f"select * from t{i % 3} where id = {i}",
            start + timedelta(hours=i),
            5_000,
            0,
            10,
            0,
            0,
            5,
            400,
            0.01,
        )
        for i in range(48)
    ]
    assert d.run_all(quiet) == []
