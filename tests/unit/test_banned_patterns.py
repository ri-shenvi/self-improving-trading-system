"""Every banned-pattern rule must fire on a real violation.

A checker nobody has seen reject anything is indistinguishable from one that
always passes, so each rule is exercised against source that violates it and
against source that does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.banned_patterns import check_source

pytestmark = pytest.mark.unit


def codes(source: str, path: str = "packages/schemas/src/trading/schemas/thing.py") -> list[str]:
    return [v.code for v in check_source(Path(path), source)]


class TestNaiveDatetimeAnnotations:
    """TRD001 — D3."""

    def test_flags_bare_annotation(self) -> None:
        assert "TRD001" in codes(
            "import datetime\n\nclass Row:\n    event_time: datetime.datetime\n"
        )

    def test_flags_optional_annotation(self) -> None:
        source = "from datetime import datetime\n\nclass Row:\n    revision_time: datetime | None\n"
        assert "TRD001" in codes(source)

    def test_flags_string_annotation(self) -> None:
        source = 'class Row:\n    event_time: "datetime"\n'
        assert "TRD001" in codes(source)

    def test_flags_function_signatures(self) -> None:
        source = "from datetime import datetime\n\ndef at(t: datetime) -> None: ...\n"
        assert "TRD001" in codes(source)

    def test_allows_date(self) -> None:
        source = "import datetime\n\nclass Row:\n    session: datetime.date\n"
        assert codes(source) == []

    def test_allows_int_nanoseconds(self) -> None:
        assert codes("class Row:\n    event_time_ns: int\n") == []


class TestFeatureJoins:
    """TRD002 — D5."""

    FEATURES = "packages/features/src/trading/features/orderflow.py"
    PIT = "packages/features/src/trading/features/pit.py"

    def test_flags_raw_join_in_features(self) -> None:
        assert "TRD002" in codes("def f(a, b):\n    return a.join(b)\n", self.FEATURES)

    def test_flags_join_asof_in_features(self) -> None:
        assert "TRD002" in codes("def f(a, b):\n    return a.join_asof(b)\n", self.FEATURES)

    def test_pit_module_is_the_sanctioned_join(self) -> None:
        assert codes("def f(a, b):\n    return a.join_asof(b)\n", self.PIT) == []

    def test_other_packages_are_unaffected(self) -> None:
        source = "def f(a, b):\n    return a.join(b)\n"
        assert codes(source, "packages/backtest/src/trading/backtest/report.py") == []


class TestTickerJoins:
    """TRD003 — D6."""

    @pytest.mark.parametrize("key", ["symbol", "ticker", "SYMBOL"])
    def test_flags_ticker_key(self, key: str) -> None:
        assert "TRD003" in codes(f'def f(a, b):\n    return a.join(b, on="{key}")\n')

    def test_flags_ticker_inside_key_list(self) -> None:
        source = 'def f(a, b):\n    return a.join(b, left_on=["symbol", "date"])\n'
        assert "TRD003" in codes(source)

    def test_allows_instrument_id(self) -> None:
        assert codes('def f(a, b):\n    return a.join(b, on="instrument_id")\n') == []


class TestRandomness:
    """TRD004 — D9."""

    def test_flags_stdlib_random_import(self) -> None:
        assert "TRD004" in codes("import random\n")

    def test_flags_stdlib_random_from_import(self) -> None:
        assert "TRD004" in codes("from random import choice\n")

    def test_flags_unseeded_generator(self) -> None:
        assert "TRD004" in codes("import numpy as np\n\nrng = np.random.default_rng()\n")

    def test_seeds_module_may_construct_generators(self) -> None:
        source = (
            "import numpy as np\n\ndef f(s):\n    return np.random.Generator(np.random.PCG64(s))\n"
        )
        assert codes(source, "packages/runtime/src/trading/runtime/seeds.py") == []


class TestAllowComment:
    def test_suppresses_with_a_reason(self) -> None:
        source = "import random  # allow: TRD004 used only to shuffle a fixture\n"
        assert codes(source) == []

    def test_reason_is_mandatory(self) -> None:
        assert "TRD004" in codes("import random  # allow: TRD004\n")

    def test_does_not_suppress_other_codes(self) -> None:
        source = 'def f(a, b):\n    return a.join(b, on="symbol")  # allow: TRD004 unrelated\n'
        assert "TRD003" in codes(source)


class TestRepositoryIsClean:
    def test_no_violations_in_library_code(self) -> None:
        from tools.banned_patterns import check_path, discover

        violations = [v for path in discover([]) for v in check_path(path)]
        assert violations == [], "\n".join(v.render() for v in violations)
