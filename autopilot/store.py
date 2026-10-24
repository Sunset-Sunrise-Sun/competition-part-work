"""SQLite-backed task store and state machine.

All mutations that matter for ordering happen inside ``BEGIN IMMEDIATE``
transactions. The global lease is a singleton row; a scheduler may only claim
work while it owns an unexpired lease.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import (
    ALLOWED_TRANSITIONS,
    InvalidTransition,
    LeaseLost,
    LeaseNotHeld,
    ReviewOutcome,
    ReviewResult,
    ReviewVerdict,
    StaleClaim,
    TaskRecord,
    TaskSpec,
    TaskStatus,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source_key TEXT,
    status TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    head_sha TEXT,
    branch TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    rework_rounds INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    claimed_at REAL,
    attempt_has_result INTEGER NOT NULL DEFAULT 0,
    claim_token TEXT
);

CREATE TABLE IF NOT EXISTS lease (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    owner TEXT,
    acquired_at REAL,
    expires_at REAL,
    generation INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO lease (singleton, owner, acquired_at, expires_at)
VALUES (1, NULL, NULL, NULL);

CREATE TABLE IF NOT EXISTS events (
    event_key TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    head_sha TEXT NOT NULL,
    verdict TEXT NOT NULL,
    defects_json TEXT NOT NULL DEFAULT '[]',
    reviewer TEXT NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS reviews_active_unique
    ON reviews (task_id, head_sha, reviewer)
    WHERE stale = 0;

CREATE TABLE IF NOT EXISTS transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    head_sha TEXT,
    created_at REAL NOT NULL
);
"""


class SqliteStore:
    """Persistent task store. One instance per scheduler process/connection."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        max_attempts: int = 2,
        max_rework_rounds: int = 3,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if max_rework_rounds < 0:
            raise ValueError("max_rework_rounds must be >= 0")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_attempts = max_attempts
        self.max_rework_rounds = max_rework_rounds
        self.conn = sqlite3.connect(
            str(self.db_path),
            timeout=busy_timeout_ms / 1000.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._ensure_column("tasks", "attempt_has_result", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("tasks", "claim_token", "TEXT")
        self._ensure_column("lease", "generation", "INTEGER NOT NULL DEFAULT 0")

    def _ensure_column(self, table: str, column: str, definition: str) -> None:
        """Small forward migration for databases created by Phase 1A.0."""
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ------------------------------------------------------------------ basics
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def close(self) -> None:
        self.conn.close()

    # -------------------------------------------------------------- task rows
    def _task_row(self, task_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            title=row["title"],
            status=TaskStatus(row["status"]),
            base_sha=row["base_sha"],
            head_sha=row["head_sha"],
            payload=json.loads(row["payload_json"]),
            rework_rounds=int(row["rework_rounds"]),
            attempts=int(row["attempts"]),
            last_error=row["last_error"],
            branch=row["branch"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            claim_token=row["claim_token"],
        )

    def get_task(self, task_id: str) -> TaskRecord | None:
        row = self._task_row(task_id)
        return self._to_record(row) if row is not None else None

    def list_tasks(self) -> list[TaskRecord]:
        rows = self.conn.execute(
            "SELECT * FROM tasks ORDER BY created_at, rowid"
        ).fetchall()
        return [self._to_record(row) for row in rows]

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status"
        ).fetchall()
        result = {status.value: 0 for status in TaskStatus}
        for row in rows:
            result[row["status"]] = int(row["n"])
        return result

    def review_count(self, task_id: str | None = None) -> int:
        if task_id is None:
            row = self.conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n FROM reviews WHERE task_id = ?", (task_id,)
            ).fetchone()
        return int(row["n"])

    # ----------------------------------------------------------- idempotency
    def enqueue_task(self, spec: TaskSpec, now: float) -> bool:
        """Insert a task once. Returns False for a repeated task/event."""
        if not spec.task_id:
            raise ValueError("task_id must be non-empty")
        payload = json.dumps(dict(spec.payload), ensure_ascii=False, sort_keys=True)
        with self.transaction():
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO tasks
                    (task_id, title, source_key, status, base_sha, head_sha,
                     branch, payload_json, rework_rounds, attempts, last_error,
                     created_at, updated_at, claimed_at)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 0, 0, NULL, ?, ?, NULL)
                """,
                (
                    spec.task_id,
                    spec.title,
                    spec.task_id,
                    TaskStatus.READY.value,
                    spec.base_sha,
                    payload,
                    now,
                    now,
                ),
            )
            return cursor.rowcount == 1

    def record_event(
        self,
        event_key: str,
        task_id: str,
        stage: str,
        detail: dict[str, Any] | None,
        now: float,
    ) -> bool:
        """Insert an external event once; duplicates return False."""
        payload = json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)
        with self.transaction():
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO events
                    (event_key, task_id, stage, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event_key, task_id, stage, payload, now),
            )
            return cursor.rowcount == 1

    # --------------------------------------------------------------- leases
    def get_lease(self) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM lease WHERE singleton = 1").fetchone()
        if row is None:
            return None
        return {
            "owner": row["owner"],
            "acquired_at": row["acquired_at"],
            "expires_at": row["expires_at"],
            "generation": row["generation"],
        }

    def acquire_lease(self, owner: str, ttl_seconds: float, now: float) -> int | None:
        """Acquire the singleton lease and return its new fencing generation."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        with self.transaction():
            row = self.conn.execute(
                "SELECT owner, expires_at, generation FROM lease WHERE singleton = 1"
            ).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO lease "
                    "(singleton, owner, acquired_at, expires_at, generation) "
                    "VALUES (1, NULL, NULL, NULL, 0)"
                )
                row = {"owner": None, "expires_at": None, "generation": 0}
            current_owner = row["owner"]
            expires_at = row["expires_at"]
            if current_owner and expires_at is not None and float(expires_at) > now:
                return None
            generation = int(row["generation"] or 0) + 1
            self.conn.execute(
                "UPDATE lease SET owner = ?, acquired_at = ?, expires_at = ?, "
                "generation = ? WHERE singleton = 1",
                (owner, now, now + ttl_seconds, generation),
            )
            return generation

    def renew_lease(
        self, owner: str, ttl_seconds: float, now: float, fence: int
    ) -> bool:
        with self.transaction():
            row = self.conn.execute(
                "SELECT owner, expires_at, generation FROM lease WHERE singleton = 1"
            ).fetchone()
            if (
                row is None
                or row["owner"] != owner
                or int(row["generation"] or 0) != int(fence)
                or row["expires_at"] is None
                or float(row["expires_at"]) <= now
            ):
                return False
            self.conn.execute(
                "UPDATE lease SET expires_at = ? "
                "WHERE singleton = 1 AND owner = ? AND generation = ?",
                (now + ttl_seconds, owner, int(fence)),
            )
            return True

    def release_lease(self, owner: str, fence: int | None = None) -> bool:
        with self.transaction():
            row = self.conn.execute(
                "SELECT owner, generation FROM lease WHERE singleton = 1"
            ).fetchone()
            if row is None or row["owner"] != owner:
                return False
            if fence is not None and int(row["generation"] or 0) != int(fence):
                return False
            cursor = self.conn.execute(
                "UPDATE lease SET owner = NULL, acquired_at = NULL, expires_at = NULL "
                "WHERE singleton = 1 AND owner = ?",
                (owner,),
            )
            return cursor.rowcount == 1

    def _require_fence(self, fence: int, now: float) -> None:
        """Reject a worker whose lease generation is stale or expired."""
        row = self.conn.execute(
            "SELECT owner, expires_at, generation FROM lease WHERE singleton = 1"
        ).fetchone()
        if (
            row is None
            or row["owner"] is None
            or int(row["generation"] or 0) != int(fence)
            or row["expires_at"] is None
            or float(row["expires_at"]) <= now
        ):
            raise LeaseLost(
                "lease generation is stale or expired; result must be discarded"
            )

    # -------------------------------------------------------- state machine
    def _log_transition(
        self,
        task_id: str,
        from_status: str | None,
        to_status: str,
        reason: str,
        head_sha: str | None,
        now: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO transitions
                (task_id, from_status, to_status, reason, head_sha, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, from_status, to_status, reason, head_sha, now),
        )

    def transition(
        self,
        task_id: str,
        to_status: TaskStatus,
        reason: str,
        now: float,
        *,
        head_sha: str | None = None,
    ) -> TaskRecord:
        """Apply one externally requested transition (used by tests/operators)."""
        with self.transaction():
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])
            if to_status not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"cannot transition {task_id} from {current.value} "
                    f"to {to_status.value}"
                )
            self.conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (to_status.value, now, task_id),
            )
            self._log_transition(
                task_id, current.value, to_status.value, reason, head_sha, now
            )
            return self._to_record(self._task_row(task_id))  # type: ignore[arg-type]

    def claim_next(self, owner: str, now: float, fence: int) -> TaskRecord | None:
        """Claim a task while holding the current lease generation."""
        with self.transaction():
            lease = self.conn.execute(
                "SELECT owner, expires_at, generation FROM lease WHERE singleton = 1"
            ).fetchone()
            if (
                lease is None
                or lease["owner"] != owner
                or int(lease["generation"] or 0) != int(fence)
                or lease["expires_at"] is None
                or float(lease["expires_at"]) <= now
            ):
                raise LeaseLost(
                    "claim_next requires the current unexpired lease generation"
                )

            row = self.conn.execute(
                """
                SELECT * FROM tasks
                WHERE status IN (?, ?)
                ORDER BY created_at, rowid
                LIMIT 1
                """,
                (TaskStatus.READY.value, TaskStatus.CHANGES_REQUESTED.value),
            ).fetchone()
            if row is None:
                return None

            attempt = int(row["attempts"]) + 1
            claim_token = uuid.uuid4().hex
            self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, attempts = ?, claimed_at = ?, updated_at = ?,
                    attempt_has_result = 0, claim_token = ?
                WHERE task_id = ? AND status = ?
                """,
                (
                    TaskStatus.WORKING.value,
                    attempt,
                    now,
                    now,
                    claim_token,
                    row["task_id"],
                    row["status"],
                ),
            )
            self._log_transition(
                row["task_id"],
                row["status"],
                TaskStatus.WORKING.value,
                "claimed for execution",
                None,
                now,
            )
            return self._to_record(self._task_row(row["task_id"]))  # type: ignore[arg-type]

    def _require_claim(
        self, row: sqlite3.Row, claim_token: str | None
    ) -> None:
        if not claim_token or row["claim_token"] != claim_token:
            raise StaleClaim(
                "claim token does not belong to the current attempt"
            )

    def record_execution_result(
        self,
        task_id: str,
        head_sha: str,
        summary: str,
        now: float,
        *,
        fence: int,
        claim_token: str | None,
    ) -> TaskRecord:
        if not head_sha:
            raise ValueError("head_sha must be non-empty")
        with self.transaction():
            self._require_fence(fence, now)
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])
            if current is not TaskStatus.WORKING:
                raise InvalidTransition(
                    f"execution result requires working state, got {current.value}"
                )
            self._require_claim(row, claim_token)
            self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, head_sha = ?, attempts = 0, last_error = NULL,
                    claimed_at = NULL, updated_at = ?, attempt_has_result = 1,
                    claim_token = NULL
                WHERE task_id = ?
                """,
                (TaskStatus.REVIEW.value, head_sha, now, task_id),
            )
            self._log_transition(
                task_id,
                current.value,
                TaskStatus.REVIEW.value,
                f"execution committed: {summary or 'ok'}",
                head_sha,
                now,
            )
            return self._to_record(self._task_row(task_id))  # type: ignore[arg-type]

    def record_execution_failure(
        self,
        task_id: str,
        message: str,
        now: float,
        *,
        fence: int,
        claim_token: str | None,
        retryable: bool,
        timeout: bool = False,
    ) -> TaskRecord:
        with self.transaction():
            self._require_fence(fence, now)
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])
            if current is not TaskStatus.WORKING:
                raise InvalidTransition(
                    f"execution failure requires working state, got {current.value}"
                )
            self._require_claim(row, claim_token)
            attempts = int(row["attempts"])
            if timeout or not retryable or attempts >= self.max_attempts:
                target = TaskStatus.NEEDS_OWNER
                reason = (
                    "execution timeout"
                    if timeout
                    else f"execution failed ({attempts}/{self.max_attempts} attempts)"
                )
            else:
                target = TaskStatus.READY
                reason = f"retryable execution failure ({attempts}/{self.max_attempts})"
            self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, last_error = ?, claimed_at = NULL, updated_at = ?,
                    attempt_has_result = 0, claim_token = NULL
                WHERE task_id = ?
                """,
                (target.value, message, now, task_id),
            )
            self._log_transition(task_id, current.value, target.value, reason, None, now)
            return self._to_record(self._task_row(task_id))  # type: ignore[arg-type]

    def next_review_task(self) -> TaskRecord | None:
        """A task awaiting a review for its current head, if any."""
        row = self.conn.execute(
            """
            SELECT t.* FROM tasks t
            WHERE t.status = ?
              AND t.head_sha IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM reviews r
                  WHERE r.task_id = t.task_id
                    AND r.head_sha = t.head_sha
                    AND r.stale = 0
              )
            ORDER BY t.updated_at, t.rowid
            LIMIT 1
            """,
            (TaskStatus.REVIEW.value,),
        ).fetchone()
        return self._to_record(row) if row is not None else None

    def submit_review(
        self,
        task_id: str,
        review: ReviewResult,
        now: float,
        *,
        fence: int,
        event_key: str | None = None,
    ) -> ReviewOutcome:
        """Consume one structured review, bound to the exact current head SHA."""
        verdict = ReviewVerdict(review.verdict)
        with self.transaction():
            self._require_fence(fence, now)
            if event_key is not None:
                cursor = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO events
                        (event_key, task_id, stage, detail_json, created_at)
                    VALUES (?, ?, 'review', ?, ?)
                    """,
                    (
                        event_key,
                        task_id,
                        json.dumps(
                            {
                                "head_sha": review.head_sha,
                                "verdict": verdict.value,
                                "reviewer": review.reviewer,
                            },
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    current = self._task_row(task_id)
                    if current is None:
                        raise KeyError(task_id)
                    status = TaskStatus(current["status"])
                    return ReviewOutcome(
                        accepted=status is TaskStatus.DONE,
                        stale=False,
                        status=status,
                        message="duplicate review event ignored",
                    )

            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])

            if review.head_sha != row["head_sha"]:
                try:
                    self.conn.execute(
                        """
                        INSERT OR IGNORE INTO reviews
                            (task_id, head_sha, verdict, defects_json, reviewer,
                             stale, created_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            task_id,
                            review.head_sha,
                            verdict.value,
                            json.dumps(list(review.defects), ensure_ascii=False),
                            review.reviewer,
                            now,
                        ),
                    )
                except sqlite3.Error:
                    pass
                return ReviewOutcome(
                    accepted=False,
                    stale=True,
                    status=current,
                    message=(
                        f"stale review: current head is {row['head_sha']}, "
                        f"review targets {review.head_sha}"
                    ),
                )

            if current is not TaskStatus.REVIEW:
                return ReviewOutcome(
                    accepted=current is TaskStatus.DONE,
                    stale=False,
                    status=current,
                    message=f"task is not under review (status={current.value})",
                )

            review_cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO reviews
                    (task_id, head_sha, verdict, defects_json, reviewer,
                     stale, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    task_id,
                    review.head_sha,
                    verdict.value,
                    json.dumps(list(review.defects), ensure_ascii=False),
                    review.reviewer,
                    now,
                ),
            )
            if review_cursor.rowcount == 0:
                return ReviewOutcome(
                    accepted=False,
                    stale=False,
                    status=current,
                    message="duplicate review for this head ignored",
                )

            if verdict is ReviewVerdict.APPROVED:
                target = TaskStatus.DONE
                reason = "review approved"
            elif verdict is ReviewVerdict.CHANGES_REQUESTED:
                if int(row["rework_rounds"]) >= self.max_rework_rounds:
                    target = TaskStatus.NEEDS_OWNER
                    reason = "rework limit reached"
                else:
                    target = TaskStatus.CHANGES_REQUESTED
                    reason = "changes requested"
            else:
                target = TaskStatus.NEEDS_OWNER
                reason = "reviewer requires owner"

            extra: dict[str, Any] = {}
            if (
                verdict is ReviewVerdict.CHANGES_REQUESTED
                and target is TaskStatus.CHANGES_REQUESTED
            ):
                extra["rework_rounds"] = int(row["rework_rounds"]) + 1
            fields = ["status = ?", "updated_at = ?"]
            params: list[Any] = [target.value, now]
            for key, value in extra.items():
                fields.append(f"{key} = ?")
                params.append(value)
            params.append(task_id)
            self.conn.execute(
                "UPDATE tasks SET " + ", ".join(fields) + " WHERE task_id = ?",
                params,
            )
            self._log_transition(
                task_id,
                current.value,
                target.value,
                reason,
                review.head_sha,
                now,
            )
            return ReviewOutcome(
                accepted=target is TaskStatus.DONE,
                stale=False,
                status=target,
                message=reason,
            )

    def mark_review_failure(
        self, task_id: str, message: str, now: float, *, fence: int
    ) -> TaskRecord:
        with self.transaction():
            self._require_fence(fence, now)
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])
            if current is not TaskStatus.REVIEW:
                return self._to_record(row)
            self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, last_error = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (TaskStatus.NEEDS_OWNER.value, message, now, task_id),
            )
            self._log_transition(
                task_id,
                current.value,
                TaskStatus.NEEDS_OWNER.value,
                f"review failed: {message}",
                row["head_sha"],
                now,
            )
            return self._to_record(self._task_row(task_id))  # type: ignore[arg-type]

    def pause(self, task_id: str, reason: str, now: float, *, fence: int) -> TaskRecord:
        with self.transaction():
            self._require_fence(fence, now)
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            current = TaskStatus(row["status"])
            if current in (TaskStatus.DONE, TaskStatus.NEEDS_OWNER):
                return self._to_record(row)
            if TaskStatus.NEEDS_OWNER not in ALLOWED_TRANSITIONS[current]:
                raise InvalidTransition(
                    f"cannot pause {task_id} from {current.value}"
                )
            self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, last_error = ?, claimed_at = NULL, updated_at = ?
                WHERE task_id = ?
                """,
                (TaskStatus.NEEDS_OWNER.value, reason, now, task_id),
            )
            self._log_transition(
                task_id, current.value, TaskStatus.NEEDS_OWNER.value, reason, None, now
            )
            return self._to_record(self._task_row(task_id))  # type: ignore[arg-type]

    # ------------------------------------------------------------ recovery
    def recover(self, now: float) -> dict[str, int]:
        """Recover after a crash/lease expiry.

        * active lease -> nothing is recovered (another scheduler owns the run);
        * expired lease -> clear it;
        * working with a committed current-attempt result -> review (never execute again);
        * working without a committed current-attempt result -> ready for retry,
          or needs-owner at the attempt limit (an interrupted rework is retried,
          not sent to review of the old head);
        * review/changes-requested are left for normal processing.
        """
        recovered = {"requeued": 0, "review": 0, "needs_owner": 0, "lease_cleared": 0}
        with self.transaction():
            lease = self.conn.execute(
                "SELECT owner, expires_at FROM lease WHERE singleton = 1"
            ).fetchone()
            if (
                lease is not None
                and lease["owner"] is not None
                and lease["expires_at"] is not None
                and float(lease["expires_at"]) > now
            ):
                return recovered
            if lease is not None and lease["owner"] is not None:
                self.conn.execute(
                    "UPDATE lease SET owner = NULL, acquired_at = NULL, expires_at = NULL "
                    "WHERE singleton = 1"
                )
                recovered["lease_cleared"] = 1

            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status = ?", (TaskStatus.WORKING.value,)
            ).fetchall()
            for row in rows:
                task_id = row["task_id"]
                if int(row["attempt_has_result"] or 0) == 1:
                    target = TaskStatus.REVIEW
                    recovered["review"] += 1
                    reason = "recovered committed current-attempt execution into review"
                elif int(row["attempts"]) >= self.max_attempts:
                    target = TaskStatus.NEEDS_OWNER
                    recovered["needs_owner"] += 1
                    reason = "recovery retry limit reached"
                else:
                    target = TaskStatus.READY
                    recovered["requeued"] += 1
                    reason = "recovered interrupted execution for retry"
                self.conn.execute(
                    """
                    UPDATE tasks
                    SET status = ?, claimed_at = NULL, updated_at = ?,
                        attempt_has_result = 0, claim_token = NULL
                    WHERE task_id = ?
                    """,
                    (target.value, now, task_id),
                )
                self._log_transition(
                    task_id,
                    TaskStatus.WORKING.value,
                    target.value,
                    reason,
                    row["head_sha"],
                    now,
                )
            return recovered
