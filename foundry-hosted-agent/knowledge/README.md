# AiraCare knowledge corpus

Grounding documents for the care-orchestrator's `knowledge` specialist, served through a
**Foundry IQ** knowledge base (agentic retrieval over Azure AI Search).

These are short, general, non-clinical caregiver-guidance notes on common in-home dementia
scenarios. They contain **no patient data** — nothing here is PII. They expand the four seeded
snippets originally in `foundry-a2a-server/airacare_foundry/agents/knowledge.py`
(`DEFAULT_GUIDELINES`).

## How it is used

1. The files in `corpus/` are uploaded to an Azure Blob container (`knowledge source`).
2. A Foundry IQ **knowledge base** indexes them (chunking + `text-embedding-3-small`
   vectors + hybrid retrieval), using `gpt-5.4` as the agentic query planner.
3. The hosted agent's `search_care_guidelines` tool calls the knowledge base `retrieve`
   action and returns grounded snippets **with citations**; the `knowledge` specialist
   reasons only over what is returned.

Guidance grounds *advice* only. It never sets or changes the risk level and never triggers
escalation — those remain the edge's and the orchestrator's safety-path responsibilities.

## Content note

These notes paraphrase widely published, general home-care guidance for dementia caregivers
(e.g. calm-approach, safe-environment, and when-to-seek-help principles). They are educational,
not a substitute for professional medical advice.
