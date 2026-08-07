from llm_platform.evaluation.learned import assignment_bucket
from llm_platform.evaluation.offline import Outcome, evaluate


def test_offline_evaluator_and_stable_assignment() -> None:
    report = evaluate([Outcome("a", True, 2), Outcome("a", False, 4), Outcome("b", True, 3)])
    assert report.count == 3
    assert report.success_rate == 2 / 3
    assert report.mean_elapsed_seconds == 3
    assert assignment_bucket("task", "experiment") == assignment_bucket("task", "experiment")
