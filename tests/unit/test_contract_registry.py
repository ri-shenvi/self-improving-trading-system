"""A contract cannot change shape without the change appearing in a diff.

The registry is the mechanism that makes the M1 freeze real. If it could not
detect an edit, "frozen" would be a comment rather than a control — so each way
a contract can drift is exercised here against a lock written to a temp file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading.schemas.registry import Lock, LockEntry, RegistryError, check, register, render_lock
from trading.schemas.spec import (
    ContractSpec,
    FieldKind,
    FieldSpec,
    Maturity,
    TimeGroup,
    emitter_version,
)

pytestmark = pytest.mark.unit


def toy(
    *, version: int = 1, maturity: Maturity = Maturity.FROZEN, extra: bool = False
) -> ContractSpec:
    fields = [
        FieldSpec("event_time", FieldKind.TIMESTAMP_NS, unit="ns_utc"),
        FieldSpec("price_nano", FieldKind.NANO_DOLLARS, unit="nanodollar"),
    ]
    if extra:
        fields.append(FieldSpec("venue", FieldKind.CODE, codeset="exchange_v1"))
    return ContractSpec(
        name="toy.contract",
        version=version,
        maturity=maturity,
        doc="A contract used only to prove the registry works.",
        fields=tuple(fields),
        time_group=TimeGroup.CORE,
    )


@pytest.fixture
def lock_file(tmp_path: Path) -> Path:
    path = tmp_path / "contracts.json"
    path.write_text(render_lock((toy(),)), encoding="utf-8")
    return path


class TestDriftDetection:
    def test_unchanged_contract_passes(self, lock_file: Path) -> None:
        assert check(lock_file, (toy(),)) == []

    def test_added_field_without_a_bump_fails(self, lock_file: Path) -> None:
        (finding,) = check(lock_file, (toy(extra=True),))
        assert "version is still 1" in finding.detail

    def test_the_failure_names_the_field_that_changed(self, lock_file: Path) -> None:
        """Two differing hex strings tell a reviewer nothing; a diff does."""
        (finding,) = check(lock_file, (toy(extra=True),))
        assert "+field=002:venue" in finding.detail

    def test_frozen_contracts_say_so(self, lock_file: Path) -> None:
        (finding,) = check(lock_file, (toy(extra=True),))
        assert "FROZEN" in finding.detail
        assert "--break-frozen" in finding.detail

    def test_provisional_contracts_ask_only_for_a_bump(self, tmp_path: Path) -> None:
        path = tmp_path / "lock.json"
        path.write_text(render_lock((toy(maturity=Maturity.PROVISIONAL),)), encoding="utf-8")
        (finding,) = check(path, (toy(maturity=Maturity.PROVISIONAL, extra=True),))
        assert "FROZEN" not in finding.detail
        assert "Bump the version" in finding.detail

    def test_a_bumped_version_still_needs_accepting(self, lock_file: Path) -> None:
        (finding,) = check(lock_file, (toy(version=2, extra=True),))
        assert "version bumped 1 -> 2" in finding.detail

    def test_promoting_maturity_is_itself_a_change(self, lock_file: Path) -> None:
        """Provisional -> frozen must be a recorded, hashed event, not an edit."""
        assert check(lock_file, (toy(maturity=Maturity.PROVISIONAL),)) != []

    def test_undeclared_contract_is_reported(self, lock_file: Path) -> None:
        (finding,) = check(lock_file, ())
        assert "no longer declared" in finding.detail

    def test_unlocked_contract_is_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.json"
        path.write_text(
            json.dumps(Lock(emitter_version=emitter_version(), contracts={}, breaks=[]))
        )
        (finding,) = check(path, (toy(),))
        assert "not in the lock" in finding.detail

    def test_emitter_change_invalidates_everything_at_once(self, tmp_path: Path) -> None:
        """A remapped FieldKind changes bytes without changing any contract hash."""
        path = tmp_path / "lock.json"
        body = Lock(
            emitter_version="stale",
            breaks=[],
            contracts={
                "toy.contract": LockEntry(
                    version=1,
                    maturity="frozen",
                    hash=toy().content_hash(),
                    canonical=toy().canonical_form(),
                )
            },
        )
        path.write_text(json.dumps(body), encoding="utf-8")
        findings = check(path, (toy(),))
        assert findings[0].contract == "<emitter>"


class TestCanonicalForm:
    def test_hash_is_stable(self) -> None:
        assert toy().content_hash() == toy().content_hash()

    def test_hash_is_independent_of_pyarrow(self) -> None:
        """Pinned literal: pyarrow's own serialization carries no stability promise."""
        expected = (
            "contract=toy.contract\n"
            "version=1\n"
            "maturity=frozen\n"
            "time_group=core\n"
            "field=000:event_time:timestamp_ns:required:unit=ns_utc:codeset=\n"
            "field=001:price_nano:nano_dollars:required:unit=nanodollar:codeset=\n"
        )
        assert toy().canonical_form() == expected

    def test_docstrings_are_not_hashed(self) -> None:
        """Improving documentation must not force a version bump."""
        documented = ContractSpec(
            name=toy().name,
            version=toy().version,
            maturity=toy().maturity,
            doc="A completely different explanation.",
            fields=tuple(
                FieldSpec(f.name, f.kind, f.nullable, doc="prose", unit=f.unit, codeset=f.codeset)
                for f in toy().fields
            ),
            time_group=toy().time_group,
        )
        assert documented.content_hash() == toy().content_hash()

    def test_units_are_hashed(self) -> None:
        """A unit change alters how the bytes must be read, so it must move the hash."""
        assert (
            FieldSpec("x", FieldKind.TEXT, unit="a").__hash__ is not None
        )  # frozen dataclass sanity
        a = ContractSpec("c", 1, Maturity.FROZEN, "", (FieldSpec("x", FieldKind.TEXT, unit="a"),))
        b = ContractSpec("c", 1, Maturity.FROZEN, "", (FieldSpec("x", FieldKind.TEXT, unit="b"),))
        assert a.content_hash() != b.content_hash()

    def test_codesets_are_hashed(self) -> None:
        a = ContractSpec(
            "c", 1, Maturity.FROZEN, "", (FieldSpec("x", FieldKind.TEXT, codeset="v1"),)
        )
        b = ContractSpec(
            "c", 1, Maturity.FROZEN, "", (FieldSpec("x", FieldKind.TEXT, codeset="v2"),)
        )
        assert a.content_hash() != b.content_hash()

    def test_field_order_is_part_of_the_contract(self) -> None:
        """Column order decides parquet bytes, so reordering is a breaking change."""
        forward = toy(extra=True)
        reversed_fields = ContractSpec(
            name=forward.name,
            version=forward.version,
            maturity=forward.maturity,
            doc=forward.doc,
            fields=tuple(reversed(forward.fields)),
            time_group=forward.time_group,
        )
        assert forward.content_hash() != reversed_fields.content_hash()


class TestValidation:
    def test_required_units_are_enforced(self) -> None:
        with pytest.raises(ValueError, match="must declare unit='nanodollar'"):
            FieldSpec("price", FieldKind.NANO_DOLLARS)

    def test_duplicate_field_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate field names"):
            ContractSpec(
                "c",
                1,
                Maturity.FROZEN,
                "",
                (FieldSpec("x", FieldKind.TEXT), FieldSpec("x", FieldKind.BOOL)),
            )

    def test_empty_contract_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one field"):
            ContractSpec("c", 1, Maturity.FROZEN, "", ())

    def test_double_registration_rejected(self) -> None:
        spec = ContractSpec(
            "dup.contract", 1, Maturity.FROZEN, "", (FieldSpec("x", FieldKind.TEXT),)
        )
        register(spec)
        with pytest.raises(RegistryError, match="registered twice"):
            register(spec)

    def test_class_name_derivation(self) -> None:
        assert toy().class_name == "ToyContract"
