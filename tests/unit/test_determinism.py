"""The determinism envelope must refuse to run in an environment it cannot pin."""

from __future__ import annotations

import pytest

from trading.runtime.determinism import (
    PINNED_ENV,
    numeric_libraries_already_imported,
    require_deterministic_environment,
    verify_environment,
)
from trading.runtime.errors import DeterminismError

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_env() -> dict[str, str]:
    return dict(PINNED_ENV)


def test_pinned_environment_has_no_violations(clean_env: dict[str, str]) -> None:
    assert verify_environment(clean_env) == []


def test_missing_variable_is_reported(clean_env: dict[str, str]) -> None:
    del clean_env["OMP_NUM_THREADS"]
    (violation,) = verify_environment(clean_env)
    assert violation.name == "OMP_NUM_THREADS"
    assert violation.actual is None


def test_wrong_value_is_reported(clean_env: dict[str, str]) -> None:
    clean_env["OMP_NUM_THREADS"] = "8"
    (violation,) = verify_environment(clean_env)
    assert violation.actual == "8"
    assert violation.expected == "1"


def test_thread_counts_are_pinned_to_one() -> None:
    """Any value above one makes float reduction order depend on the machine."""
    thread_vars = {
        k: v for k, v in PINNED_ENV.items() if k.endswith(("_THREADS", "_MAXIMUM_THREADS"))
    }
    assert thread_vars, "the envelope must pin thread counts"
    assert set(thread_vars.values()) == {"1"}


def test_requires_utc_and_stable_hashing() -> None:
    assert PINNED_ENV["TZ"] == "UTC"
    assert PINNED_ENV["PYTHONHASHSEED"] == "0"


def test_require_raises_and_names_every_violation(clean_env: dict[str, str]) -> None:
    clean_env["TZ"] = "America/New_York"
    del clean_env["MKL_NUM_THREADS"]

    with pytest.raises(DeterminismError) as excinfo:
        require_deterministic_environment(clean_env)

    message = str(excinfo.value)
    assert "TZ" in message
    assert "MKL_NUM_THREADS" in message


def test_require_passes_on_a_pinned_environment(clean_env: dict[str, str]) -> None:
    require_deterministic_environment(clean_env)


def test_error_explains_why_a_late_fix_will_not_work(clean_env: dict[str, str]) -> None:
    """numpy is imported by the time tests run, so the hint must say so."""
    clean_env["OMP_NUM_THREADS"] = "4"
    assert "numpy" in numeric_libraries_already_imported()

    with pytest.raises(DeterminismError, match="before starting the interpreter"):
        require_deterministic_environment(clean_env)
