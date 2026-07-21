# Microsoft Foundry — Friction Log (AiraCare)

A candid engineering friction log from building **AiraCare**, a hybrid edge–cloud guardian for
in-home Alzheimer's care, on the **Microsoft Foundry** platform. It records what we actually hit
while taking the cloud "care-orchestrator" from a local stub to a **deployed Foundry Hosted Agent**
that the edge talks to over the **standard A2A protocol**, grounded by a **Foundry IQ** knowledge
base and persisting to **Cosmos DB via Managed Identity**.

This is written for the platform team and hackathon judges: concrete, reproducible, and honest.
Dates/versions reflect the July 2026 preview state we worked against.

**What we built on Foundry (for context):**
- A **Hosted Agent** (`airacare-care-orchestrator`) on the **Microsoft Agent Framework**, served via
  `ResponsesHostServer`, deployed with **`azd`** (`microsoft.foundry` infra provider).
- **Incoming A2A** enabled on that agent so the edge speaks **standard A2A** (`message/send` +
  `tasks/get`) directly — retiring a bespoke local JSON-RPC shim.
- **Deterministic pre-model middleware** (pure Python) that computes the L0–L3 risk verdict, so the
  **LLM stays advisory** and never sets the safety level.
- **Foundry IQ** agentic RAG over a dementia-care guideline corpus (Azure AI Search underneath),
  surfaced to the agent as a `search_care_guidelines` tool with citations.
- **Cosmos DB** persistence and a read-only live dashboard off the safety path.

---

## ✅ What worked well

- **The `azd` hosted-agent flow is genuinely good once installed.** `azd provision` → `azd ai agent
  run` (local, port 8088) → `azd deploy` → `azd ai agent invoke "<prompt>"` → `azd ai agent monitor
  --follow` is a clean, coherent inner loop. Being able to run the *same* agent container locally
  before deploying removed a lot of guesswork.
- **The Agent Framework hosting contract is small and predictable.** `FoundryChatClient(project_endpoint,
  model, credential=DefaultAzureCredential())` + `ResponsesHostServer(agent).run()` is about all the
  boilerplate there is. The `Dockerfile` (`python:3.12-slim`, `EXPOSE 8088`, `CMD python main.py`) is
  trivial. We had a hosted agent answering in well under a day of coding.
- **Pre-model / post-model middleware is the feature that made our safety story possible.** Because
  the response is non-streaming, our `ConsideredAssessmentMiddleware` can deterministically compute
  the verdict *before* the model runs and **append** a `CONSIDERED ASSESSMENT (JSON)` block to
  `result.messages` *after* it runs. The safety-critical level is pure Python; the LLM only narrates.
  This clean separation is exactly what a care/safety product needs, and Foundry accommodated it.
- **Standard A2A interop is real.** Enabling incoming A2A let us **delete an entire codebase** (our
  bespoke `foundry-a2a-server` JSON-RPC shim). The edge now points an A2A card resolver at the
  published agent card and just works with off-the-shelf A2A SDKs.
- **Managed Identity to Cosmos worked cleanly** once RBAC was assigned — no keys in the agent.
- **Foundry IQ's `retrieve` is GA and returns citations.** Agentic retrieval (2026-04-01 Search REST)
  gave us grounded, cited guideline snippets that map directly onto a `@tool`, which is precisely the
  shape a caregiver-facing agent needs (advice you can trace to a source).
- **Connected/specialist agents as tools** (`Agent.as_tool`) composed naturally for our multi-agent
  narrator.

## 🤔 What was confusing

- **Two overlapping `azd` extensions with unclear boundaries.** The infra provider is
  `microsoft.foundry`, but the `azd ai agent ...` *commands* come from `azure.ai.agents`. The docs
  reference both and it's not obvious which you need or which version. We resolved it empirically with
  `azd ext list` after install rather than from documentation.
- **"Responses agent" vs "A2A agent" is a prerequisite you learn the hard way.** Incoming A2A
  *requires* the agent already be built for the **Responses protocol**. That coupling ("to expose A2A
  you must first be a responses host") isn't obvious up front — you discover it when enabling A2A.
- **Enabling incoming A2A is REST/SDK-only and split across two concerns in one call.** There's **no
  portal UI**. It's a single control-plane `PATCH` that simultaneously (a) authors the **agent card**
  and (b) adds `a2a` to `protocol_configuration`. Worse: the **Python SDK can toggle the protocol but
  cannot author the agent card** — card authoring is **REST-only**. Having capability split across SDK
  and raw REST for one logical operation was the single most confusing part of the whole integration.
- **A2A version negotiation defaults surprised us.** Foundry serves both **v0.3 and v1.0** on the same
  base path and **defaults to v0.3** if the caller doesn't specify. Pinning v1.0 requires one of three
  non-obvious mechanisms (fetch `agentCard/v1.0`, send header `A2A-Version: 1.0`, or append
  `?a2a-version=1.0`). Additionally **v1.0 is JSONRPC-only** while **HTTP+JSON is v0.3-only** — a
  protocol-binding matrix you have to internalize.
- **`404 DeploymentNotFound` that is actually an auth problem.** When the AI Search managed identity
  lacked data-plane access to the embedding model, Azure OpenAI returned **404 (not 403)**. We spent
  real time chasing a "missing deployment" that existed and worked fine with a user token. A 403 would
  have pointed us at RBAC immediately.
- **Foundry IQ API-version capability tiers aren't obvious.** `2026-04-01` is minimal/extractive; LLM
  query-planning and answer-synthesis need `2026-05-01-preview`. And the `retrieve` body silently
  needs `{"type": "semantic", ...}` in each intent — omit it and you get a `400` with little guidance.

## 🐌 What slowed us down

- **`azd` wasn't installed and the init flow is interactive.** `azd` is a hard blocker for the whole
  pivot, and `azd ai agent init` is an **interactive prompt sequence** (agent name, project, tenant,
  sub, region, model, SKU, capacity…) that's painful to drive from automation/CI. We abandoned `init`
  and **manually scaffolded** the azd project from the Basic sample, then drove `azd env set` +
  `azd provision` / `azd deploy` non-interactively. That was the right call but cost us time to
  discover.
- **Foundry IQ embedding ingestion: the multi-day `DeploymentNotFound` saga.** The Search indexer's
  embedding skill got `404 DeploymentNotFound` calling the embedding deployment **as the Search MI**,
  even though the exact same endpoint returned `200` with our user token and the MI had both
  *Cognitive Services User* and *Cognitive Services OpenAI User*. Contributing factors that each cost
  time to rule in/out:
  - **RBAC propagation lag** (~10+ minutes) for the Search managed identity.
  - **Cross-region split** — AI Search **Basic was out of capacity in `eastus2`**, so it landed in
    **`eastus`** while the Foundry account/embeddings were in `eastus2`. Cross-region is *allowed* but
    became a prime suspect and muddied diagnosis.
  - **`disableLocalAuth: true`** on the Foundry account meant we **couldn't fall back to an API key**
    in the embedding skill (a workaround that exists for other skills), forcing MI auth to work.
- **Indexer change-tracking high-water mark.** After a failed ingestion, re-running the indexer
  processes **0 items**. You must `POST /indexers/{name}/reset` *then* run to reprocess — non-obvious,
  and easy to think "nothing changed" when really nothing was retried.
- **SDK gaps pushed us to raw REST.** `azure-search-documents 12.0.0` ships `KnowledgeBase` /
  `AzureBlobKnowledgeSource` models, but they use opaque typespec fields (empty `_attribute_map`), so
  serialization didn't round-trip. We rewrote provisioning against the **REST API with `requests`**.
  Same story on the agent side (card authoring is REST-only). We wrote more raw REST than expected.
- **Region capacity roulette.** Beyond Search, capacity/SKU availability shaped *where* things could
  live and forced the cross-region layout that then complicated the embedding auth debugging.
- **Environment/tooling paper cuts.** Each shell needed a manual PATH refresh for `az`/`azd`; piped
  Python output buffered during long provisioning polls (no incremental progress unless you
  `flush=True`); these are small but add up during a time-boxed hackathon.

## 🧩 Missing capabilities / wishlist

- **Portal (or single-SDK) support for enabling incoming A2A + authoring the agent card.** Today it's
  REST-only for the card and SDK-partial for the protocol toggle. One first-class path (portal *and*
  complete SDK) would remove the biggest sharp edge we hit.
- **A2A streaming (SSE).** The preview is **non-streaming only**. It happens to enable our deterministic
  append trick, but for conversational caregiver briefings we'd want token streaming without losing the
  ability to attach a trusted structured block.
- **Richer A2A modality than text.** Preview is **text-only** (no file/binary parts). Fine for us (we
  intentionally send only a scrubbed `DailyLivingEvent`, never raw audio/video), but a real limit for
  agents that need to exchange artifacts.
- **A cloud→edge control channel / policy feedback loop.** We designed "cloud refines edge policy over
  time," but there's no built-in downstream/push path, so `fetch_policy` is currently a no-op and the
  agent always reports `policy_version = 1`. A2A `pushNotifications` is advertised as a capability but
  `false` in preview. First-class support for an agent handing structured guidance *back* to a caller
  would directly unlock our learning loop.
- **Native, GA knowledge-base binding for hosted agents.** The direct Foundry-agent KB reference is
  **portal/preview-only**, which pushed us to the code-first `@tool` calling `retrieve`. Good that the
  code path exists, but a GA declarative binding would be simpler and less brittle.
- **Clearer auth error semantics.** `404 DeploymentNotFound` for a data-plane RBAC gap (instead of
  `403`) actively misleads. A distinct, actionable error for "identity lacks data-plane access" would
  have saved hours.
- **SDK models that actually serialize.** `azure-search-documents` knowledge-base/knowledge-source
  models with empty attribute maps should either work or not ship; right now they invite a REST detour.
- **Tighter, converged `azd` extension story + non-interactive `init`.** One extension (or crisp docs
  on which is which) and a fully flag-driven `azd ai agent init` would make the flow CI-friendly.
- **Tracing/observability out of the box.** We leaned on `azd ai agent monitor` logs; first-class
  request/trace visibility for the A2A + middleware pipeline would help debug the exact
  pre-model/post-model boundary our safety design depends on.

---

### Bottom line

Foundry let a two-person team stand up a **deployed, A2A-interoperable, knowledge-grounded hosted
agent with a deterministic safety core** in hackathon time — the hosting contract and middleware model
are real strengths, and standard A2A let us delete code. The friction was concentrated in **preview
edges**: A2A enablement being REST-only and version-finicky, Foundry IQ embedding auth across regions
with `disableLocalAuth`, SDKs that don't yet serialize, and misleading `404` auth errors. None were
blockers we couldn't engineer around, but each cost disproportionate time relative to the happy path.

*Filed against the Foundry state as of July 2026.*
