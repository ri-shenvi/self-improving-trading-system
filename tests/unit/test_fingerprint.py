"""Provenance: what image ran, and what environment it was built from."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading.runtime import fingerprint as fp
from trading.runtime.errors import ProvenanceError

pytestmark = pytest.mark.unit

VALID_DIGEST = "sha256:" + "ab" * 32


@pytest.fixture
def lockfile(tmp_path: Path) -> Path:
    path = tmp_path / "uv.lock"
    path.write_text("version = 1\n")
    return path


class TestContainerIdentity:
    def test_host_process_has_no_image(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fp, "_is_containerized", lambda: False)
        identity = fp.container_identity({})
        assert identity.provenance == "host"
        assert identity.image_digest is None
        assert not identity.is_reproducible_context

    def test_container_reads_the_injected_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fp, "_is_containerized", lambda: True)
        identity = fp.container_identity({fp.CONTAINER_DIGEST_ENV: VALID_DIGEST})
        assert identity.provenance == "container"
        assert identity.image_digest == VALID_DIGEST
        assert identity.is_reproducible_context

    def test_container_without_a_digest_is_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recording None here would produce rows that look reproducible and are not."""
        monkeypatch.setattr(fp, "_is_containerized", lambda: True)
        with pytest.raises(ProvenanceError, match="unset"):
            fp.container_identity({})

    @pytest.mark.parametrize(
        "bad", ["", "latest", "sha256:short", "md5:" + "ab" * 16, "sha256:" + "AB" * 32]
    )
    def test_container_rejects_a_malformed_digest(
        self, monkeypatch: pytest.MonkeyPatch, bad: str
    ) -> None:
        monkeypatch.setattr(fp, "_is_containerized", lambda: True)
        with pytest.raises(ProvenanceError):
            fp.container_identity({fp.CONTAINER_DIGEST_ENV: bad})


class TestEnvironmentFingerprint:
    def test_is_stable_across_repeated_computation(self, lockfile: Path) -> None:
        """Two builds from one lockfile must fingerprint identically (M0 exit test)."""
        first = fp.compute_environment_fingerprint(lockfile, base_image_digest=VALID_DIGEST)
        second = fp.compute_environment_fingerprint(lockfile, base_image_digest=VALID_DIGEST)
        assert first.value == second.value
        assert first == second

    def test_changes_when_the_lock_changes(self, lockfile: Path) -> None:
        before = fp.compute_environment_fingerprint(lockfile).value
        lockfile.write_text("version = 1\n# an upgraded transitive dependency\n")
        assert fp.compute_environment_fingerprint(lockfile).value != before

    def test_changes_with_the_base_image(self, lockfile: Path) -> None:
        a = fp.compute_environment_fingerprint(lockfile, base_image_digest=VALID_DIGEST)
        b = fp.compute_environment_fingerprint(lockfile, base_image_digest="sha256:" + "cd" * 32)
        assert a.value != b.value

    def test_changes_with_the_interpreter(self, lockfile: Path) -> None:
        a = fp.compute_environment_fingerprint(lockfile, python_version="3.12.3")
        b = fp.compute_environment_fingerprint(lockfile, python_version="3.12.4")
        assert a.value != b.value

    def test_canonical_form_shows_which_field_diverged(self, lockfile: Path) -> None:
        """A reviewer comparing fingerprints needs the fields, not just the hash."""
        printed = fp.compute_environment_fingerprint(lockfile).canonical_form()
        assert printed.splitlines() == sorted(printed.splitlines())
        assert "lock_sha256=" in printed
        assert "python_version=" in printed

    def test_missing_lockfile_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="uv lock"):
            fp.compute_environment_fingerprint(tmp_path / "absent.lock")

    def test_repository_lockfile_fingerprints(self) -> None:
        root = Path(__file__).resolve().parents[2]
        result = fp.compute_environment_fingerprint(root / "uv.lock")
        assert len(result.value) == 64
        assert result.lock_sha256 != result.pinned_env_sha256
