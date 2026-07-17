# Copyright (c) Microsoft. All rights reserved.
"""AiraCare — Foundry Hosted Agent entrypoint (Responses protocol).

This is the cloud **care-orchestrator** graduated onto the Microsoft Agent Framework and hosted by
Azure AI Foundry Agent Service. A caregiver or clinician converses with it (Responses API); the
orchestrator consults five connected specialists — risk-reasoning, knowledge, escalation,
cognitive-trend, briefing — each wrapped as a tool, grounds care guidance in a
**Foundry IQ** knowledge base (agentic retrieval over Azure AI Search) via the
``search_care_guidelines`` tool, and can look up the patient's real filed events / state from
Cosmos DB and save an advisory briefing back.

Safety discipline: the model is **advisory only**. It never sets or second-guesses the risk
level and never triggers alerts. The considered level and the ack-tracked escalation ladder are
computed **deterministically** by the ported ``airacare_care`` domain (a pure pydantic/stdlib
package the model can never front) in pre-model middleware. Any ``considered_level`` is
authoritative and is restated verbatim. No diagnosis, no medication changes.

Data access (least privilege, AAD only — no keys):
- **Deterministic assessment + escalation (the safety-critical verdict).** The edge speaks
  standard A2A to this hosted agent, forwarding each privacy-scrubbed event as a
  ``DAILY EVENT RECORD (JSON)`` block in the caregiver turn. ``ConsideredAssessmentMiddleware``
  runs BEFORE the model on **every** turn: it reads the patient's stored state, computes the
  considered ``CloudAssessment`` with ``ConsideredAssessor``, starts the L3 escalation ladder, and
  appends a delimited ``CONSIDERED ASSESSMENT (JSON)`` block to the response so the edge parses the
  authoritative verdict back — independent of anything the advisory-only LLM decides.
- **Deterministic persistence (the safety-critical write).** ``DailyEventPersistenceMiddleware``
  writes the forwarded record to the ``daily_event`` container BEFORE the model runs, stamping the
  deterministic considered level. This hosted agent owns persistence; the stored item is
  schema-compatible with ``foundry-a2a-server``'s ``CosmosEventStore.append`` so the live care
  dashboard reads it.
- Reads the **same** Cosmos containers it writes (``daily_event``, ``patient_state``), surfacing
  only derived, privacy-scrubbed facts (event type, timestamp, considered level, patient
  name/stage) — never raw audio/video/transcripts or the voice-biomarker feature vector.
- Also writes advisory ``care_briefing`` notes (agent-authored). It never mutates the authoritative
  ``patient_state`` records.
- If ``AIRACARE_COSMOS_ENDPOINT`` is unset, the data tools and the middleware degrade gracefully
  (the considered level still computes from the event + a safe default state; persistence is
  skipped), so the agent still runs as a stateless advisor.

This hosted agent is the single cloud brain: the deterministic care domain plus the advisory
conversational surface, reached by the edge over standard A2A.

Runtime contract (from the Foundry Agent-Framework Responses sample):
- ``FoundryChatClient`` reaches the Foundry **project** endpoint (``FOUNDRY_PROJECT_ENDPOINT``)
  with ``DefaultAzureCredential`` (Managed Identity in the container; ``az login`` locally) — no key.
- ``ResponsesHostServer(agent).run()`` serves ``POST /responses`` on port 8088; the hosting
  infrastructure manages conversation history, so ``default_options={"store": False}``.
"""

import json
import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from agent_framework import Agent, AgentContext, AgentMiddleware, Message, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Deterministic care domain (pure pydantic/stdlib — never fronted by the advisory model). This is
# the safety-critical logic ported out of the standalone foundry-a2a-server when the edge moved to
# speaking standard A2A directly to this hosted agent: the considered level and the ack-tracked
# escalation ladder are computed by this Python in middleware, BEFORE the model runs.
from airacare_care import (
    ConsideredAssessor,
    DailyLivingEvent,
    EscalationAgent,
    PatientState,
    render_assessment_block,
)

# Load environment variables from a local .env when present (no-op in the container).
load_dotenv()


# --------------------------------------------------------------------------------------------
# The five DELIBERATE-tier Connected Agents, as (name, role, instructions) descriptors. Ordering
# and wording mirror connected_agent_specs() in the main package so the hosted brain matches the
# offline one. Each is exposed to the orchestrator as a tool.
# --------------------------------------------------------------------------------------------

_SPECIALISTS: list[dict[str, str]] = [
    {
        "name": "risk_reasoning",
        "role": "Fuse the reported event with patient state into a considered risk level.",
        "instructions": (
            "Given a scrubbed daily-living event and any patient context, explain the considered "
            "risk level (L0-L3). Never de-escalate below the level already assessed at the edge "
            "(safety floor). If a considered level is stated, restate it exactly and justify it; "
            "do not invent a new one."
        ),
    },
    {
        "name": "knowledge",
        "role": "Ground caregiver advice in established dementia care guidelines.",
        "instructions": (
            "You MUST call the search_care_guidelines tool with a short description of the "
            "situation before answering, and base your guidance on the passages it returns, citing "
            "the source guideline names it provides. Offer brief, practical, evidence-aligned "
            "dementia-care guidance relevant to the situation, with a short rationale. If the tool "
            "returns nothing clearly relevant (or is unavailable), say so briefly and give only "
            "general, clearly-labelled advice rather than speculating."
        ),
    },
    {
        "name": "escalation",
        "role": "Explain the ack-tracked family -> community -> emergency escalation ladder.",
        "instructions": (
            "For a high-risk (L3) situation, explain the timed escalation ladder — family first, "
            "then community, then emergency — and how an acknowledgement resolves a rung. You "
            "describe the ladder; you never trigger it. Below L3, note that no escalation is due."
        ),
    },
    {
        "name": "cognitive_trend",
        "role": "Interpret the patient's cognitive trajectory over time.",
        "instructions": (
            "If the caregiver describes trends over days or weeks, summarise whether things appear "
            "improving, stable, or declining, in plain language. Do not fabricate data points; "
            "reason only over what is provided."
        ),
    },
    {
        "name": "briefing",
        "role": "Compose the family daily recap and the clinician roll-up.",
        "instructions": (
            "When asked to summarise, produce either a reassuring family recap or a concise "
            "clinical roll-up (counts and notable events), matching the audience the caregiver asks "
            "for. Warm and clear for family; factual and structured for clinicians."
        ),
    },
]


_ORCHESTRATOR_INSTRUCTIONS = (
    "You are AiraCare's cloud care-orchestrator, a warm conversational assistant for the family "
    "caregivers and clinicians of an in-home Alzheimer's patient. You help them understand "
    "privacy-scrubbed daily-living events and decide gentle next steps.\n\n"
    "Hard rules (safety — never break these):\n"
    "1. You are ADVISORY ONLY. You never decide or change the risk level and you never trigger "
    "alerts or escalation. Any considered level (L0-L3) — whether the caregiver states it or you "
    "read it from the event store — is authoritative: restate it EXACTLY and never raise, lower, "
    "or second-guess it.\n"
    "2. Use ONLY facts the caregiver provides or that you read via the data tools. Do not invent "
    "events, vitals, names, medications, or history. If you need a detail, ask.\n"
    "3. No diagnosis and no medication changes. For anything urgent or medical, advise contacting "
    "the appropriate professional or emergency services.\n"
    "4. Never request or handle raw audio, video, images, or transcripts — reason only over the "
    "derived facts described to you or returned by the tools.\n\n"
    "Data tools: when the caregiver refers to a specific patient (by id, e.g. 'p-001'), you may "
    "call fetch_recent_events and fetch_patient_state to ground your answer in their real filed "
    "history, and log_care_briefing to save a short advisory recap for the record. Saving a "
    "briefing is just a note — it never changes the patient's care, risk level, or escalation. "
    "When a report includes a DAILY EVENT RECORD (JSON), that event has ALREADY been filed to the "
    "care record automatically before you saw it — you do not need to save it, and the considered "
    "level in it is authoritative. "
    "Before giving any care guidance, call search_care_guidelines (or delegate to the knowledge "
    "specialist, which uses it) so the advice is grounded in the dementia-care guideline knowledge "
    "base and cite the source guideline names it returns.\n\n"
    "Consult the specialist tools (risk_reasoning, knowledge, escalation, cognitive_trend, "
    "briefing) as helpful for the caregiver's question, passing along the relevant "
    "situation. Then reply with a short, warm, plain-language message: acknowledge what happened, "
    "restate the considered level and why it stands (when one is given), note what has already been "
    "done, and offer one gentle, practical next step. Do not include internal tool chatter."
)


# --------------------------------------------------------------------------------------------
# Cosmos DB data access (least privilege, AAD only). Reads the same containers the edge/A2A
# pipeline writes; writes only to the dedicated care_briefing container. Built lazily so the agent
# still starts (and the specialist tools still work) when Cosmos is not configured.
# --------------------------------------------------------------------------------------------

_COSMOS_ENDPOINT = os.getenv("AIRACARE_COSMOS_ENDPOINT", "")
_COSMOS_DATABASE = os.getenv("AIRACARE_COSMOS_DATABASE", "airacare")
# Cosmos authentication, in order of precedence:
#   1. AIRACARE_COSMOS_KEY            — an explicit account key (dev/manual override).
#   2. Key Vault secret               — AIRACARE_COSMOS_KEY_VAULT_URI + AIRACARE_COSMOS_KEY_SECRET:
#      the key is fetched at first use with the running identity's AAD token (Managed Identity in
#      the container / az login locally). This is how the deployed hosted agent gets its key without
#      any secret in its environment.
#   3. AAD / Managed Identity direct  — used when neither of the above is set; works wherever the
#      running identity holds a Cosmos SQL data-plane role.
# The deployed Foundry hosted agent authenticates as a ``ServiceIdentity`` principal that Cosmos
# data-plane RBAC rejects, so it cannot use path 3 for Cosmos; it uses path 2 (that same identity
# *can* be granted Azure RBAC on Key Vault, so it fetches the key with MI and no secret in its env).
_COSMOS_KEY = os.getenv("AIRACARE_COSMOS_KEY", "")
_COSMOS_KEY_VAULT_URI = os.getenv("AIRACARE_COSMOS_KEY_VAULT_URI", "")
_COSMOS_KEY_SECRET = os.getenv("AIRACARE_COSMOS_KEY_SECRET", "airacare-cosmos-primary-key")
_DAILY_EVENT_CONTAINER = "daily_event"
_PATIENT_STATE_CONTAINER = "patient_state"
_CARE_BRIEFING_CONTAINER = "care_briefing"

# --------------------------------------------------------------------------------------------
# Foundry IQ knowledge base (agentic retrieval over Azure AI Search) for grounded, cited care
# guidance. Query-time auth is keyless: the running identity calls the Search "retrieve" endpoint
# with its AAD token (needs *Search Index Data Reader* on the service). If the search endpoint is
# unset the knowledge tool degrades gracefully and the specialist answers from its own knowledge.
# --------------------------------------------------------------------------------------------
_SEARCH_ENDPOINT = os.getenv("AIRACARE_SEARCH_ENDPOINT", "").rstrip("/")
_SEARCH_KB = os.getenv("AIRACARE_SEARCH_KB", "airacare-care-kb")
_SEARCH_KS = os.getenv("AIRACARE_SEARCH_KS", "airacare-guidelines-ks")
_SEARCH_API = "2026-04-01"
_SEARCH_SCOPE = "https://search.azure.com/.default"

# Shared AAD credential (also used by FoundryChatClient) and a cached Cosmos database client.
_CREDENTIAL: DefaultAzureCredential | None = None
_COSMOS_DB: Any = None


def _credential() -> DefaultAzureCredential:
    global _CREDENTIAL
    if _CREDENTIAL is None:
        _CREDENTIAL = DefaultAzureCredential()
    return _CREDENTIAL


def _cosmos_key() -> str:
    """Resolve the Cosmos account key from an env override or Key Vault; '' when neither applies."""
    if _COSMOS_KEY:
        return _COSMOS_KEY
    if _COSMOS_KEY_VAULT_URI:
        # Fetch with the running identity's AAD token (Managed Identity in the container).
        from azure.keyvault.secrets import SecretClient  # lazy: only when KV-backed key is used

        secret = SecretClient(_COSMOS_KEY_VAULT_URI, _credential()).get_secret(_COSMOS_KEY_SECRET)
        return secret.value or ""
    return ""


def _cosmos_db() -> Any:
    """Return a cached Cosmos database client, or None when Cosmos is not configured/available."""
    global _COSMOS_DB
    if not _COSMOS_ENDPOINT:
        return None
    if _COSMOS_DB is None:
        from azure.cosmos import CosmosClient  # lazy: only needed when the data tools are used

        # A resolved key (explicit or Key-Vault-backed) takes precedence; otherwise use AAD/Managed
        # Identity directly (the default, no-key path used locally and by MI-capable identities).
        key = _cosmos_key()
        if key:
            client = CosmosClient(_COSMOS_ENDPOINT, credential=key)
        else:
            client = CosmosClient(_COSMOS_ENDPOINT, _credential())
        _COSMOS_DB = client.get_database_client(_COSMOS_DATABASE)
    return _COSMOS_DB


# --------------------------------------------------------------------------------------------
# Deterministic daily-event persistence (the safety-critical Cosmos write).
#
# The edge → local A2A server pipeline forwards each privacy-scrubbed event to this hosted agent as
# a "DAILY EVENT RECORD (JSON)" block embedded in the caregiver turn. We persist that record to the
# daily_event container in AGENT MIDDLEWARE that runs on every turn BEFORE the model — so the write
# is deterministic and independent of anything the (advisory-only) LLM decides to do. The local A2A
# server never connects to Cosmos; this hosted agent owns persistence.
#
# The stored item is schema-compatible with foundry-a2a-server's CosmosEventStore.append(): the live
# care dashboard deserialises `record_json` into a RecordedEvent, so these rows render unchanged.
# --------------------------------------------------------------------------------------------

_DAILY_EVENT_MARKER = "DAILY EVENT RECORD (JSON)"


def _extract_daily_event_record(text: str) -> tuple[dict[str, Any], str] | None:
    """Return (parsed_record, record_json_substring) forwarded in a caregiver turn, or None.

    Locates the DAILY EVENT RECORD (JSON) marker and decodes the JSON object that immediately
    follows it, returning both the parsed dict and the exact JSON substring (stored verbatim as
    ``record_json`` so it round-trips through RecordedEvent.model_validate_json).
    """
    marker = text.find(_DAILY_EVENT_MARKER)
    if marker == -1:
        return None
    brace = text.find("{", marker)
    if brace == -1:
        return None
    try:
        record, end = json.JSONDecoder().raw_decode(text, brace)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict) or "event" not in record:
        return None
    return record, text[brace:end]


def _persist_daily_event(
    record: dict[str, Any], record_json: str, considered_level: str | None = None
) -> str | None:
    """Write the forwarded event to the daily_event container; return its id, or None on skip.

    Never raises: returns None when Cosmos is unconfigured or the record lacks the keys the store
    (and dashboard) require. Provenance is stamped with ``source="a2a-forward"``. When
    ``considered_level`` is supplied (the deterministic verdict computed by
    :class:`ConsideredAssessmentMiddleware`), it is stored authoritatively; otherwise the level
    carried in the record or the edge's own level is used.
    """
    db = _cosmos_db()
    if db is None:
        return None
    event = record.get("event") or {}
    patient_id = event.get("patient_id")
    ts = event.get("timestamp")
    if not patient_id or not ts:
        return None
    item_id = str(uuid.uuid4())
    container = db.get_container_client(_DAILY_EVENT_CONTAINER)
    container.create_item(
        {
            "id": item_id,
            "patient_id": patient_id,
            "ts": ts,
            "type": event.get("type", "unknown"),
            "considered_level": considered_level
            or record.get("considered_level")
            or event.get("edge_assessed_level", "L0"),
            "record_json": record_json,
            "source": "a2a-forward",
        }
    )
    return item_id


# --------------------------------------------------------------------------------------------
# Deterministic considered assessment + escalation (the safety-critical verdict).
#
# In the standard-A2A topology the standalone foundry-a2a-server is retired, so THIS hosted agent
# owns the considered level and the escalation ladder — and both must stay deterministic (never
# decided by the advisory model). ConsideredAssessmentMiddleware runs BEFORE the model: it parses
# the forwarded event, reads the patient's stored state from Cosmos, computes the considered
# CloudAssessment with the ported ConsideredAssessor, starts the ack-tracked ladder for L3, and
# stashes the verdict on context.metadata so the persistence middleware files the deterministic
# level. After the model narrates, it appends a delimited CONSIDERED ASSESSMENT (JSON) block so the
# edge parses the authoritative verdict back over A2A regardless of the model's wording.
# --------------------------------------------------------------------------------------------

_ASSESSMENT_META_KEY = "airacare_considered_assessment"

# Module-level so escalation ladders (real threading.Timer windows) persist across turns.
_ESCALATION_AGENT = EscalationAgent()


def _read_patient_state(patient_id: str) -> PatientState | None:
    """Read the patient's stored state from Cosmos; None when unconfigured, missing, or on error.

    A miss (or no store) makes the assessor fall back to its safe default (moderate stage), so the
    considered level is never blocked on state.
    """
    db = _cosmos_db()
    if db is None:
        return None
    try:
        from azure.cosmos import exceptions as cosmos_exc  # lazy

        container = db.get_container_client(_PATIENT_STATE_CONTAINER)
        try:
            item = container.read_item(item=patient_id, partition_key=patient_id)
        except cosmos_exc.CosmosResourceNotFoundError:
            return None
        return PatientState(
            patient_id=patient_id,
            name=item.get("name", ""),
            disease_stage=item.get("disease_stage", "moderate"),
            baseline_deviation=float(item.get("baseline_deviation", 0.0) or 0.0),
        )
    except Exception:  # noqa: BLE001 — state is best-effort; the assessor has a safe default
        return None


class ConsideredAssessmentMiddleware(AgentMiddleware):
    """Compute the deterministic considered level + escalation on every turn (pre-model).

    A caregiver turn that carries no DAILY EVENT RECORD (JSON) block (a plain conversational
    question) is a no-op. All failures are swallowed so the advisory turn always proceeds.
    """

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        assessment = None
        try:
            text = "\n".join(m.text for m in context.messages if getattr(m, "text", ""))
            extracted = _extract_daily_event_record(text) if text else None
            if extracted is not None:
                record, _record_json = extracted
                event = DailyLivingEvent.model_validate(record.get("event") or {})
                state = _read_patient_state(event.patient_id)
                assessment = ConsideredAssessor().assess(event, state)
                context.metadata[_ASSESSMENT_META_KEY] = assessment
                session = _ESCALATION_AGENT.handle(event, assessment)
                note = f"; escalation started at {session.current_channel}" if session else ""
                print(
                    f"[considered] {event.patient_id} -> {assessment.considered_level}{note}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001 — assessment must never break the advisory turn
            print(f"[considered] skipped ({type(exc).__name__}: {exc})", flush=True)

        await call_next()

        # Append the deterministic verdict so the edge parses it back over A2A (the model's warm
        # narration is advisory; this block is the authoritative considered level).
        if assessment is not None:
            try:
                result = context.result
                if result is not None and hasattr(result, "messages"):
                    block = render_assessment_block(assessment)
                    result.messages.append(Message(role="assistant", contents=[block]))
            except Exception as exc:  # noqa: BLE001 — never break the turn over presentation
                print(f"[considered] block append skipped ({type(exc).__name__}: {exc})", flush=True)


class DailyEventPersistenceMiddleware(AgentMiddleware):
    """Deterministically persist the forwarded daily_event to Cosmos on every turn (pre-model).

    Runs before the advisory model so the safety-critical write happens regardless of what the LLM
    chooses to do. A caregiver turn that carries no DAILY EVENT RECORD (JSON) block (a plain
    conversational question) is a no-op. Persistence failures are swallowed so the advisory turn
    always proceeds. When :class:`ConsideredAssessmentMiddleware` ran first, its deterministic
    considered level (on ``context.metadata``) is stored authoritatively.
    """

    async def process(
        self, context: AgentContext, call_next: Callable[[], Awaitable[None]]
    ) -> None:
        try:
            text = "\n".join(m.text for m in context.messages if getattr(m, "text", ""))
            extracted = _extract_daily_event_record(text) if text else None
            if extracted is not None:
                record, record_json = extracted
                assessment = context.metadata.get(_ASSESSMENT_META_KEY)
                considered = getattr(assessment, "considered_level", None)
                event_id = _persist_daily_event(record, record_json, considered)
                patient = (record.get("event") or {}).get("patient_id", "?")
                if event_id:
                    print(f"[daily_event] persisted {event_id} for {patient}", flush=True)
                else:
                    print("[daily_event] not persisted (store unconfigured or incomplete record)",
                          flush=True)
        except Exception as exc:  # noqa: BLE001 — persistence must never break the advisory turn
            print(f"[daily_event] persist skipped ({type(exc).__name__}: {exc})", flush=True)
        await call_next()


@tool(
    name="fetch_recent_events",
    description=(
        "Look up a patient's recently filed daily-living events (privacy-scrubbed) from the care "
        "record. Returns counts by type and considered level plus the most recent events. Use when "
        "the caregiver asks about a specific patient's history or wants a recap grounded in data."
    ),
)
def fetch_recent_events(
    patient_id: Annotated[str, "The patient identifier, e.g. 'p-001'."],
    days: Annotated[int, "How many days back to include (default 14)."] = 14,
) -> str:
    db = _cosmos_db()
    if db is None:
        return "The care record store is not configured, so I can't look up filed events here."
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    container = db.get_container_client(_DAILY_EVENT_CONTAINER)
    # Select only derived, scrubbed fields — never record_json / the voice-biomarker features.
    rows = list(
        container.query_items(
            query=(
                "SELECT c.type, c.considered_level, c.ts FROM c "
                "WHERE c.patient_id = @pid AND c.ts >= @since ORDER BY c.ts DESC"
            ),
            parameters=[{"name": "@pid", "value": patient_id}, {"name": "@since", "value": since}],
            partition_key=patient_id,
        )
    )
    if not rows:
        return f"No filed events for patient {patient_id} in the last {days} days."
    by_type: dict[str, int] = {}
    by_level: dict[str, int] = {}
    for r in rows:
        by_type[r.get("type", "?")] = by_type.get(r.get("type", "?"), 0) + 1
        by_level[r.get("considered_level", "?")] = by_level.get(r.get("considered_level", "?"), 0) + 1
    recent = "; ".join(
        f"{r.get('ts', '?')}: {r.get('type', '?')} (considered {r.get('considered_level', '?')})"
        for r in rows[:8]
    )
    types = ", ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
    levels = ", ".join(f"{k}={v}" for k, v in sorted(by_level.items()))
    return (
        f"Patient {patient_id}: {len(rows)} events in the last {days} days. "
        f"By type: {types}. By considered level: {levels}. "
        f"Most recent — {recent}."
    )


@tool(
    name="fetch_patient_state",
    description=(
        "Look up a patient's stored profile (name, disease stage, baseline drift) from the care "
        "record. Use to personalise tone and context for a specific patient."
    ),
)
def fetch_patient_state(
    patient_id: Annotated[str, "The patient identifier, e.g. 'p-001'."],
) -> str:
    db = _cosmos_db()
    if db is None:
        return "The care record store is not configured, so I can't look up patient details here."
    from azure.cosmos import exceptions as cosmos_exc  # lazy

    container = db.get_container_client(_PATIENT_STATE_CONTAINER)
    try:
        item = container.read_item(item=patient_id, partition_key=patient_id)
    except cosmos_exc.CosmosResourceNotFoundError:
        return f"No stored profile for patient {patient_id}."
    name = item.get("name", "(unknown)")
    stage = item.get("disease_stage", "moderate")
    drift = item.get("baseline_deviation", 0.0)
    return f"Patient {patient_id}: {name}, disease stage {stage}, baseline drift {drift:.2f}."


@tool(
    name="log_care_briefing",
    description=(
        "Save a short advisory caregiver briefing to the care record for later reference. This is "
        "an advisory note only — it does NOT change the patient's care, risk level, or escalation. "
        "Use after you have summarised a situation and the caregiver wants it recorded."
    ),
)
def log_care_briefing(
    patient_id: Annotated[str, "The patient identifier, e.g. 'p-001'."],
    summary: Annotated[str, "The plain-language briefing text to store."],
    audience: Annotated[str, "Who it is for: 'family' or 'clinician' (default 'family')."] = "family",
) -> str:
    db = _cosmos_db()
    if db is None:
        return "The care record store is not configured, so I couldn't save this briefing."
    container = db.get_container_client(_CARE_BRIEFING_CONTAINER)
    ts = datetime.now(timezone.utc).isoformat()
    container.create_item(
        {
            "id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "ts": ts,
            "audience": audience,
            "summary": summary,
            "source": "care-orchestrator",
        }
    )
    return f"Saved an advisory {audience} briefing for patient {patient_id} at {ts}."


def _blob_title(blob_url: str) -> str:
    """Turn a source blob URL into a readable citation, e.g. 'exit-seeking-elopement.md'."""
    name = blob_url.rstrip("/").rsplit("/", 1)[-1] if blob_url else ""
    return name or blob_url or "guideline"


@tool(
    name="search_care_guidelines",
    description=(
        "Retrieve grounded, cited guidance from AiraCare's dementia-care guideline knowledge base "
        "(Foundry IQ agentic retrieval over Azure AI Search). Use this BEFORE giving any care advice "
        "so the guidance is evidence-aligned rather than invented. Returns relevant guideline "
        "passages with their source citations."
    ),
)
def search_care_guidelines(
    query: Annotated[
        str,
        "A natural-language description of the caregiving situation or question, "
        "e.g. 'patient wandering toward the door at night'.",
    ],
    top: Annotated[int, "Maximum number of guideline passages to return (default 3)."] = 3,
) -> str:
    if not _SEARCH_ENDPOINT:
        return (
            "The care-guideline knowledge base is not configured here, so I can't retrieve cited "
            "guidance. Answer from established dementia-care practice and say it is general advice."
        )
    try:
        import requests  # lazy: only needed when the knowledge tool is used

        token = _credential().get_token(_SEARCH_SCOPE).token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {
            "intents": [{"type": "semantic", "search": query}],
            "knowledgeSourceParams": [{"knowledgeSourceName": _SEARCH_KS, "kind": "azureBlob"}],
        }
        url = f"{_SEARCH_ENDPOINT}/knowledgebases/{_SEARCH_KB}/retrieve?api-version={_SEARCH_API}"
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — advisory tool must never crash the turn
        return (
            f"Could not reach the care-guideline knowledge base ({type(exc).__name__}); answer "
            "from general dementia-care practice and note it is general advice."
        )

    # Map ref_id -> source citation from the references block.
    citations = {
        str(ref.get("id")): _blob_title(ref.get("blobUrl", ""))
        for ref in (data.get("references") or [])
    }

    # The response carries content blocks whose text is a JSON array of {ref_id, content}.
    passages: list[str] = []
    for block in data.get("response") or []:
        for part in block.get("content") or []:
            text = part.get("text") or ""
            try:
                items = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                if text.strip():
                    passages.append(text.strip())
                continue
            for item in items if isinstance(items, list) else []:
                content = (item.get("content") or "").strip()
                if not content:
                    continue
                cite = citations.get(str(item.get("ref_id")), "guideline")
                snippet = content[:900]
                passages.append(f"[{cite}] {snippet}")

    passages = passages[: max(1, top)]
    if not passages:
        return f"No care guideline clearly matched '{query}'. Say so briefly rather than speculating."
    cited = {p.split("] ", 1)[0].lstrip("[") for p in passages if p.startswith("[")}
    sources = ", ".join(sorted(cited))
    header = f"Grounded guidance for '{query}' (sources: {sources}):\n\n" if sources else ""
    return header + "\n\n---\n\n".join(passages)


def _build_orchestrator(client: FoundryChatClient) -> Agent:
    """Build the care-orchestrator agent with the five specialists and the data tools."""
    tools: list[Any] = []
    for spec in _SPECIALISTS:
        # The knowledge specialist gets the retrieval tool so its advice is grounded + cited.
        specialist_tools = [search_care_guidelines] if spec["name"] == "knowledge" else None
        specialist = Agent(
            client=client,
            name=spec["name"],
            description=spec["role"],
            instructions=(
                f"{spec['instructions']}\n\nContribute only within your role. Treat any considered "
                "risk level or edge action mentioned as authoritative and unchangeable. If the "
                "situation is irrelevant to your role, say so briefly."
            ),
            tools=specialist_tools,
            default_options={"store": False},
        )
        tools.append(
            specialist.as_tool(
                arg_name="situation",
                arg_description="the caregiver's described situation to reason about",
                propagate_session=False,
            )
        )

    # Cosmos-backed data tools (read the real care record; write only to care_briefing) plus the
    # Foundry IQ retrieval tool (also exposed at the top level so the orchestrator can cite
    # guidelines directly when it answers without delegating to the knowledge specialist).
    tools.extend(
        [fetch_recent_events, fetch_patient_state, log_care_briefing, search_care_guidelines]
    )

    return Agent(
        client=client,
        name="care-orchestrator",
        description="Compose an advisory caregiver briefing for a reported daily-living event.",
        instructions=_ORCHESTRATOR_INSTRUCTIONS,
        tools=tools,
        # Deterministic pre-model middleware, in order: (1) compute the considered level +
        # escalation, then (2) file the forwarded daily_event to Cosmos with that deterministic
        # level. Neither is left to the advisory LLM's discretion.
        middleware=[ConsideredAssessmentMiddleware(), DailyEventPersistenceMiddleware()],
        # History is managed by the hosting infrastructure; the service need not store it.
        default_options={"store": False},
    )


def main() -> None:
    model_name = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.getenv("FOUNDRY_MODEL_NAME")
    if not model_name:
        raise RuntimeError(
            "Model deployment name is not configured. Set "
            "AZURE_AI_MODEL_DEPLOYMENT_NAME or FOUNDRY_MODEL_NAME."
        )

    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=model_name,
        credential=_credential(),
    )

    agent = _build_orchestrator(client)

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
