# Enabling incoming A2A on the Foundry hosted agent

This document records how AiraCare's **Foundry hosted agent** (`airacare-care-orchestrator`) is
exposed as a standard **Agent2Agent (A2A)** endpoint so the **edge speaks A2A directly to it** —
retiring the bespoke `foundry-a2a-server` (the local stdlib JSON-RPC shim). It is both the runbook
for reproducing the enablement and the design note for how determinism is preserved over A2A.

> Status: **incoming A2A enabled and verified** on the live agent (agent card published, `a2a`
> protocol added). The deterministic considered-assessment middleware that makes the hosted agent
> the sole authority for the risk level ships in the next deploy (see
> [§6 Deploy dependency](#6-deploy-dependency)).

---

## 1. Why

Originally the edge talked to a local `foundry-a2a-server` process that spoke a *bespoke* JSON-RPC
contract (`airacare.report` / `airacare.fetch_policy`) and did the deterministic considered
assessment + Cosmos writes itself, then forwarded a text block to the cloud hosted agent for the
warm caregiver briefing. That is two hops and two codebases for one logical cloud brain.

**Option C** collapses this: the edge speaks **standard A2A** straight to the Foundry hosted agent,
and the hosted agent becomes the single cloud brain — it owns both the **deterministic** care
domain (considered level + escalation ladder, computed in pre-model middleware) and the
**advisory** conversational briefing (the model). The standalone `foundry-a2a-server` is retired.

## 2. Prerequisites (all satisfied here)

- A deployed agent in Foundry Agent Service that uses the **responses protocol**. Incoming A2A
  requires it. Ours qualifies: `azure.yaml` declares `protocols: [responses 2.0.0]` and `main.py`
  serves via `ResponsesHostServer`. (Prompt agents support responses by default; a *hosted* agent
  must be built for it — ours is.)
- Azure role **Foundry User** or higher on the Foundry project (to author the card / enable A2A).
- For *callers* (the edge): role **Foundry Agent Consumer** or higher on the project, presenting a
  Microsoft Entra token. Anonymous and key-based access are **not** supported.

## 3. Enable it (the one PATCH)

Enabling incoming A2A is a single control-plane `PATCH` that does two things at once: authors the
**agent card** (what other agents discover) and adds **`a2a`** to the endpoint's protocol
configuration (alongside the existing `responses`). It is REST/SDK only — not yet in the portal.
Authoring the agent card is **REST-only** (the Python SDK can toggle the protocol but not set the
card).

Our concrete values:

| Setting | Value |
|---|---|
| Base URL | `https://cog-jo2jqgwc7xe2m.services.ai.azure.com/api/projects/airacare-agent` |
| Agent name | `airacare-care-orchestrator` |
| Subscription | `d850e6bf-8390-4eee-b886-d750638fbd72` |
| Resource group | `rg-airacare-agent` |
| Foundry account | `cog-jo2jqgwc7xe2m` |
| Token resource | `https://ai.azure.com` |

```powershell
$base  = "https://cog-jo2jqgwc7xe2m.services.ai.azure.com/api/projects/airacare-agent"
$agent = "airacare-care-orchestrator"
$tok   = az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv

$body = @{
    agent_card = @{
        description = "AiraCare's advisory cloud care-orchestrator ..."   # see the live card
        version     = "1.0"
        skills = @(
            @{ id = "considered-care-assessment"; name = "Considered care assessment"
               description = "Accepts a privacy-scrubbed daily-living event and returns the deterministic considered risk level (L0-L3), escalations, and the considered-assessment JSON block the edge parses." },
            @{ id = "caregiver-briefing"; name = "Caregiver briefing"
               description = "Composes reassuring, plain-language recaps grounded only in recorded, derived events." }
        )
    }
    agent_endpoint = @{
        protocol_configuration = @{ responses = @{}; a2a = @{} }   # keep responses, add a2a
    }
} | ConvertTo-Json -Depth 6

Invoke-RestMethod -Method Patch -Uri "$base/agents/$agent`?api-version=v1" `
    -Headers @{ Authorization = "Bearer $tok" } -ContentType "application/json" -Body $body
```

After the PATCH the endpoint reports `protocols: ["a2a", "responses"]`.

## 4. The live A2A URLs (after enabling)

All require a Microsoft Entra token (Foundry Agent Consumer+). Anonymous access is rejected.

- **A2A base path** (JSONRPC endpoint the edge POSTs to):
  `…/agents/airacare-care-orchestrator/endpoint/protocols/a2a`
- **Agent card v1.0** (recommended — the edge points its resolver here):
  `…/agents/airacare-care-orchestrator/endpoint/protocols/a2a/agentCard/v1.0`
- **Agent card v0.3**: `…/endpoint/protocols/a2a/agentCard/v0.3`

**Version negotiation.** Foundry serves both versions on the same base path. If the caller doesn't
specify, Foundry defaults to **v0.3**. The edge must pin **v1.0** in one of three ways: fetch the
`agentCard/v1.0` card (most A2A SDKs then negotiate v1.0 automatically), set header
`A2A-Version: 1.0`, or append `?a2a-version=1.0`.

**Verified live card** (fetched from `agentCard/v1.0`):

```jsonc
{
  "name": "airacare-care-orchestrator",
  "version": "1.0",
  "supportedInterfaces": [
    { "protocolBinding": "JSONRPC",   "protocolVersion": "1.0", "url": ".../protocols/a2a" },
    { "protocolBinding": "JSONRPC",   "protocolVersion": "0.3", "url": ".../protocols/a2a" },
    { "protocolBinding": "HTTP+JSON", "protocolVersion": "0.3", "url": ".../protocols/a2a" }
  ],
  "capabilities": { "streaming": false, "pushNotifications": false },
  "defaultInputModes":  ["text"],
  "defaultOutputModes": ["text"],
  "skills": [ { "id": "considered-care-assessment", ... }, { "id": "caregiver-briefing", ... } ]
}
```

## 5. Constraints that shaped our design

The Foundry incoming-A2A preview has limits that our architecture already respects:

- **Text modality only.** File/binary/nontext parts aren't supported. AiraCare only ever sends the
  derived, privacy-scrubbed `DailyLivingEvent` — never raw audio/video/point-cloud — so text is
  sufficient. The event and the considered verdict both travel as delimited JSON text blocks.
- **No streaming (SSE).** The response is always non-streaming, so the hosted agent's middleware
  can deterministically **append** the considered-assessment block to `context.result.messages`
  after the model runs (`result.messages` is a plain `list[Message]`). This is what makes the
  text-block channel reliable rather than dependent on A2A DataPart projection.
- **v1.0 is JSONRPC-only** (HTTP+JSON is v0.3-only). The edge client uses JSONRPC for v1.0.
- **Preview** — not recommended for production workloads yet.

### How determinism survives the A2A hop

The model is **advisory only**. The safety-critical verdict is computed by pure Python
(`airacare_care`, pydantic+stdlib) in **pre-model middleware** and carried back to the edge in a
delimited text block the edge parses deterministically — independent of anything the LLM writes:

```
edge --A2A message/send--> hosted agent
  [ConsideredAssessmentMiddleware]  (pre-model)
     - parse the "DAILY EVENT RECORD (JSON)" block from the caregiver turn
     - read patient_state from Cosmos
     - ConsideredAssessor.assess(event, state)  -> considered level (L0-L3)  [deterministic]
     - EscalationAgent.handle(...)              -> ack-tracked ladder for L3 [deterministic]
     - stash verdict on context.metadata
  [DailyEventPersistenceMiddleware] (pre-model)
     - write daily_event to Cosmos with the deterministic considered level
  [model runs] -> warm, plain-language caregiver briefing (advisory)
  [ConsideredAssessmentMiddleware, post-model]
     - append "CONSIDERED ASSESSMENT (JSON)" block to result.messages
edge <--A2A response-- hosted agent
  - edge parses the "CONSIDERED ASSESSMENT (JSON)" block -> authoritative considered level
```

Because the edge already acted locally in real time, none of this is on the safety path — the
cloud verdict refines the record and drives caregiver escalation, it never gates the edge.

## 6. Deploy dependency

Enabling A2A (this document) is a **control-plane** change on the existing deployment (currently
**v6**). The `ConsideredAssessmentMiddleware` + `render` block that make the hosted agent the sole
deterministic authority are **code** changes (see the `airacare_care` package and `main.py`) that
ship in the **next deploy**. Until that deploy, the A2A endpoint is live but answers with the v6
behavior (advisory briefing + deterministic Cosmos persistence, but the considered level is taken
from the forwarded record rather than recomputed here). Redeploying the hosted agent with the new
middleware is required before the edge is flipped to standard A2A (Phase 3) — that deploy is a
gated Azure step.

## 7. Caller (edge) shape — Phase 3 preview

The edge will present an Entra token (Foundry Agent Consumer role), point an A2A card resolver at
`agentCard/v1.0` (so it negotiates v1.0 / JSONRPC), and `message/send` the caregiver turn carrying
the `DAILY EVENT RECORD (JSON)` block. It parses the returned `CONSIDERED ASSESSMENT (JSON)` block
for the authoritative considered level and reads the briefing prose for the caregiver. This
replaces the edge's current bespoke `A2AClient` (the `airacare.report` JSON-RPC shim) — the
retirement of `foundry-a2a-server` in Phase 4.

## References

- MS Learn — *Enable incoming A2A on a Foundry agent (preview)*.
- `foundry-hosted-agent/src/airacare-care-orchestrator/main.py` — the middleware pipeline.
- `foundry-hosted-agent/src/airacare-care-orchestrator/airacare_care/` — the deterministic domain.
