"""Unit under test: the console's view of the strategy settings (docs/to_be_developed/model-strategy.md 3.5.B):
`console.services.prices.ModelPrices`, the models list and edit, the steps' routing, and the usage figures.

Why: a price or a model that is about to change must be seen before it changes a lesson's cost: the Gemini 3.6 and 3.8
Flash price doubles on 2027-01-01 and a provider's shutdown date is a deadline. Saving a step's routing replaces its
whole chain, so a per-layer setting the screen did not carry would be wiped by the next save.

Use cases:
- a model's current price is the row in force today (or, with none, the price typed on the model, marked legacy); what
  it becomes and from when is the next row; no price at all is a warning
- warnings: no price; a price that ends or changes within 60 days (and what it becomes); a shutdown within 60 days or
  already past; a deprecated model; none for a model that is fine
- the models list carries tier, status, shutdown date, reasoning levels and off mode, strict flag, cache and request
  limits, the current and next price and the warnings, and a model's strategy settings can be edited
- a step's routing carries each layer's output cap, timeout, structured mode, fall-through events and price; a save
  stores them, a save that leaves them out resets them, and an unknown mode or event is a 400
- a layer that could pass its model's request limit is refused with the numbers, and the step shows it
- usage shows the spend in rupees at the `USD_INR_RATE` setting
- usage per step: the share of first-layer attempts that worked, the share of attempts that fell through, thinking and
  cached tokens, cost per call, and per model: thinking and cached tokens
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from console.periods import Periods
from console.services.prices import ModelPrices
from console.services.usage import UsageFilters, UsageReport
from llm_registry.models import LLMModel, ModelCall, ModelPrice, NodeModelBinding

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 15)
H = timedelta(hours=1)


def price(model, **kw):
    values = dict(input_per_mtok=Decimal("0.75"), output_per_mtok=Decimal("3.75"),
                  source_url="https://example.com/pricing", checked_on=date(2026, 11, 15))  # fmt: skip
    return ModelPrice.objects.create(model=model, **{**values, **kw})


def reader(model):
    """The prices of a model as the console reads them: with its rows prefetched, like the list does."""
    return ModelPrices(today=lambda: TODAY), LLMModel.objects.prefetch_related("prices").get(pk=model.pk)


class TestPrices:
    def test_the_current_price_is_the_row_in_force_today_and_the_next_is_what_it_becomes(self, registry):
        flash = registry.models["flash"]
        price(flash, valid_until=date(2026, 12, 31), cached_input_per_mtok=Decimal("0.075"))
        price(flash, input_per_mtok=Decimal("1.5"), output_per_mtok=Decimal("7.5"), valid_from=date(2027, 1, 1))
        prices, model = reader(flash)

        assert prices.current(model) == {
            "input": "0.7500", "output": "3.7500", "cached_input": "0.0750", "legacy": False,
            "checked_on": "2026-11-15", "source_url": "https://example.com/pricing", "valid_until": "2026-12-31",
        }  # fmt: skip
        assert prices.upcoming(model) == {"from": "2027-01-01", "input": "1.5000", "output": "7.5000"}

    def test_a_model_with_no_rows_falls_back_to_the_price_typed_on_it_marked_legacy(self, registry):
        lite = registry.models["lite"]
        LLMModel.objects.filter(pk=lite.pk).update(input_cost_per_mtok="0.3", output_cost_per_mtok="2.5")
        prices, model = reader(lite)

        current = prices.current(model)

        assert (current["input"], current["output"], current["legacy"], current["source_url"]) == (
            "0.3000", "2.5000", True, "")  # fmt: skip
        assert prices.upcoming(model) is None

    def test_no_price_at_all_is_none_and_a_warning(self, registry):
        prices, model = reader(registry.models["lite"])

        assert prices.current(model) is None
        assert prices.warnings(model) == ["No price: its calls have no cost."]

    def test_a_price_that_changes_within_60_days_warns_with_what_it_becomes(self, registry):
        flash = registry.models["flash"]
        price(flash, valid_until=date(2026, 12, 31))
        price(flash, input_per_mtok=Decimal("1.5"), output_per_mtok=Decimal("7.5"), valid_from=date(2027, 1, 1))
        prices, model = reader(flash)

        assert prices.warnings(model) == ["The price changes on 2027-01-01: $0.75 / $3.75 becomes $1.50 / $7.50."]

    def test_a_price_that_ends_with_nothing_after_it_says_so(self, registry):
        flash = registry.models["flash"]
        price(flash, valid_until=date(2026, 12, 1))
        prices, model = reader(flash)

        assert prices.warnings(model) == ["Its price ends on 2026-12-01 and no later price is set."]

    def test_a_price_that_changes_later_than_60_days_does_not_warn(self, registry):
        flash = registry.models["flash"]
        price(flash, valid_until=date(2027, 2, 1))
        prices, model = reader(flash)

        assert prices.warnings(model) == []

    def test_a_shutdown_within_60_days_or_already_past_and_a_deprecated_model_warn(self, registry):
        flash = registry.models["flash"]
        price(flash)
        LLMModel.objects.filter(pk=flash.pk).update(shutdown_on=date(2026, 12, 1), status="deprecated")
        prices, model = reader(flash)

        assert prices.warnings(model) == ["The provider stops serving it on 2026-12-01.", "Deprecated by its provider."]

        LLMModel.objects.filter(pk=flash.pk).update(shutdown_on=date(2026, 8, 16), status="stable")
        prices, model = reader(flash)

        assert prices.warnings(model) == ["The provider stopped serving it on 2026-08-16."]

    def test_a_model_that_is_fine_has_no_warnings(self, registry):
        flash = registry.models["flash"]
        price(flash)
        prices, model = reader(flash)

        assert prices.warnings(model) == []


class TestModelsEndpoint:
    def test_a_model_lists_its_strategy_settings_price_and_warnings(self, staff_client, registry):
        flash = registry.models["flash"]
        LLMModel.objects.filter(pk=flash.pk).update(
            tier="T2", status="preview", reasoning_levels=["low", "medium", "high"], reasoning_off="unsupported",
            strict_structured=True, min_cache_tokens=4096, max_request_tokens=6000,
        )  # fmt: skip
        price(flash, valid_until=date(2999, 1, 1))

        body = next(m for m in staff_client.get("/api/console/models").json()["results"] if m["id"] == flash.id)

        assert (body["tier"], body["status"], body["shutdown_on"]) == ("T2", "preview", None)
        assert (body["reasoning_levels"], body["reasoning_off"]) == (["low", "medium", "high"], "unsupported")
        assert (body["strict_structured"], body["min_cache_tokens"], body["max_request_tokens"]) == (True, 4096, 6000)
        assert body["price"]["input"] == "0.7500" and body["price"]["legacy"] is False
        assert body["next_price"] is None and body["warnings"] == []

    def test_a_model_with_no_price_lists_the_warning(self, staff_client, registry):
        body = next(m for m in staff_client.get("/api/console/models").json()["results"]
                    if m["id"] == registry.models["lite"].id)  # fmt: skip

        assert body["price"] is None and body["warnings"] == ["No price: its calls have no cost."]

    def test_the_strategy_settings_can_be_edited(self, staff_client, registry):
        lite = registry.models["lite"]

        response = staff_client.patch(
            f"/api/console/models/{lite.id}",
            {"tier": "T1", "status": "deprecated", "shutdown_on": "2026-12-01", "reasoning_levels": ["minimal", "low"],
             "reasoning_off": "minimal", "strict_structured": True, "min_cache_tokens": 2048,
             "max_request_tokens": 8000}, format="json")  # fmt: skip

        assert response.status_code == 200
        lite.refresh_from_db()
        assert (lite.tier, lite.status, lite.shutdown_on, lite.reasoning_levels) == (
            "T1", "deprecated", date(2026, 12, 1), ["minimal", "low"])  # fmt: skip
        assert (lite.reasoning_off, lite.strict_structured, lite.min_cache_tokens, lite.max_request_tokens) == (
            "minimal", True, 2048, 8000)  # fmt: skip

    def test_an_unknown_tier_or_status_is_refused(self, staff_client, registry):
        lite = registry.models["lite"]

        for change in ({"tier": "T9"}, {"status": "retired"}, {"reasoning_off": "sometimes"}):
            assert staff_client.patch(f"/api/console/models/{lite.id}", change, format="json").status_code == 400

    def test_the_query_count_does_not_grow_with_the_models(self, staff_client, registry, count_queries):
        for model in registry.models.values():
            price(model)
        small = count_queries(lambda: staff_client.get("/api/console/models"))
        for n in range(6):
            extra = LLMModel.objects.create(provider=registry.providers["groq"], name=f"extra-{n}")
            price(extra)

        assert count_queries(lambda: staff_client.get("/api/console/models")) == small


def put(client, key, **changes):
    body = {"enabled": True, "reasoning_effort": "medium", "max_attempts": 2, "timeout_s": 60, "bindings": []}
    return client.put(f"/api/console/nodes/{key}", {**body, **changes}, format="json")


def layer(registry, name, **extra):
    return {"model": registry.models[name].id, "max_retries": 2, **extra}


def node_of(client, key):
    groups = client.get("/api/console/nodes").json()["phases"]
    return {n["key"]: n for g in groups for n in g["nodes"]}[key]


class TestRoutingLayers:
    def test_a_layer_carries_its_cap_timeout_mode_events_and_price(self, staff_client, registry):
        flash = registry.models["flash"]
        price(flash, valid_until=date(2999, 1, 1))
        registry.bind("lesson.plan", "flash", max_output_tokens=4000, timeout_s=45, structured_mode="strict",
                      fall_through_on=["quota"])  # fmt: skip

        [binding] = node_of(staff_client, "lesson.plan")["bindings"]

        assert (binding["max_output_tokens"], binding["timeout_s"]) == (4000, 45)
        assert (binding["structured_mode"], binding["fall_through_on"]) == ("strict", ["quota"])
        assert binding["price"]["input"] == "0.7500"

    def test_a_save_stores_them_and_one_that_leaves_them_out_resets_them(self, staff_client, registry):
        registry.bind("lesson.plan", "flash")

        response = put(staff_client, "lesson.plan", bindings=[layer(
            registry, "lite", max_output_tokens=4096, timeout_s=30, structured_mode="best_effort",
            fall_through_on=["quota", "validation"])])  # fmt: skip

        assert response.status_code == 200
        [b] = NodeModelBinding.objects.filter(node__node_key="lesson.plan")
        assert (b.max_output_tokens, b.timeout_s, b.structured_mode, b.fall_through_on) == (
            4096, 30, "best_effort", ["quota", "validation"])  # fmt: skip

        put(staff_client, "lesson.plan", bindings=[layer(registry, "lite")])
        [b] = NodeModelBinding.objects.filter(node__node_key="lesson.plan")
        assert (b.max_output_tokens, b.timeout_s, b.structured_mode, b.fall_through_on) == (None, None, "", [])

    @pytest.mark.parametrize("change", [{"structured_mode": "magic"}, {"fall_through_on": ["weather"]},
                                        {"max_output_tokens": 0}, {"timeout_s": 0}])  # fmt: skip
    def test_an_unknown_mode_or_event_or_a_zero_is_a_400(self, staff_client, registry, change):
        assert put(staff_client, "lesson.plan", bindings=[layer(registry, "lite", **change)]).status_code == 400

    def test_a_layer_that_could_pass_the_models_request_limit_is_refused_with_the_numbers(self, staff_client, registry):
        LLMModel.objects.filter(pk=registry.models["oss"].pk).update(max_request_tokens=6000)

        response = put(staff_client, "diagnostic.generate", bindings=[layer(registry, "oss", max_output_tokens=8000)])

        assert response.status_code == 400
        assert "6000" in " ".join(response.json()["fields"]["bindings"])

    def test_the_step_lists_that_problem_for_a_layer_already_saved(self, staff_client, registry):
        LLMModel.objects.filter(pk=registry.models["oss"].pk).update(max_request_tokens=6000)
        registry.bind("diagnostic.generate", "oss")  # no cap: the model's full 65K reply

        [binding] = node_of(staff_client, "diagnostic.generate")["bindings"]

        assert any("6000" in problem for problem in binding["problems"])


class TestUsageFigures:
    def test_per_step_layer_one_pass_rate_fall_through_thinking_cached_and_cost_per_call(self, make_call, now):
        make_call(ago=1 * H, input_tokens=100, output_tokens=100, reasoning_tokens=40, cached_input_tokens=30,
                  cost="0.002000")  # fmt: skip
        make_call(ago=2 * H, status=ModelCall.Status.INVALID_OUTPUT, input_tokens=100, output_tokens=50,
                  cost="0.001000")  # fmt: skip
        make_call(ago=3 * H, fallback_index=1, input_tokens=100, output_tokens=100, reasoning_tokens=10,
                  cost="0.003000")  # fmt: skip
        make_call(ago=4 * H, fallback_index=1, status=ModelCall.Status.RETRYABLE_ERROR)

        report = UsageReport().build(UsageFilters.of(Periods().of("7d", now)))
        [node] = report["by_node"]

        assert node["layer1_ok_pct"] == 50.0  # two attempts on layer 1, one worked
        assert node["fallback_pct"] == 50.0  # two of four attempts were on a fallback layer
        assert node["thinking_k"] == 0.05 and node["cached_k"] == 0.03  # 50 and 30 tokens, in thousands
        assert node["thinking_pct"] == 20.0  # 50 of the 250 output tokens
        assert node["cost_per_call"] == "0.001500"  # 0.006 over four calls (the error has no cost: counted as a call)

    def test_per_model_thinking_and_cached_tokens(self, make_call, now):
        make_call(ago=1 * H, output_tokens=100, reasoning_tokens=40, cached_input_tokens=3000)

        [model] = UsageReport().build(UsageFilters.of(Periods().of("7d", now)))["by_model"]

        assert (model["thinking_k"], model["cached_k"]) == (0.04, 3.0)


def test_usage_shows_the_spend_in_rupees_at_the_rate_setting(make_call, now, settings):
    settings.USD_INR_RATE = 90.0
    make_call(ago=1 * H, cost="0.010000", input_tokens=10, output_tokens=10)
    make_call(ago=2 * H, cost="0.020000", input_tokens=10, output_tokens=10)

    report = UsageReport().build(UsageFilters.of(Periods().of("7d", now)))

    assert report["usd_inr_rate"] == "90.00"
    assert report["kpis"]["spend_inr"] == "2.70"  # $0.03
    assert report["by_node"][0]["cost_per_call_inr"] == "1.35"  # $0.015 a call
