# AiraCare — Foundry Hosted Agent (care-orchestrator)

Graduates the AiraCare cloud **care-orchestrator** — the six DELIBERATE-tier Connected Agents on
the **Microsoft Agent Framework** — into an **Azure AI Foundry Hosted Agent** that speaks the
**Responses** protocol.

This is a **new conversational surface** for family caregivers and clinicians. It is **advisory /
narrative only** and is **distinct from** (does not replace):

- the frozen **edge A2A safety path** (`airacare.report` / `airacare.fetch_policy`), and
- the existing **ACA A2A server** (`foundry-a2a-server/` + `foundry-a2a-server/infra/foundry.bicep`).

The model never sets or changes the risk level and never triggers escalation — the deterministic
edge/cloud Python agents remain the sole authority. See the safety framing in
`foundry-a2a-server/airacare_foundry/agents/agent_framework.py` (FH6).

## Layout

```
foundry-hosted-agent/
├─ azure.yaml                         # azd + microsoft.foundry: model deployment + hosted agent
└─ src/airacare-care-orchestrator/
   ├─ main.py                         # orchestrator + six specialists (as tools) via FoundryChatClient
   ├─ requirements.txt                # agent-framework-foundry(+hosting), python-dotenv, debugpy
   ├─ Dockerfile                      # python:3.12-slim, EXPOSE 8088, CMD python main.py
   ├─ .env.example                    # FOUNDRY_PROJECT_ENDPOINT, AZURE_AI_MODEL_DEPLOYMENT_NAME
   └─ .dockerignore
```

## Prerequisites

- Python 3.13+
- Azure Developer CLI `azd` ≥ 1.25.3 with the Foundry extension:
  `azd ext install microsoft.foundry`
- `az login` (and `azd auth login`) to the target subscription.

## Deploy (azd)

```bash
cd foundry-hosted-agent
azd env new airacare-agent
azd env set AZURE_SUBSCRIPTION_ID <sub-id>
azd env set AZURE_LOCATION eastus2
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME gpt-5.4-mini

azd provision                          # Foundry project + model deployment + ACR + App Insights
azd ai agent run                       # run locally on http://localhost:8088
azd ai agent invoke --local "Mom got up at 2am and seemed confused near the front door. Edge acted at L3."
azd deploy                             # build + deploy the container to Foundry Agent Service
azd ai agent invoke "Give me a short recap of last night for the family."
azd ai agent monitor --follow         # logs

azd down                               # tear everything down
```

## What the agent does

A caregiver describes a privacy-scrubbed situation (or asks for a recap). The orchestrator consults
the specialists as needed and replies with a warm, plain-language briefing: what happened, the
considered level and why it stands (restated verbatim when provided), what the edge already did, and
one gentle next step. It asks for missing facts rather than inventing them, and defers anything
urgent/medical to the appropriate professional or emergency services.
