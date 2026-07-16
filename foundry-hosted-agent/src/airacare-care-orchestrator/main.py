# Copyright (c) Microsoft. All rights reserved.
"""AiraCare — Foundry Hosted Agent entrypoint (Responses protocol).

This is the cloud **care-orchestrator** graduated onto the Microsoft Agent Framework and hosted by
Azure AI Foundry Agent Service. A caregiver or clinician converses with it (Responses API); the
orchestrator consults six connected specialists — risk-reasoning, knowledge, escalation,
cognitive-trend, briefing, policy-learning — each wrapped as a tool, and can look up the patient's
real filed events / state from Cosmos DB and save an advisory briefing back.

Safety discipline (mirrors the FH6 design in
``foundry/airacare_foundry/agents/agent_framework.py``): the model is **advisory only**. It never
sets or second-guesses the risk level and never triggers alerts — the deterministic edge/cloud
Python agents remain the sole authority for the considered level and for escalation. Any
``considered_level`` read from the event store is authoritative and is restated verbatim. No
diagnosis, no medication changes.

Data access (least privilege, AAD only — no keys):
- Reads the **same** Cosmos containers the edge/A2A pipeline writes (``daily_event``,
  ``patient_state``), surfacing only derived, privacy-scrubbed facts (event type, timestamp,
  considered level, patient name/stage) — never raw audio/video/transcripts or the voice-biomarker
  feature vector.
- Writes ONLY to a dedicated ``care_briefing`` container (agent-authored notes). It never mutates
  the authoritative ``daily_event`` / ``patient_state`` / ``edge_policy`` records.
- If ``AIRACARE_COSMOS_ENDPOINT`` is unset, the data tools degrade gracefully (the agent still runs
  as a stateless advisor), mirroring the store-optional design of the main package.

This hosted agent is a NEW conversational surface, DISTINCT from the frozen edge A2A safety path
(``airacare.report`` / ``airacare.fetch_policy``) and the ACA A2A server.

Runtime contract (from the Foundry Agent-Framework Responses sample):
- ``FoundryChatClient`` reaches the Foundry **project** endpoint (``FOUNDRY_PROJECT_ENDPOINT``)
  with ``DefaultAzureCredential`` (Managed Identity in the container; ``az login`` locally) — no key.
- ``ResponsesHostServer(agent).run()`` serves ``POST /responses`` on port 8088; the hosting
  infrastructure manages conversation history, so ``default_options={"store": False}``.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Load environment variables from a local .env when present (no-op in the container).
load_dotenv()


# --------------------------------------------------------------------------------------------
# The six DELIBERATE-tier Connected Agents, as (name, role, instructions) descriptors. Ordering
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
            "Offer brief, practical, evidence-aligned dementia-care guidance relevant to the "
            "situation described, with a short rationale. If nothing is clearly relevant, say so "
            "briefly rather than speculating."
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
    {
        "name": "policy_learning",
        "role": "Suggest personalised edge-policy tuning from recurring patterns.",
        "instructions": (
            "On recurring patterns (e.g. repeated nighttime wandering), suggest — as advice only — "
            "how the edge policy might be personalised (e.g. a gentler reassurance prompt). Frame "
            "it as a recommendation for a caregiver/clinician to approve. Never claim to change "
            "the live policy or the current risk level."
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
    "briefing is just a note — it never changes the patient's care, risk level, or escalation.\n\n"
    "Consult the specialist tools (risk_reasoning, knowledge, escalation, cognitive_trend, "
    "briefing, policy_learning) as helpful for the caregiver's question, passing along the relevant "
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


def _build_orchestrator(client: FoundryChatClient) -> Agent:
    """Build the care-orchestrator agent with the six specialists and the data tools."""
    tools: list[Any] = []
    for spec in _SPECIALISTS:
        specialist = Agent(
            client=client,
            name=spec["name"],
            description=spec["role"],
            instructions=(
                f"{spec['instructions']}\n\nContribute only within your role. Treat any considered "
                "risk level or edge action mentioned as authoritative and unchangeable. If the "
                "situation is irrelevant to your role, say so briefly."
            ),
            default_options={"store": False},
        )
        tools.append(
            specialist.as_tool(
                arg_name="situation",
                arg_description="the caregiver's described situation to reason about",
                propagate_session=False,
            )
        )

    # Cosmos-backed data tools (read the real care record; write only to care_briefing).
    tools.extend([fetch_recent_events, fetch_patient_state, log_care_briefing])

    return Agent(
        client=client,
        name="care-orchestrator",
        description="Compose an advisory caregiver briefing for a reported daily-living event.",
        instructions=_ORCHESTRATOR_INSTRUCTIONS,
        tools=tools,
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
