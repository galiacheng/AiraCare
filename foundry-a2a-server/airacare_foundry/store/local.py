"""Local stores — SQLite (file or in-memory) for patient state and edge policy.

Decision #6 = C for this scaffold: no Cosmos DB / Fabric. Single-table SQLite stores keep
patient state (disease stage + rolling baseline) and the versioned edge policy local and
dependency-free. Use ``:memory:`` for tests/dev or a file path to persist across runs.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime

from airacare_foundry.contracts import EdgePolicyUpdate
from airacare_foundry.store.base import PatientState, RecordedEvent


class LocalPatientStateStore:
    """SQLite-backed :class:`PatientStateStore`.

    A single connection is shared and guarded by a lock so the store is safe to use from
    the threaded A2A server. ``check_same_thread=False`` is required because the HTTP
    handler runs on worker threads.
    """

    def __init__(self, sqlite_path: str = ":memory:") -> None:
        self._path = sqlite_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
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
    """Build a local store pre-seeded with the flagship patient (idempotent upsert)."""
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


class LocalPolicyStore:
    """SQLite-backed :class:`PolicyStore` — the latest versioned policy per patient.

    Stores the full :class:`EdgePolicyUpdate` as JSON keyed by ``patient_id``; only the most
    recent version is retained (MVP). Shares the single-connection + lock pattern of
    :class:`LocalPatientStateStore` so it is safe under the threaded A2A server.
    """

    def __init__(self, sqlite_path: str = ":memory:") -> None:
        self._path = sqlite_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS edge_policy (
                    patient_id  TEXT PRIMARY KEY,
                    version     INTEGER NOT NULL,
                    policy_json TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    def get(self, patient_id: str) -> EdgePolicyUpdate | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT policy_json FROM edge_policy WHERE patient_id = ?",
                (patient_id,),
            ).fetchone()
        if row is None:
            return None
        return EdgePolicyUpdate.model_validate_json(row["policy_json"])

    def upsert(self, policy: EdgePolicyUpdate) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO edge_policy (patient_id, version, policy_json)
                VALUES (:patient_id, :version, :policy_json)
                ON CONFLICT(patient_id) DO UPDATE SET
                    version = excluded.version,
                    policy_json = excluded.policy_json
                """,
                {
                    "patient_id": policy.patient_id,
                    "version": policy.version,
                    "policy_json": policy.model_dump_json(),
                },
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class LocalEventStore:
    """SQLite-backed :class:`EventStore` — the append-only log of filed events per patient.

    Stores the full scrubbed :class:`RecordedEvent` as JSON plus a few columns lifted out for
    time-ordered querying (``patient_id``, event ``ts``, ``type``, ``considered_level``). This
    stands in for the production Cosmos DB container (partition key = ``patient_id``) that would
    mirror into Fabric/OneLake for Power BI. Shares the single-connection + lock pattern so it
    is safe under the threaded A2A server.
    """

    def __init__(self, sqlite_path: str = ":memory:") -> None:
        self._path = sqlite_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(sqlite_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
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
