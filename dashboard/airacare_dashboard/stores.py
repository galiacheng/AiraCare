"""Event/state stores the dashboard reads — local SQLite (offline) or Azure Cosmos DB (live).

The dashboard is a read-only analytics surface, but it uses the **same** store models and the
**same** ``daily_event`` schema the Foundry hosted agent writes, so the numbers on the page match
exactly what the safety path recorded. Two backends implement one pair of protocols:

- ``local`` — single-table SQLite (``:memory:`` or a file), dependency-free; used for the offline
  dry-run / tests and a ``--seed`` demo month.
- ``cosmos`` — Azure Cosmos DB (partition key ``/patient_id``), the live demo backend. The
  ``azure-cosmos`` SDK is imported **lazily** (the ``[cosmos]`` extra) so importing this module and
  running the local demo never requires it.

Privacy invariant: only derived :class:`~airacare_dashboard.contracts.DailyLivingEvent` data is
read — never raw audio/video/point-cloud.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from airacare_dashboard.contracts import DailyLivingEvent, Grade, utcnow

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from azure.cosmos import ContainerProxy

DiseaseStage = Literal["mild", "moderate", "severe"]

# Default Cosmos container names (must match the hosted agent's writer). PK = /patient_id.
PATIENT_STATE_CONTAINER = "patient_state"
DAILY_EVENT_CONTAINER = "daily_event"
PARTITION_KEY_PATH = "/patient_id"

_MISSING_SDK = (
    "azure-cosmos is not installed. The cosmos backend requires the optional [cosmos] extra: "
    "`pip install -e \".[cosmos]\"`. For the offline dry-run use store.backend: local instead."
)


# --------------------------------------------------------------------------------------------
# Models + protocols
# --------------------------------------------------------------------------------------------


class PatientState(BaseModel):
    """Per-patient state used for the dashboard header (name + disease stage)."""

    patient_id: str
    name: str = ""
    disease_stage: DiseaseStage = "moderate"
    baseline_deviation: float = Field(default=0.0, ge=0.0, le=1.0)


class RecordedEvent(BaseModel):
    """A filed :class:`DailyLivingEvent` plus the cloud's considered level — the analytics record.

    Byte-compatible with the record the Foundry hosted agent persists to ``daily_event``: only
    privacy-scrubbed event data is stored (never raw audio/video).
    """

    event: DailyLivingEvent
    considered_level: Grade
    recorded_at: datetime = Field(default_factory=utcnow)


@runtime_checkable
class PatientStateStore(Protocol):
    """Read/write access to per-patient state, keyed by ``patient_id``."""

    def get(self, patient_id: str) -> PatientState | None: ...

    def upsert(self, state: PatientState) -> None: ...


@runtime_checkable
class EventStore(Protocol):
    """Append-only log of filed events per patient — the dashboard's source of truth."""

    def append(self, record: RecordedEvent) -> None: ...

    def list_for_patient(
        self,
        patient_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RecordedEvent]: ...


# --------------------------------------------------------------------------------------------
# Local SQLite stores
# --------------------------------------------------------------------------------------------


class LocalPatientStateStore:
    """SQLite-backed :class:`PatientStateStore` (shared connection guarded by a lock)."""

    def __init__(self, sqlite_path: str = ":memory:") -> None:
        self._path = sqlite_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS patient_state (
                    patient_id         TEXT PRIMARY KEY,
                    name               TEXT NOT NULL DEFAULT '',
                    disease_stage      TEXT NOT NULL DEFAULT 'moderate',
                    baseline_deviation REAL NOT NULL DEFAULT 0.0
                )
                """
            )
            self._conn.commit()

    def get(self, patient_id: str) -> PatientState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT patient_id, name, disease_stage, baseline_deviation "
                "FROM patient_state WHERE patient_id = ?",
                (patient_id,),
            ).fetchone()
        if row is None:
            return None
        return PatientState(
            patient_id=row["patient_id"],
            name=row["name"],
            disease_stage=row["disease_stage"],
            baseline_deviation=row["baseline_deviation"],
        )

    def upsert(self, state: PatientState) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO patient_state (patient_id, name, disease_stage, baseline_deviation)
                VALUES (:patient_id, :name, :disease_stage, :baseline_deviation)
                ON CONFLICT(patient_id) DO UPDATE SET
                    name = excluded.name,
                    disease_stage = excluded.disease_stage,
                    baseline_deviation = excluded.baseline_deviation
                """,
                state.model_dump(),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def seeded_local_store(
    sqlite_path: str = ":memory:",
    *,
    patient_id: str = "p-001",
    name: str = "Grandpa Zhang",
    disease_stage: str = "moderate",
    baseline_deviation: float = 0.0,
) -> LocalPatientStateStore:
    """Build a local state store pre-seeded with the flagship patient (idempotent upsert)."""
    store = LocalPatientStateStore(sqlite_path)
    if store.get(patient_id) is None:
        store.upsert(
            PatientState(
                patient_id=patient_id,
                name=name,
                disease_stage=disease_stage,  # type: ignore[arg-type]
                baseline_deviation=baseline_deviation,
            )
        )
    return store


class LocalEventStore:
    """SQLite-backed :class:`EventStore` — the append-only log of filed events per patient."""

    def __init__(self, sqlite_path: str = ":memory:") -> None:
        self._path = sqlite_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_event (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id       TEXT NOT NULL,
                    ts               TEXT NOT NULL,
                    type             TEXT NOT NULL,
                    considered_level TEXT NOT NULL,
                    record_json      TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_daily_event_patient_ts "
                "ON daily_event (patient_id, ts)"
            )
            self._conn.commit()

    def append(self, record: RecordedEvent) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO daily_event (patient_id, ts, type, considered_level, record_json)
                VALUES (:patient_id, :ts, :type, :considered_level, :record_json)
                """,
                {
                    "patient_id": record.event.patient_id,
                    "ts": record.event.timestamp.isoformat(),
                    "type": record.event.type,
                    "considered_level": record.considered_level,
                    "record_json": record.model_dump_json(),
                },
            )
            self._conn.commit()

    def list_for_patient(
        self,
        patient_id: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[RecordedEvent]:
        clauses = ["patient_id = ?"]
        params: list[str] = [patient_id]
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since.isoformat())
        if until is not None:
            clauses.append("ts < ?")
            params.append(until.isoformat())
        sql = (
            "SELECT record_json FROM daily_event "
            f"WHERE {' AND '.join(clauses)} ORDER BY ts ASC, id ASC"
        )
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [RecordedEvent.model_validate_json(row["record_json"]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# --------------------------------------------------------------------------------------------
# Azure Cosmos DB stores (read the same daily_event the hosted agent writes)
# --------------------------------------------------------------------------------------------


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
        body["id"] = state.patient_id
        self._container.upsert_item(body)


def _recorded_from_item(item: dict[str, Any]) -> RecordedEvent:
    """Reconstruct a :class:`RecordedEvent` from a ``daily_event`` item, tolerating both writer
    shapes seen in the live container:

    * hosted agent (``source="a2a-forward"``): ``record_json`` is the raw report envelope
      ``{"event": {...}}`` and the considered level is the sibling ``considered_level`` column;
    * seeded / legacy writer: ``record_json`` is a full serialized ``RecordedEvent``
      (``{"event", "considered_level", "recorded_at"}``).
    """
    rj = json.loads(item["record_json"])
    normalized: dict[str, Any] = {"event": rj["event"]}
    normalized["considered_level"] = rj.get("considered_level") or item.get("considered_level")
    if "recorded_at" in rj:
        normalized["recorded_at"] = rj["recorded_at"]
    record = RecordedEvent.model_validate(normalized)
    # The hosted agent (a2a-forward) writes naive UTC timestamps while seeded/legacy records are
    # tz-aware; coerce to aware UTC so analytics never mixes naive and aware datetimes.
    if record.event.timestamp.tzinfo is None:
        record.event.timestamp = record.event.timestamp.replace(tzinfo=timezone.utc)
    return record


class CosmosEventStore(_CosmosBase):
    """:class:`EventStore` backed by Cosmos DB (append-only; the dashboard's live source)."""

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
        query = "SELECT c.record_json, c.considered_level FROM c WHERE c.patient_id = @pid"
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
        return [_recorded_from_item(item) for item in items]


# --------------------------------------------------------------------------------------------
# Backend factory
# --------------------------------------------------------------------------------------------


def build_stores(config) -> tuple[PatientStateStore, EventStore]:
    """Construct the (state, event) store pair for the configured backend.

    ``local`` uses the seeded SQLite stores (offline dry-run/tests). ``cosmos`` builds the live
    Azure Cosmos DB stores (partition = ``/patient_id``); it requires ``cosmos_endpoint`` (and,
    for key auth, ``cosmos_credential``) and the ``[cosmos]`` extra. The demo patient state is
    upserted if absent so the header renders against a fresh account.
    """
    sc = config.store
    if sc.backend == "cosmos":
        endpoint = sc.resolve_endpoint()
        credential = sc.resolve_credential()
        database = sc.resolve_database()
        if not endpoint or (sc.cosmos_auth == "key" and not credential):
            raise ValueError(
                "store.backend: cosmos requires store.cosmos_endpoint and store.cosmos_credential."
            )
        kwargs = {
            "database": database,
            "auth": sc.cosmos_auth,
            "tls_verify": sc.cosmos_tls_verify,
        }
        state_store: PatientStateStore = CosmosPatientStateStore(endpoint, credential or "", **kwargs)
        if state_store.get(config.patient.id) is None:
            state_store.upsert(
                PatientState(
                    patient_id=config.patient.id,
                    name=config.patient.name,
                    disease_stage=config.patient.disease_stage,
                )
            )
        event_store: EventStore = CosmosEventStore(endpoint, credential or "", **kwargs)
        return state_store, event_store

    # local backend
    state = seeded_local_store(
        sc.sqlite_path,
        patient_id=config.patient.id,
        name=config.patient.name,
        disease_stage=config.patient.disease_stage,
    )
    events = LocalEventStore(sc.sqlite_path)
    return state, events


__all__ = [
    "PatientState",
    "RecordedEvent",
    "PatientStateStore",
    "EventStore",
    "LocalPatientStateStore",
    "LocalEventStore",
    "seeded_local_store",
    "CosmosPatientStateStore",
    "CosmosEventStore",
    "build_stores",
    "PATIENT_STATE_CONTAINER",
    "DAILY_EVENT_CONTAINER",
    "PARTITION_KEY_PATH",
]
