"""Unit under test: `llm_registry.usage.UsageReport` and the admin page built on it (`modelcall/usage/`).

Why: the model calls are the running cost of the product. An operator deciding whether a node needs a cheaper model, or
why lessons got slow, reads these numbers; averages that include fast failures, a cost that forgets retried calls, or a
window that silently shows everything would point them at the wrong node.

Use cases:
- per node: calls, how many succeeded and failed, attempts on a fallback model, tokens, cost, and average and p95
  latency of the successful attempts only
- per model: the same, by provider and model name
- the costliest node comes first, then the busiest
- the total covers every call
- a window keeps only the recent calls, and an unknown window means the default one
- the p95 is the nearest rank, and an empty log gives zeros rather than an error
- the admin page shows the tables, the window links, and honours the window
- the page needs a signed-in staff user with permission to see the log, and the changelist links to it
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from llm_registry.models import ModelCall
from llm_registry.usage import Usage, UsageReport

pytestmark = pytest.mark.django_db


def call(node="lesson.plan", model="flash", status="ok", ms=100, cost="0.01", tokens=(10, 5), fallback=0, age_days=0):
    row = ModelCall.objects.create(
        node_key=node, provider_key="gemini", model_name=model, attempt=1, fallback_index=fallback, status=status,
        latency_ms=ms, input_tokens=tokens[0], output_tokens=tokens[1], cost=Decimal(cost),
    )  # fmt: skip
    ModelCall.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=age_days))
    return row


def by_label(rows):
    return {row.label: row for row in rows}


class TestPerNode:
    def test_calls_outcomes_tokens_and_cost_are_added_up(self):
        call(ms=100, cost="0.02", tokens=(10, 5))
        call(ms=300, cost="0.03", tokens=(20, 15))
        call(status="retryable_error", ms=5, cost="0", tokens=(None, None))
        call(status="invalid_output", ms=900, cost="0.01", fallback=1)

        usage = by_label(UsageReport().per_node())["lesson.plan"]

        assert (usage.calls, usage.succeeded, usage.failed, usage.fallbacks) == (4, 2, 2, 1)
        assert (usage.input_tokens, usage.output_tokens, usage.cost) == (40, 25, Decimal("0.06"))
        assert usage.success_rate == 50

    def test_latency_is_of_the_successful_attempts_only(self):
        call(ms=100)
        call(ms=300)
        call(status="fatal_error", ms=1)
        call(status="invalid_output", ms=5000)

        usage = by_label(UsageReport().per_node())["lesson.plan"]

        assert (usage.avg_ms, usage.p95_ms) == (200, 300)

    def test_a_node_with_only_failures_has_no_latency_and_no_error(self):
        call(status="fatal_error", ms=3)

        usage = by_label(UsageReport().per_node())["lesson.plan"]

        assert (usage.avg_ms, usage.p95_ms, usage.succeeded, usage.success_rate) == (0, 0, 0, 0)

    def test_the_costliest_node_comes_first_then_the_busiest(self):
        call(node="cheap.many", cost="0.001")
        call(node="cheap.many", cost="0.001")
        call(node="cheap.few", cost="0.001")
        call(node="dear", cost="0.5")

        assert [u.label for u in UsageReport().per_node()] == ["dear", "cheap.many", "cheap.few"]

    def test_missing_tokens_and_cost_count_as_zero(self):
        row = call()
        ModelCall.objects.filter(pk=row.pk).update(input_tokens=None, output_tokens=None, cost=None)

        usage = UsageReport().per_node()[0]

        assert (usage.input_tokens, usage.output_tokens, usage.cost) == (0, 0, Decimal(0))


class TestPerModelAndTotal:
    def test_models_are_listed_by_provider_and_name(self):
        call(model="flash", cost="0.01")
        call(model="pro", cost="0.20")

        usages = UsageReport().per_model()

        assert [u.label for u in usages] == ["gemini/pro", "gemini/flash"]

    def test_the_total_covers_every_call(self):
        call(node="a", cost="0.01")
        call(node="b", cost="0.02", status="fatal_error")

        total = UsageReport().total()

        assert (total.label, total.calls, total.succeeded, total.cost) == ("All calls", 2, 1, Decimal("0.03"))


class TestWindow:
    def test_only_the_recent_calls_are_kept(self):
        call(age_days=0)
        call(age_days=3)
        call(age_days=20)

        assert [UsageReport().within(w).total().calls for w in ("1", "7", "30", "all")] == [1, 2, 3, 3]

    def test_an_unknown_window_is_the_default_one(self):
        call(age_days=3)
        call(age_days=20)

        assert UsageReport().within("forever").total().calls == 1


class TestEmptyAndPercentile:
    def test_an_empty_log_gives_zeros(self):
        report = UsageReport()

        assert report.per_node() == [] and report.per_model() == []
        assert report.total() == Usage("All calls", 0, 0, 0, 0, 0, Decimal(0), 0, 0)
        assert report.total().success_rate == 0

    @pytest.mark.parametrize(
        ("values", "expected"),
        [([], 0), ([7], 7), ([1, 2, 3, 4], 4), (list(range(1, 101)), 95), (list(range(1, 21)), 19)],
    )
    def test_the_p95_is_the_nearest_rank(self, values, expected):
        assert UsageReport._percentile(values, 95) == expected


class TestAdminPage:
    URL = "usage_url"

    @pytest.fixture
    def url(self):
        return reverse("admin:llm_registry_modelcall_usage")

    def test_it_shows_the_tables_and_the_window_links(self, admin_client, url):
        call(node="lesson.plan", ms=120, cost="0.05", tokens=(1000, 500))
        call(node="page.generate", status="fatal_error", ms=3)

        response = admin_client.get(url)
        html = response.content.decode()

        assert response.status_code == 200
        for text in (
            "lesson.plan",
            "page.generate",
            "gemini/flash",
            "All calls",
            "0.0500",
            "Last 7 days",
            "?window=30",
        ):
            assert text in html
        assert "<strong>Last 7 days</strong>" in html

    def test_the_window_is_honoured_and_a_bad_one_means_the_default(self, admin_client, url):
        call(node="old.node", age_days=20)

        recent = admin_client.get(url, {"window": "1"}).content.decode()
        everything = admin_client.get(url, {"window": "all"}).content.decode()
        bad = admin_client.get(url, {"window": "nope"}).content.decode()

        assert "old.node" not in recent and "No calls in this period." in recent
        assert "old.node" in everything and "<strong>Everything</strong>" in everything
        assert "<strong>Last 7 days</strong>" in bad

    def test_the_changelist_links_to_it(self, admin_client):
        response = admin_client.get(reverse("admin:llm_registry_modelcall_changelist"))

        assert reverse("admin:llm_registry_modelcall_usage") in response.content.decode()

    def test_it_needs_a_signed_in_staff_user(self, client, url):
        response = client.get(url)

        assert response.status_code == 302 and "/admin/login/" in response["Location"]

    def test_staff_without_permission_to_see_the_log_are_refused(self, client, url):
        staff = get_user_model().objects.create_user("ops@example.com", password="x", is_staff=True)
        client.force_login(staff)

        assert client.get(url).status_code == 403
