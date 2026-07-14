"""Local patient-state store — SQLite (file or in-memory).

Decision #6 = C for this scaffold: no Cosmos DB / Fabric. A single-table SQLite store keeps
patient state (disease stage + rolling baseline) local and dependency-free. Use
``:memory:`` for tests/dev or a file path to persist across runs.
"""

from __future__ import annotations

import sqlite3
import threading

from airacare_foundry.store.base import PatientState


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
