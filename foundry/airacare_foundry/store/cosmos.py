"""Cosmos DB stores — the production graduation seam (Decision #6: local → Cosmos is a *swap*).

The MVP runs on the local SQLite stores (``local.py``). This module implements the **same**
:class:`PatientStateStore`, :class:`PolicyStore`, and :class:`EventStore` protocols against
**Azure Cosmos DB** so graduating to production is a config flip (``store.backend: cosmos``),
not a rewrite. Everything upstream — the assessment policy, policy-learning, batch trend /
briefing agents, and the orchestrator — is untouched.

Design (matches ``spec/foundry-design.md`` §7):

- **Partition key = ``/patient_id``** for every container → single-digit-ms point reads that
  keep the report response prompt, and per-patient event queries that stay in one partition.
- Three containers: ``patient_state`` and ``edge_policy`` (id = ``patient_id``, one item per
  patient) and ``daily_event`` (append-only, id = a per-event uuid).
- Analytics never runs here: the events container is **mirrored to Microsoft Fabric / OneLake**
  (zero-copy, no ETL) where Cognitive-Trend batch modeling and Power BI live. See
  ``docs/production.md``.

The ``azure-cosmos`` SDK is an **optional** dependency (the ``[cosmos]`` extra); it is imported
lazily so importing this module — and running the local-store demo/tests — never requires it.
Constructing a Cosmos store without the SDK installed raises a clear, actionable error.

Privacy invariant is unchanged: only derived :class:`DailyLivingEvent` data is stored; no raw
audio/video/point-cloud ever reaches Cosmos or OneLake.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from airacare_foundry.contracts import EdgePolicyUpdate
from airacare_foundry.store.base import PatientState, RecordedEvent

if TYPE_CHECKING:  # only for type hints; never imported at runtime unless the extra is installed
    from azure.cosmos import ContainerProxy

_MISSING_SDK = (
    "azure-cosmos is not installed. Cosmos stores require the optional [cosmos] extra: "
    "`pip install -e \".[cosmos]\"`. For the local demo use store.backend: local instead."
)

# Default container names (overridable via config). Partition key path is /patient_id for all.
PATIENT_STATE_CONTAINER = "patient_state"
EDGE_POLICY_CONTAINER = "edge_policy"
DAILY_EVENT_CONTAINER = "daily_event"
PARTITION_KEY_PATH = "/patient_id"


def _import_cosmos() -> tuple[Any, Any]:
    """Lazily import the Azure Cosmos SDK, raising a clear error when the extra is missing."""
    try:
        import azure.cosmos as cosmos  # noqa: PLC0415 (intentional lazy import)
        import azure.cosmos.exceptions as cosmos_exc  # noqa: PLC0415

        return cosmos, cosmos_exc
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(_MISSING_SDK) from exc


def _aad_credential() -> Any:
    """Lazily build a DefaultAzureCredential (Managed Identity in prod, az login locally)."""
    try:
        from azure.identity import DefaultAzureCredential  # noqa: PLC0415

        return DefaultAzureCredential()
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "azure-identity is not installed. AAD auth requires the optional [cosmos] extra: "
            '`pip install -e ".[cosmos]"`.'
        ) from exc


class _CosmosBase:
    """Shared Cosmos client/container bootstrap (partition key = ``/patient_id``)."""

    def __init__(
        self,
        endpoint: str,
        credential: str,
        *,
        database: str = "airacare",
        container: str,
        auth: str = "key",
        tls_verify: bool = True,
    ) -> None:
        cosmos, _ = _import_cosmos()
        self._cosmos = cosmos
        cred: Any = _aad_credential() if auth == "aad" else credential
        # connection_verify=False lets the SDK talk to the emulator's self-signed cert (localhost).
        kwargs: dict[str, Any] = {} if tls_verify else {"connection_verify": False}
        self._client = cosmos.CosmosClient(endpoint, cred, **kwargs)
        db = self._client.create_database_if_not_exists(id=database)
        self._container: "ContainerProxy" = db.create_container_if_not_exists(
            id=container,
            partition_key=cosmos.PartitionKey(path=PARTITION_KEY_PATH),
        )


class CosmosPatientStateStore(_CosmosBase):
    """:class:`PatientStateStore` backed by Cosmos DB (one item per patient)."""

    def __init__(
        self,
        endpoint: str,
        credential: str,
        *,
        database: str = "airacare",
        container: str = PATIENT_STATE_CONTAINER,
        auth: str = "key",
        tls_verify: bool = True,
    ) -> None:
        super().__init__(
            endpoint, credential, database=database, container=container,
            auth=auth, tls_verify=tls_verify,
        )

    def get(self, patient_id: str) -> PatientState | None:
        _, exc = _import_cosmos()
        try:
            item = self._container.read_item(item=patient_id, partition_key=patient_id)
        except exc.CosmosResourceNotFoundError:
            return None
        return PatientState(
            patient_id=item["patient_id"],
            name=item.get("name", ""),
            disease_stage=item.get("disease_stage", "moderate"),
            baseline_deviation=item.get("baseline_deviation", 0.0),
        )

    def upsert(self, state: PatientState) -> None:
        body = state.model_dump()
        body["id"] = state.patient_id  # Cosmos item id
        self._container.upsert_item(body)


class CosmosPolicyStore(_CosmosBase):
    """:class:`PolicyStore` backed by Cosmos DB (latest versioned policy per patient)."""

    def __init__(
        self,
        endpoint: str,
        credential: str,
        *,
        database: str = "airacare",
        container: str = EDGE_POLICY_CONTAINER,
        auth: str = "key",
        tls_verify: bool = True,
    ) -> None:
        super().__init__(
            endpoint, credential, database=database, container=container,
            auth=auth, tls_verify=tls_verify,
        )

    def get(self, patient_id: str) -> EdgePolicyUpdate | None:
        _, exc = _import_cosmos()
        try:
            item = self._container.read_item(item=patient_id, partition_key=patient_id)
        except exc.CosmosResourceNotFoundError:
            return None
        return EdgePolicyUpdate.model_validate_json(item["policy_json"])

    def upsert(self, policy: EdgePolicyUpdate) -> None:
        self._container.upsert_item(
            {
                "id": policy.patient_id,
                "patient_id": policy.patient_id,
                "version": policy.version,
                "policy_json": policy.model_dump_json(),
            }
        )


class CosmosEventStore(_CosmosBase):
    """:class:`EventStore` backed by Cosmos DB (append-only; mirrored to Fabric/OneLake)."""

    def __init__(
        self,
        endpoint: str,
        credential: str,
        *,
        database: str = "airacare",
        container: str = DAILY_EVENT_CONTAINER,
        auth: str = "key",
        tls_verify: bool = True,
    ) -> None:
        super().__init__(
            endpoint, credential, database=database, container=container,
            auth=auth, tls_verify=tls_verify,
        )

    def append(self, record: RecordedEvent) -> None:
        self._container.create_item(
            {
                "id": str(uuid.uuid4()),
                "patient_id": record.event.patient_id,
                "ts": record.event.timestamp.isoformat(),
                "type": record.event.type,
                "considered_level": record.considered_level,
                "record_json": record.model_dump_json(),
            }
        )

    def list_for_patient(
        self,
        patient_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RecordedEvent]:
        query = "SELECT c.record_json FROM c WHERE c.patient_id = @pid"
        params: list[dict[str, object]] = [{"name": "@pid", "value": patient_id}]
        if since is not None:
            query += " AND c.ts >= @since"
            params.append({"name": "@since", "value": since.isoformat()})
        if until is not None:
            query += " AND c.ts < @until"
            params.append({"name": "@until", "value": until.isoformat()})
        query += " ORDER BY c.ts ASC"
        items = self._container.query_items(
            query=query,
            parameters=params,
            partition_key=patient_id,
        )
        return [RecordedEvent.model_validate_json(item["record_json"]) for item in items]


__all__ = [
    "CosmosPatientStateStore",
    "CosmosPolicyStore",
    "CosmosEventStore",
    "PATIENT_STATE_CONTAINER",
    "EDGE_POLICY_CONTAINER",
    "DAILY_EVENT_CONTAINER",
    "PARTITION_KEY_PATH",
]
