import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from llm_platform.persistence.models import InferenceRequestRow, utc_now


@dataclass(frozen=True, slots=True)
class RequestRecord:
    request_id: str
    user_id: str
    state: str
    requested_model: str
    selected_deployment: str | None


def body_metadata(body: dict[str, Any]) -> tuple[str, int]:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


class RequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        request_id: str,
        user_id: str,
        requested_model: str,
        priority: str,
        body: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> RequestRecord:
        if idempotency_key is not None:
            existing = await self.session.scalar(
                select(InferenceRequestRow).where(
                    InferenceRequestRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return self._record(existing)
        digest, size = body_metadata(body)
        row = InferenceRequestRow(
            id=request_id,
            idempotency_key=idempotency_key,
            user_id=user_id,
            mode="inference",
            requested_model=requested_model,
            priority=priority,
            state="queued",
            body_hash=digest,
            body_size=size,
        )
        self.session.add(row)
        await self.session.commit()
        return self._record(row)

    async def transition(
        self,
        request_id: str,
        from_states: set[str],
        target: str,
        *,
        selected_deployment: str | None = None,
        error_code: str | None = None,
    ) -> bool:
        row = await self.session.get(InferenceRequestRow, request_id)
        if row is None or row.state not in from_states:
            return False
        row.state = target
        if selected_deployment is not None:
            row.selected_deployment = selected_deployment
        if target == "running":
            row.started_at = utc_now()
        if target in {"completed", "failed", "cancelled"}:
            row.completed_at = utc_now()
        row.error_code = error_code
        await self.session.commit()
        return True

    async def recover_unfinished(self) -> list[RequestRecord]:
        rows = (
            await self.session.scalars(
                select(InferenceRequestRow).where(
                    InferenceRequestRow.state.in_(["queued", "assigned", "running"])
                )
            )
        ).all()
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: InferenceRequestRow) -> RequestRecord:
        return RequestRecord(
            row.id, row.user_id, row.state, row.requested_model, row.selected_deployment
        )


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.astimezone()
