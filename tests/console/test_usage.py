"""Unit under test: `console.services.usage` (`UsageReport`, `UsageFilters`, `UsageCsv`) and the endpoints
`GET /api/console/usage` and `GET /api/console/usage/export.csv`.

Why: the usage page is where cost and flakiness are found. A percentile taken over failed calls, a retry counted as a
failure, or an export that does not match the filters on screen would make the numbers worth less than no numbers.
The calls are fixed rows with known latencies, so every figure is derived by hand.

Use cases:
- KPIs: calls, tokens in and out, spend, and the median and 95th percentile call time of the calls that worked
- by model: median and p95 call time, how many calls worked, were retried or failed, and the calls and spend
- by step: calls, share that worked, retry attempts, fallbacks, thousands of tokens, spend and p95
- filters: range, provider, model, step and outcome narrow every figure; none matching gives zeros and no times
- a custom range of whole days (`start` and `end`, inclusive) works for the page and the CSV, and names its period; it
  needs both dates, in order, within a year
- an unknown outcome or range is a 400; an unknown provider is just no calls
- the CSV has one row per call with the same filters, oldest first, with the outcome named like the page names it
- the CSV is streamed, sends a download name, and cannot be used to inject a spreadsheet formula
- both endpoints run a fixed number of queries however many calls there are
"""

import csv
import io
from datetime import timedelta

import pytest

from console.periods import Periods
from console.services.usage import UsageCsv, UsageFilters, UsageReport
from llm_registry.models import ModelCall

pytestmark = pytest.mark.django_db

H = timedelta(hours=1)
D = timedelta(days=1)
INVALID = ModelCall.Status.INVALID_OUTPUT
GROQ = dict(provider_key="groq", model_name="openai/gpt-oss-120b")


@pytest.fixture
def data(make_call):
    return {
        "A": make_call(ago=1 * H, latency_ms=1000, input_tokens=100, output_tokens=50, cost="0.010000"),
        "B": make_call(ago=2 * H, latency_ms=3000, input_tokens=200, output_tokens=100, cost="0.020000"),
        "C": make_call(ago=3 * H, latency_ms=500, node_key="page.generate", status=INVALID, error="bad json"),
        "D": make_call(
            ago=4 * H,
            latency_ms=2000,
            node_key="page.generate",
            attempt=2,
            fallback_index=1,
            input_tokens=1000,
            output_tokens=500,
            cost="0.005000",
            **GROQ,
        ),  # fmt: skip
        "E": make_call(ago=5 * H, latency_ms=4000, input_tokens=300, output_tokens=150, cost="0.001000", **GROQ),
        "old": make_call(ago=40 * D, latency_ms=100, cost="9.000000"),  # outside every range
    }


def report(now, **filters):
    return UsageReport().build(UsageFilters.of(Periods().of(filters.pop("range", "7d"), now), **filters))


def test_kpis_total_the_calls_and_time_only_the_ones_that_worked(data, now):
    kpis = report(now)["kpis"]

    # latencies of the four calls that worked: 1.0, 2.0, 3.0, 4.0 s (the 0.5 s failure is left out)
    assert kpis == {"calls": 5, "tokens_in": 1600, "tokens_out": 800, "spend": "0.036000",
                    "median_latency_s": 2.5, "p95_latency_s": 3.85}  # fmt: skip


def test_by_model_gives_each_models_times_and_outcomes(data, now):
    rows = {(r["provider"], r["model"]): r for r in report(now)["by_model"]}

    assert rows[("gemini", "gemini-3.5-flash")] == {
        "model": "gemini-3.5-flash", "provider": "gemini", "median_s": 2.0, "p95_s": 2.9,
        "ok": 2, "retried": 0, "failed": 1, "calls": 3, "spend": "0.030000",
    }  # fmt: skip
    assert rows[("groq", "openai/gpt-oss-120b")] == {
        "model": "openai/gpt-oss-120b", "provider": "groq", "median_s": 3.0, "p95_s": 3.9,
        "ok": 1, "retried": 1, "failed": 0, "calls": 2, "spend": "0.006000",
    }  # fmt: skip


def test_by_step_gives_each_steps_reliability_tokens_and_cost(data, now):
    rows = {r["node"]: r for r in report(now)["by_node"]}

    assert rows["learner.assess"] == {"node": "learner.assess", "calls": 3, "ok_pct": 100.0, "retries": 0,
                                      "fallbacks": 0, "tokens_k": 0.9, "spend": "0.031000", "p95_s": 3.9}  # fmt: skip
    # one call failed, one worked on a retry attempt (on the fallback model): half worked, and it is 1.5k tokens
    assert rows["page.generate"] == {"node": "page.generate", "calls": 2, "ok_pct": 50.0, "retries": 1,
                                     "fallbacks": 1, "tokens_k": 1.5, "spend": "0.005000", "p95_s": 2.0}  # fmt: skip


def test_the_busiest_models_and_steps_come_first(data, now):
    result = report(now)

    assert [r["node"] for r in result["by_node"]] == ["learner.assess", "page.generate"]
    assert [r["model"] for r in result["by_model"]][0] == "gemini-3.5-flash"  # 3 calls against 2


@pytest.mark.parametrize(
    ("filters", "calls"),
    [
        ({"provider": "groq"}, 2),
        ({"model": "gemini-3.5-flash"}, 3),
        ({"node": "page.generate"}, 2),
        ({"outcome": "failed"}, 1),
        ({"outcome": "retried"}, 1),
        ({"outcome": "ok"}, 3),
        ({"provider": "groq", "node": "learner.assess"}, 1),
        ({"range": "30d"}, 5),
    ],
)
def test_each_filter_narrows_every_figure(data, now, filters, calls):
    result = report(now, **filters)

    assert result["kpis"]["calls"] == calls
    assert sum(r["calls"] for r in result["by_node"]) == calls
    assert sum(r["ok"] + r["retried"] + r["failed"] for r in result["by_model"]) == calls


def test_the_range_decides_which_calls_count(make_call, now):
    make_call(ago=2 * H)  # today
    make_call(ago=1 * D + 2 * H)  # yesterday morning
    make_call(ago=20 * D)  # this month's range only

    counts = {key: report(now, range=key)["kpis"]["calls"] for key in ("today", "7d", "30d")}

    assert counts == {"today": 1, "7d": 2, "30d": 3}


def test_nothing_matching_gives_zeros_and_no_times(data, now):
    result = report(now, provider="openai")

    assert result["kpis"] == {"calls": 0, "tokens_in": 0, "tokens_out": 0, "spend": "0.000000",
                              "median_latency_s": None, "p95_latency_s": None}  # fmt: skip
    assert result["by_model"] == [] and result["by_node"] == []


def test_a_step_with_no_priced_calls_still_has_zero_spend(make_call, now):
    make_call()

    assert report(now)["by_node"][0]["spend"] == "0.000000"


# --- endpoints -----------------------------------------------------------------------------------------------------


def test_the_usage_endpoint_applies_the_filters(staff_client, data):
    body = staff_client.get("/api/console/usage?range=30d&provider=groq&outcome=retried").json()

    assert body["kpis"]["calls"] == 1 and body["by_model"][0]["provider"] == "groq"
    assert set(body) == {"range", "period", "kpis", "by_model", "by_node"}
    assert body["period"]["start"] == "2026-02-14T00:00:00Z" and body["period"]["end"] == "2026-03-15T12:00:00Z"


def test_an_unknown_outcome_or_range_is_a_bad_request(staff_client):
    assert "outcome" in staff_client.get("/api/console/usage?outcome=slow").json()["fields"]
    assert "range" in staff_client.get("/api/console/usage?range=1y").json()["fields"]
    assert staff_client.get("/api/console/usage/export.csv?outcome=slow").status_code == 400


def test_an_unknown_provider_is_simply_no_calls(staff_client, data):
    assert staff_client.get("/api/console/usage?provider=nobody").json()["kpis"]["calls"] == 0


def read_csv(response):
    return list(csv.DictReader(io.StringIO(b"".join(response.streaming_content).decode())))


def test_the_csv_has_a_row_per_call_oldest_first_with_the_same_filters(staff_client, data):
    response = staff_client.get("/api/console/usage/export.csv?range=7d&model=gemini-3.5-flash")
    rows = read_csv(response)

    assert [r["outcome"] for r in rows] == ["failed", "ok", "ok"]  # C, B, A: oldest first
    assert [r["node"] for r in rows] == ["page.generate", "learner.assess", "learner.assess"]
    assert rows[0]["status"] == "invalid_output" and rows[0]["error"] == "bad json"
    assert rows[2]["cost"] == "0.010000" and rows[2]["latency_ms"] == "1000" and rows[2]["tokens_in"] == "100"
    assert rows[2]["created_at"] == "2026-03-15T11:00:00+00:00"


def test_the_csv_names_the_retry_and_the_fallback(staff_client, data):
    [row] = read_csv(staff_client.get("/api/console/usage/export.csv?provider=groq&outcome=retried"))

    assert (row["outcome"], row["attempt"], row["fallback_index"]) == ("retried", "2", "1")
    assert row["provider"] == "groq" and row["model"] == "openai/gpt-oss-120b"


def test_the_csv_is_streamed_and_downloads_with_a_name(staff_client, data):
    response = staff_client.get("/api/console/usage/export.csv?range=30d")

    assert response.streaming and response["Content-Type"].startswith("text/csv")
    assert response["Content-Disposition"] == 'attachment; filename="socra-usage-30d-2026-03-15.csv"'
    assert response["Cache-Control"] == "no-store"
    assert next(iter(response.streaming_content)).decode().startswith("created_at,")


def test_the_csv_header_is_the_documented_columns(staff_client, data):
    response = staff_client.get("/api/console/usage/export.csv")
    header = b"".join(response.streaming_content).decode().splitlines()[0]

    assert header.split(",") == UsageCsv.COLUMNS


@pytest.mark.parametrize("text", ['=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_a_cell_that_would_be_a_spreadsheet_formula_is_defused(staff_client, make_call, text):
    make_call(status=ModelCall.Status.FATAL_ERROR, error=text)

    [row] = read_csv(staff_client.get("/api/console/usage/export.csv"))

    assert row["error"] == "'" + text


def test_a_cell_with_commas_and_quotes_survives_a_round_trip(staff_client, make_call):
    make_call(status=ModelCall.Status.FATAL_ERROR, error='said "no", twice\nthen stopped')

    [row] = read_csv(staff_client.get("/api/console/usage/export.csv"))

    assert row["error"] == 'said "no", twice\nthen stopped'


def test_usage_and_export_query_counts_do_not_grow_with_the_calls(staff_client, make_call, count_queries):
    def fetch():
        staff_client.get("/api/console/usage?range=30d")
        b"".join(staff_client.get("/api/console/usage/export.csv?range=30d").streaming_content)

    for index in range(3):
        make_call(node_key=f"n{index}", model_name=f"m{index}")
    few = count_queries(fetch)

    for index in range(30):
        make_call(node_key=f"n{index}", model_name=f"m{index}", status=INVALID)
    many = count_queries(fetch)

    assert many == few


# --- custom ranges ---------------------------------------------------------------------------------------------------


@pytest.fixture
def spread(make_call):
    """One call a day for ten days, the latest today at 11:00."""
    for days in range(10):
        make_call(ago=timedelta(days=days, hours=1), latency_ms=1000 * (days + 1))


def test_a_custom_range_counts_the_whole_days_asked_for(staff_client, spread):
    body = staff_client.get("/api/console/usage?range=custom&start=2026-03-10&end=2026-03-12").json()

    assert body["range"] == "custom" and body["kpis"]["calls"] == 3  # the 10th, 11th and 12th
    assert body["period"] == {"start": "2026-03-10T00:00:00Z", "end": "2026-03-13T00:00:00Z"}


def test_a_custom_range_ending_today_ends_now(staff_client, spread):
    body = staff_client.get("/api/console/usage?range=custom&start=2026-03-14&end=2026-03-30").json()

    assert body["kpis"]["calls"] == 2 and body["period"]["end"] == "2026-03-15T12:00:00Z"


def test_custom_dates_work_with_the_other_filters_and_the_csv(staff_client, spread):
    rows = read_csv(staff_client.get("/api/console/usage/export.csv?range=custom&start=2026-03-10&end=2026-03-11"))

    assert [r["created_at"][:10] for r in rows] == ["2026-03-10", "2026-03-11"]
    response = staff_client.get("/api/console/usage/export.csv?range=custom&start=2026-03-10&end=2026-03-11")
    assert response["Content-Disposition"] == 'attachment; filename="socra-usage-custom-2026-03-11.csv"'


@pytest.mark.parametrize(
    ("query", "field"),
    [
        ("range=custom", "start"),
        ("range=custom&start=2026-03-01", "end"),
        ("range=custom&start=2026-03-10&end=2026-03-01", "end"),
        ("range=custom&start=2024-01-01&end=2026-03-01", "end"),
        ("range=custom&start=yesterday&end=2026-03-01", "start"),
    ],
)
def test_a_custom_range_needs_two_dates_in_order_within_a_year(staff_client, query, field):
    response = staff_client.get(f"/api/console/usage?{query}")

    assert response.status_code == 400 and field in response.json()["fields"]


def test_dates_are_ignored_unless_the_range_is_custom(staff_client, spread):
    body = staff_client.get("/api/console/usage?range=today&start=2026-03-01&end=2026-03-02").json()

    assert body["range"] == "today" and body["kpis"]["calls"] == 1
