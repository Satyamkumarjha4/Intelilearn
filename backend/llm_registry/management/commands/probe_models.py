from django.core.management import BaseCommand, CommandError
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from llm_registry import providers
from llm_registry.gateway import Gateway
from llm_registry.models import LLMModel
from llm_registry.node_specs import NODE_SPECS, OutputMode
from llm_registry.probes import probe_model
from llm_registry.redaction import REDACTOR
from llm_registry.resolver import RegistryResolver


class _Echo(BaseModel):
    word: str = Field(description="The word 'pong'")


class Command(BaseCommand):
    help = (
        "Make small real API calls to check that models work and have the capabilities they claim "
        "(the admin's 'Test model', from the command line). Exits non-zero if anything fails."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--model", action="append", default=[], help="provider/name; repeatable. Default: every bound model."
        )
        parser.add_argument("--node", action="append", default=[], help="Also run one call through this node's chain.")

    def handle(self, *args, model, node, **options):
        failures = 0
        for llm_model in self._models(model):
            self.stdout.write(self.style.MIGRATE_HEADING(str(llm_model)))
            for result in probe_model(llm_model, chat_factory=providers.CHAT_MODEL_FACTORY):
                style = self.style.SUCCESS if result.ok else self.style.ERROR
                failures += not result.ok
                line = (
                    f"  {'✔' if result.ok else '✘'} {result.capability:<18} {result.latency_ms:>6} ms  {result.detail}"
                )
                self.stdout.write(style(line))

        for node_key in node:
            failures += not self._run_node(node_key)

        if failures:
            raise CommandError(f"{failures} check(s) failed")
        self.stdout.write(self.style.SUCCESS("All checks passed"))

    def _models(self, labels):
        models = LLMModel.objects.select_related("provider").filter(is_enabled=True, provider__is_enabled=True)
        if not labels:
            return list(models.filter(bindings__is_enabled=True, bindings__node__is_enabled=True).distinct())
        found = []
        for label in labels:
            provider_key, _, name = label.partition("/")
            match = models.filter(provider__key=provider_key, name=name).first()
            if match is None:
                raise CommandError(f"No enabled model {label!r} (use provider/name, e.g. gemini/gemini-2.5-flash)")
            found.append(match)
        return found

    def _run_node(self, node_key) -> bool:
        spec = NODE_SPECS[node_key]
        self.stdout.write(self.style.MIGRATE_HEADING(f"node {node_key} (through the gateway)"))
        if spec.output == OutputMode.TOOLS:
            self.stdout.write("  skipped: tool-calling nodes need real tools; use the model probes instead")
            return True
        events = []
        try:
            result = Gateway(providers.CHAT_MODEL_FACTORY).invoke(
                node_key,
                [HumanMessage("This is a connectivity check. Reply with the single word: pong")],
                snapshot=RegistryResolver().snapshot(),
                schema=_Echo if spec.output == OutputMode.STRUCTURED else None,
                on_event=events.append,
            )
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  ✘ {type(exc).__name__}: {REDACTOR.redact(str(exc))}"))
            return False
        for event in events:
            self.stdout.write(f"  · {event['type']}: {event.get('model', '')} {event.get('reason', '')}".rstrip())
        answer = result.output.word if spec.output == OutputMode.STRUCTURED else str(result.output)[:60]
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✔ answered by {result.model.label} (fallback #{result.fallback_index}, "
                f"attempt {result.attempts}): {answer!r}"
            )
        )
        return True
