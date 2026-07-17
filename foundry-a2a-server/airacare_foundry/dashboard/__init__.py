"""Live analytics dashboard for the Foundry Care Orchestrator (off the safety path).

A dependency-light, self-contained web dashboard that reads the same privacy-scrubbed
:class:`~airacare_foundry.store.base.EventStore` the production Cosmos DB / OneLake mirror would
hold and renders the population-/longitudinal-care story: the cognitive trajectory, the event
mix, the escalation funnel (edge vs. cloud), the nighttime-wander risk signal, and the family /
clinician briefings.

Two pieces:

- :mod:`airacare_foundry.dashboard.data` — the backend-agnostic data layer (:class:`DashboardData`)
  that turns filed events into the dashboard payload, reusing the Cognitive-Trend and Briefing
  agents so the numbers match the rest of the system exactly.
- :mod:`airacare_foundry.dashboard.server` — a stdlib :class:`http.server` app (the same pattern as
  ``a2a_server``; **no new dependencies**) that serves a single-page front-end and one JSON API.

Privacy invariant is unchanged: only derived event data is read — never raw audio/video, and no
feature vector beyond the single reduced voice-biomarker index.
"""

from airacare_foundry.dashboard.data import DashboardData

__all__ = ["DashboardData"]
