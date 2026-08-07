from llm_platform.common.enums import QueueClass
from llm_platform.queueing.fair import FairRequestQueue, QueueItem, QueueState


def test_three_user_round_robin_fairness() -> None:
    queue = FairRequestQueue()
    for sequence in range(3):
        for user in ("a", "b", "c"):
            queue.enqueue(QueueItem(f"{user}{sequence}", user, "shared", QueueClass.AGENT))
    order = [queue.dequeue().user_id for _ in range(9)]  # type: ignore[union-attr]
    assert order == ["a", "b", "c"] * 3


def test_cancel_one_request_does_not_cancel_shared_neighbor() -> None:
    queue = FairRequestQueue()
    first = QueueItem("a", "alice", "shared")
    second = QueueItem("b", "bob", "shared")
    queue.enqueue(first)
    queue.enqueue(second)
    assert queue.cancel("a")
    assert first.state is QueueState.CANCELLED
    assert queue.dequeue() is second
    assert second.state is QueueState.ASSIGNED


def test_background_eventually_runs() -> None:
    queue = FairRequestQueue(max_pending_per_user=30)
    queue.enqueue(QueueItem("background", "b", None, QueueClass.BACKGROUND))
    for index in range(12):
        queue.enqueue(QueueItem(f"interactive-{index}", "a", None, QueueClass.INTERACTIVE))
    selected = [queue.dequeue() for _ in range(10)]
    assert any(item and item.request_id == "background" for item in selected)
