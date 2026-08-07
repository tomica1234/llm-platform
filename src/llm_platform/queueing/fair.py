from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from llm_platform.common.enums import QueueClass


class QueueState(StrEnum):
    WAITING = "waiting"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class QueueItem:
    request_id: str
    user_id: str
    deployment_id: str | None
    queue_class: QueueClass = QueueClass.AGENT
    state: QueueState = QueueState.WAITING


class FairRequestQueue:
    """Weighted-class, round-robin-per-user queue for at most three users."""

    _CLASS_ORDER = (
        QueueClass.MAINTENANCE,
        QueueClass.INTERACTIVE,
        QueueClass.AGENT,
        QueueClass.BACKGROUND,
    )

    def __init__(self, max_users: int = 3, max_pending_per_user: int = 20) -> None:
        self.max_users = max_users
        self.max_pending_per_user = max_pending_per_user
        self._queues: dict[QueueClass, dict[str, deque[QueueItem]]] = {
            queue_class: {} for queue_class in self._CLASS_ORDER
        }
        self._user_order: deque[str] = deque()
        self._items: dict[str, QueueItem] = {}
        self._background_turn = 0

    def enqueue(self, item: QueueItem) -> None:
        if item.request_id in self._items:
            raise ValueError("request ID already exists")
        users = {
            value.user_id for value in self._items.values() if value.state is QueueState.WAITING
        }
        if item.user_id not in users and len(users) >= self.max_users:
            raise ValueError("maximum active users reached")
        pending = sum(
            value.user_id == item.user_id and value.state is QueueState.WAITING
            for value in self._items.values()
        )
        if pending >= self.max_pending_per_user:
            raise ValueError("per-user pending request limit reached")
        user_queue = self._queues[item.queue_class].setdefault(item.user_id, deque())
        user_queue.append(item)
        self._items[item.request_id] = item
        if item.user_id not in self._user_order:
            self._user_order.append(item.user_id)

    def _next_class(self) -> QueueClass | None:
        self._background_turn += 1
        if self._background_turn % 10 == 0 and any(self._queues[QueueClass.BACKGROUND].values()):
            return QueueClass.BACKGROUND
        for queue_class in self._CLASS_ORDER:
            if any(self._queues[queue_class].values()):
                return queue_class
        return None

    def dequeue(self) -> QueueItem | None:
        queue_class = self._next_class()
        if queue_class is None:
            return None
        for _ in range(len(self._user_order)):
            user_id = self._user_order[0]
            self._user_order.rotate(-1)
            user_queue = self._queues[queue_class].get(user_id)
            if user_queue:
                item = user_queue.popleft()
                item.state = QueueState.ASSIGNED
                self._cleanup_user(user_id)
                return item
        return self.dequeue()

    def cancel(self, request_id: str) -> bool:
        item = self._items.get(request_id)
        if item is None or item.state in {QueueState.COMPLETED, QueueState.CANCELLED}:
            return False
        if item.state is QueueState.WAITING:
            queue = self._queues[item.queue_class].get(item.user_id)
            if queue is not None:
                self._queues[item.queue_class][item.user_id] = deque(
                    queued for queued in queue if queued.request_id != request_id
                )
        item.state = QueueState.CANCELLED
        self._cleanup_user(item.user_id)
        return True

    def _cleanup_user(self, user_id: str) -> None:
        has_pending = any(self._queues[kind].get(user_id) for kind in self._CLASS_ORDER)
        if not has_pending:
            self._user_order = deque(value for value in self._user_order if value != user_id)

    def position(self, request_id: str) -> int | None:
        item = self._items.get(request_id)
        if item is None or item.state is not QueueState.WAITING:
            return None
        return sum(
            value.state is QueueState.WAITING and value.request_id != request_id
            for value in self._items.values()
        )

    def snapshot(self) -> tuple[QueueItem, ...]:
        return tuple(self._items.values())
