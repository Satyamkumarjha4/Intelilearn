"""Default registry: Gemini for most nodes, Groq Llama as the usual fallback (mirrors the original project).

Model ids and capability flags change often: verify them against each provider's catalogue, then tune
everything in the admin. Loaded by `manage.py seed_registry`.
"""

from .serialization import RegistrySerializer

_GEMINI = {
    "supports_structured_output": True,
    "structured_output_method": "json_schema",
    "supports_tool_calling": True,
    "supports_parallel_tool_calls": True,
    "supports_vision": True,
    "supports_reasoning": True,
    "reasoning_control": "budget_tokens",
    "context_window": 1_048_576,
    "max_output_tokens": 65_536,
}

_MODELS = [
    {"provider": "gemini", "name": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", **_GEMINI,
     "default_params": {"temperature": 0.5}},
    {"provider": "gemini", "name": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", **_GEMINI,
     "default_params": {"temperature": 0.4}},
    {"provider": "gemini", "name": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite", **_GEMINI,
     "default_params": {"temperature": 0.4}},
    {"provider": "groq", "name": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B (Groq)",
     "supports_structured_output": True, "structured_output_method": "function_calling",
     "supports_tool_calling": True, "supports_parallel_tool_calls": True, "supports_vision": False,
     "supports_reasoning": False, "reasoning_control": "none",
     "context_window": 131_072, "max_output_tokens": 32_768, "default_params": {"temperature": 0.4}},
]  # fmt: skip

FLASH, PRO, LITE, LLAMA = (
    ("gemini", "gemini-2.5-flash"),
    ("gemini", "gemini-2.5-pro"),
    ("gemini", "gemini-2.5-flash-lite"),
    ("groq", "llama-3.3-70b-versatile"),
)

# node_key: (chain, node settings)
_NODES = {
    "diagnostic.generate": ([FLASH, LLAMA], {"params_override": {"temperature": 0.5}}),
    # An optional judge of the diagnostic quiz (independence, band calibration): on, with a model that can judge.
    "diagnostic.review": ([FLASH, LLAMA], {"params_override": {"temperature": 0}}),
    "learner.assess": ([FLASH, LLAMA], {}),
    "study.generate": ([FLASH, PRO], {}),
    "lesson.plan": ([PRO, FLASH], {}),
    "page.generate": ([FLASH, PRO], {}),
    "test.generate": ([FLASH, LLAMA], {"params_override": {"temperature": 0.3}}),
    "interactive.plan": ([FLASH, LLAMA], {}),
    "media.search": ([FLASH, LLAMA], {}),
    # The vision check of a found picture (needs a vision model, so no Llama): on, with a cheap fallback.
    "media.verify": ([FLASH, LITE], {"params_override": {"temperature": 0}}),
    "interactive.generate": ([FLASH, PRO], {"params_override": {"temperature": 0.6}}),
    "alignment.judge": ([PRO, FLASH], {"params_override": {"temperature": 0}}),
    "page.compile": ([FLASH, PRO], {"params_override": {"temperature": 0.4}}),
    "code.repair": ([FLASH, PRO], {"params_override": {"temperature": 0.2}}),
    "runtime.repair": ([FLASH, PRO], {"params_override": {"temperature": 0.2}}),
    "test.grade": ([FLASH, LLAMA], {"params_override": {"temperature": 0}}),
}


class DefaultRegistry:
    """The seed as RegistrySerializer JSON, so `seed_registry` loads it exactly like an exported file."""

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
            "nodes": [
                {
                    "node_key": key,
                    **settings,
                    "bindings": [{"provider": p, "model": m, "priority": i} for i, (p, m) in enumerate(chain)],
                }
                for key, (chain, settings) in _NODES.items()
            ],
        }
