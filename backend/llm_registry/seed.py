"""Default registry for the free tiers: Groq answers the light nodes first, Gemini the big-output ones, and the
chains put a second quota bucket behind each so one spent quota doesn't stop a lesson.

Providers retire model ids often (the Gemini 2.5 family and Groq's Llama models are already gone for new accounts).
Verify ids, capability flags and rpm limits against each provider's current catalogue and console, run
`manage.py probe_models`, then tune everything in the admin. The rpm limits are free-tier figures, so raise or clear
them on a paid plan. Loaded by `manage.py seed_registry`.
"""

from .node_specs import NODE_SPECS, Effort
from .serialization import RegistrySerializer

_GEMINI = {
    "supports_structured_output": True,
    "structured_output_method": "json_schema",
    "supports_tool_calling": True,
    "supports_parallel_tool_calls": True,
    "supports_vision": True,
    "supports_reasoning": True,
    "reasoning_control": "effort",  # Gemini 3 takes thinking_level; the 2.5 budget is the older control
    "context_window": 1_048_576,
    "max_output_tokens": 65_536,
}

# Groq's free tier allows about 8,000 tokens a minute per model, so a single request (prompt plus reply) has to fit
# in that: Groq models only lead the nodes whose prompt and reply are small.
_GROQ = {
    "supports_structured_output": True, "structured_output_method": "json_schema",
    "supports_tool_calling": True, "supports_parallel_tool_calls": True, "supports_vision": False,
    "supports_reasoning": True, "reasoning_control": "effort",
    "context_window": 131_072, "max_output_tokens": 65_536, "rpm_limit": 30,
}  # fmt: skip

_MODELS = [
    {"provider": "gemini", "name": "gemini-3.5-flash", "label": "Gemini 3.5 Flash", **_GEMINI, "rpm_limit": 10,
     "default_params": {"temperature": 0.5}},
    {"provider": "gemini", "name": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite", **_GEMINI,
     "rpm_limit": 15, "default_params": {"temperature": 0.4}},
    {"provider": "gemini", "name": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite", **_GEMINI,
     "rpm_limit": 15, "default_params": {"temperature": 0.4}},
    {"provider": "groq", "name": "openai/gpt-oss-120b", "label": "GPT-OSS 120B (Groq)", **_GROQ,
     "default_params": {"temperature": 0.4}},
    {"provider": "groq", "name": "openai/gpt-oss-20b", "label": "GPT-OSS 20B (Groq)", **_GROQ,
     "default_params": {"temperature": 0.4}},
]  # fmt: skip

FLASH, LITE, LITE_31, GPT_OSS, GPT_OSS_SMALL = (
    ("gemini", "gemini-3.5-flash"),
    ("gemini", "gemini-3.5-flash-lite"),
    ("gemini", "gemini-3.1-flash-lite"),
    ("groq", "openai/gpt-oss-120b"),
    ("groq", "openai/gpt-oss-20b"),
)

# node_key: (chain, node settings)
# Light nodes (small prompt, small reply) lead with Groq and fall over to Gemini. The nodes that write 16K+ tokens or
# read whole lessons lead with Gemini, because a Groq free-tier request over its token cap is rejected outright; behind
# Flash they have Flash-Lite, which has its own quota, so only the light-and-medium ones also list a Groq model.
_NODES = {
    # Low effort: at medium, gpt-oss drops required fields of this big schema; low parses every time.
    "diagnostic.generate": ([GPT_OSS, FLASH], {"params_override": {"temperature": 0.5}, "reasoning_effort": "low"}),
    # An optional judge of the diagnostic quiz (independence, band calibration): on, small and cheap first.
    "diagnostic.review": ([GPT_OSS_SMALL, FLASH], {"params_override": {"temperature": 0}}),
    "learner.assess": ([GPT_OSS_SMALL, FLASH], {}),
    "study.generate": ([FLASH, LITE], {}),
    "lesson.plan": ([FLASH, GPT_OSS, LITE], {}),
    "page.generate": ([FLASH, LITE], {}),
    "test.generate": ([FLASH, LITE], {"params_override": {"temperature": 0.3}}),
    "interactive.plan": ([GPT_OSS_SMALL, FLASH], {}),
    "media.search": ([GPT_OSS_SMALL, FLASH], {}),
    # The vision check of a found picture (needs a vision model, so Gemini only): on, with a cheap fallback.
    "media.verify": ([FLASH, LITE], {"params_override": {"temperature": 0}}),
    "interactive.generate": ([FLASH, LITE], {"params_override": {"temperature": 0.6}}),
    "alignment.judge": ([FLASH, LITE], {"params_override": {"temperature": 0}}),
    "page.compile": ([FLASH, LITE], {"params_override": {"temperature": 0.4}}),
    "code.repair": ([FLASH, LITE], {"params_override": {"temperature": 0.2}}),
    "runtime.repair": ([FLASH, LITE], {"params_override": {"temperature": 0.2}}),
    "test.grade": ([GPT_OSS, FLASH], {"params_override": {"temperature": 0}}),
    # Onboarding must not wait: the smallest Groq model first and a Flash-Lite behind it, low effort, one attempt, 4 s a
    # call and no retry on a model (the next model is the retry). Past that the learner gets the catalogue instead.
    "onboarding.suggest_topics": (
        [GPT_OSS_SMALL, LITE],
        {
            "params_override": {"temperature": 0.5},
            "reasoning_effort": "low",
            "max_attempts": 1,
            "timeout_s": 4,
            "max_retries": 0,
        },
    ),
}


class DefaultRegistry:
    """The seed as RegistrySerializer JSON, so `seed_registry` loads it exactly like an exported file."""

    #: how the profile is offered in the console's list: a short name and one sentence on when to pick it
    label = "Default"
    description = "The free-tier layout: Groq answers the light steps, Gemini the big ones, a second quota behind each."
    nodes = _NODES

    def build(self) -> dict:
        return {
            "format_version": RegistrySerializer.FORMAT_VERSION,
            "providers": [
                {
                    "key": "gemini",
                    "kind": "google_genai",
                    "api_key_env": "GEMINI_API_KEY",
                    "base_url": "",
                    "is_enabled": True,
                },
                {"key": "groq", "kind": "groq", "api_key_env": "GROQ_API_KEY", "base_url": "", "is_enabled": True},
            ],
            "models": _MODELS,
            "nodes": [self._node(key, chain, settings) for key, (chain, settings) in self.nodes.items()],
        }

    @staticmethod
    def _node(key: str, chain: list, settings: dict) -> dict:
        """One node as RegistrySerializer JSON. `max_retries` in a node's settings is a binding setting: it goes on
        every model of the chain instead of the node."""
        settings = dict(settings)
        retries = {"max_retries": settings.pop("max_retries")} if "max_retries" in settings else {}
        return {
            "node_key": key,
            **settings,
            "bindings": [{"provider": p, "model": m, "priority": i, **retries} for i, (p, m) in enumerate(chain)],
        }


# A node that the default leads with Groq keeps gpt-oss-20b first (small replies fit its token cap); every other node
# (big replies, or reading a whole lesson, or vision) runs on the two Flash-Lite models, which have separate quotas.
_CHEAP_LIGHT = [GPT_OSS_SMALL, LITE, LITE_31]
_CHEAP_HEAVY = [LITE, LITE_31]


class CheapRegistry(DefaultRegistry):
    """For validating the lesson flow end to end without hitting rate or billing limits: only the cheapest models, at
    low reasoning effort. Quality is not the point. Once the flow works, seed the default and tune for accuracy."""

    label = "Cheap"
    description = "Only the cheapest models, at low reasoning effort. For trying the flow end to end, not for quality."
    nodes = {
        key: (_CHEAP_LIGHT if chain[0][0] == "groq" else _CHEAP_HEAVY, {**settings, "reasoning_effort": "low"})
        for key, (chain, settings) in _NODES.items()
    }


# The steps where the lesson's quality is decided (writing it, planning it, judging it, grading the learner), and the
# mechanical ones that only reshape or repair what was written. Balanced spends the better model on the first kind.
_JUDGEMENT_NODES = frozenset({
    "diagnostic.generate", "learner.assess", "study.generate", "lesson.plan", "page.generate", "test.generate",
    "interactive.generate", "alignment.judge", "test.grade", "media.verify",
})  # fmt: skip
_QUICK_NODES = frozenset({"onboarding.suggest_topics"})  # the learner is waiting: every profile keeps these as seeded


def _own_effort(key: str) -> str:
    """The reasoning effort the node's spec asks for."""
    return str(NODE_SPECS[key].default_reasoning)


def _raised(effort: str) -> str:
    """One step more reasoning (nothing to raise when it is off or already high)."""
    return {Effort.LOW: "medium", Effort.MEDIUM: "high"}.get(Effort(effort), effort)


class BalancedRegistry(DefaultRegistry):
    """Gemini Flash writes and judges the lesson, the two Flash-Lite models (and the small Groq model on the light
    steps) do the mechanical work, every node at its own reasoning effort."""

    label = "Balanced"
    description = "Gemini Flash writes and judges the lesson; the cheaper models do the mechanical steps."
    nodes = {
        key: (
            ([FLASH, LITE] if key in _JUDGEMENT_NODES else _CHEAP_LIGHT if chain[0][0] == "groq" else _CHEAP_HEAVY),
            {**settings, "reasoning_effort": _own_effort(key)},
        )
        if key not in _QUICK_NODES
        else (chain, settings)
        for key, (chain, settings) in _NODES.items()
    }


class QualityRegistry(DefaultRegistry):
    """Gemini Flash first on every step, with the second Flash-Lite and the big Groq model behind it where Groq can
    take the reply, and one step more reasoning than each node asks for. For when the cost does not matter."""

    label = "Quality"
    description = "The strongest model first on every step, thinking a step harder. Slower and the most expensive."
    nodes = {
        key: (
            ([FLASH, GPT_OSS, LITE] if any(p == "groq" for p, _ in chain) else [FLASH, LITE]),
            {**settings, "reasoning_effort": _raised(_own_effort(key))},
        )
        if key not in _QUICK_NODES
        else (chain, settings)
        for key, (chain, settings) in _NODES.items()
    }


# `seed_registry --profile NAME`: add a profile by adding a class here (and its label and description).
SEED_PROFILES = {
    "default": DefaultRegistry,
    "cheap": CheapRegistry,
    "balanced": BalancedRegistry,
    "quality": QualityRegistry,
}
