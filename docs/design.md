# Object design

This document is the **binding object model** for Lesson Crafter: the rules every module follows, the classes each module is made of, and the design patterns used where. It covers the code that exists today and the target for every roadmap phase.

- New code follows this document. If a change needs a class, collaborator, or pattern that isn't here, update this document **in the same change**.
- Where today's code differs from the target, the gap is listed in the [refactor backlog](#refactor-backlog). Close it when you next touch that module, or in a dedicated `refactor/<topic>` branch.
- Diagrams are Mermaid (`classDiagram`, `sequenceDiagram`); GitHub and VS Code render them. They show the public surface and the key collaborators, not every private helper.

Legend for status columns: ✅ in code · ◐ partly (functions still to wrap in a class) · ☐ planned (roadmap phase).

## 1. Rules

### 1.1 Everything is object-oriented

Behaviour lives in classes. A unit of work is a method on an object with a single, nameable responsibility, and its collaborators are passed in.

| Construct | Use |
|---|---|
| **Class with methods** | All behaviour: services, policies, adapters, validators, graph nodes, prompt builders |
| **`typing.Protocol`** | Ports (interfaces) a class depends on: `LLMGateway`, `RateLimiter`, `MediaSource`… Structural, so test fakes need no inheritance |
| **`abc.ABC`** | Base classes that share an algorithm (Template Method): `Node`, `LLMNode`, `Prompt`, `HealthCheck` |
| **`@dataclass(frozen=True)` / Pydantic `BaseModel`** | Value objects: results, reports, snapshots, LLM inputs and outputs. Immutable, compared by value |
| **`StrEnum` / `models.TextChoices`** | Closed sets of values (`Capability`, `Stage`, `Route`) |
| **Module-level constants** | Configuration that never changes at runtime (`PAGE_KEYS`, `MAX_BYTES`) |
| **Django model methods, managers, querysets** | Behaviour that belongs to a row (`Profile.is_complete`) or to a query (`Lesson.objects.owned_by(user)`) |

**Allowed exceptions.** Some frameworks require a function, a module, or a component function at a fixed place. These are *adapters*, not logic: each one is a few lines that build or look up an object and call one method on it.

| Framework hook | Shape |
|---|---|
| Django `settings.py`, `urls.py`, migrations | Modules, as Django requires |
| Signal receivers (`@receiver`), system checks (`@register`), DRF `EXCEPTION_HANDLER` | Function → one call into a class (`RegistryResolver().invalidate()`) |
| Celery tasks (`@shared_task`) | Function → `FlowRunner().start(lesson_id)` |
| LangGraph state reducers in `Annotated[...]` | `@staticmethod`s on a `Reducers` class |
| pytest test functions and fixtures | pytest idiom (test classes are optional); see [testing.md](testing.md) |
| React components and hooks | Function components and hooks (class components are legacy React). Non-UI logic they use lives in TypeScript classes in `lib/` |

### 1.2 SOLID in this codebase

| Principle | Rule here | Example | Smell to refuse |
|---|---|---|---|
| **S**ingle responsibility | One reason to change per class. Views parse and format; services decide; adapters talk to the outside world. | `Gateway` orchestrates the fallback chain; retrying, rate limiting, logging and output parsing are separate collaborators. | A view that grades a quiz, saves an attempt and enqueues Celery inline |
| **O**pen/closed | Add a variant by adding a class and registering it, not by editing an `if/elif` ladder. | A new provider kind is a new `ProviderProfile`; a new media source is a new `MediaSource`; a new LLM step is a new `NodeSpec` + node class. | `if kind == "anthropic": … elif kind == "google_genai": …` spread across modules |
| **L**iskov substitution | Every implementation of a port honours its contract, including errors raised and "empty" results. | Any `MediaSource.search` returns `[]` for no hits (never `None`) and raises `MediaError` for transport failures. | A subclass that ignores an argument or raises where the base returns |
| **I**nterface segregation | Ports are small and named for the client's need. | Validators depend on `LatexChecker.latex(expressions)`, not on all of `SandboxRunner`. | Passing the whole `FlowContext` into a pure validator |
| **D**ependency inversion | High-level code depends on Protocols; concrete classes are chosen at the composition root and injected through constructors. | Graph nodes use `ctx.gateway: LLMGateway`; tests inject a `FakeGateway`. `default_context()` is the composition root. | `Gateway()` or `httpx.Client()` constructed inside a node or validator |

### 1.3 Further conventions

- **Constructor injection** with production defaults, so callers stay short and tests pass fakes: `Gateway(chat_factory=..., limiter=..., sleep=...)`.
- **Composition over inheritance.** Inherit only for Template Method bases and framework base classes (Django, DRF, LangChain).
- **Tell, don't ask.** `lesson.advance_to(Stage.READY)` rather than `lesson.stage = "ready"` followed by checks at every caller.
- **Value objects cross boundaries.** Services return `GatewayResult`, `QuizResult`, `SyncReport`, never loose dicts. (LangGraph state stays a `TypedDict` of JSON-safe data, because it is checkpointed.)
- **Exceptions are classes per failure**, named for what went wrong (`AllModelsFailed`, `MissingAPIKey`, `RepairFailed`), and owned by the module that raises them.
- **No hidden globals.** Module-level singletons like `MEDIA_GRAPH = build_media_graph()` are acceptable only for immutable, compiled artefacts; anything holding a client or state is injected.

## 2. Layers

```mermaid
flowchart TB
    subgraph Presentation["Presentation (thin adapters)"]
        V[DRF views + serializers]
        A[Django admin]
        M[Management commands]
        T[Celery tasks]
        N[Next.js pages, route handler]
    end
    subgraph Application["Application services"]
        LS[LessonService / QuizService]
        FR[FlowRunner]
        HS[HealthService]
        DS[DatabaseSyncer]
        RS[RegistrySerializer / DefaultRegistry]
    end
    subgraph Orchestration["Graph orchestration (LangGraph)"]
        GB[Graph builders]
        ND[Nodes + routers]
    end
    subgraph Domain["Domain"]
        DM[Django models + managers]
        SC[Pydantic schemas]
        QG[QuizGrader / RoutingPolicy]
        VA[Validators]
        NS[NodeSpecCatalog]
    end
    subgraph Infrastructure["Infrastructure adapters"]
        GW[Gateway → LangChain chat models]
        SB[SandboxRunner → node scripts]
        MS[MediaSources → Wikimedia, Openverse, Giphy]
        EP[RedisEventPublisher]
        RL[RateLimiter / RegistryResolver cache]
    end
    Presentation --> Application
    Application --> Orchestration
    Application --> Domain
    Orchestration --> Domain
    Orchestration -. "via Protocols in FlowContext" .-> Infrastructure
    Application -. "via Protocols" .-> Infrastructure
```

**Dependency rule:** arrows point down. Domain code imports nothing from presentation, orchestration, or infrastructure. Orchestration and services reach infrastructure only through Protocols, so every layer above infrastructure is testable with fakes.

## 3. Pattern catalogue

| Pattern | Where | Classes | Why here | Status |
|---|---|---|---|---|
| **Facade** | `llm_registry/gateway.py` | `Gateway` | One call (`invoke`) hides resolution, retries, fallback, rate limits, output parsing and logging from every node | ✅ |
| | `graph/media.py` | `MediaLibrary` | One object for search, download, sniffing and storage | ✅ |
| | flow execution | `FlowRunner` | Celery tasks and services run a graph segment without knowing LangGraph | ✅ |
| **Chain of Responsibility** | gateway | `ResolvedNode.chain` walked by `Gateway` | Each model in priority order handles the call or passes it on to the next fallback | ✅ |
| **Strategy** | gateway | `OutputAdapter` (`Structured…`, `Tools…`, `Text…`) | Output mode varies per node; the retry loop must not branch on it | ✅ |
| | gateway | `RetryPolicy` (`ExponentialBackoffPolicy`) | Which errors are retryable and how long to wait, swappable and testable | ✅ |
| | providers | `ProviderProfile` per provider kind | Allowed params, renames and reasoning kwargs differ per vendor | ✅ |
| | rate limits | `RateLimiter` (`CacheWindowRateLimiter`) | Gateway depends on "wait for room", not on Redis | ✅ |
| | probes | `CapabilityProbe` per capability | Each capability has its own check; `ModelProber` runs the declared ones | ✅ |
| | graph | `Validator` per artefact | Deterministic rules per output type, fed back as retry feedback | ✅ Stage A and study material · ◐ plan, page, test and interactive-plan validators are classes but not wired until Phase 5 |
| | graph | `RoutingPolicy` | Diagnostic score → route uses admin thresholds | ✅ |
| | media | `MediaSource` (`Wikimedia…`, `Openverse…`, `Giphy…`) | Sources are added or disabled by settings | ✅ |
| | health | `HealthCheck` (`Database…`, `Redis…`, `Celery…`) | Each dependency checked the same way | ✅ |
| **Composite** | health | `HealthService` aggregates `HealthCheck`s | Overall status = worst child status | ✅ |
| | graph | `CompositeValidator` | Deterministic validator + optional LLM reviewer (`diagnostic.review`) behave as one validator | ✅ |
| **Template Method** | graph | `Node`, `LLMNode`, `ValidateNode`, `PublishNode`, `AwaitNode` | Every LLM node follows prompt → gateway → state update; every publish/await pair keeps side effects out of the re-executed `await` | ✅ Stage A · ☐ later stages (Phases 4–6) |
| | prompts | `Prompt` (`system()`, `user()`, shared feedback and language blocks) | 15+ prompts share the same skeleton | ✅ |
| | accounts | `_PublicAuthView` | Auth views share permission, throttle and CSRF set-up | ✅ |
| | Django | `BaseCommand`, `AppConfig`, `ModelAdmin` (registry admins share the `StatusMarks` and `RegistryExportActions` mixins) | Framework-defined hooks | ✅ |
| **Builder** | graph | `FlowGraphBuilder`, `StudyMaterialGraphBuilder`, `RuntimeRepairGraphBuilder`, `MediaGraphBuilder`, `CodeFixLoopBuilder` | Graphs are assembled step by step (nodes, edges, conditional edges) then compiled | ✅ flow (Stage A) · ☐ the others (Phases 4–6) |
| | codegen | `DocumentAssembler` | The TSX document is built from page and component parts | ◐ (`codegen.py` functions) |
| **Factory** | providers | `ChatModelFactory` (`LangChainChatModelFactory`) | Builds a LangChain client from a `ResolvedModel`; tests inject a fake factory | ✅ |
| | graph | `default_context()` (composition root) | The one place concrete adapters are chosen | ✅ |
| **Registry** | specs | `NODE_SPECS`, a `NodeSpecCatalog` (read-only `Mapping`) | Node keys are discovered by the admin, migrations and checks | ✅ |
| | graph | `GraphRegistry` over `GRAPH_BUILDERS` | `GraphRun.graph` name → builder | ✅ |
| | providers | `ProviderProfiles` | Provider kind → `ProviderProfile` | ✅ |
| **Adapter** | sandbox | `SandboxRunner` | Wraps `node sandbox/scripts/*.mjs` subprocesses as Python methods | ✅ |
| | media | `MediaSource` implementations | Wrap each external search API to one shape | ◐ |
| | accounts | `CookieJWTAuthentication` | Adapts simplejwt to read the token from a cookie with CSRF | ✅ |
| | frontend | `app/api/[...path]/route.ts` | Remote proxy from Next.js to Django with forwarded headers | ✅ |
| **Observer** | Django signals | registry cache invalidation, `NodeConfig` sync on `post_migrate`, profile creation, media file deletion | Side effects follow saves without the saver knowing | ✅ |
| | progress | `EventPublisher` → Redis pub/sub → SSE `RunEventStream` | Nodes emit events; any number of browsers listen | ✅ |
| | gateway | `on_event` callback | Retries and fallbacks surface as progress events | ✅ |
| **Proxy (caching)** | resolver | `RegistryResolver` with cache-aside in Redis | Resolution is expensive; invalidated on every registry save | ✅ |
| **Repository** | Django managers | `UserManager`, `LessonQuerySet.owned_by(user)` | Ownership filtering lives in one place, so a forgotten filter can't leak lessons | ✅ |
| **Singleton** | settings | `FlowSettings.load()` | One editable settings row | ✅ |
| **Memento** | snapshots | `Lesson.config_snapshot`, `settings_snapshot`, `LessonVersion` | A lesson keeps the registry and code it was built with; repairs can roll back | ✅ / ☐ Phase 6 |
| **State** | lessons | `Lesson.advance_to(stage)` with `StageTransitions` | Only legal stage moves happen (`awaiting_diagnostic` → `generating_lesson`, never `ready` → `awaiting_diagnostic`) | ✅ |
| **Command** | execution | Celery task messages, LangGraph `Command(resume=…)`, `Send` | Work is captured as data, queued, retried and replayed from checkpoints | ✅ |
| **Value Object** | everywhere | `ResolvedModel`, `ResolvedNode`, `GatewayResult`, `SyncReport`, `ProbeResult`, `CheckResult`, `RenderReport`, Pydantic schemas | Immutable results that are safe to cache, snapshot and compare in tests | ✅ |
| **Dependency Injection** | everywhere | constructor parameters, `FlowContext` (LangGraph runtime context) | DIP; fakes in tests | ✅ (`FlowContext` fields are Protocols) |

## 4. Module designs

### 4.1 `accounts`

```mermaid
classDiagram
    direction LR
    class User {
        +UUID id
        +str email
        +str name
        +bool is_staff
        +clean()
    }
    class UserManager {
        +create_user(email, password, extra) User
        +create_superuser(email, password, extra) User
        +get_by_natural_key(email) User
    }
    class Profile {
        +str education_level
        +str learning_preference
        +str goal
        +is_complete() bool
    }
    class CookieJWTAuthentication {
        +authenticate(request) tuple
        -enforce_csrf(request)
    }
    class AuthCookies {
        +str ACCESS
        +str REFRESH
        +str SESSION
        +str ONBOARDED
        +set_session(response, access, refresh, onboarded)
        +set_onboarded(response, onboarded)
        +clear(response)
    }
    class PublicAuthView {
        <<abstract>>
        permission_classes
        throttle_scope
        +signed_in_response(user, status_code) Response
    }
    class RegisterView
    class LoginView
    class RefreshView
    class LogoutView
    class ProfileView
    class AuthRateThrottle
    class LoginAccountThrottle

    UserManager --> User : creates
    User "1" *-- "1" Profile
    PublicAuthView <|-- RegisterView
    PublicAuthView <|-- LoginView
    PublicAuthView <|-- RefreshView
    PublicAuthView <|-- LogoutView
    RegisterView ..> AuthCookies
    LoginView ..> AuthCookies
    RefreshView ..> AuthCookies
    LogoutView ..> AuthCookies
    ProfileView ..> AuthCookies
    LoginView ..> LoginAccountThrottle
    PublicAuthView ..> AuthRateThrottle
```

- `PublicAuthView` in the diagram is `_PublicAuthView` in code (module-private base).
- `Profile` is created by a `post_save` receiver (Observer) that only calls `Profile.objects.get_or_create`.
- `AuthCookies` (`cookies.py`) owns the cookie names, paths and flags; lifetimes and `Secure` come from settings unless injected. `CookieJWTAuthentication` and the OpenAPI scheme read `AuthCookies.ACCESS`.

### 4.2 `core` and `config`

```mermaid
classDiagram
    direction LR
    class HealthCheck {
        <<abstract>>
        +str name
        +run() CheckResult
        #probe()*
    }
    class DatabaseHealthCheck
    class RedisHealthCheck
    class CeleryHealthCheck
    class HealthService {
        -list~HealthCheck~ checks
        +report() HealthReport
    }
    class HealthReport {
        <<value>>
        +dict components
        +bool ok
        +str status
        +to_dict() dict
    }
    class CheckResult {
        <<value>>
        +str status
        +str detail
        +int latency_ms
    }
    class HealthView {
        +get(request) Response
    }
    class DatabaseSyncer {
        +str source
        +str target
        +sync() SyncReport
        -copy(model, result) list
        -models_in_dependency_order() list
        -reset_sequences(models)
    }
    class SyncReport {
        <<value>>
        +dict models
        +int inserted
    }
    class ModelResult {
        <<value>>
        +int inserted
        +int skipped
    }
    class DatabaseConfig {
        -env
        -int conn_max_age
        +local_url(host, port, name, user, password)$ str
        +build(local_url, supabase_url, testing) dict
    }

    HealthCheck <|-- DatabaseHealthCheck
    HealthCheck <|-- RedisHealthCheck
    HealthCheck <|-- CeleryHealthCheck
    HealthService o-- HealthCheck
    HealthCheck ..> CheckResult
    HealthService ..> HealthReport
    HealthReport *-- CheckResult
    HealthView --> HealthService
    DatabaseSyncer ..> SyncReport
    SyncReport *-- ModelResult
```

- `bootstrap` and `sync_to_supabase` commands call `DatabaseSyncer().sync()`.
- `DatabaseConfig` is used from `settings.py`, which stays a module.
- Framework hooks stay thin: the DRF `EXCEPTION_HANDLER` (`api_exception_handler`) runs DRF's handler and then `ApiErrorFormatter().format(...)` for the `{detail, code, fields?}` shape; the `check --deploy` hook returns `DeploySecurityChecks().errors()`.

### 4.3 `llm_registry`: registry and resolution

```mermaid
classDiagram
    direction LR
    class Provider {
        +str key
        +str kind
        +str api_key_env
        +int rpm_limit
        +has_api_key() bool
        +clean()
    }
    class LLMModel {
        +str name
        +dict default_params
        +str reasoning_control
        +int context_window
        +int max_output_tokens
        +capabilities() set~Capability~
        +clean()
    }
    class NodeConfig {
        +str node_key
        +str reasoning_effort
        +int max_attempts
        +spec() NodeSpec
        +clean()
    }
    class NodeModelBinding {
        +int priority
        +dict params_override
        +problems() list~str~
        +clean()
    }
    class ModelCall {
        +str node_key
        +str status
        +int latency_ms
        +Decimal cost
    }
    class NodeSpec {
        <<value>>
        +str key
        +Stage stage
        +OutputMode output
        +frozenset requires
        +int min_output_tokens
        +bool optional
    }
    class NodeSpecCatalog {
        <<Mapping>>
        +__getitem__(key) NodeSpec
        +required() list~NodeSpec~
        +optional() list~NodeSpec~
    }
    class RegistryResolver {
        -Cache cache
        -ProviderProfiles profiles
        -NodeSpecCatalog specs
        +resolve() dict~str, ResolvedNode~
        +snapshot() RegistrySnapshot
        +invalidate()
        -resolve_binding(node, binding) ResolvedModel
    }
    class RegistrySnapshot {
        <<value>>
        +int version
        +node(key) ResolvedNode
        +node_keys() list~str~
        +to_json() dict
        +from_json(data)$ RegistrySnapshot
    }
    class ResolvedNode {
        <<value>>
        +str node_key
        +bool enabled
        +OutputMode output
        +int max_attempts
        +int timeout_s
        +list~ResolvedModel~ chain
    }
    class ResolvedModel {
        <<value>>
        +str provider_kind
        +str model_name
        +dict params
        +dict reasoning
        +int max_retries
    }
    class ProviderProfile {
        <<abstract>>
        +str kind
        +str langchain_provider
        +frozenset allowed_params
        +bool needs_base_url
        +bool needs_api_key
        +bool supports_client_timeout
        +validate_params(params) list~str~
        +to_integration_kwargs(params) dict
        +reasoning_kwargs(control, effort) dict
        +apply_reasoning(control, effort, params, disables_sampling) tuple
        #_reasoning_kwargs(control, effort)* dict
    }
    class OpenAICompatibleProfile
    class OpenAIProfile
    class AnthropicProfile
    class GoogleGenAIProfile
    class GroqProfile
    class OllamaProfile
    class ProviderProfiles {
        +for_kind(kind) ProviderProfile
        +kinds() list~str~
    }
    class RegistrySerializer {
        +int FORMAT_VERSION
        +export() dict
        +load(data, replace_bindings) dict
    }
    class DefaultRegistry {
        +build() dict
    }

    Provider "1" *-- "many" LLMModel
    NodeConfig "1" *-- "many" NodeModelBinding
    LLMModel "1" o-- "many" NodeModelBinding
    NodeConfig ..> NodeSpecCatalog : spec()
    NodeModelBinding ..> ProviderProfiles : validates params
    RegistryResolver ..> NodeConfig : reads
    RegistryResolver ..> ProviderProfiles
    RegistryResolver ..> RegistrySnapshot : builds
    RegistrySnapshot *-- ResolvedNode
    ResolvedNode *-- ResolvedModel
    ProviderProfile <|-- OpenAIProfile
    OpenAIProfile <|-- OpenAICompatibleProfile
    OpenAIProfile <|-- GroqProfile
    ProviderProfile <|-- AnthropicProfile
    ProviderProfile <|-- GoogleGenAIProfile
    ProviderProfile <|-- OllamaProfile
    ProviderProfiles o-- ProviderProfile
    DefaultRegistry ..> RegistrySerializer : same JSON format
```

- `ProviderProfile` (`profiles.py`) holds everything that differs per vendor: allowed params and renames, whether a base URL or API key is needed, whether the client takes `timeout`, and reasoning translation. `OpenAICompatibleProfile` and `GroqProfile` subclass `OpenAIProfile`. `Provider.profile` returns the row's profile.
- Every save or delete of a registry row fires a receiver that calls `RegistryResolver().invalidate()` (Observer). A `post_migrate` receiver calls `NodeConfigSync().ensure()` (`node_configs.py`), which creates missing `NodeConfig` rows from `NODE_SPECS`.
- The `registry_check` system check is a thin hook over `RegistryHealth().warnings()`, one warning per kind of problem.

### 4.4 `llm_registry`: the gateway

```mermaid
classDiagram
    direction LR
    class LLMGateway {
        <<interface>>
        +invoke(node_key, messages, snapshot, schema, tools, lesson_id, run_id, on_event) GatewayResult
    }
    class Gateway {
        -ChatModelFactory chat_factory
        -RetryPolicy retry_policy
        -RateLimiter limiter
        -ModelCallRecorder recorder
        -OutputAdapters adapters
        +invoke(...) GatewayResult
        -try_model(call, model, index, messages) GatewayResult
    }
    class ChatModelFactory {
        <<interface>>
        +__call__(model, timeout_s) BaseChatModel
    }
    class LangChainChatModelFactory {
        -ProviderProfiles profiles
        +__call__(model, timeout_s) BaseChatModel
    }
    class OutputAdapter {
        <<abstract>>
        +OutputMode mode
        +check_request(node_key, schema, tools)
        +bind(chat, structured_output_method, schema, tools)* Runnable
        +interpret(reply)* Outcome
        +repair_messages(messages, outcome) list
    }
    class Outcome {
        <<value>>
        +bool ok
        +output
        +AIMessage message
        +str problem
    }
    class OutputAdapters {
        +for_mode(mode) OutputAdapter
    }
    class StructuredOutputAdapter {
        +repair_messages(messages, outcome) list
    }
    class ToolsOutputAdapter
    class TextOutputAdapter
    class RetryPolicy {
        <<interface>>
        +is_retryable(exc) bool
        +delay(attempt, exc) float
    }
    class ExponentialBackoffPolicy {
        +float base_s
        +float max_s
        +is_retryable(exc) bool
        +delay(attempt, exc) float
    }
    class RateLimiter {
        <<interface>>
        +acquire(limits) float
    }
    class CacheWindowRateLimiter {
        +int WINDOW_S
        +float max_wait_s
        -cache
        -sleep
        -clock
        +acquire(limits) float
        -try_take(scope, limit, now) float
    }
    class ModelCallRecorder {
        -Redactor redactor
        +record(node_key, model, attempt, status, latency_ms, error, message)
        +cost(model, input_tokens, output_tokens)$ float
    }
    class Redactor {
        +redact(text) str
    }
    class GatewayResult {
        <<value>>
        +output
        +raw
        +ResolvedModel model
        +int fallback_index
        +int attempt
    }
    class AllModelsFailed
    class NodeDisabled
    class MissingAPIKey

    LLMGateway <|.. Gateway
    Gateway o-- ChatModelFactory
    Gateway o-- RetryPolicy
    Gateway o-- RateLimiter
    Gateway o-- ModelCallRecorder
    Gateway o-- OutputAdapters
    OutputAdapters o-- OutputAdapter : by node.output
    OutputAdapter ..> Outcome
    Gateway ..> GatewayResult
    Gateway ..> AllModelsFailed : raises
    Gateway ..> NodeDisabled : raises
    ChatModelFactory <|.. LangChainChatModelFactory
    LangChainChatModelFactory ..> ProviderProfiles
    LangChainChatModelFactory ..> MissingAPIKey : raises
    OutputAdapter <|-- StructuredOutputAdapter
    OutputAdapter <|-- ToolsOutputAdapter
    OutputAdapter <|-- TextOutputAdapter
    RetryPolicy <|.. ExponentialBackoffPolicy
    RateLimiter <|.. CacheWindowRateLimiter
    ModelCallRecorder --> Redactor
```

```mermaid
sequenceDiagram
    participant N as LLMNode
    participant G as Gateway
    participant S as RegistrySnapshot
    participant F as ChatModelFactory
    participant L as RateLimiter
    participant O as OutputAdapter
    participant R as ModelCallRecorder
    N->>G: invoke(node_key, messages, snapshot, schema)
    G->>S: node(node_key)
    loop each model in chain (Chain of Responsibility)
        G->>F: build(model, timeout)
        G->>O: bind(chat, schema, tools)
        loop attempt ≤ max_retries (+1 schema repair)
            G->>L: acquire(provider and model limits)
            G->>O: interpret(runnable.invoke(messages))
            G->>R: record(status, latency, tokens)
            alt ok
                G-->>N: GatewayResult
            else retryable
                G->>G: sleep(RetryPolicy.delay)
            else invalid output, first time
                G->>O: repair_messages(...)
            else fatal or exhausted
                G->>G: next model (on_event fallback_model)
            end
        end
    end
    G-->>N: raise AllModelsFailed
```

### 4.5 `llm_registry`: probes

```mermaid
classDiagram
    direction LR
    class ModelProber {
        -ChatModelFactory chat_factory
        -list~CapabilityProbe~ probes
        -int timeout_s
        +probe(llm_model) list~ProbeResult~
    }
    class ProbeTarget {
        <<value>>
        +llm_model
        +chat
        +chat_at(effort)
    }
    class CapabilityProbe {
        <<abstract>>
        +str capability
        +applies_to(llm_model) bool
        +run(target) ProbeResult
        #check(target)* str
    }
    class TextProbe
    class StructuredOutputProbe
    class ToolCallingProbe
    class VisionProbe {
        +solid_png(rgb, size)$ bytes
    }
    class ReasoningProbe
    class ProbeResult {
        <<value>>
        +str capability
        +bool ok
        +int latency_ms
        +str detail
    }
    ModelProber o-- CapabilityProbe
    CapabilityProbe <|-- TextProbe
    CapabilityProbe ..> ProbeTarget
    CapabilityProbe <|-- StructuredOutputProbe
    CapabilityProbe <|-- ToolCallingProbe
    CapabilityProbe <|-- VisionProbe
    CapabilityProbe <|-- ReasoningProbe
    CapabilityProbe ..> ProbeResult
```

The admin **Test model** action and `manage.py probe_models` both call `ModelProber().probe(model)`.

### 4.6 `lessons`: domain and services

```mermaid
classDiagram
    direction LR
    class Lesson {
        +UUID id
        +User owner
        +str topic
        +Stage stage
        +Route route
        +dict config_snapshot
        +dict settings_snapshot
        +int code_version
        +advance_to(stage)
        +fail(error)
    }
    class LessonQuerySet {
        +owned_by(user) LessonQuerySet
        +active() LessonQuerySet
    }
    class StageTransitions {
        +allowed(from_stage, to_stage) bool
    }
    class Quiz {
        +str kind
        +list questions
        +public_questions() list
    }
    class QuizAttempt {
        +dict answers
        +dict result
    }
    class StudyMaterial {
        +str kind
        +dict content
    }
    class MediaAsset {
        +str spec_id
        +str kind
        +str source
        +str license
        +bool verified
    }
    class LessonVersion {
        +int code_version
        +str code
    }
    class GraphRun {
        +str graph
        +str trigger
        +str status
        +dict node_status
        +is_active() bool
    }
    class FlowSettings {
        <<singleton>>
        +load()$ FlowSettings
        +snapshot() dict
    }
    class LessonService {
        -FlowRunner runner
        -RegistryResolver resolver
        +create(user, topic, user_context) tuple
        +retry(lesson) GraphRun
        +delete(lesson)
    }
    class QuizService {
        -QuizGrader grader
        -FlowRunner runner
        +for_learner(lesson, kind) dict
        +submit(lesson, kind, answers) tuple
        +review(lesson, kind) dict
    }
    class LessonDocumentBuilder {
        -MediaUrlSigner signer
        +build(lesson) dict
    }
    class MediaUrlSigner {
        +sign(asset_id, expires_at) str
        +verify(asset_id, exp, sig) bool
    }

    Lesson ..> StageTransitions
    Lesson "1" *-- "0..2" Quiz
    Quiz "1" *-- "0..1" QuizAttempt
    Lesson "1" *-- "many" StudyMaterial
    Lesson "1" *-- "many" MediaAsset
    Lesson "1" *-- "many" LessonVersion
    Lesson "1" *-- "many" GraphRun
    LessonQuerySet ..> Lesson
    LessonService ..> Lesson
    LessonService ..> FlowSettings : snapshot
    QuizService ..> Quiz
    QuizService ..> QuizAttempt
    LessonDocumentBuilder --> MediaUrlSigner
    LessonDocumentBuilder ..> Lesson
```

- Views are thin: `LessonViewSet` calls `LessonService` / `QuizService` and serializes the result. Every queryset in a view starts from `Lesson.objects.owned_by(request.user)`, so another user's lesson is a `404`.
- `Quiz.public_questions()` is the only way questions leave the server before submission (answers stripped).

### 4.7 `graph`: nodes, routers and builders

```mermaid
classDiagram
    direction TB
    class FlowContext {
        +str run_id
        +LLMGateway gateway
        +CodeSandbox sandbox
        +MediaProvider media
        +EventSink events
    }
    class Node {
        <<abstract>>
        +str name
        +__call__(state, runtime) dict
        #run(state, ctx)* dict
    }
    class LLMNode {
        <<abstract>>
        +str node_key
        +Prompt prompt
        +type schema
        #run(state, ctx) dict
        #to_state(result, state)* dict
    }
    class ValidateNode {
        <<abstract>>
        +Validator validator
        +str retry_node
        #run(state, ctx) dict
    }
    class PublishNode {
        <<abstract>>
        #publish(state, ctx)* dict
    }
    class AwaitNode {
        +str kind
        +__call__(state) dict
    }
    class JoinNode {
        <<abstract>>
    }
    class Router {
        <<abstract>>
        +__call__(state) str
    }
    class CheckRouter {
        +str ok
        +str retry
        +str fail
    }
    class LevelRouter {
        -RoutingPolicy policy
    }
    class AlignmentRouter
    class SendFanOut {
        <<abstract>>
        +__call__(state) list~Send~
    }
    class GenerateDiagnosticNode
    class AssessLearnerNode
    class PlanLessonNode
    class WritePageNode
    class AlignmentJudgeNode
    class CompilePageNode
    class PublishDiagnosticNode
    class GraphBuilder {
        <<abstract>>
        +build(checkpointer) CompiledGraph
        #add_nodes(graph)*
        #add_edges(graph)*
    }
    class FlowGraphBuilder
    class StudyMaterialGraphBuilder
    class RuntimeRepairGraphBuilder
    class MediaGraphBuilder
    class CodeFixLoopBuilder
    class GraphRegistry {
        +builder(name) GraphBuilder
    }

    Node <|-- LLMNode
    Node <|-- ValidateNode
    Node <|-- PublishNode
    Node <|-- JoinNode
    LLMNode <|-- GenerateDiagnosticNode
    LLMNode <|-- AssessLearnerNode
    LLMNode <|-- PlanLessonNode
    LLMNode <|-- WritePageNode
    LLMNode <|-- AlignmentJudgeNode
    LLMNode <|-- CompilePageNode
    PublishNode <|-- PublishDiagnosticNode
    Router <|-- CheckRouter
    Router <|-- LevelRouter
    Router <|-- AlignmentRouter
    Node ..> FlowContext
    GraphBuilder <|-- FlowGraphBuilder
    GraphBuilder <|-- StudyMaterialGraphBuilder
    GraphBuilder <|-- RuntimeRepairGraphBuilder
    GraphBuilder <|-- MediaGraphBuilder
    GraphBuilder <|-- CodeFixLoopBuilder
    GraphBuilder o-- Node
    GraphBuilder o-- Router
    GraphBuilder o-- SendFanOut
    GraphRegistry o-- GraphBuilder
```

- **Segments.** `FlowGraphBuilder` assembles the lesson flow from `Segment`s (diagnose, mastery, author, build) plus the failure segment (`mark_failed` → `await_retry`). A segment adds its nodes and edges and is told where its exits (`lesson`, `mastery`, `failed`) lead; a segment can `provide` an exit for the others (the author segment provides `lesson`). Exits nobody provides lead to `END`, so Stage A works on its own and later stages plug in.
- **Node instances are the callables LangGraph registers** (`graph.add_node("plan_lesson", PlanLessonNode())`). `Node.__call__` unpacks `runtime.context`, calls `run`, and emits `node_started` / `retrying` / `degraded` events, so subclasses contain only their own logic.
- **`PublishNode` / `AwaitNode` pairing** encodes the rule from [lesson-graph.md](lesson-graph.md): side effects go in `publish`; `AwaitNode` only calls `interrupt()`, because it re-executes on resume.
- `FlowContext` fields are typed with Protocols (`LLMGateway`, `CodeSandbox`, `EventSink`; `MediaProvider` joins in Phase 5); `default_context()` is the composition root. `NodeBudget.of(state, node_key)` reads a node's attempts and whether it is enabled from the lesson's registry snapshot.
- A node declares the `stage` the lesson is in while it works; running while the lesson is `failed` moves it back, which is how Retry resumes without the nodes knowing about retries. A node also closes its worker thread's database connection when it ends.
- State stays a `TypedDict` (`FlowState`, `Branch`, `MediaState`, `FixState`, `RepairState`); reducers are static methods on `Reducers`.

### 4.8 `graph`: domain logic (grading, validation, prompts, codegen)

```mermaid
classDiagram
    direction LR
    class QuizGrader {
        +check_answers(questions, answers) dict
        +grade(questions, answers) QuizResult
        -consistent(by_band) bool
    }
    class RoutingPolicy {
        +route_for(result, settings) Route
        +prerequisites_to_cover(prerequisites, questions, result) list
    }
    class Validator {
        <<interface>>
        +validate(subject, settings) list~str~
    }
    class DiagnosticValidator
    class PlanValidator
    class PageValidator
    class FinalTestValidator
    class InteractivePlanValidator
    class StudyMaterialValidator
    class CompositeValidator {
        +list~Validator~ parts
    }
    class LatexChecker {
        <<interface>>
        +latex(expressions) list~str~
    }
    class AssessmentGuard {
        +apply(assessment, prerequisites_to_cover) dict
    }
    class Prompt {
        <<abstract>>
        +messages(state, feedback) list~BaseMessage~
        #system(state)* str
        #user(state)* str
        #feedback_block(feedback) str
        #language_rule(profile) str
    }
    class DiagnosticPrompt
    class PlanLessonPrompt
    class WritePagePrompt
    class CompilePagePrompt
    class RepairCodePrompt
    class DocumentAssembler {
        +template_page(key, placements) str
        +test_page() str
        +assemble(components, pages) str
    }
    class CodeSanitizer {
        +sanitize(code) str
    }

    Validator <|.. DiagnosticValidator
    Validator <|.. PlanValidator
    Validator <|.. PageValidator
    Validator <|.. FinalTestValidator
    Validator <|.. InteractivePlanValidator
    Validator <|.. StudyMaterialValidator
    Validator <|.. CompositeValidator
    CompositeValidator o-- Validator
    DiagnosticValidator ..> LatexChecker
    PageValidator ..> LatexChecker
    FinalTestValidator ..> LatexChecker
    StudyMaterialValidator ..> LatexChecker
    Prompt <|-- DiagnosticPrompt
    Prompt <|-- PlanLessonPrompt
    Prompt <|-- WritePagePrompt
    Prompt <|-- CompilePagePrompt
    Prompt <|-- RepairCodePrompt
    DocumentAssembler --> CodeSanitizer
```

- `QuizGrader` is shared by `QuizService` (synchronous grading in the request) and the `grade_*` nodes, so both always agree.
- Validators are pure: no ORM, no network. They depend only on `LatexChecker` (implemented by `SandboxRunner`, faked in tests).
- `Prompt` subclasses hold no state between calls; one class per node key in `graph/prompts/`.

### 4.9 `graph`: media and sandbox adapters

```mermaid
classDiagram
    direction LR
    class MediaProvider {
        <<interface>>
        +tools(session, sources) list~StructuredTool~
        +download(session, url) Download
        +store(lesson_id, content, extension) StoredFile
    }
    class MediaLibrary {
        -dict~str, MediaSource~ sources
        -MediaDownloader downloader
        -MediaStorage storage
    }
    class MediaSource {
        <<interface>>
        +str key
        +search(session, query, media_type) list~MediaCandidate~
    }
    class WikimediaSource
    class OpenverseSource
    class GiphySource
    class MediaDownloader {
        +download(session, url) Download
        -sniff(content) str
        -check_url(url)
    }
    class LicensePolicy {
        +normalise(raw) str
        +allowed(license, settings) bool
    }
    class MediaSession {
        +dict seen
    }
    class CodeSandbox {
        <<interface>>
        +check_code(code, contract, required) CheckResult
        +latex(expressions) list~str~
        +render_check(code, data, pages, media_files) RenderReport
    }
    class SandboxRunner {
        -Path sandbox_dir
        -str node
        +available() bool
        -run(script, payload, timeout_s) dict
    }
    class RenderReport {
        <<value>>
        +bool ok
        +dict errors_by_page
    }

    MediaProvider <|.. MediaLibrary
    MediaLibrary o-- MediaSource
    MediaLibrary o-- MediaDownloader
    MediaSource <|.. WikimediaSource
    MediaSource <|.. OpenverseSource
    MediaSource <|.. GiphySource
    WikimediaSource ..> LicensePolicy
    OpenverseSource ..> LicensePolicy
    MediaSource ..> MediaSession
    CodeSandbox <|.. SandboxRunner
    LatexChecker <|.. SandboxRunner
    SandboxRunner ..> RenderReport
```

All external I/O goes through one injected `httpx.Client`; tests use `httpx.MockTransport`.

### 4.10 Flow execution and progress (Phase 3)

```mermaid
classDiagram
    direction LR
    class FlowRunner {
        -GraphRegistry graphs
        -CheckpointerFactory checkpointers
        -EventPublisher events
        +execute(run_id) GraphRun
        -stream(run) dict
        -input(graph, run, config)
    }
    class EventPublisher {
        <<interface>>
        +publish(run_id, event)
    }
    class RedisEventPublisher
    class RunEventStream {
        +events(run_id) Iterator~str~
    }
    class RunEventsView {
        +get(request, run_id) StreamingHttpResponse
    }
    class GraphRunRecorder {
        +node_status(run, node, status)
        +finish(run, status, error)
    }
    class CheckpointerFactory {
        +conninfo() str
        +saver() PostgresSaver
        +setup()
    }
    class RunLock
    class FailureMessage
    class RunEventTranslator
    class RunSnapshot
    FlowRunner --> GraphRegistry
    FlowRunner --> CheckpointerFactory
    FlowRunner --> EventPublisher
    FlowRunner --> GraphRunRecorder
    FlowRunner --> RunLock
    FlowRunner --> FailureMessage
    FlowRunner --> RunEventTranslator
    RunEventsView ..> RunSnapshot
    EventPublisher <|.. RedisEventPublisher
    RunEventsView --> RunEventStream
```

```mermaid
sequenceDiagram
    participant B as Browser
    participant V as QuizAttemptView
    participant Q as QuizService
    participant C as Celery resume_flow
    participant R as FlowRunner
    participant P as RedisEventPublisher
    B->>V: POST /lessons/{id}/quizzes/diagnostic/attempt
    V->>Q: submit(lesson, kind, answers)
    Q->>Q: QuizGrader.grade → QuizAttempt
    Q->>Q: GraphRun(trigger, payload={resume: attempt_id})
    Q->>C: enqueue(run)
    V-->>B: 202 {result, run_id}
    C->>R: execute(run_id)
    R->>R: graph.stream(Command(resume=attempt_id))
    R->>P: publish(run_id, node / awaiting_input / done)
    P-->>B: SSE via RunEventStream
```

### 4.11 Frontend (`frontend/lib`)

```mermaid
classDiagram
    direction LR
    class ApiClient {
        -Fetch fetcher
        -readCookie(name) str
        -Promise refreshing
        +request(path, options) Promise~T~
        +refreshSession() Promise~bool~
        -csrfToken() Promise~str~
        -toApiError(response) Promise~ApiError~
    }
    class ApiError {
        +int status
        +str code
        +FieldErrors fields
    }
    class RunEventStream {
        +constructor(runId, onEvent)
        +close()
    }
    class SandboxMessages {
        +parse(data)$ SandboxMessage
        +from(event, frame)$ SandboxMessage
    }
    class HarnessBuilder {
        +html(template) str
        +absolute(document) LessonDocument
    }
    class RepairGate {
        +shouldRepair(error, currentVersion) bool
        +stop()
    }
    class RedirectPolicy {
        +safeNext(value)$ str
    }
    ApiClient ..> ApiError : throws
```

- Components call the shared `apiClient` instance (`apiClient.request<T>(path, options)`), so concurrent 401s share one refresh. `fetch` and the cookie reader are constructor parameters, so `lib/api.test.ts` drives the client with a scripted fake `fetch`.
- `useRunEvents`, `useProfile` and the `LessonSandbox` component are hooks/components that own one instance of these classes.
- `SandboxMessages.from` accepts only messages whose `event.source` is the embedded iframe and gives every field a safe type; `HarnessBuilder` fills the harness with absolute addresses (the iframe's origin is opaque); `RepairGate` asks for a repair once per code version and stops when the server refuses; `HarnessSource` fetches the harness once; `RenderMessage` and `RepairReport` shape what is posted to the iframe and to `/repair`; `LessonPdf` prints the reading pages.

Where the pieces live: `lessons/runner.py` (`FlowRunner`, `GraphRunRecorder`, `RunLock`, `FailureMessage`), `lessons/events.py` (`RunEvent`, `RunEventTranslator`, `RedisEventPublisher`, `RunEventStream`, `RunSnapshot`), `lessons/checkpoints.py`, `lessons/tasks.py` (the tasks, `CeleryTaskQueue`, and `InlineTaskQueue` for the `flow` command), `lessons/services.py` (`LessonService`, `QuizService`, `RunDispatcher` over the `TaskQueue` port, chosen by `LESSON_TASK_QUEUE`), `lessons/reports.py`. Domain failures are `APIException`s in `lessons/errors.py`, so the API formats them itself.

### 4.12 Stage C and runtime repair (Phase 6)

```mermaid
classDiagram
    direction LR
    class Node {
        <<abstract>>
        +__call__(state, runtime)
        #run(state, ctx)*
    }
    class CodeFixer {
        +fix(ctx, data, code, contract, required, components, asset_ids) tuple
    }
    class CodeFixLoopBuilder
    class CompilePageNode
    class AssembleDocumentNode
    class RenderCheckNode
    class RepairPageNode
    class RepairComponentNode
    class PersistLessonNode
    class RenderPolicy {
        +decide(report, state, round_number) RenderVerdict
    }
    class PageParts {
        +of(data, key)$ tuple
        +component_code(state)$ dict
    }
    class LoadRepairNode
    class RepairRuntimeNode
    class AssembleRepairedNode
    class RegressionCheckNode
    class VerifyRepairNode
    class SaveRepairNode
    class RepairTargetLocator {
        +locate(error, parts) RepairTarget
    }
    class RegressionCheck {
        +problems(before, after, pages) list~str~
    }
    class CodeSignature {
        +of(code, section_ids)$ frozenset
    }
    class RuntimeRepairGraphBuilder
    class CodeService {
        +document(lesson) dict
        +request_repair(lesson, error, code_version) GraphRun
        +versions(lesson) QuerySet
        +restore(lesson, number) Lesson
    }

    Node <|-- CompilePageNode
    Node <|-- AssembleDocumentNode
    Node <|-- RenderCheckNode
    Node <|-- RepairPageNode
    Node <|-- RepairComponentNode
    Node <|-- PersistLessonNode
    Node <|-- LoadRepairNode
    Node <|-- RepairRuntimeNode
    Node <|-- AssembleRepairedNode
    Node <|-- RegressionCheckNode
    Node <|-- VerifyRepairNode
    Node <|-- SaveRepairNode
    CompilePageNode o-- CodeFixer
    RepairPageNode o-- CodeFixer
    RepairComponentNode o-- CodeFixer
    RepairRuntimeNode o-- CodeFixer
    CodeFixer --> CodeFixLoopBuilder
    RenderCheckNode o-- RenderPolicy
    RenderPolicy ..> PageParts
    LoadRepairNode o-- RepairTargetLocator
    RegressionCheckNode o-- RegressionCheck
    RegressionCheck ..> CodeSignature
    RuntimeRepairGraphBuilder o-- LoadRepairNode
    CodeService ..> RuntimeRepairGraphBuilder : queues a run
```

- **Template Method** again: every node is a `Node` subclass with its own `run`. `CodeFixer` is a small facade over the code-fix subgraph, injected into the nodes that need it so tests can replace it.
- **Strategy**: `RenderPolicy` decides what to do with a render report (pass, repair, fall back, fail) from the report and the round; the node only carries the decision out.
- `RepairTargetLocator`, `RegressionCheck` and `CodeSignature` are pure: no ORM, no network, no sandbox.
- `CodeService` owns the lesson's code use cases (serve, request a repair, list versions, restore); views stay thin.

## 5. How to extend

| You are adding | Do this |
|---|---|
| An LLM step | `NodeSpec` in `node_specs.py` → `Prompt` subclass → `LLMNode` subclass (+ `Validator` and `ValidateNode` if its output has rules) → register in the graph builder → `migrate` → bind models. Tests first for the validator and the node with `FakeGateway`. |
| A provider kind | `ProviderProfile` subclass, registered in `ProviderProfiles`; a test that builds the real client offline (`tests/llm_registry/test_providers.py`). |
| A media source | `MediaSource` implementation, a `FlowSettings.media_sources` value, tests with `httpx.MockTransport`. |
| A health dependency | `HealthCheck` subclass, added to `HealthService`'s default list. |
| A lesson stage | `Stage` value, `StageTransitions` entries, a frontend view for it, and the stage table in [data-model.md](data-model.md). |
| An endpoint | Thin view with `@extend_schema` → service method → domain objects. |

## Refactor backlog

Code written before this document that doesn't follow it yet. Behaviour must not change in a refactor: tests stay green before and after, and only imports and names in tests change. Tick items off here as they land.

Every phase 0–2 item is done. The rows still open describe the work-in-progress lesson-flow code (`graph/`, `lessons/`), which is kept on the `phase-3/lesson-flow` branch rather than in `main`. It is brought in line with this design, with tests, as Phase 3 lands.

| Module | Today | Target | Do it |
|---|---|---|---|
| ~~`llm_registry/params.py`, `reasoning.py`~~ | ~~dict tables and `if kind ==`~~ | `ProviderProfile` per kind + `ProviderProfiles` (`profiles.py`) | ✅ Done |
| ~~`llm_registry/gateway.py`~~ | ~~`is_retryable`, `backoff_delay`, `_record`, `if node.output ==`~~ | `ExponentialBackoffPolicy` (`retry.py`), `ModelCallRecorder` (`recorder.py`), `OutputAdapter`s (`outputs.py`), `LangChainChatModelFactory` (`providers.py`) | ✅ Done |
| ~~`llm_registry/ratelimit.py`~~ | ~~`acquire()` function~~ | `RateLimiter` Protocol + `CacheWindowRateLimiter` | ✅ Done |
| ~~`llm_registry/resolver.py`~~ | ~~module functions~~ | `RegistryResolver`, `RegistrySnapshot` | ✅ Done |
| ~~`llm_registry/probes.py`~~ | ~~`probe_model()`~~ | `ModelProber` + `CapabilityProbe`s | ✅ Done |
| ~~`llm_registry/serialization.py`, `seed.py`~~ | ~~functions~~ | `RegistrySerializer` (`export` / `load`), `DefaultRegistry` | ✅ Done |
| ~~`llm_registry/node_specs.py`~~ | ~~dict + `get_spec()`~~ | `NodeSpecCatalog` (`NODE_SPECS[key]`) | ✅ Done |
| ~~`llm_registry/redaction.py`~~ | ~~`redact()`~~ | `Redactor` + the stateless `REDACTOR` default | ✅ Done |
| ~~`core/views.py`~~ | ~~`_database`, `_redis`, `_celery`~~ | `HealthCheck`s + `HealthService` (`core/health.py`) | ✅ Done |
| ~~`core/sync.py`~~ | ~~`sync_databases()`~~ | `DatabaseSyncer(source, target).sync()` | ✅ Done |
| ~~`config/databases.py`~~ | ~~functions~~ | `DatabaseConfig(env).build(...)`, `DatabaseConfig.local_url(...)` | ✅ Done |
| ~~`accounts/cookies.py`~~ | ~~functions~~ | `AuthCookies`; `_signed_in_response` → `_PublicAuthView.signed_in_response` | ✅ Done |
| ~~`graph/grading.py`~~ | ~~functions~~ | `QuizGrader`, `RoutingPolicy` | ✅ Done |
| ~~`graph/validators.py`~~ | ~~`validate_*` functions~~ | `Validator` classes, `AssessmentGuard` (`graph/validators/`) | ✅ Done (tests for the study, plan, page, test and interactive-plan validators come with Phases 4–5) |
| ~~`graph/prompts.py`~~ | ~~functions in one 470-line module~~ | `graph/prompts/` package, one `Prompt` subclass per node | ✅ Done |
| ~~`graph/nodes/*.py`~~ | ~~functions~~ | `Node` and `Router` subclasses: Stage A, the mastery path, Stage B, the media agent, Stage C (`build.py`, `build_routers.py`) and the runtime repair (`repair.py`) | ✅ Done |
| ~~`graph/builders.py`, `graph/registry.py`~~ | ~~functions~~ | `FlowGraphBuilder` (diagnose, mastery, author, build and failure segments), `StudyMaterialGraphBuilder`, `MediaGraphBuilder`, `CodeFixLoopBuilder`, `RuntimeRepairGraphBuilder`; `GraphRegistry` | ✅ Done |
| ~~`graph/context.py`~~ | ~~`Any`-typed fields, `emit`/`warn`/`llm` functions~~ | Protocol-typed `FlowContext`, `EventSink` | ✅ Done |
| ~~`graph/codegen.py`~~ | ~~page/test templates and `assemble` as functions~~ | `DocumentAssembler`, `CodeSanitizer` (`graph/sanitizer.py`) | ✅ Done |
| ~~`graph/media.py`~~ | ~~search methods on `MediaLibrary`~~ | `graph/media/`: `MediaSource` classes, `MediaDownloader` behind a `UrlGuard`, `LicensePolicy`, `MediaStorage`, `MediaLibrary` facade | ✅ Done |
| ~~`lessons/document.py`~~ | ~~functions~~ | `LessonSource`, `LessonData`, `LessonDocumentBuilder`, with `MediaUrlSigner` (`lessons/media_urls.py`) | ✅ Done |
| ~~`frontend/lib/api.ts`~~ | ~~module functions + `ApiError`~~ | `ApiClient` + the shared `apiClient` instance | ✅ Done |
| ~~`frontend/lib/safe-redirect.ts`~~ | ~~`safeNext()`~~ | `RedirectPolicy.safeNext` | ✅ Done |
