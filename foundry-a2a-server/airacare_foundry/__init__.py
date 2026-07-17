"""AiraCare Foundry Care Orchestrator package.

Cloud-side graded reasoning for AiraCare. Speaks the same A2A / JSON-RPC 2.0 contract as
the edge's local stub (method ``airacare.report``), so it is a drop-in replacement: the edge
points at this server with ``cloud.mode: foundry`` and no other change.

The edge is authoritative — it grades and acts on its own, then reports the event. The
cloud returns a considered assessment. Two decision tiers: a synchronous T1 considered
assessment (off the edge's safety path) and an asynchronous DELIBERATE tier (T2, stubbed
in this scaffold).
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
