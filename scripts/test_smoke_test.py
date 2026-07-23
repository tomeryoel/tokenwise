from scripts.smoke_test import _safe_run_id


def test_safe_run_ids_are_letter_only_and_distinct() -> None:
    run_ids = {_safe_run_id() for _ in range(1_000)}

    assert len(run_ids) == 1_000
    assert all(len(run_id) == 10 for run_id in run_ids)
    assert all(run_id.isascii() and run_id.isalpha() and run_id.islower() for run_id in run_ids)
