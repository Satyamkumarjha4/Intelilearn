# Model strategy: research and design

**Status:** design only, no code changed. Written 2026-11-15 on branch `docs/model-strategy`.
**Supersedes:** the "lean profile" proposal on `chore/model-costs` (not applied here). That branch's price book (`backend/llm_registry/prices.py`) is not reused: every price below was re-read from the providers' own pages today.
**Scope:** Gemini, OpenAI, Anthropic and Groq text models; every LLM node in `llm_registry/node_specs.py`; a tier rule, a fallback chain, an optimisation list and a cost model per node; the adapter design; the test and rollout plan.

## How to read this document

- **Sources.** Every provider fact carries a source key such as `[GP]`. The key table in Appendix A gives the URL and the date it was read. **All pages were read on 2026-11-15.** Nothing comes from memory.
- **"(unverified)"** marks anything a page did not print, a fact that was only available through the fetch tool's summary of a long page (marked "summary"), or something two pages disagreed on. The full list is in Appendix B.
- **Blocked domains.** `ai.google.dev` refused the fetcher ("Unable to verify if domain ai.google.dev is safe to fetch"). Its pages redirect (HTTP 301) to the same paths on `aistudio.google.com`, which did read, so the Gemini facts are complete except where Appendix B says otherwise. The old `docs.anthropic.com` sub-pages failed with no output, but the same pages on `platform.claude.com` read. **Nothing is blocked that needs your action**, except the one item in decision 3 (Groq's free-plan limits table, which needs a console login).
- **Estimates.** Token counts per node come from the live `ModelCall` log where it has rows, and from reading the prompts where it does not (marked "est."). The cost model is therefore good to about ±40%, and its ranking of options is more reliable than its absolute rupees. All rupee figures use **₹90 per US dollar**, which is an assumption (no official source): one rupee of change moves every figure by about 1.1%.
- **The prices in your brief are the doubled ones** (₹98 / ₹398 / ₹558). The branch `chore/pricing-2x` now carries the tripled ones (₹147 / ₹597 / ₹837, commit `897854f`). Section 3.4 shows revenue at both. Decision 1 asks which applies.

## 0. What the code and the live data already say

These findings shape everything below, so they come first.

1. **The registry's lead model is not on any current Google page.** `gemini-3.5-flash` leads or backs up 17 of the 19 nodes in `llm_registry/seed.py`. It appears on none of Google's models, pricing or rate-limits pages `[GM][GP][GR]`; only `gemini-3.5-flash-lite` does. Of the 532 recorded attempts (2026-10-24 to 2026-11-15, 20 lessons), **221 were a 429 RESOURCE_EXHAUSTED on `gemini-3.5-flash`**, and 30 were "503 high demand". Each node then fell through to Flash-Lite, which succeeded on 100% of its calls for pages, tests, interactives and the judge. Its price is also unknown, so its cost could never be recorded.
2. **Gemini cost is never recorded.** `LLMModel.input_cost_per_mtok` is empty for every Gemini model in the dev database, so `ModelCall.cost` is null for every Gemini call. Only the two Groq models have prices.
3. **Groq's strict structured output is never requested.** `langchain-groq` supports `strict=True` for `openai/gpt-oss-20b` and `openai/gpt-oss-120b` (constrained decoding), and Groq says it "never errors or produces invalid JSON" `[QS]`. The gateway calls `with_structured_output(method="json_schema")` with no `strict`, which is Groq's best-effort mode ("valid JSON, but schema adherence not guaranteed" `[QS]`). The live log shows the effect: `learner.assess` on gpt-oss-20b was **invalid 9 times in 14 attempts** (the model echoed the schema back), and `diagnostic.generate` on 20b and 120b had 8 invalid outputs and 11 "Failed to generate JSON" 400s in 60 attempts.
4. **A graph retry always restarts at layer 1.** `ValidateNode` sends the node back and `Gateway.invoke` walks the chain from the top, so a validation failure re-pays the cheapest model again instead of escalating. `diagnostic.generate` averaged **2.3 successful calls per lesson** (max 10), and `page.generate` 4.0 against 3 needed.
5. **Two LLM steps are mechanical.** `page.compile` ("read the content from `LESSON.pages.<key>` and render it; never retype or change the text") already has a template fallback (`DocumentAssembler`, "the broken pages fall back to the template layout"). `media.search` runs a tool-calling agent for **8.8 successful calls per lesson** to turn a 2 to 5 word `media_query` (already written by `interactive.plan`) into a search request.
6. **Provider quirks the current adapters get wrong** (details in 3.5): Anthropic now rejects `temperature`, `top_p` and `top_k` with a 400 from API version 2026-10-21 `[AD][AT]`, and `AnthropicProfile` allows them; Claude 5.x models do not accept `budget_tokens` and some cannot turn thinking off `[AT]`; Gemini 3.8 Flash and the Gemini 4 models reject `minimal` `[GMx]`; OpenAI Chat Completions function calling with `gpt-6-luna` works only at effort `none` `[OM]`.
7. **Cheap models are no longer only Google's and Groq's.** `gpt-6-luna` ($0.10 / $0.50) and Claude Haiku 5.5 ($0.10 / $0.50 up to 100K prompt tokens) cost the same as, or less than, Gemini Flash-Lite and sit in tier T1 `[OP][AP]`. "Not OpenAI or Anthropic premium" is therefore a rule about tier, not vendor. They need keys you do not have yet, so they are used only as a last layer and are starred (`*`) in the tables.
8. **Prices move on dates inside the planning window.** Gemini 3.6 Flash and 3.8 Flash double on 2027-01-01; Gemini 4 Argon and Carbon double on 2026-12-01 `[GP]`; `gemini-2.5-flash` and `-pro` stop on 2026-12-01 (rerouted) `[GM]`; Claude Sonnet 4.5 retires "not sooner than" 2026-11-30 `[AD]`; `gpt-5`, `gpt-5-mini`, `gpt-5-nano`, `o3` stop on 2026-12-11 `[OD]`. Groq's `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` have already been shut down (2026-08-16) `[QD]`, which is why the dev log shows `llama-3.3-70b-versatile` returning 404.

---

## Part 1. Provider and model catalogue

Capability tiers used throughout: **T0** tiny/cheapest, **T1** cheap, **T2** mid, **T3** strong, **T4** premium. A model's tier is set by its price and its stated class, not by a quality benchmark (no benchmark source was read); quality is decided by the golden runs in Part 3.6.

Prices are US dollars per 1M tokens. "Cached" is the cached-input price. Reasoning (thinking) tokens are billed as output tokens at every provider, and the usage numbers include them (Gemini `[GT]`: "response pricing is the sum of output tokens and thinking tokens"; Anthropic `[AT]`; OpenAI `[OR]`; Groq's page does not say (unverified), but the live log shows `output_tokens` greater than `reasoning_tokens` on Groq and Gemini rows, which is consistent).

### 1.1 Gemini (read via `aistudio.google.com`, the redirect target of `ai.google.dev`)

Sources: models `[GM]`, per-model pages `[GMx]`, pricing `[GP]`, rate limits `[GR]`, thinking `[GT]`, structured output `[GS]`, caching `[GC]`, batch `[GB]`, billing `[GBL]`, terms `[GTe]`, regions `[GRg]`.

All twelve models below: context 1,048,576 input tokens, max output 65,536 (Gemini 4: 65,536 by default, up to 1,048,576 "long decode"), image input, structured outputs, function calling, batch, flex and priority supported `[GMx]`. Knowledge cutoff is printed only for the 2.5 family (January 2025).

| Model id | Tier | Status `[GM][GMx]` | Thinking: default (levels) `[GT]` | Free tier `[GP]` | Paid input / output | Cached (+ storage /h) | Batch in / out |
|---|---|---|---|---|---|---|---|
| `gemini-4-hydrogen` | T2 | Stable, Nov 2026 | on, high (low, medium, high, xhigh) | free of charge | $1.50 / $7.50 | $0.075, implicit only | $0.75 / $3.75 |
| `gemini-4-argon` | T3 | Stable, Oct 2026 | on, medium (low, medium, high) | not available | **$2.00 / $10.00 until 2026-11-30**, then $4.00 / $20.00 | $0.10, then $0.20, implicit only | $1.00 / $5.00, then $2.00 / $10.00 |
| `gemini-4-carbon` | T3 | Stable, Nov 2026 | on, medium (low, medium, high) | not available | same as Argon | same as Argon | same as Argon |
| `gemini-3.8-flash` | T2 | Stable, Sep 2026 | on, medium (low, medium, high; `minimal` errors) | free of charge | **$0.75 / $3.75 until 2026-12-31**, then $1.50 / $7.50 | $0.075, then $0.15 (+ $0.50, then $1.00) | $0.375 / $1.875, then $0.75 / $3.75 |
| `gemini-3.6-flash` | T2 | Stable, Jul 2026 | on, medium (minimal, low, medium, high) | free of charge | same as 3.8 Flash | same | same |
| `gemini-3.5-flash-lite` | T1 | Stable, Jul 2026 | on, **minimal** (minimal to high) | free of charge (caching not available) | $0.30 / $2.50 | $0.03 (+ $1.00) | $0.15 / $1.25 |
| `gemini-3.1-flash-lite` | T1 | Stable, May 2026 | on, **minimal** (minimal to high) | free of charge | $0.25 / $1.50 (audio in $0.50) | $0.025 (+ $1.00) | $0.125 / $0.75 |
| `gemini-2.5-flash-lite` | T0 | Stable, "served until further notice"; "for new projects use Gemini 4 Hydrogen or 3.5 Flash-Lite" | **off** (low, medium, high) | free of charge | $0.10 / $0.40 | $0.01 (+ $1.00) | $0.05 / $0.20 |
| `gemini-3-flash-preview` | T2 | **Preview**, Dec 2025 | on, high (minimal to high) | free of charge | $0.50 / $3.00 | $0.05 (+ $1.00) | $0.25 / $1.50 |
| `gemini-3.1-pro-preview` | T3 | **Preview**, Feb 2026 | on, high (low, medium, high) | not available | $2.00 / $12.00 (prompt over 200K: $4.00 / $18.00) | $0.20 (+ $4.50) | $1.00 / $6.00 |
| `gemini-2.5-flash` | T1 | **Deprecated**: from 2026-12-01 requests route to `gemini-3.5-flash-lite` | on (low, medium, high) | free of charge | $0.30 / $2.50 | $0.03 (+ $1.00) | $0.15 / $1.25 |
| `gemini-2.5-pro` | T3 | **Deprecated**: from 2026-12-01 requests route to `gemini-3.8-flash` | on (low, medium, high) | free of charge | $1.25 / $10.00 (over 200K: $2.50 / $15.00) | $0.125 (+ $4.50) | $0.625 / $5.00 |

Notes:
- **`gemini-3.5-flash`, the registry's lead model, is on none of these pages.** Preview models "might come with more restrictive rate limits and will be deprecated with at least 2 weeks notice" `[GM]`.
- **Long-context surcharge:** only the two Pro models print a threshold (200K). No other row has one `[GP]`.
- **Minimum cacheable prompt** (implicit caching is on by default for 2.5 and newer): 4,096 tokens for Gemini 4, 3.8, 3.6 and 3.1 Pro; 2,048 for 2.5 Flash and Pro `[GC]`. The pages did not print a minimum for the two Flash-Lite 3.x models (unverified). Socra's prompts are 0.3K to 2K tokens, so **Gemini caching will not trigger** on any node except the alignment judge (10K), and only if its prefix is stable. Gemini 4 caches "only if the new request adds at least 2,050 tokens" `[GC]`.
- **Thinking billing and cap:** "max_output_tokens ... including thought tokens"; a response that hits the cap is "incomplete" and the thinking is still billed `[GT]`.
- **Request names.** The docs read describe the Interactions API (`thinking_level` in `generation_config`; `response_format: {type: "text", mime_type: "application/json", schema}`) `[GT][GS]`. The Python SDK form `ThinkingConfig(thinking_level="high")` and the config keys `response_mime_type` and `response_json_schema` are printed on a model page `[GMx]`. The REST camelCase names (`thinkingConfig.thinkingLevel`, `responseJsonSchema`) and the usage field for thinking tokens were **not printed** (unverified). Socra uses `langchain-google-genai` 4.4.0, whose field is `thinking_level` (`thinking_budget` is "deprecated for Gemini 3+"; verified in the installed package).
- **Structured output** `[GS]` (summary): JSON Schema subset; `minLength`, `maxLength`, `uniqueItems` and similar are **stripped silently**; `minItems` and `maxItems` are enforced; very large or deeply nested schemas "may be rejected" with 400 INVALID_ARGUMENT; combining with built-in tools is preview. Validate values in the application.
- **Batch:** 50% of standard; "target turnaround time is 24 hours, but in majority of cases, it is much quicker"; expires after 48 hours; `generateContent` only `[GB]`.
- **Rate limits.** `[GR]` prints **no RPM, TPM or RPD for any of these text models** on either the Free tier or Tier 1 or Tier 2: it says they "can be viewed in Google AI Studio" (a login page, not read) (unverified). It does print: tiers (Free; Tier 1 = "set up and link an active billing account", cap $250; Tier 2 = "Paid $100 + 3 days from first successful payment", cap $2,000; Tier 3 = "Paid $1,000 + 30 days", cap $20,000 to $100,000+); upgrades are automatic ("Free to Tier 1 ... typically take effect instantly", others "within 10 minutes"); spend limit per 10 minutes Tier 1 $10, Tier 2 $200; batch enqueued tokens per model per tier. The registry's 10 and 15 RPM figures for Gemini are therefore **not backed by a source** (unverified).
- **Paying from India** `[GBL]`: set up billing in AI Studio ("select your country", then contact details and a payment method); prepaid credits from a minimum of $5 "or equivalent in other currencies" to $5,000, expiring after 1 year; Prepay and Postpay plans "start taking effect March 23, 2026"; at $0 prepaid credit requests fail with HTTP 402. **India is listed as an available region** `[GRg]`. The accepted payment methods and INR are **not printed** (unverified).
- **Data use** `[GTe]` (effective 2026-03-23): free tier: "Google uses the content you submit to the Services and any generated responses to provide, improve, and develop" its products, and "human reviewers may read, annotate, and process your API input and output". Paid tier: "Google doesn't use your prompts ... or responses to improve our products"; prompts and responses are logged "for a limited period of time, solely for detecting and preventing violations". The pricing page's cards say the same (free: "Content used to improve our products"; paid: "not used") `[GP]`. **Learner content sent on the free tier is therefore training data.** The terms also require users to be 18 or older and the use to be "for professional or business purposes" (decision 5).
- **Quirks for structured generation:** `gemini-3.8-flash` "minimal is not supported and returns an error" `[GMx]`; the lite models default to `minimal`, the 3.6 and 3.8 Flash and Gemini 4 Argon and Carbon default to `medium`, Hydrogen and 3 Flash default to `high`, so an **unset effort costs a different amount on every model** `[GT]`; 2.5 Flash-Lite defaults to thinking off.

### 1.2 Groq (`console.groq.com`)

Sources: models `[QM]`, rate limits `[QR]`, reasoning `[QRs]`, structured outputs `[QS]`, prompt caching `[QC]`, batch `[QB]`, deprecations `[QD]`, billing FAQs `[QBF]`, data `[QY]`, services agreement `[QSA]`, spend limits `[QSL]`.

| Model id | Tier | Status | Context / max output | Price in / out | Cached | Notes |
|---|---|---|---|---|---|---|
| `openai/gpt-oss-20b` | T0 | Production | 131,072 / 65,536 | $0.075 / $0.30 | 50% off = $0.0375 | 1000 tokens/s printed; strict JSON; reasoning |
| `openai/gpt-oss-120b` | T1 | Production | 131,072 / 65,536 | $0.15 / $0.60 | 50% off = $0.075 | 500 tokens/s printed; strict JSON; reasoning |
| `openai/gpt-oss-safeguard-20b` | T0 | Preview | 131,072 / 65,536 | $0.075 / $0.30 | 50% off | safety classifier model |
| `qwen/qwen3.8-27b` | T1 | Preview | 131,072 / 16,384 | $0.80 / $4.00 | not listed | strict JSON; the only Groq model where reasoning can be `none` |
| `llama-3.1-8b-instant`, `llama-3.3-70b-versatile` | n/a | **shut down 2026-08-16** `[QD]` (the models page still lists them as "Enterprise", price "ContactSales"; the two pages disagree) | | | | do not use |
| `meta-models/muse-spark-open`, `minimaxai/minimax-m2.7` | n/a | Preview, Enterprise | | ContactSales | | no public price |

- **Rate limits (unresolved).** `[QR]` prints, for `gpt-oss-120b`, `gpt-oss-20b` and `qwen3.8-27b`: **30 RPM, 1K RPD, 8K TPM, 200K TPD**, and says "the limits shown below are the base limits for the Developer plan". `[QM]` prints, for the same models, "RATE LIMITS (DEVELOPER PLAN)": **1K RPM, 250K TPM**. The two pages disagree, and the Free-plan tab's table was not in the fetched text (unverified, decision 3). The registry assumes the 8K TPM figure, which is why "a single request (prompt plus reply) has to fit" in `seed.py`. Limits are per organisation; "cached tokens do not count towards your rate limits" `[QR][QC]`. Upgrading: "Upgrade to Developer plan" in the console.
- **Reasoning** `[QRs]`: `reasoning_effort` accepts `low`, `medium`, `high` for the two gpt-oss models; `none` and `default` are "only supported by Qwen 3.8 27B", so **gpt-oss reasoning cannot be turned off** (inferred; not stated outright). `include_reasoning` (default true) and `reasoning_format` are mutually exclusive, and `reasoning_format` "is not supported" for gpt-oss. Default temperature 0.6, default `max_completion_tokens` 1024. How reasoning tokens are billed is not on the page (unverified).
- **Structured output** `[QS]`: `response_format: {type: "json_schema", json_schema: {name, schema, strict}}`. `strict: true` uses constrained decoding and requires every field in `required` and `additionalProperties: false`; supported on `gpt-oss-20b`, `gpt-oss-120b`, `qwen3.8-27b`, `muse-spark-open`. `strict: false` (the default) is best-effort. "Streaming and tool use are not currently supported with Structured Outputs." Whether it works together with reasoning is not stated (unverified).
- **Prompt caching** `[QC]`: automatic, no extra fee, 50% off cached input, expires after 2 hours without use, needs an exact prefix match; models: the two gpt-oss and the safeguard model. The minimum size ("128 to 1024 tokens depending on the model") is from the tool's summary (unverified).
- **Batch** `[QB]`: 50% off, "24-hour to 7 day processing window"; does not stack with caching.
- **Data** `[QY][QSA]`: "By default, Groq does not retain customer data for inference requests"; logs "retained for up to 30 days" only for troubleshooting or abuse (opt-out in Data Controls); data stored in US Google Cloud buckets. Services Agreement §4.2: "Groq is not permitted to use Inputs or Outputs for training or fine-tuning any AI Model Services". It draws **no free-versus-paid distinction**.
- **Paying from India** `[QBF]`: cards (Visa, MasterCard, American Express, Discover), US bank accounts and SEPA debit are accepted; fees are in USD (§5.2 of `[QSA]`); "customers with a billing address in India have different progressive billing thresholds ... only $1, $10, and then $100 recurring". **India is not listed as a supported country anywhere that was read** (unverified), but the India-specific threshold text implies Indian billing exists. Spend limits are monthly, organisation-wide, paid plans only `[QSL]`.

### 1.3 OpenAI (`developers.openai.com`, the redirect target of `platform.openai.com/docs`)

Sources: pricing `[OP]`, models and per-model pages `[OM]`, reasoning `[OR]`, structured outputs `[OS]`, caching `[OC]`, batch `[OB]`, rate limits `[ORL]`, deprecations `[OD]`, data `[OY]`, countries `[OSC]`.

The catalogue is the GPT-6 and GPT-5.6 families, named Luna (small), Terra (mid), Sol (strong) and Astra (flagship). Context 1,050,000, max output 128,000 for the GPT-6 models printed `[OM]`.

| Model id | Tier | Status | Input / cached / output | Batch in / out | Over 272K tokens in / out |
|---|---|---|---|---|---|
| `gpt-6-luna` | T1 | Active, cutoff 2026-05-18 | $0.10 / $0.01 / $0.50 | $0.05 / $0.25 | $0.20 / $0.75 |
| `gpt-5.6-luna` | T1 | Active, cutoff 2026-02-16 | $0.20 / $0.02 / $1.20 | $0.10 / $0.60 | $0.40 / $1.80 |
| `gpt-6.1-terra` | T2 | Active, cutoff 2026-06-01 | $1.00 / $0.05 / $5.00 | $0.50 / $2.50 | $2.00 / $7.50 |
| `gpt-5.6-terra` | T2 | Active | $2.00 / $0.20 / $12.00 | $1.00 / $6.00 | $4.00 / $18.00 |
| `gpt-6.1-sol`, `gpt-6-sol` | T3 | Active | $2.00 / $0.10 / $10.00 ($0.20 cached for `gpt-6-sol`) | $1.00 / $5.00 | $4.00 / $15.00 |
| `gpt-5.6-sol` | T3 | Active; **promo price until 2026-11-30** | $4.00 / $0.40 / $20.00 | $2.00 / $10.00 | $8.00 / $30.00 |
| `gpt-6-astra` | T4 | Active (flagship) | $10.00 / $1.00 / $50.00 | $5.00 / $25.00 | $20.00 / $75.00 |
| `gpt-5.5`, `gpt-5.4` | T3 | Active | $5.00 / $0.50 / $30.00 and $2.50 / $0.25 / $15.00 | half | listed |
| `gpt-5.4-mini` | T2 | Active | $0.75 / $0.075 / $4.50 | half | not listed |
| `gpt-5.4-nano` | T1 | **Deprecated**, shutdown 2027-04-01, replacement `gpt-6-luna` | $0.20 / $0.02 / $1.25 | half | |
| `gpt-5-mini`, `gpt-5-nano`, `gpt-5`, `o3` | | **Deprecated**, shutdown 2026-12-11 | | | |
| `gpt-4o-mini`, `gpt-4.1-mini` | | **Deprecated**, shutdown 2027-01-14 | | | |

- **Capabilities** (Luna, Terra pages `[OM]`): streaming, structured outputs, function calling, image input, prompt caching, batch; Chat Completions supported. "Tool calling requires the Responses API" for Terra; for Luna, "Chat Completions supports function calling only with `reasoning_effort` set to `none`". **Chat Completions does not support function calling with GPT-6 Astra or GPT-6.1 Sol** `[OR]`.
- **Reasoning** `[OR][OM]`: `reasoning.effort` (Responses API) or `reasoning_effort` (Chat Completions). Luna and Terra accept `none`, `low`, `medium` (default), `high`, `xhigh`, `max`. **Astra and 6.1 Sol do not accept `none`** (400 on Astra); Sol 6.1 "defaults to `medium`". `reasoning.mode` is `standard` (default) or `pro`. `max_output_tokens` caps reasoning plus visible output.
- **Structured outputs** `[OS]` (partly summary): Responses API `text.format = {type: "json_schema", strict: true, schema}`; subset limits: root must be an object, every field `required` (optional = null union), `additionalProperties: false` on every object, at most 5,000 properties and 10 nesting levels; `allOf`, `not`, `if/then/else` unsupported; a `refusal` can replace the output.
- **Caching** `[OC]`: automatic, from 1,024 tokens (GPT-5.6 and later); reads cost 0.1× the input price (0.05× for 6.1 Sol and Terra); explicit writes 1.25× (30 minutes) or 2.5× (12 hours). **Batch** `[OB]`: 50% off, "within 24 hours", 50,000 requests per batch.
- **Limits** `[ORL]`: tiers Free ("must be in an allowed geography", $100 a month), Build ($5 total purchases, $500 a month), Launch ($100), Grow ($500); upgrades are automatic on total purchases. Luna: Build 5,000 RPM / 2M TPM, Launch 10,000 / 10M. Terra: Build 5,000 / 1M. **Free-tier RPM and TPM are not printed** (unverified).
- **Data** `[OY]`: "data sent to the OpenAI API is not used to train or improve OpenAI models (unless you explicitly opt in)"; abuse-monitoring logs kept up to 30 days; zero data retention needs approval. **India is a supported country** `[OSC]`; payment methods are not stated (unverified).

### 1.4 Anthropic (`platform.claude.com`, the redirect target of `docs.anthropic.com`)

Sources: models `[AM]`, pricing `[AP]`, rate limits `[AR]`, thinking `[AT]`, effort `[AE]`, structured outputs `[AS]`, caching `[AC]`, batch `[AB]`, deprecations `[AD]`, countries `[AX]`, terms `[AY]`.

| Model (API id) | Tier | Context / max out | Input / output | Cache read (5-min write / 1-hour write) | Batch in / out | Retirement "not sooner than" |
|---|---|---|---|---|---|---|
| Haiku 5.5 (`claude-haiku-5-5`) | T1 | 1M / 128K | **$0.10 / $0.50** up to 100K prompt; over 100K $0.50 / $2.50 | $0.01 ($0.125 / $0.20) | $0.05 / $0.25 | 2027-10-07 |
| Sonnet 5.5 (`claude-sonnet-5-5`) | T3 | 1M / 128K | $2 / $10 | $0.10 ($2.50 / $4) | $1 / $5 | 2027-09-28 |
| Opus 5.5 (`claude-opus-5-5`) | T4 | 1M / 128K | $4 / $20 | $0.20 ($5 / $8) | $2 / $10 | 2027-09-22 |
| Fable 5.2 (`claude-fable-5-2`) | T4 | 1M / 128K | $8 / $40 | $0.20 ($10 / $16) | $4 / $20 | 2027-11-09 |
| Sonnet 5 / Opus 5 | T3 / T4 | 1M / 128K | $2 / $10 and $5 / $25 | $0.20 and $0.50 | | 2027-06-30, 2027-07-24 |
| Haiku 4.5 | T1 | 200K / 64K | $1 / $5 | $0.10 | $0.50 / $2.50 | listed Active; "not sooner than 2026-10-15", a date that has passed |
| Sonnet 4.5 | | | | | | deprecated; tentative retirement 2026-11-30 |

- **Thinking and effort** `[AT][AE]`: effort is `output_config.effort` with levels `max`, `xhigh`, `high`, `medium`, `low`; defaults: Haiku 5.5 `medium`, Sonnet 5.5 `high`, Opus 5.5 `medium`, Fable 5.2 `high`. Thinking is `{"type": "adaptive"}` on these models. **`budget_tokens` returns a 400 on Haiku 5.5 and Sonnet 5.5.** `thinking: {"type": "disabled"}` is accepted on Haiku 5.5 at effort `high` or below; it is **rejected on Sonnet 5.5, Opus 5.5 and Fable 5.2** (Sonnet 5.5's substitute is `between_tools`). Thinking tokens are billed as output even when `display` is `omitted` (the default for these models). I did not find the usage field name for thinking tokens (unverified).
- **Sampling** `[AD][AT]`: from API version `2026-10-21` a request containing `temperature`, `top_p` or `top_k` "returns a 400 error on every model" (partly summary). Whether `langchain-anthropic` 1.7.4 sends that version is unverified.
- **Structured outputs** `[AS]`: `output_config.format` with `type: "json_schema"`; recursive schemas, external `$ref` and numeric constraints are unsupported; `additionalProperties` must be `false`; changing the format invalidates the prompt cache (partly summary).
- **Caching** `[AC]`: top-level `"cache_control": {"type": "ephemeral"}`, TTL 5 minutes or `"ttl": "1h"`; minimum cacheable length is 512 tokens for Haiku 5.5, Sonnet 5.5 and Opus 5.5 (summary, "spot-check this figure"). **Batch** `[AB]`: 50% off, "most batches completing within 1 hour", expire after 24 hours.
- **Limits** `[AR]`: no "Tier 1" and no free tier is described; tiers are Start, Build, Scale (placed automatically; "Request tier increase" in the console), and new organisations "may start in the Evaluation tier, with limits below" them. Haiku 5.5 on Start: 4,000 RPM, 2,000,000 input and 400,000 output tokens per minute; cached tokens do not count toward input limits. Monthly spend cap Start $500.
- **Data** `[AY]`: "Anthropic may not train models on Customer Content from Services" (Commercial Terms). **India is listed** `[AX]`; payment methods and INR are not stated (unverified). Image input for Haiku 5.5 was not confirmed on the pages read (unverified).

### 1.5 Tier map used in the rest of the document

| Tier | Models (current, non-deprecated) | Used for |
|---|---|---|
| **T0** tiny | Groq `gpt-oss-20b`; Gemini `2.5-flash-lite` (legacy: not for new projects) | one-shot tiny outputs: traits, onboarding, prerequisites, review, plan of interactives |
| **T1** cheap | Groq `gpt-oss-120b`; Gemini `3.1-flash-lite`, `3.5-flash-lite`; `gpt-6-luna`*; Claude Haiku 5.5*; Groq `qwen3.8-27b` (preview) | the workhorse layer: pages, tests, interactives, judge, grading |
| **T2** mid | Gemini `3.6-flash`, `3.8-flash`, `4-hydrogen`, `3-flash-preview`; `gpt-6.1-terra`* | the quality fallback and the Quality profile |
| **T3** strong | Claude Sonnet 5.5*; `gpt-6.1-sol`*; Gemini `4-argon`, `4-carbon`, `3.1-pro-preview` | last-resort layer; never a default |
| **T4** premium | `gpt-6-astra`*, Claude Opus 5.5*, Fable 5.2* | not used by any profile |

`*` needs an OpenAI or Anthropic key, which Socra does not have yet.

---

## Part 2. Socra's requirements, node by node

### 2.1 What was read, and how good the data is

Read: `llm_registry/node_specs.py`, `seed.py`, `gateway.py`, `resolver.py`, `profiles.py`, `recorder.py`, `retry.py`, `outputs.py`; the lesson graph (`graph/nodes/*`, `graph/prompts/*`, `graph/authoring.py`, `graph/sheets.py`, `graph/questions/*`); the retake (`LoadBankNode`), quiz (`graph/nodes/quiz.py`), sheets, repair, media and onboarding flows; the credit costs in `docs/architecture/credits-system.md`.

Live data: the dev database's `llm_registry_modelcall`: **532 attempts, 2026-10-24 to 2026-11-15, 20 lessons, 41 runs, 0 quizzes**. It is a developer's free-tier log of small test lessons, so it is a good picture of failure modes and a thin picture of volume. **There are no rows at all for** `diagnostic.review`, `prerequisites.plan`, `media.verify`, `runtime.repair`, `onboarding.suggest_topics`, and none from a quick quiz or a retake; for those nodes the tokens are estimates from the prompts (est.).

The prompts are built from `Prompt.system()` and `Prompt.user()`; in every authoring prompt the large shared material (topic, learner profile, assessment, full plan JSON) comes **first** and the part that varies per call (`page_plan`, the batch's cells, the spec) comes **last**, which is the right order for prefix caching. Whether a cache can hit is a provider matter (1.1 to 1.4): Gemini needs 4,096 tokens, so no; Groq, OpenAI and Anthropic could. The three page calls and the two test batches are sent in parallel (`Send`), so the second and third start before the first has written the cache; **the cost model assumes no cache hits** and treats caching as upside.

Per-attempt budgets today: `NodeConfig.max_attempts` (graph rounds; spec defaults 2, `diagnostic.generate` 3, the three quick ones 1), `NodeModelBinding.max_retries` (default 2 transport retries per model), `timeout_s` (default 60 s per call). On a 429 the gateway retries up to twice on the same model with backoff before falling through, unless the message names a daily quota.

### 2.2 Live numbers per node (ok = a successful attempt)

| Node | Lessons with rows | ok calls per lesson, avg (max) | Input tokens, avg (max) | Output tokens incl. thinking, avg (max) | What happened at layer 1 |
|---|---|---|---|---|---|
| `diagnostic.generate` | 17 | 2.3 (10) | 0.6K to 1.5K (5.8K) | 1.9K to 5.1K (7.9K) | gpt-oss-20b 24 ok of 40 (3 invalid, 8 retryable 429, 5 fatal 400 "Failed to generate JSON"); gpt-oss-120b 8 of 20 (5 invalid, 6 fatal); Flash 4 of 18 (13 × 429); Flash-Lite 4 of 5 |
| `learner.assess` | 6 | 1.0 | 0.4K to 1.6K | 0.2K to 0.25K | gpt-oss-20b **4 ok of 14 (9 invalid)**; Flash-Lite 2 of 2 |
| `lesson.plan` | 8 | 1.0 | 0.56K to 1.1K | 1.0K to 1.3K | Flash 3 of 9 (6 × 429); Flash-Lite 3 of 3; gpt-oss-120b 2 of 2 |
| `page.generate` | 8 | 4.0 (6) | 1.8K to 1.9K (2.4K) | 1.5K to 1.9K (2.8K) | Flash **5 of 60 ok** (55 × 429/503); Flash-Lite 27 of 27 |
| `test.generate` | 8 | 1.5 (4) | 1.6K (1.9K) | 1.3K to 2.8K | Flash 1 of 25; Flash-Lite 11 of 11 |
| `interactive.plan` | 8 | 1.0 | 1.2K (2.5K) | 0.64K (0.9K) | gpt-oss-20b 8 of 10 (2 invalid) |
| `media.search` | 4 | **8.8 (12)** | 0.9K (1.3K) | 49 (94) | gpt-oss-20b 35 of 40 (5 retryable); 0.6 s per call |
| `interactive.generate` | 8 | 5.5 (9) | 1.5K (2.3K) | 1.2K to 2.4K (3.4K) | Flash 5 of 88 (83 retryable; **66 s** per ok call); Flash-Lite 39 of 39 (5.6 s) |
| `alignment.judge` | 7 | 1.0 | **9.5K to 10.8K (11.8K)** | 68 | Flash 1 of 10; Flash-Lite 6 of 6 |
| `page.compile` | 7 | 3.0 | 1.1K | 0.29K to 0.37K | Flash 1 of 35 (**39 s** per ok call); Flash-Lite 19 of 22 |
| `code.repair` | 1 | 6.0 | 1.1K (1.2K) | 0.29K (0.34K) | Flash 0 of 18; Flash-Lite 6 of 6 |
| `test.grade` | 3 | 1.0 | 1.2K to 1.6K | 0.3K to 0.4K | gpt-oss-20b 2 of 3; 120b 1 of 1 |
| `study.generate` | 1 | 2.0 | 0.2K | 0.9K to 1.5K | Flash 1 of 4; Flash-Lite 1 of 1 |
| `topic.traits` | 1 | 1 | 0.27K | 0.04K | gpt-oss-20b 1 of 1 |

Failure inventory over all 532 attempts: 221 × `RESOURCE_EXHAUSTED` on `gemini-3.5-flash` (and 3 on Flash-Lite); 30 × "503 UNAVAILABLE, high demand"; 16 × Groq 429 (per-minute); 10 × Groq 400 "Failed to generate JSON"; 19 × invalid output (the model returned the schema's own `{"description": "", "properties": ...}` instead of an answer, or a malformed bundle); 4 × 404 for retired ids (`gemini-2.5-flash`, `llama-3.3-70b-versatile`); 2 × network unreachable.

### 2.3 The nodes

Each entry: **does** / **called by, how often** / **input (typical, max; repeated part)** / **output** / **needs** / **wait** / **if wrong** / **now**.

Common: today's seed (`DefaultRegistry`) leads with `gemini-3.5-flash` (Flash) or Groq and falls back to Flash-Lite; `LITE` = `gemini-3.5-flash-lite`. Output includes thinking tokens.

1. **`diagnostic.generate`**: writes the Quick check: 10 diagnostic questions in five difficulty bands (2 per band) plus 5 prerequisite questions (`DiagnosticBundle`). *Called by* the lesson's Quick-check path once per lesson (up to `max_attempts` 3 on a failed rule), and by the quiz warm-up (calibration pool: 2 per band, no prerequisites, 10 questions). *Input* 0.6K to 1.5K (max 5.8K); about 40% is the fixed system prompt. *Output* 2K to 5K tokens of JSON, up to 7.9K. *Needs* structured output; reasoning low (the seed notes that at medium gpt-oss "drops required fields of this big schema; low parses every time"). *Wait* a learner is waiting (the Quick check is the next screen). *If wrong* user-visible (a wrong answer key or two identical options); **caught** by `DiagnosticValidator` and the optional reviewer. *Now* `[gpt-oss-120b, Flash]`, effort low, temperature 0.5, 3 attempts. *Observed* highest retry rate of any node (2.3 calls per lesson).
2. **`diagnostic.review`**: an optional judge that the 15 questions are independent and correctly banded (`QuizReview`). *Called by* `ValidateDiagnosticNode`, once per bundle that passes the rules. *Input* est. 2.6K (the whole bundle); *output* est. 0.25K. *Needs* structured output, no reasoning. *Wait* learner waiting. *If wrong* harmless: it cannot fail a lesson (all-models-failed is skipped with a warning; spent attempts keep the quiz). *Now* `[gpt-oss-20b, Flash]`, temperature 0. No live rows.
3. **`learner.assess`**: turns the quiz result and profile into a `LearnerAssessment` (gaps, author notes); the **level itself is set by code** (`LevelScheme`, `AssessmentSource`), not by the model. *Called by* the Quick-check path once. *Input* 0.4K to 1.6K; *output* about 0.25K. *Needs* structured output. *Wait* background (lesson generating screen). *If wrong* the lesson is tailored badly, user-visible only indirectly; `AssessmentGuard` checks it. *Now* `[gpt-oss-20b, Flash]`. *Observed* **9 of 14 invalid on gpt-oss-20b**.
4. **`prerequisites.plan`**: 3 to 6 prerequisites for a Beginner who took no quiz. *Called by* the self-rating path for beginners, once. est. in 0.9K, out 0.5K. Structured output. *If wrong* user-visible (what the introduction teaches), caught by `PlanValidator`. *Now* `[gpt-oss-20b, Flash]`. No live rows.
5. **`study.generate`**: a cheat sheet or revision sheet (`CheatSheet | RevisionSheet`). *Called by* the sheets path, **2 calls per pair**, in parallel, 5 credits per pair; also for "sheets only" lessons. *Input* 0.2K to 1.2K (concepts, optional grounding in the lesson's pages); *output* 0.9K to 1.5K. Structured output. *Wait* learner waiting. *If wrong* user-visible; caught by `StudyMaterialValidator`. *Now* `[Flash, Flash-Lite]`.
6. **`lesson.plan`**: plans the three pages and says whether the topic is quantitative (decides if the test has numerical questions). *Called by* every lesson once (plus retries). *Input* 0.6K to 1.2K; *output* 1.0K to 1.4K. Structured output; the spec default is `high` reasoning. *Wait* background. *If wrong* everything downstream follows it; caught by `PlanValidator`. *Now* `[Flash, gpt-oss-120b, Flash-Lite]`.
7. **`page.generate`**: writes one content page (introduction, core, advanced). *Called by* every lesson **3 times in parallel**, plus retries and judge fixes (4.0 observed). *Input* 1.8K to 2.4K, of which about 1.2K (system prompt, learner, assessment, full plan JSON) is identical across the three calls. *Output* 1.5K to 2.8K of structured JSON (sections with Markdown bodies, formulas). Structured output; no vision. *Wait* background. *If wrong* **user-visible**; caught by `PageValidator` (structure, concepts, LaTeX through the sandbox) but not for factual accuracy (that is the judge's job). *Now* `[Flash, Flash-Lite]`.
8. **`test.generate`**: one batch of test questions, one per cell (MCQ, MSQ, numerical, short, long). *Called by* the lesson (10 cells, batch size 5, so **2 calls**), the quick quiz (batches of 5; a 10-question quiz is 2 calls), and the retake (cells already covered by unused bank questions need no call). *Input* 1.6K to 1.9K (plan, assessment, up to 60 earlier stems, 160 chars each); *output* 1.3K to 2.8K. Structured output. *If wrong* user-visible; marks, ids and a numerical answer are **set by code** (`QuestionFinisher`), and `QuestionBatchValidator` checks the rest. *Now* `[Flash, Flash-Lite]`, temperature 0.3.
9. **`interactive.plan`**: decides which interactives and media each page gets (kind, anchor, `media_query`, at most 3 per page). *Called by* every lesson once. *Input* 1.2K (2.5K); *output* 0.64K. Structured output. *If wrong* degrades: `UsableSpecs` keeps the valid specs. *Now* `[gpt-oss-20b, Flash]`.
10. **`media.search`**: a tool-calling agent (up to 6 tool steps) that searches Wikimedia Commons and Openverse and submits a choice (`MediaSelection`). *Called by* `find_media` once per image or GIF spec: **8.8 calls per lesson** where there is media. *Input* 0.9K; *output* 49 tokens (it only emits tool calls). *Needs* tool calling. *Wait* background. *If wrong* harmless: the picture is downloaded, licence-checked and (optionally) vision-checked, and a miss falls back to an SVG. *Now* `[gpt-oss-20b, Flash]`, 6 steps.
11. **`media.verify`**: a vision check that the downloaded image shows what the spec describes, plus alt text. *Called by* `verify_media`, est. 2 to 3 per lesson. *Input* est. 1.5K to 1.9K (image tokens); *output* est. 0.15K. *Needs* **vision** and structured output (Gemini only among Groq and Gemini). *If wrong* user-visible (a wrong picture); this node is the check. Optional. *Now* `[Flash, Flash-Lite]`, temperature 0. No live rows.
12. **`interactive.generate`**: one self-contained React component in TSX (`InteractiveComponent`). *Called by* `build_interactive` per interactive spec: 5.5 per lesson observed (max 9), plus fixes. *Input* 1.5K (the scope reference is about 2.7 KB of fixed text); *output* 1.2K to 2.4K (max 3.4K). Structured output carrying code. *If wrong* user-visible; caught by the sandbox (`check_code`: static and security), and a spec that keeps failing is **dropped with a warning**. *Now* `[Flash, Flash-Lite]`, temperature 0.6. *Observed* Flash took 66 s per call; Flash-Lite 5.6 s.
13. **`alignment.judge`**: reviews the whole lesson (pages, test, interactives, media captions) against the topic and this learner; scores 1 to 5 and issues with a fix instruction. *Called by* every lesson, normally once; a "fix" decision re-runs the flagged items and the judge. *Input* **9.5K to 11.8K**, none of it reusable across lessons; *output* 68 tokens when there are no issues (est. 0.45K when there are). Structured output; spec default reasoning `high`; needs 64K context. *If wrong* a major issue **fails the run**, but `AlignmentPolicy` recomputes `passed` from the scores, so the judge's own verdict is not trusted. *Now* `[Flash, Flash-Lite]`, temperature 0.
14. **`page.compile`**: turns one page's JSON into a TSX component that renders `LESSON.pages.<key>` ("never retype, cut or change the text"). *Called by* every lesson **3 times**. *Input* 1.1K; *output* 0.3K to 0.4K of TSX. Text output. *If wrong* caught by the static and render checks; a broken page falls back to the template layout. *Now* `[Flash, Flash-Lite]`.
15. **`code.repair`**: fixes TSX that failed the static, security or render checks (also used by `repair_page` and `repair_component`). est. 0.5 calls per lesson (one lesson needed 6). *Input* 1.1K; *output* 0.3K. Text. *Now* `[Flash, Flash-Lite]`, temperature 0.2.
16. **`runtime.repair`**: fixes TSX that threw in the learner's browser. Learner-initiated, rare. *Input* the whole broken code (est. 1K to 6K) plus the stack; *output* about the same size as the code. Text. *If wrong* harmless: regression check, render check and a version snapshot happen before anything is saved, and the old code stays on failure. *Now* `[Flash, Flash-Lite]`. No live rows.
17. **`test.grade`**: grades short, long and code answers against the model answer and rubric (`GradeReport`), temperature 0. *Called by* each Test attempt that has open answers, **once** (not batched). *Input* 1.2K to 1.6K; *output* 0.3K to 0.4K. *Wait* the learner waits for the score. *If wrong* **user-visible and money-adjacent** (a score); the validator bounds each award by the criterion's marks. The learner's answer is data, never instructions (the prompt says so). *Now* `[gpt-oss-120b, Flash]`.
18. **`topic.traits`**: is the quick-quiz topic mainly calculation, is it programming (`TopicTraitsJudgement`). *Called by* the quiz wizard once per topic typed. *Input* 0.27K; *output* 0.04K. *Wait* the learner is waiting: 4 s, 1 attempt, 0 retries. *If wrong* harmless: off or slow, the wizard offers every kind of question. *Now* `[gpt-oss-20b, Flash-Lite]`.
19. **`onboarding.suggest_topics`**: first-topic suggestions when the curated catalogue has no match, and translating the catalogue's titles for a non-English learner. *Called by* onboarding. est. in 0.5K, out 0.35K (at least 4 topics). *Wait* the learner is waiting: 4 s, 1 attempt. *If wrong* harmless: the learner gets the catalogue. *Now* `[gpt-oss-20b, Flash-Lite]`.

### 2.4 Calls per flow (used by the cost model)

| Flow | Calls (expected, after the changes in 3.3) | Credits charged | Source |
|---|---|---|---|
| Full lesson, Quick-check path | about 19 (diagnostic 1.2, review 1, assess 1, plan 1, pages 4.4, tests 2, interactive plan 1, media search 0.5, verify 2.5, interactives 2.7, judge 1.3, repair 0.5); **about 32 today** (diagnostic 1.6, compile 3, media search 9, interactives 4, the rest the same) | 10 | `[credits-system.md §2.1]` |
| Quick quiz, 10 questions | 3 (traits 1, test batches 2) plus 1 grading per attempt | 2 (3 from a lesson) | §2.2 |
| Lesson Test retake | 1.5 (test batches, some cells served from the bank) plus 1 grading | 2 | §2.3 |
| Cheat sheet + revision sheet | 2 | 5 | §2.3 |
| Test grading | 1 per attempt | 0 (part of the lesson or quiz) | §2.2 |

---

## Part 3. Strategy design

### 3.1 Tier rule per node

The rule: **start every node at the lowest tier that can meet its quality bar, and let the validators and the escalation rule (3.2) lift it only when it fails.** A node's bar is set by who sees a mistake and who catches it. The tiers below are hypotheses until the golden runs in 3.6 confirm them; "promote" means move the node's layer 1 up one tier.

| Node | Start tier | Reason (what a wrong answer costs, who catches it) | Promote when |
|---|---|---|---|
| `topic.traits`, `onboarding.suggest_topics` | **T0** | 40 to 350 output tokens, a 4 s deadline, harmless if wrong (the wizard or catalogue takes over) | never |
| `prerequisites.plan` | T0 | 0.5K of output, checked by `PlanValidator` | first-attempt pass under 85% |
| `diagnostic.review` | T0 | a judge that cannot fail a lesson (skipped on failure); must never be a premium model | never |
| `interactive.plan` | T0 | degrades to the valid specs (`UsableSpecs`) | spec yield under 80% |
| `media.search` | T0, or no model | the plan already supplies the query; harmless, because verify and licence checks follow | n/a |
| `learner.assess` | T1 | the model supplies only gaps and notes; the level is set by code. T0 failed 9 of 14, but in best-effort JSON mode (finding 3), so T1 with strict JSON | invalid rate over 5% with strict JSON |
| `diagnostic.generate` | T1 | an answer key a learner sees; 15 questions in one structured reply; the validator catches structure, not truth | first-attempt pass under 85% |
| `lesson.plan` | T1, effort medium | everything downstream follows it; `PlanValidator` checks shape | alignment scores under 4 |
| `page.generate`, `study.generate` | T1 | the user-visible content; the judge reviews accuracy | judge reports a major factual issue in over 10% of lessons |
| `test.generate` | T1 | answer keys; finishing and validation in code | answer-key errors found by the judge over 5% |
| `interactive.generate` | T1 | the sandbox rejects broken code and the interactive is dropped | static-check pass under 70% |
| `alignment.judge` | T1, effort medium | a judge must not be premium. It needs 64K context and a stable reading of 10K tokens | its verdict disagrees with a human on over 1 in 5 golden lessons |
| `test.grade` | T1 | a user-visible score; temperature 0; awards bounded by the rubric; answers are data, not instructions | over ±1 mark from the human reference on the 20 golden answers, or any injection moves a grade |
| `media.verify` | T1, vision | catches a wrong picture; needs vision (Gemini, `gpt-6-luna`*; Claude Haiku 5.5's image support is unverified) | misses over 10% of planted wrong images |
| `code.repair`, `runtime.repair` | T1 | validated by static and render checks before saving | repair success under 60% |
| `page.compile` | **no LLM** | deterministic: a template already exists (3.3) | n/a |

**Rule for simple tasks.** Judges, reviewers, compile, media, traits, assess and onboarding never start above T1, and never use OpenAI or Anthropic models other than `gpt-6-luna` or Claude Haiku 5.5 (both T1).

### 3.2 Fallback chains

#### Chain rules (every node, every profile)

| Event | Action |
|---|---|
| 429 that says a daily quota is spent (`per day`, `(rpd)`, `(tpd)`) | next layer at once (exists today) |
| 429 per-minute | wait up to the `Retry-After` (cap 30 s), but **1 s for a node the learner is waiting on**; then next layer. Max 1 retry on the same layer (today 2) |
| 5xx, timeout, connection error | 1 retry (0 for waiting nodes), then next layer |
| 400 schema or "Failed to generate JSON" | next layer, no retry: it will fail the same way |
| Invalid output | one in-place repair (exists), then next layer |
| Graph validator rejects the output (new) | **attempt k of the node starts at layer k** (attempt 1 at L1, attempt 2 at L2, ...) instead of restarting at L1. The retry feedback is passed as today |
| Missing API key (a `*` layer with no key) | the layer is **skipped when the registry resolves**, not tried and failed (today it is a fatal error and a log row on every call) |
| Provider returns 401 or 402 three times in a row (new) | skip that provider for 5 minutes (circuit breaker) |

#### Economy profile: node to tier to L1..L4, settings and cost per call

Layers: **L1** Groq `gpt-oss` (T0/T1, strict JSON); **L2** Gemini 3.1 Flash-Lite (a separate quota bucket, cheaper output than 3.5 Flash-Lite); **L3** Gemini 3.5 Flash-Lite for the tiny nodes, Gemini 3.6 Flash for the writing nodes (the T2 quality step); **L4** an OpenAI or Anthropic model, used only when the three layers before it failed (`*` needs a key). Settings column: reasoning effort / temperature / max output tokens (it counts thinking tokens, so it is the visible size plus about 40%) / timeout in seconds / retries on the layer. Provider parameter names are in 3.5. Costs are ₹ per call for the typical call of 2.3, at ₹90 per dollar, with no cache hits.

The node-by-node table (tier, layers, settings and the cost of one call on each layer) is the first table of section 4.

`page.compile` has no row: it is replaced by the template (3.3). `media.search` is called only when a direct search finds nothing (0.5 per lesson).

**Demo profile** (free tiers only, ₹0): heavy and light nodes use `[gpt-oss-120b or 20b (Groq free), Gemini 3.1 Flash-Lite (free), Gemini 3.5 Flash-Lite (free), Gemini 3.6 Flash (free)]`; `media.verify` uses `[3.1 Flash-Lite, 3.5 Flash-Lite, 3.6 Flash, Gemini 4 Hydrogen]` (all free). All of these show "free of charge" on `[GP]`; Groq's free plan exists `[QR]`. Capacity is the limit, not cost. One lesson is about **43K input and 27K output tokens**. Groq's table prints 200K tokens a day per model `[QR]`, about **2.8 lessons a day per Groq model** if every call stayed on it; Gemini's free limits are not printed (unverified), and Gemini's free tier **trains on content** (decision 5). Use Demo only for synthetic or consented content.

**Quality profile** (paid, best available with the keys held today): writing, planning, assessing, judging and grading nodes use `[Gemini 3.8 Flash, Gemini 4 Hydrogen, Gemini 3.6 Flash, Claude Sonnet 5.5*]` at one effort step higher than the Economy table (about 40% more output tokens); `media.verify` uses `[3.5 Flash-Lite, 3.1 Flash-Lite, gpt-6-luna*, Haiku 5.5*]`; the quick nodes are unchanged. With OpenAI and Anthropic keys the first layer could be `gpt-6.1-terra` or Sonnet 5.5; that is not costed because the keys do not exist. Note the price steps: 3.8 and 3.6 Flash **double on 2027-01-01** `[GP]`.

### 3.3 Prompt, input and output optimisation per node

Token estimates are per call unless stated; rupees are per full lesson on the Economy chain.

| # | Node | Change | Saving |
|---|---|---|---|
| 1 | `page.compile` | **Remove the model call.** The prompt says the content is data and must not be retyped; `DocumentAssembler` already produces the template layout as the fallback. Use it as the first and only path, and keep the model only behind a per-lesson flag for "richer layout" | −3 calls, −3.3K in, −1.1K out, about 15 s of latency; ₹0.06 |
| 2 | `media.search` | **Search directly with the plan's `media_query`** (2 to 5 words), take the top candidates, let `media.verify` pick. Call the model only when a search returns nothing, to rewrite the query once | −8.5 calls and −7.7K in per lesson; the agent loop's wall time; ₹0.08 |
| 3 | `diagnostic.generate` | Strict JSON on Groq (3.5) and **`OptionRepair`-style repair in place**: rewrite only the failing question instead of regenerating 15 (the unmerged `a072030` on `chore/model-costs` does this for duplicated options; extend the idea to any single-question rule failure). Drop schema fields the UI never shows (est. −15% output) | 1.6 → 1.2 calls (−0.4 × 5.1K tokens); ₹0.13 |
| 4 | `interactive.generate` | At most **2 interactives per page** (`max_interactives_per_page` 3 → 2, a setting, no code); anchor section only (already) | −1.3 calls per lesson (−2K in, −2.4K out); ₹0.31 |
| 5 | `alignment.judge` | Stop sending the lesson plan JSON (its outline is already in the pages) and trim the interactive and media JSON to ids and purposes: 10K → 6.5K tokens in (est. −35%). Keep the full page text because factual accuracy is its job | −3.5K in × 1.3 rounds; ₹0.07 and about 1 s |
| 6 | `page.generate` | Pass the page's own plan entry plus a one-line concept list of the other two pages instead of the whole plan JSON (est. −0.6K in, −30%) | −2.6K in per lesson; ₹0.04 |
| 7 | `diagnostic.review` | Fold its two checks (independence, banding) into `DiagnosticValidator` as code where possible, or keep it optional and off in Economy | −1 call, −2.6K in; ₹0.03 |
| 8 | `learner.assess` | Send per-concept right and wrong counts, not 15 full questions with options (est. −0.6K in, −40%) | ₹0.01 |
| 9 | `test.generate` | Cap earlier stems at 30 (from 60) on retakes; serve unused bank questions first (exists) | −0.5K in on a retake; ₹0.01 |
| 10 | Prompt caching | Keep the shared prefix first (already so). Groq (50% off), OpenAI and Anthropic cache automatically or with one field, but the three page calls run in parallel, so only the **second wave** (fix rounds, retakes, sheets, the second test batch) can hit. Gemini needs 4,096 tokens, so no Gemini node benefits. Run page 1 alone first if caching is wanted: it costs 6 to 8 s of latency for about ₹0.03 | ₹0.02 to ₹0.03, **not counted in the model** |
| 11 | Batch API (24 h) | Not for anything a learner waits on. Use it for **pre-writing the retake question bank** while the learner studies (retakes then cost no call at all) and for golden runs: Groq, Gemini, OpenAI and Anthropic all give 50% `[QB][GB][OB][AB]` | ₹0.17 per retake; ₹0 per lesson |
| 12 | Output caps | Set `max_tokens` per node (3.2 table) so a runaway generation, or a thinking loop on a model with default `high` thinking, cannot bill 65K tokens | prevents tail cost; not counted |
| 13 | Thinking | Set effort explicitly on every binding. Unset, Gemini 3.6 Flash thinks at `medium` and Hydrogen at `high`, while the lite models think at `minimal` `[GT]`: the same node would cost 2 to 4 times more on the fallback than on L1 | prevents tail cost |

### 3.4 Cost model

**Assumptions** (the inputs are the token counts and chains in this document; the arithmetic was done with a throwaway script that is not committed): token counts from 2.2 (live) and 2.3 (est.); thinking is included in output tokens at the Economy effort (low); **no cache hits**; layer failure probabilities per node of 5% (judges, traits), 8% (plans, pages, assess, grade), 10% (tests), 15% (diagnostic), 20% (interactives, repair), each layer reached with probability `p^(layer-1)` and charged in full (conservative for quota errors, which bill nothing); ₹90 per dollar. "L1 only" = every call succeeds on layer 1. "Expected" = with that fall-through. GST (18%, prices are tax-inclusive) and the gateway fee (3% of the gross) come off revenue. The model does **not** include: the 18% GST that may apply to imported digital services from the providers' invoices, foreign-card or FX charges, grading of the first Test (₹0.05), and the credits given away free (those earn ₹0).

**Where the lesson's money goes (Economy, after the changes in 3.3, expected, ₹):** pages 0.70 · interactives 0.61 · tests 0.41 · diagnostic 0.39 · judge 0.23 · media verify 0.16 · plan 0.14 · the rest 0.17 = **2.80**.

**Optimisation ladder** (cost of one lesson, expected, Economy, from today's `Cheap` seed as the starting point):

| Step | ₹ per lesson |
|---|---|
| 0. Today's `Cheap` seed (Flash-Lite 3.5 on the heavy nodes, 32 calls) | 8.85 |
| 1. Lead with Groq `gpt-oss-120b`, Gemini 3.1 Flash-Lite behind it | 3.38 |
| 2. + strict JSON and repair in place (diagnostic 1.6 → 1.2 calls) | 3.25 |
| 3. + page compile from the template | 3.19 |
| 4. + search media directly | 3.11 |
| 5. + at most 2 interactives per page | **2.80** |

Without Groq (no key, quota, or the TPM limit is really 8K): the same chain led by Gemini 3.1 Flash-Lite costs **₹5.67**; led by 3.5 Flash-Lite it would cost ₹8.01. Choosing 3.1 over 3.5 is worth ₹2.34 a lesson because 3.5 Flash-Lite's output is $2.50 against $1.50.

**Cost per flow and profile, ₹** (L1 only / expected with fall-through):

| Flow | Demo | Economy (Groq-led) | Economy (Gemini only) | Quality (promo prices) | Quality (from 2027-01-01) |
|---|---|---|---|---|---|
| Full lesson | 0 | 2.06 / **2.80** | 4.63 / **5.67** | 15.45 / **19.22** | 30.66 / **34.66** |
| Quick quiz, 10 questions | 0 | 0.32 / 0.42 | 0.77 / 0.91 | 2.60 / 3.15 | 5.19 / 5.77 |
| Lesson Test retake | 0 | 0.28 / 0.36 | 0.66 / 0.78 | 2.26 / 2.71 | 4.53 / 5.00 |
| Cheat sheet + revision sheet | 0 | 0.19 / 0.24 | 0.46 / 0.53 | 1.58 / 1.84 | 3.16 / 3.43 |
| Grading one test attempt | 0 | 0.05 | 0.10 | 0.32 / 0.35 | 0.64 / 0.68 |

Reference only: **every node on Claude Sonnet 5.5** would cost about ₹47 a lesson, so the tiering is worth a factor of about 17.

**Revenue per flow, net** (gross ÷ 1.18, minus 3% of the gross; one lesson is 10 credits, a 10-question quiz or a retake 2, both sheets 5 `[credits-system.md §2]`):

| Paid with | ₹ per credit | Lesson | Quiz or retake | Sheets pair |
|---|---|---|---|---|
| One-time credits | 2.00 | 16.35 | 3.27 | 8.17 |
| Weekly Pro, **doubled** (₹98) | 0.98 | 8.01 | 1.60 | 4.01 |
| Monthly Pro, doubled (₹398) | 0.796 | 6.51 | 1.30 | 3.25 |
| Pro Plus, doubled (₹558) | 0.744 | 6.08 | 1.22 | 3.04 |
| Weekly Pro, **tripled** (₹147, on `chore/pricing-2x`) | 1.47 | 12.02 | 2.40 | 6.01 |
| Monthly Pro, tripled (₹597) | 1.194 | 9.76 | 1.95 | 4.88 |
| Pro Plus, tripled (₹837) | 1.116 | 9.12 | 1.82 | 4.56 |

**Lesson margin** (net revenue minus expected cost), at the lowest-paying plan, Pro Plus:

| Profile | Cost | Doubled (net ₹6.08) | Tripled (net ₹9.12) | One-time (net ₹16.35) |
|---|---|---|---|---|
| Economy, Groq-led | 2.80 | +3.28 (54%) | +6.32 (69%) | +13.55 (83%) |
| Economy, Gemini only | 5.67 | **+0.41 (7%)** | +3.45 (38%) | +10.68 (65%) |
| Quality, promo prices | 19.22 | **−13.14** | **−10.10** | **−2.87** |
| Quality, from 2027-01-01 | 34.66 | **−28.58** | **−25.54** | **−18.31** |

**What this says**
- **The ₹5 to ₹6 target is met on Economy**: ₹2.80 with Groq, ₹5.67 without it. Without Groq the doubled Pro Plus price leaves ₹0.41 of margin, which is too thin for a 40% error in the token estimates. The Groq layer is what makes the doubled prices work; the tripled prices make either variant safe.
- **Quality loses money at every price list**, even on one-time credits at ₹2 a credit, and gets worse when the Flash promo ends on 2027-01-01. It is a cost ceiling to compare against, not a profile to sell. To break even on Pro Plus it would need about ₹2.35 a credit gross while the promo lasts and ₹4.24 after 2027-01-01 (decision 6).
- **Free credits cost real money**: a free lesson costs ₹2.80 to ₹5.67 and earns ₹0. Spending free credits on the Demo profile is the only way to keep their cost at zero (decision 5 on privacy).
- The quick quiz at Quality (₹3.15 to ₹5.77) also exceeds its net revenue on every plan (₹1.22 to ₹3.27).

### 3.5 Adapter design (no code)

The registry already has the right shape: `ProviderProfile` is a **Strategy** per provider (parameter names, renames, reasoning kwargs), `OutputAdapter` a Strategy per output mode, `ResolvedModel` carries one binding's settings, and `NodeModelBinding.priority` is the layer. The design extends these instead of adding a parallel structure, and keeps `docs/architecture/design.md` §4 as the home of the class diagrams.

#### A. How a generic setting becomes a provider parameter

| Generic setting | Gemini (`langchain-google-genai`) | Groq (`langchain-groq`) | OpenAI (`langchain-openai`, Responses API) | Anthropic (`langchain-anthropic`) |
|---|---|---|---|---|
| `effort` none / low / medium / high | `thinking_level`. `none` → the lowest level the model accepts: `minimal` on lite and 3.6 Flash; **`low` on 3.8 Flash and Gemini 4** (`minimal` errors) `[GMx][GT]`. Hydrogen also allows `xhigh` (not in our enum) | `reasoning_effort` low / medium / high. **`none` → `low`** (gpt-oss cannot turn reasoning off) `[QRs]` | `reasoning.effort`. `none` is valid on Luna and Terra; on Astra and 6.1 Sol `none` → `low` (400 otherwise) `[OR][OM]` | `output_config.effort` (our `effort` alias works in the installed package). `none` → `thinking: {"type": "disabled"}` **only on Haiku 5.5**; on Sonnet 5.5, Opus 5.5 and Fable 5.2 it means effort `low`, because disabled is rejected `[AT]` |
| `max_tokens` | `max_output_tokens`, which **includes thinking**: add the effort's thinking allowance to the visible cap `[GT]` | `max_completion_tokens` (the page's default is 1024: always set it) `[QRs]` | `max_output_tokens`, which includes reasoning `[OR]` | `max_tokens` (required), thinking counts toward it `[AT]` |
| `temperature`, `top_p`, `top_k` | pass through (the pages read print no guidance for Gemini 3 and 4: unverified) | `temperature` only | whether reasoning models accept `temperature` is not on the pages read (unverified): do not send it on effort above `none` | **never send** (400 from API version 2026-10-21) `[AD]` |
| Structured output | `response_mime_type: application/json` + `response_json_schema` (names from `[GMx]`). Normaliser removes keywords Gemini strips (`minLength`, `uniqueItems`); validate the rest in code `[GS]` | `with_structured_output(method="json_schema", strict=True)`, normalised so every field is `required` and every object has `additionalProperties: false` `[QS]`. **Not available together with tools** | `text.format = {type: "json_schema", strict: true}`, same normaliser; check for `refusal` `[OS]` | `output_config.format = {type: "json_schema"}`; normaliser removes recursion, `$ref` and numeric constraints, sets `additionalProperties: false`; changing it invalidates the prompt cache `[AS]` |
| Tool calling (`media.search`) | native | native, no structured output at the same time | Responses API; on Chat Completions only at effort `none` for Luna `[OM]` | native |
| Cache | implicit, nothing to send; 4,096-token minimum `[GC]` | automatic, 50% off, 2 h `[QC]` | automatic from 1,024 tokens; set `prompt_cache_key` per node and lesson so the 15-per-minute routing limit does not scatter requests `[OC]` | top-level `cache_control: {"type": "ephemeral"}` on the shared prefix; 512-token minimum (spot-check) `[AC]` |
| Timeout | client timeout per binding | same | same | same |

A new `StrictSchema` class (one responsibility: take the Pydantic model's JSON schema and return the provider's accepted subset) is the single new piece of logic; each provider profile names the rules it needs. Each rule is a small class in a list (open for extension, as `design.md` asks), not an `if provider ==` branch.

#### B. What the registry and console store

- **`LLMModel` gets:** `tier` (T0 to T4), `status` (stable, preview, deprecated), `shutdown_on` (date), `reasoning_levels` (the levels the model accepts), `reasoning_off` (how "none" is expressed: `unsupported`, `minimal`, `disabled`, `none`), `strict_structured` (bool), `min_cache_tokens`, `vision` (exists), and the existing context and output limits.
- **A `ModelPrice` table** (one row per model per validity window): input, output (thinking included), cached input, cache write, long-context threshold and prices, batch discount, `valid_from`, `valid_until` (a promo's end), `source_url`, `checked_on`. This replaces the two nullable cost columns, so a price change is a new row and old `ModelCall` rows keep the price they were billed at. One global setting holds the USD to INR rate.
- **`NodeModelBinding` gets:** `max_output_tokens`, `timeout_s` (today per node, but a Groq layer and a Gemini 3.6 Flash layer need different timeouts: 3 s against 60 s), `structured_mode` (strict, best-effort, off) and `fall_through_on` (the events in 3.2). The layer order is the existing `priority`.
- **A profile** stays a seed class in `SEED_PROFILES`, loaded by `seed_registry --profile`: `DemoRegistry`, `EconomyRegistry`, `QualityRegistry` replace `Cheap`, `Balanced` and `Quality` (decision 12). A lesson already stores a snapshot of the resolved registry, so switching profiles never changes a lesson in progress.
- **The console shows:** per binding the price, its `checked_on` date and a warning when `valid_until` or `shutdown_on` is within 60 days; per node the layer-1 pass rate, fall-through rate, tokens and cost per day; the thinking share of output tokens; and which layers are skipped for a missing key.
- **Cost per call and per thinking token.** `ModelCall` gains `cached_input_tokens`, `cache_write_tokens` and `cost_usd`; `reasoning_tokens` exists already. Cost = `(input − cached) × input price + cached × cached price + cache writes × write price + output × output price`, where **output includes thinking** (all four providers bill it as output), with the long-context and promo rows chosen by the call's date and prompt size. An invalid-output attempt is billed; a 429 is not. Thinking tokens are shown separately so the dashboard can show "what thinking costs". Whether `langchain-google-genai` reports cached tokens and `thoughtsTokenCount` is unverified: the first golden run must print one raw `usage_metadata` per provider.

#### C. Keys

Only `GEMINI_API_KEY` and `GROQ_API_KEY` exist today. **Demo, Economy and Quality layers 1 to 3 work with those two.** Every `*` layer needs `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`; until they exist the resolver skips those layers (3.2). Getting a key does not change the other layers, so the keys can be added one at a time (decision 4).

#### D. Defects in today's adapters that the design fixes

1. `AnthropicProfile.allowed_params` includes `temperature`, `top_p`, `top_k` (400 from 2026-10-21), and its `budget_tokens` control is invalid for Claude 5.x `[AT]`.
2. "Effort none" is passed as no parameter, which on Gemini and Anthropic means **the model's own default thinking**, not "off".
3. `OpenAIProfile` uses Chat Completions parameters; Luna function calling there needs effort `none`, and Astra and 6.1 Sol cannot do function calling on Chat Completions at all `[OR][OM]`.
4. Gemini 3.8 Flash and Gemini 4 reject `minimal`; the `Effort` enum has no `minimal`, so a seed asking for the lowest effort on them must map to `low`.
5. Groq strict mode is never requested (finding 3).
6. The recorder prices only `input_tokens × input + output_tokens × output` and only for models with a price (finding 2).

### 3.6 Test plan and rollout

**Unit and contract tests** (no network, in the existing style: fake chat models, `httpx.MockTransport`; each use case has a test, in `tests/llm_registry/` mirroring `backend/llm_registry/`):
- The parameter table in 3.5.A as data: for every provider and effort, the exact kwargs; every `reasoning_off` mode; `temperature` is dropped for Anthropic.
- `StrictSchema`: every Pydantic output model in `graph/schemas` passes the Groq, OpenAI, Gemini and Anthropic rules (all required, no extra properties, no recursion).
- Price arithmetic: cached split, long-context threshold, promo `valid_until`, a call on the day the promo ends, a model with no price.
- Chain resolution: layers with a missing key skipped; the escalation rule (attempt k starts at layer k); the circuit breaker; a waiting node never sleeps more than 1 s.
- Each flag in 3.3 has a test that the old behaviour stays available (`page.compile` through the model; `media.search` as an agent).

**Golden runs** (`pytest -m live`, the existing `tests/live/golden*` harness, run by a person, never in CI). The topic set covers every code path: a quantitative topic (physics), a programming topic, a humanities topic, a learner writing in Hindi, a topic with real-world images (biology), a Beginner with no quiz, and a perfect Quick check (sheets). For each profile, run: a full lesson, a 10-question quiz from a topic, a retake, the sheet pair, and grading of 20 stored answers (correct, partial, wrong and three with injected instructions).

| What is proved | Pass bar |
|---|---|
| The chain never dies | zero `AllModelsFailed` in 3 runs of every topic |
| Layer 1 is good enough | first-attempt validator pass per node: at least 85%; 70% for `interactive.generate` |
| Content quality | the judge's scores average at least 4 of 5, no major issue after one fix round; **three pages per profile read blind by a person against Quality**, with no factual error |
| Grading is fair and safe | within ±1 mark of the human reference on all 20 answers; no injected sentence changes a grade |
| Cost matches this document | measured `ModelCall.cost_usd` per flow within 30% of 3.4 |
| It is not slower | p95 latency of the Quick check and of lesson generation no worse than the first measured run of today's `Cheap` seed |

A node whose pass rate misses is promoted one tier (3.1) and that node alone is re-run.

**Rollout order** (each step is its own change on its own branch, with its own tests):
1. **Observe**: `ModelPrice`, cached and thinking tokens, `cost_usd`, the console columns. No behaviour change. Without this nothing below can be measured.
2. **Clean the registry**: remove `gemini-3.5-flash`, `gemini-2.5-*`, `llama-3.3-70b-versatile` and other retired ids; skip layers with no key; fix the six adapter defects in 3.5.D; request Groq strict JSON.
3. **Demo profile** on free tiers: golden runs prove the whole flow end to end at ₹0.
4. **Economy profile**: golden runs; then use it first for lessons paid with **free credits** (no revenue at stake), then for everyone.
5. **Mechanical steps**: `page.compile` from the template and direct media search, each behind a setting, golden-checked by the render pass rate.
6. **Escalate on retry** and `max_interactives_per_page` 2.
7. **Keys**: add OpenAI and Anthropic keys; contract-test the L4 layers only.
8. **Quality profile**: admin-selectable only, never the default (3.4).

**Safety net:** the registry is data and every lesson stores its snapshot, so a bad profile is undone by re-seeding the previous one without touching lessons in progress. Alarm when a node's layer-1 pass rate falls under 80% or the day's expected cost per lesson passes ₹6.

---

## 4. Summary

### 4.1 Node to tier to layers to settings to cost per call (Economy profile)

Settings: reasoning effort / temperature / max output tokens / timeout in seconds / retries on the layer. Cost: ₹ per typical call on layers 1, 2, 3 and 4 (₹90 per dollar, no cache hits). `*` needs an OpenAI or Anthropic key. Demo uses the same shape on free tiers; Quality is in 3.2.

| Node | Tier | L1 | L2 | L3 | L4 | effort / temp / max out / timeout s / retries | ₹ per call L1 / L2 / L3 / L4 |
|---|---|---|---|---|---|---|---|
| `topic.traits` | T0 | Groq gpt-oss-20b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | low / 0 / 256 / 4 / 0 | 0.004 / 0.015 / 0.022 / 0.005 |
| `onboarding.suggest_topics` | T0 | Groq gpt-oss-20b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | low / 0.5 / 1024 / 4 / 0 | 0.013 / 0.058 / 0.092 / 0.020 |
| `prerequisites.plan` | T0 | Groq gpt-oss-20b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | low / 0.4 / 1024 / 20 / 1 | 0.020 / 0.088 / 0.137 / 0.031 |
| `learner.assess` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | Claude Haiku 5.5* | low / 0.3 / 1024 / 30 / 1 | 0.046 / 0.097 / 0.144 / 0.035 |
| `diagnostic.generate` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | low / 0.5 / 8192 / 60 / 1 | 0.215 / 0.520 / 1.316 / 1.755 |
| `diagnostic.review` | T0 | Groq gpt-oss-20b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | low / 0 / 1024 / 20 / 1 | 0.024 / 0.092 / 0.126 / 0.035 |
| `lesson.plan` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | medium / 0.4 / 4096 / 45 / 1 | 0.111 / 0.266 / 0.675 / 0.900 |
| `page.generate` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | low / 0.5 / 4096 / 60 / 1 | 0.130 / 0.301 / 0.776 / 1.035 |
| `test.generate` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | low / 0.3 / 6144 / 60 / 1 | 0.158 / 0.376 / 0.959 / 1.278 |
| `interactive.plan` | T0 | Groq gpt-oss-20b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | low / 0.4 / 2048 / 30 / 1 | 0.028 / 0.124 / 0.193 / 0.043 |
| `media.search` | T0 | Groq gpt-oss-20b | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | low / 0.2 / 256 / 10 / 0 | 0.008 / 0.028 / 0.038 / 0.011 |
| `media.verify` | T1 | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | gpt-6-luna* | Claude Haiku 5.5* | none / 0 / 512 / 20 / 1 | 0.058 / 0.080 / 0.022 / 0.022 |
| `interactive.generate` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | Claude Sonnet 5.5* | low / 0.6 / 6144 / 60 / 1 | 0.124 / 0.292 / 0.749 / 1.998 |
| `alignment.judge` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | medium / 0 / 2048 / 60 / 1 | 0.159 / 0.286 / 0.827 / 1.103 |
| `code.repair` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | Claude Sonnet 5.5* | low / 0.2 / 3072 / 45 / 1 | 0.038 / 0.081 / 0.216 / 0.576 |
| `test.grade` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | low / 0 / 2048 / 30 / 1 | 0.046 / 0.097 / 0.260 / 0.347 |
| `study.generate` | T1 | Groq gpt-oss-120b | Gemini 3.1 Flash-Lite | Gemini 3.6 Flash | gpt-6.1-terra* | low / 0.4 / 4096 / 60 / 1 | 0.097 / 0.230 / 0.587 / 0.783 |


`page.compile` is replaced by the template. `media.search` runs only after an empty direct search.

### 4.2 Cost per lesson against revenue, by profile

Expected cost with fall-through, net revenue after 18% GST and 3% gateway fee, and the margin at the lowest-paying plan (Pro Plus). Both price lists are shown because the brief and the branch differ (decision 1).

| Profile | Cost per lesson, L1 only / expected | Net revenue, doubled prices: one-time / Weekly / Monthly / Pro Plus | Margin at Pro Plus, doubled | Net revenue, tripled prices: Weekly / Monthly / Pro Plus | Margin at Pro Plus, tripled |
|---|---|---|---|---|---|
| Demo (free tiers) | ₹0 | 16.35 / 8.01 / 6.51 / 6.08 | +₹6.08 | 12.02 / 9.76 / 9.12 | +₹9.12 (but free-tier content trains Google's models, and capacity is about 3 lessons a day per Groq model) |
| Economy, Groq-led | ₹2.06 / **₹2.80** | same | **+₹3.28 (54%)** | same | **+₹6.32 (69%)** |
| Economy, Gemini only | ₹4.63 / **₹5.67** | same | **+₹0.41 (7%)** | same | **+₹3.45 (38%)** |
| Quality, promo prices | ₹15.45 / **₹19.22** | same | −₹13.14 | same | −₹10.10 |
| Quality, from 2027-01-01 | ₹30.66 / **₹34.66** | same | −₹28.58 | same | −₹25.54 |

The target of a lesson under ₹5 to ₹6 on Economy is met (₹2.80, or ₹5.67 without Groq).

### 4.3 The ten biggest savings, ranked by rupees per lesson

Measured against today's `Cheap` seed (₹8.85 a lesson). Items 1 and 2 are alternatives, not additions.

| Rank | Saving | ₹ per lesson |
|---|---|---|
| 1 | Lead every heavy node with Groq `gpt-oss-120b` (strict JSON) and put Gemini 3.1 Flash-Lite behind it, instead of Gemini 3.5 Flash-Lite first | **5.47** |
| 2 | If Groq is unavailable: lead with Gemini 3.1 Flash-Lite instead of 3.5 Flash-Lite (output $1.50 against $2.50 per million) | 2.34 (alternative to 1) |
| 3 | At most 2 interactives per page (a setting) | 0.31 |
| 4 | Pre-write the retake question bank with a batch job (50% off) | 0.17 **per retake**, 0 per lesson |
| 5 | Strict JSON and repair in place for the Quick check (1.6 → 1.2 calls) | 0.13 |
| 6 | Search media directly; the model only on a miss (−8.5 calls) | 0.08 |
| 7 | Trim the alignment judge's input by about a third | 0.07 |
| 8 | Compile pages from the template; no model (−3 calls) | 0.06 |
| 9 | Send each page only its own plan entry | 0.04 |
| 10 | Fold `diagnostic.review` into the validator (−1 call) | 0.03 |

Savings that are not rupees but matter: dropping `gemini-3.5-flash` removes the 221 rate-limited attempts in the dev log (each could wait up to two backoffs before falling through, and its calls took 39 to 66 s when they did succeed); setting effort explicitly on every binding removes a 2 to 4 times cost swing between layers; per-node output caps remove the runaway-thinking tail.

### 4.4 Decisions for you

1. **Which price list applies?** Your brief says ₹98 / ₹398 / ₹558 (doubled); `chore/pricing-2x` now holds ₹147 / ₹597 / ₹837 (tripled, commit `897854f`). Economy without Groq earns only ₹0.41 a lesson at doubled Pro Plus. Recommend: confirm the tripled prices, or require the Groq layer.
2. **The dollar rate.** Every rupee figure uses ₹90 per dollar, which is my assumption. Give the rate you want to plan on (a single setting in the design).
3. **Check Groq in your console.** The two Groq pages disagree on the limits for `gpt-oss`: 8K tokens a minute `[QR]` against 250K `[QM]`; the Free-plan table was not readable. The Economy cost (₹2.80) depends on the larger figure, and so does whether a 4K-token request can run at all. Also check that your organisation can pay by card from India (the billing FAQ names cards, US bank accounts and SEPA, and gives India its own billing thresholds, but no list of countries). This is the only item that needs your login.
4. **Do you want OpenAI and Anthropic keys, and when?** Nothing in Demo or Economy needs them. They add a last-resort layer, and `gpt-6-luna` and Claude Haiku 5.5 ($0.10 / $0.50 per million) are as cheap as Flash-Lite, so a key is not a premium commitment. Recommend: OpenAI first (Luna sees images, so it is also a second vision layer for `media.verify`).
5. **Free tiers and learners' content.** Gemini's free tier uses submitted content to improve Google products and lets humans read it `[GTe]`; paid does not. Groq does not train on either plan `[QSA]`. Should the Demo profile run only on synthetic or consented data, and should free credits be spent on Economy (₹2.80 a lesson, real money) instead? Recommend: Demo for development and staging only.
6. **What to do with the Quality profile.** It loses money on every plan and on one-time credits, and worse after 2027-01-01. Recommend: keep it admin-selectable as a benchmark, never a default, and do not offer it to learners unless it is priced at about ₹2.35 a credit gross (promo) or ₹4.24 (after).
7. **Remove the model from `page.compile` and `media.search`?** Both are behaviour changes (a template layout instead of a model-written one; a direct search instead of an agent). They save latency and calls more than money. Recommend: yes, behind settings, golden-checked.
8. **Cap interactives at 2 per page?** It is the largest single optimisation after the model choice (₹0.31) but changes what a learner sees.
9. **Retire `gemini-3.5-flash` and the other retired ids now**, and choose the Gemini layers: 3.1 Flash-Lite as layer 2, and, for the T2 layer, **Gemini 3.6 Flash until 2026-12-31 and Gemini 4 Hydrogen after** (they cost the same after the promo, $1.50 / $7.50, and Hydrogen is the model Google points new projects to).
10. **Escalate on retry** (attempt k starts at layer k): a change in the graph's retry flow, not just the registry. Recommend: yes.
11. **Strict JSON on Groq needs every schema field to be required.** Optional fields in the Pydantic models become null unions. Accept the small schema edits this implies?
12. **Replace the `Cheap`, `Balanced` and `Quality` seed profiles with `Demo`, `Economy` and `Quality`?** The `Default` seed would be rewritten too, since it leads with a model that is not on Google's pages.
13. **Where learner content goes.** Groq keeps logs up to 30 days in US cloud buckets `[QY]`; Gemini paid and OpenAI keep abuse logs (`[GTe]`, 30 days at `[OY]`). Is that acceptable for Indian learners, and does the privacy page say it?
14. **Is the retake-bank batch job worth building now?** It saves ₹0.17 a retake; recommend deferring until retakes are a measurable share of spend.
15. **Fix the Anthropic and OpenAI adapter defects now** (3.5.D items 1 to 4), even before keys exist, because a wrong parameter is a hard 400 the first day a key is added.

---

## Appendix A. Sources (every page read on 2026-11-15)

Gemini. The `ai.google.dev` pages for pricing, rate limits and deprecations **could not be read** ("Unable to verify if domain ai.google.dev is safe to fetch"); the pages below are their redirect targets (HTTP 301) and read fine.

| Key | URL |
|---|---|
| GM | https://aistudio.google.com/docs/models (redirect from ai.google.dev/gemini-api/docs/models) |
| GMx | https://aistudio.google.com/docs/models/{gemini-4-hydrogen, gemini-4-argon, gemini-4-carbon, gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-3.1-pro-preview, gemini-3-flash-preview, gemini-2.5-flash, gemini-2.5-flash-lite, gemini-2.5-pro} |
| GP | https://aistudio.google.com/docs/pricing |
| GR | https://aistudio.google.com/docs/rate-limits |
| GT | https://aistudio.google.com/docs/thinking |
| GS | https://aistudio.google.com/docs/structured-output |
| GC | https://aistudio.google.com/docs/caching |
| GB | https://aistudio.google.com/docs/batch-api |
| GBL | https://aistudio.google.com/docs/billing |
| GTe | https://aistudio.google.com/docs/terms (effective 2026-03-23) |
| GRg | https://aistudio.google.com/docs/available-regions |

Groq (`console.groq.com`):

| Key | URL |
|---|---|
| QM | https://console.groq.com/docs/models |
| QR | https://console.groq.com/docs/rate-limits |
| QRs | https://console.groq.com/docs/reasoning |
| QS | https://console.groq.com/docs/structured-outputs |
| QC | https://console.groq.com/docs/prompt-caching |
| QB | https://console.groq.com/docs/batch |
| QD | https://console.groq.com/docs/deprecations |
| QBF | https://console.groq.com/docs/billing-faqs |
| QY | https://console.groq.com/docs/your-data |
| QSA | https://console.groq.com/docs/legal/services-agreement (last modified 2026-06-22) |
| QSL | https://console.groq.com/docs/spend-limits |

`https://groq.com/pricing` was read and has marketing text only, no price list; Groq prices come from `[QM]`.

OpenAI (`developers.openai.com`; every `platform.openai.com/docs/...` URL redirects here):

| Key | URL |
|---|---|
| OP | https://developers.openai.com/api/docs/pricing |
| OM | https://developers.openai.com/api/docs/models, and /models/gpt-6-luna, /models/gpt-6.1-terra, /models/gpt-5.6-luna |
| OR | https://developers.openai.com/api/docs/guides/reasoning |
| OS | https://developers.openai.com/api/docs/guides/structured-outputs |
| OC | https://developers.openai.com/api/docs/guides/prompt-caching |
| OB | https://developers.openai.com/api/docs/guides/batch |
| ORL | https://developers.openai.com/api/docs/guides/rate-limits |
| OD | https://developers.openai.com/api/docs/deprecations |
| OY | https://developers.openai.com/api/docs/guides/your-data |
| OSC | https://developers.openai.com/api/docs/supported-countries |

Anthropic (`platform.claude.com`; the `docs.anthropic.com/en/docs/...` and `/en/api/...` URLs redirect here, and the sub-pages for thinking, structured outputs, caching, batch and deprecations failed there with no output but read on the new domain):

| Key | URL |
|---|---|
| AM | https://platform.claude.com/docs/en/about-claude/models/overview |
| AP | https://platform.claude.com/docs/en/about-claude/pricing (the first 40K of 55K characters verbatim) |
| AR | https://platform.claude.com/docs/en/api/rate-limits |
| AT | https://platform.claude.com/docs/en/build-with-claude/thinking |
| AE | https://platform.claude.com/docs/en/build-with-claude/effort |
| AS | https://platform.claude.com/docs/en/build-with-claude/structured-outputs |
| AC | https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
| AB | https://platform.claude.com/docs/en/build-with-claude/batch-processing |
| AD | https://platform.claude.com/docs/en/about-claude/model-deprecations |
| AX | https://www.anthropic.com/supported-countries (effective 2026-11-12) |
| AY | https://www.anthropic.com/legal/commercial-terms (effective 2025-06-17) |

Repository sources: `backend/llm_registry/*`, `backend/graph/*`, `backend/onboarding/topic_model.py`, `backend/quizzes/traits.py`, `docs/architecture/credits-system.md`, the dev database's `llm_registry_modelcall` table (532 rows, 2026-10-24 to 2026-11-15), the installed `langchain-google-genai` 4.4.0, `langchain-groq` 1.1.3, `langchain-openai` 1.6.6 and `langchain-anthropic` 1.7.4 packages, and the branch `chore/model-costs` (read for `a072030`, the repair-in-place commit).

How the pages were read: through a fetch tool that returns the page text. On long pages it returns the first 40K characters verbatim and a model-written summary of the rest; facts that came from such a summary are marked "summary" in the text.

## Appendix B. Everything marked "(unverified)"

- **Gemini:** free-tier and Tier 1 RPM, TPM and RPD for every text model (the page defers to a login-only console page); INR and the accepted payment methods; the REST (camelCase) names for thinking and JSON schema, and the usage field for thinking tokens; whether the lite models have a minimum cache size; any temperature guidance for Gemini 3 and 4; whether `langchain-google-genai` reports cached and thinking tokens.
- **Groq:** which of two disagreeing tables is the Developer plan's (8K or 250K TPM), and the Free-plan table; whether India is a supported billing country; how reasoning tokens are billed; whether strict JSON works with reasoning; the cache's minimum size; whether `gpt-oss` reasoning can be turned off (inferred from the page, not stated).
- **OpenAI:** free-tier RPM and TPM; limits for the cheap models by tier beyond Luna and Terra; payment methods and INR; whether reasoning models accept `temperature`.
- **Anthropic:** the usage field for thinking tokens; whether the SDK sends API version 2026-10-21; Haiku 5.5's image input; the 512-token cache minimum (summary, "spot-check"); a free tier (none described).
- **This document's own estimates:** token counts for nodes with no live rows (`diagnostic.review`, `prerequisites.plan`, `media.verify`, `runtime.repair`, `onboarding.suggest_topics`, quiz, retake, sheets); the per-layer failure rates; the call counts after the changes in 3.3; the 35% judge-input and 15% diagnostic-output trims; ₹90 per dollar.
