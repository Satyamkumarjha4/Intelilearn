# Model registry

No model name, provider, or parameter is hard-coded in graph code. Every LLM-backed node has a stable **node key** (for example `page.generate`). The registry maps that key to an ordered chain of models (a primary model plus fallbacks) with parameters and a reasoning level. You edit it in the Django admin.

Nodes also have **requirements**: a node that searches for images needs tool calling, and a node that checks images needs vision. Models declare **capabilities**. The admin refuses any binding where the model cannot meet the node's requirements.

## Concepts

```
Provider ──< LLMModel ──< NodeModelBinding >── NodeConfig ── NodeSpec (in code)
 gemini      gemini-2.5-pro     priority 0 ─┐                 requires: structured_output
 anthropic   claude-sonnet-5    priority 1 ─┼─ lesson.plan    min_output_tokens: 8k
 groq        llama-3.3-70b      priority 2 ─┘                 default reasoning: high
```

| Concept | Where | What |
|---|---|---|
| **Provider** | DB | An API vendor and how to reach it |
| **LLMModel** | DB | One model: default parameters, **capabilities**, limits |
| **NodeSpec** | code | What a node *needs*: capabilities, minimum output/context, output schema, whether it's optional. It changes only when the graph changes. |
| **NodeConfig** | DB | How a node *runs*: enabled, reasoning level, attempts, timeout, tool-step cap, parameter overrides |
| **NodeModelBinding** | DB | Attaches a model to a node at a priority (0 = primary, then fallbacks in order) |
| **ModelCall** | DB | Log of every call the gateway makes |

## Tables (`llm_registry/models.py`)

### `Provider`

| Field | Type | Notes |
|---|---|---|
| key | slug, unique | `gemini`, `groq`, `openai`, `anthropic`, `ollama`, `openrouter` |
| kind | enum | LangChain integration: `google_genai`, `groq`, `openai`, `anthropic`, `ollama`, `openai_compatible` |
| api_key_env | char, null | **Name** of the environment variable holding the key. Keys are never stored in the DB. |
| base_url | URL, null | For `ollama` and `openai_compatible` |
| rpm_limit | int, null | Provider-wide requests per minute, shared by all workers (fixed one-minute windows in Redis). A call over the limit **waits** for the next window, for up to 120 s, instead of failing. |
| is_enabled | bool | Disabling a provider skips all of its models |

### `LLMModel`

| Field | Type | Notes |
|---|---|---|
| provider | FK | |
| name | char | API model ID |
| label | char | Display name |
| default_params | JSON | For example `{"temperature": 0.4, "max_tokens": 8192}` |
| **Capabilities** | | |
| supports_structured_output | bool | Can return schema-conforming output |
| structured_output_method | enum `json_schema` \| `function_calling` \| `json_mode` | Passed to `with_structured_output(method=...)`. Set it to whatever the model does most reliably. |
| supports_tool_calling | bool | Required by `media.search` |
| supports_parallel_tool_calls | bool | Lets the media agent issue several searches in one turn |
| supports_vision | bool | Accepts image input. Required by `media.verify`. |
| supports_reasoning | bool | Has a thinking or reasoning mode |
| reasoning_control | enum `effort` \| `budget_tokens` \| `none` | How that mode is controlled; the gateway translates to it (see below) |
| reasoning_disables_sampling | bool | If set, the gateway drops `temperature` and `top_p` when reasoning is on (some providers reject both together) |
| **Limits** | | |
| context_window | int | |
| max_output_tokens | int | |
| rpm_limit | int, null | Per-model requests per minute, on top of the provider's |
| input_cost_per_mtok / output_cost_per_mtok | decimal, null | Used to cost each `ModelCall` |
| is_enabled | bool | |

`unique_together = (provider, name)`

### `NodeConfig` (one row per node key; rows created by migration from `NODE_SPECS`)

| Field | Type | Notes |
|---|---|---|
| node_key | char, unique | Must exist in `NODE_SPECS` |
| is_enabled | bool | Only optional nodes can be disabled; admin validation blocks the rest |
| reasoning_effort | enum `none` \| `low` \| `medium` \| `high` | Defaults from the spec. Ignored for models without reasoning. |
| params_override | JSON | Applied to every binding of this node |
| max_attempts | int | Graph-level generate → validate rounds (default from spec) |
| max_tool_steps | int, null | Tool-calling nodes only: cap on agent/tool loop iterations |
| timeout_s | int | Per call |

### `NodeModelBinding`

| Field | Type | Notes |
|---|---|---|
| node | FK NodeConfig | |
| model | FK LLMModel | |
| priority | int | 0 = primary |
| params_override | JSON | Highest precedence |
| reasoning_effort | enum, null | Overrides the node's setting for this model only. For example, use `high` on a small fallback model to compensate. |
| max_retries | int | Transport retries on this model before falling back (default 2) |
| is_enabled | bool | |

`unique_together = (node, priority)`. Validation in `clean()`:

- The model meets every capability in `NodeSpec.requires`.
- `model.max_output_tokens ≥ spec.min_output_tokens` and `model.context_window ≥ spec.min_context`.
- The merged parameters use only allow-listed keys for the provider kind.

### `ModelCall`

`lesson_id`, `run_id` (plain UUIDs, so the registry doesn't depend on the lessons app), `node_key`, `provider_key`, `model_name`, `attempt`, `fallback_index`, `status` (`ok` \| `retryable_error` \| `fatal_error` \| `invalid_output`), `error`, `latency_ms`, `input_tokens`, `output_tokens`, `reasoning_tokens`, `tool_calls`, `cost`, `created_at`

## Node specs

These are defined in code (`llm_registry/node_specs.py`). The graph imports the keys, the admin reads the requirements, and a `post_migrate` handler creates a `NodeConfig` row, with the spec's defaults, for any spec that doesn't have one yet.

```python
@dataclass(frozen=True)
class NodeSpec:
    key: str
    stage: Literal["diagnose", "author", "build", "post"]
    output: Literal["structured", "tools", "text"]
    schema: type[BaseModel] | None          # Pydantic output model
    requires: frozenset[Capability]          # {"structured_output", "tool_calling", "vision", ...}
    min_output_tokens: int = 4096
    min_context: int = 32_000
    default_reasoning: Effort = "medium"
    default_max_attempts: int = 2
    optional: bool = False
```

| Node key | Stage | Output → schema | Requires | Min output | Default reasoning | Optional |
|---|---|---|---|---|---|---|
| `diagnostic.generate` | diagnose | structured → `DiagnosticBundle` | structured_output | 8k | medium | |
| `diagnostic.review` | diagnose | structured → `QuizReview` | structured_output | 2k | low | ✓ |
| `learner.assess` | diagnose | structured → `LearnerAssessment` | structured_output | 2k | medium | |
| `study.generate` | diagnose | structured → `CheatSheet` / `RevisionSheet` / `PracticeSheet` | structured_output | 16k | medium | |
| `lesson.plan` | author | structured → `LessonPlan` | structured_output | 8k | **high** | |
| `page.generate` | author | structured → `PageContent` | structured_output | 16k | medium | |
| `test.generate` | author | structured → `FinalTest` | structured_output | 16k | medium | |
| `interactive.plan` | author | structured → `InteractivePlan` | structured_output | 4k | medium | |
| `media.search` | author | tools → `MediaSelection` (via `submit_media`) | **tool_calling** | 2k | low | |
| `media.verify` | author | structured → `MediaVerdict` | **vision**, structured_output | 1k | none | ✓ |
| `interactive.generate` | author | structured → `InteractiveComponent` | structured_output | 16k | medium | |
| `alignment.judge` | author | structured → `AlignmentReport` | structured_output, context ≥ 64k | 4k | **high** | |
| `page.compile` | build | text (TSX) | n/a | **32k** | medium | |
| `code.repair` | build | text (TSX) | n/a | 32k | medium | |
| `runtime.repair` | post | text (TSX) | n/a | 32k | medium | |
| `test.grade` | post | structured → `GradeReport` | structured_output | 4k | medium | |

Adding a node takes three steps: add a `NodeSpec`, write the node, and run `migrate`, which creates its `NodeConfig`. Then bind models in the admin or add them to `llm_registry/seed.py`.

## Structured output

- **Graph state** is a `TypedDict`. **LLM inputs and outputs** are Pydantic v2 models (`graph/schemas/`).
- The gateway calls `chat.with_structured_output(Schema, method=model.structured_output_method, include_raw=True)`. With `include_raw=True`, a parse failure returns the raw text and the error instead of raising, so the gateway can retry once on the same model with the error appended, then fall back.
- Schemas should work with **every** provider:
  - Prefer flat models over `oneOf` or discriminated unions. Use a `type` field with optional fields, enforced by `@model_validator`.
  - Put the length and range limits the prompt must know about in `Field(description=...)` as well as the constraint, because some providers ignore `minItems` and similar keywords.
  - Avoid recursive schemas and free-form `dict[str, Any]`.
- Some constraints can't be expressed in JSON Schema, such as "2 questions per band" or "concepts unique". Those belong to the graph's `validate_*` nodes, not the schema.

## Tool calling (`media.search`)

- The gateway exposes `invoke_tools(node_key, messages, tools)`. It returns an `AIMessage` with tool calls, and the graph's `ToolNode` runs them.
- The tools are `search_wikimedia(query, media_type)`, `search_openverse(query, media_type)`, `search_gifs(query)` (only if the Giphy key is set), and the final `submit_media(selection: MediaSelection)`.
- Loop control lives in the graph. It stops at `submit_media` or at `NodeConfig.max_tool_steps`, and the latter triggers the SVG fallback.
- If the model supports parallel tool calls, several searches run in one turn.

## Reasoning

`reasoning_effort` (`none` / `low` / `medium` / `high`) is set per node, with an optional override per binding. The gateway translates it in one place, the provider kind's `ProviderProfile` (`llm_registry/profiles.py`):

| `reasoning_control` | Translation |
|---|---|
| `effort` | The provider's effort parameter (table below) |
| `budget_tokens` | A thinking-token budget: `LLM_REASONING_BUDGET_LOW/MEDIUM/HIGH` (2048 / 8192 / 24576). For Anthropic, `max_tokens` is raised to budget + 4096 so there's room for the answer. |
| `none` | Ignored |

Parameter names, checked against the installed `langchain-*` packages (`tests/llm_registry/test_providers.py` builds each client to prove it):

| Provider kind | `effort` control | `budget_tokens` control |
|---|---|---|
| openai, openai_compatible, groq | `reasoning_effort` | *(same as effort)* |
| anthropic | `effort` | `thinking={"type": "enabled", "budget_tokens": N}` |
| google_genai | `thinking_level` | `thinking_budget=N` |
| ollama | `reasoning=True` / `False` | *(same)* |

If `reasoning_disables_sampling` is set, `temperature`, `top_p`, and `top_k` are removed while reasoning is on. Models without `supports_reasoning` always run with effort `none`.

## Parameter resolution

```
LLMModel.default_params  <  NodeConfig.params_override  <  NodeModelBinding.params_override
reasoning:  NodeSpec.default_reasoning  <  NodeConfig.reasoning_effort  <  NodeModelBinding.reasoning_effort
```

Allowed parameter keys depend on what each integration supports (`ProviderProfile.allowed_params` in `llm_registry/profiles.py`):

| Provider kind | Allowed keys |
|---|---|
| openai, openai_compatible | `temperature`, `top_p`, `max_tokens`, `stop`, `seed`, `presence_penalty`, `frequency_penalty` |
| anthropic | `temperature`, `top_p`, `top_k`, `max_tokens`, `stop` |
| google_genai | `temperature`, `top_p`, `top_k`, `max_tokens`, `stop`, `seed`, `presence_penalty`, `frequency_penalty` |
| groq | `temperature`, `max_tokens`, `stop` |
| ollama | `temperature`, `top_p`, `top_k`, `max_tokens` (sent as `num_predict`), `stop`, `seed` |

Reasoning is not set through `params`; it has its own field.

## Resolution and snapshots

```python
@dataclass(frozen=True)
class ResolvedModel:
    provider_kind: str; provider_key: str; model_name: str
    params: dict; reasoning: dict | None
    structured_output_method: str
    api_key_env: str | None; base_url: str | None
    max_retries: int; limits: dict

@dataclass(frozen=True)
class ResolvedNode:
    node_key: str; enabled: bool; output: str
    max_attempts: int; max_tool_steps: int | None; timeout_s: int
    chain: list[ResolvedModel]      # primary first
```

- `RegistryResolver().resolve()` returns `{node_key: ResolvedNode}`. It skips disabled rows and bindings that no longer satisfy the spec, and orders chains by priority. The result is cached in Redis (the Django cache). Saving or deleting any registry row clears it, so the next resolve rebuilds it.
- **Snapshot per lesson:** when a lesson is created, `RegistryResolver().snapshot().to_json()` is stored in `Lesson.config_snapshot`, and the whole flow uses it, including resumes days later. Admin edits apply to *new* lessons. Every lesson records exactly which models built it. The gateway reads it back with `RegistrySnapshot.from_json(...)` (it also accepts the dict directly).
- **Startup check** (`manage.py check`): every required node has at least one enabled binding whose provider key is present in the environment. Missing keys are warnings, so you can run with only the providers you have keys for.

## Gateway

```python
from llm_registry.gateway import Gateway

result = Gateway().invoke(
    "learner.assess", messages,
    snapshot=lesson.config_snapshot,    # never the live registry
    schema=LearnerAssessment,           # structured nodes; tools=[...] for tool nodes
    lesson_id=lesson.id, run_id=run.id,
    on_event=publish,                   # receives {"type": "retrying" | "fallback_model", ...}
)
result.output          # parsed Pydantic object / AIMessage (tools) / str (text)
result.model.label     # which model actually answered
result.fallback_index  # 0 = primary
```

Every collaborator can be injected, which is how the tests run the gateway with scripted fake models: the chat-model factory (`providers.py`), the sleep function, the rate limiter (`ratelimit.py`), the retry policy (`retry.py`), the `ModelCall` recorder (`recorder.py`), and the output adapters, one per output mode (`outputs.py`).

### Algorithm

```
for index, model in enumerate(node.chain):
    chat = init_chat_model(model.model_name, model_provider=kind, api_key=env[...], base_url=..., **params, **reasoning)
    chat = wrap for output mode (structured / tools / text)
    for attempt in 1..model.max_retries+1:
        wait for rate-limit tokens (provider, model)
        try:
            result = chat.invoke(messages, timeout=node.timeout_s)
            if structured and result.parsing_error:
                if not repaired_once: append error, repaired_once = True, retry
                else: log(invalid_output); break          → next model
            log(ok); if index > 0: emit fallback_model event; return result
        except retryable (timeout, 429, 5xx, connection): log; backoff with jitter (honour Retry-After)
                 (a 429 saying a daily quota is spent, or asking for a wait over the cap, is fatal instead)
        except fatal (401/403, model not found, 400 bad request): log; break   → next model
raise AllModelsFailed(node_key, errors)
```

## Admin

- **Provider**: shows whether the key is present (✔/✘) without revealing it.
- **LLMModel**: capability flags grouped in a fieldset. The **Test model** action runs a probe for each declared capability: a plain prompt, a small structured-output schema, a dummy tool call, a generated 16×16 PNG for vision, and a low-effort reasoning call. It reports pass or fail and latency per capability, so a wrongly ticked capability is caught before a lesson depends on it. A client that can't even be built, for example because of a missing key, is reported as a failed `setup` probe.
- **NodeConfig**: shows the spec (read-only requirements), inline bindings ordered by priority, and each binding's **effective** parameters and reasoning setting. It warns when a required node has no enabled binding.
- **ModelCall**: read-only list with filters. The changelist shows failure rate and fallback rate per node and model.
- **Export / import**: exports the registry as JSON. `manage.py seed_registry --file registry.json` loads it.
- **`manage.py probe_models`** runs the same probes from the command line (`--model provider/name`, repeatable), plus, with `--node key`, one real call through that node's whole chain. It exits non-zero if anything fails.

## Secrets in errors

Provider SDK errors sometimes echo request details. Before any error text is stored (`ModelCall.error`) or shown (admin messages, probe output, `fallback_model` events, `AllModelsFailed`), `llm_registry/redaction.py` masks the values of secret-looking environment variables (`…_API_KEY`, `…_TOKEN`, `…_SECRET`, `…PASSWORD`) and common key formats (Google `AIza…`, Groq `gsk_…`, OpenAI and Anthropic `sk-…`, bearer tokens).

## Default seed (`manage.py seed_registry`)

This is a starting point that you tune in the admin afterwards. **Verify model IDs and capability flags against each provider's current catalogue before seeding.**

| Node | Primary | Fallback |
|---|---|---|
| diagnostic.generate | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| diagnostic.review | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| learner.assess | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| study.generate | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| lesson.plan | gemini / gemini-2.5-pro | gemini / gemini-2.5-flash |
| page.generate | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| test.generate | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| interactive.plan | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| media.search | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |
| media.verify | gemini / gemini-2.5-flash | gemini / gemini-2.5-flash-lite |
| interactive.generate | gemini / gemini-2.5-flash | gemini / gemini-2.5-pro |
| alignment.judge | gemini / gemini-2.5-pro | gemini / gemini-2.5-flash |
| page.compile | gemini / gemini-2.5-flash | gemini / gemini-2.5-pro |
| code.repair | gemini / gemini-2.5-flash | gemini / gemini-2.5-pro |
| runtime.repair | gemini / gemini-2.5-flash | gemini / gemini-2.5-pro |
| test.grade | gemini / gemini-2.5-flash | groq / llama-3.3-70b-versatile |

A full lesson makes roughly 20–35 LLM calls. Set provider `rpm_limit` to match your plan, and the rate limiter will queue calls instead of failing them.
