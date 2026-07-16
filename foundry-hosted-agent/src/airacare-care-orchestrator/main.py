# Copyright (c) Microsoft. All rights reserved.
"""AiraCare — Foundry Hosted Agent entrypoint (Responses protocol).

This is the cloud **care-orchestrator** graduated onto the Microsoft Agent Framework and hosted by
Azure AI Foundry Agent Service. A caregiver or clinician converses with it (Responses API); the
orchestrator consults six connected specialists — risk-reasoning, knowledge, escalation,
cognitive-trend, briefing, policy-learning — each wrapped as a tool, and returns a warm,
plain-language caregiver briefing.

Safety discipline (mirrors the FH6 design in
``foundry/airacare_foundry/agents/agent_framework.py``): the model is **advisory only**. It never
sets or second-guesses the risk level and never triggers alerts — the deterministic edge/cloud
Python agents remain the sole authority for the considered level and for escalation. When the
caregiver states a considered level or an action already taken, the orchestrator restates it
verbatim and reasons only over facts the caregiver provides. No diagnosis, no medication changes.

This hosted agent is a NEW conversational surface. It is DISTINCT from — and does not replace — the
frozen edge A2A safety path (``airacare.report`` / ``airacare.fetch_policy``) or the existing ACA
A2A server. No raw modality data (audio, video, point-cloud, transcripts) is handled here.

Runtime contract (from the Foundry Agent-Framework Responses sample):
- ``FoundryChatClient`` reaches the Foundry **project** endpoint (``FOUNDRY_PROJECT_ENDPOINT``)
  with ``DefaultAzureCredential`` (Managed Identity in the container; ``az login`` locally) — no key.
- ``ResponsesHostServer(agent).run()`` serves ``POST /responses`` on port 8088; the hosting
  infrastructure manages conversation history, so ``default_options={"store": False}``.
"""

import os

from agent_framework import Agent
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
    "alerts or escalation. If the caregiver states a considered level (L0-L3) or an action already "
    "taken at the edge, restate it EXACTLY and never raise, lower, or second-guess it.\n"
    "2. Use ONLY facts the caregiver provides. Do not invent events, vitals, names, medications, "
    "or history. If you need a detail, ask.\n"
    "3. No diagnosis and no medication changes. For anything urgent or medical, advise contacting "
    "the appropriate professional or emergency services.\n"
    "4. Never request or handle raw audio, video, images, or transcripts — reason only over the "
    "derived facts described to you.\n\n"
    "Consult the specialist tools (risk_reasoning, knowledge, escalation, cognitive_trend, "
    "briefing, policy_learning) as helpful for the caregiver's question, passing along the relevant "
    "situation. Then reply with a short, warm, plain-language message: acknowledge what happened, "
    "restate the considered level and why it stands (when one is given), note what has already been "
    "done, and offer one gentle, practical next step. Do not include internal tool chatter."
)


def _build_orchestrator(client: FoundryChatClient) -> Agent:
    """Build the care-orchestrator agent with the six specialists wrapped as tools."""
    tools = []
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
        credential=DefaultAzureCredential(),
    )

    agent = _build_orchestrator(client)

    server = ResponsesHostServer(agent)
    server.run()


if __name__ == "__main__":
    main()
