"""Every entry point must declare exactly the pinned environment (D9).

The envelope has to be set before the interpreter starts, so it is necessarily
repeated in the Makefile, the Dockerfile and the CI workflow. Duplication that
cannot be removed is duplication that has to be pinned: a thread count silently
dropped from one of the three would leave that path producing metrics that
differ in the last bits from the other two, and nothing else would notice.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pytest

from trading.runtime.determinism import PINNED_ENV

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = ROOT / "Makefile"
DOCKERFILE = ROOT / "infra" / "docker" / "Dockerfile"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def makefile_env() -> dict[str, str]:
    pattern = re.compile(r"^export\s+(\w+)\s*:?=\s*(\S+)\s*$", re.MULTILINE)
    return dict(pattern.findall(MAKEFILE.read_text()))


def dockerfile_env() -> dict[str, str]:
    """Parse the runtime stage's ENV block, which uses backslash continuations."""
    text = DOCKERFILE.read_text()
    runtime = text.split("AS runtime", 1)[1]
    block = re.search(r"^ENV\s(.*?)(?=\n[A-Z]{3,}\s)", runtime, re.DOTALL | re.MULTILINE)
    assert block is not None, "no ENV block in the runtime stage"
    joined = block.group(1).replace("\\\n", " ")
    return dict(re.findall(r"(\w+)=(\S+)", joined))


def workflow_env() -> dict[str, str]:
    text = WORKFLOW.read_text()
    block = re.search(r"^env:\n((?:  \S+:.*\n)+)", text, re.MULTILINE)
    assert block is not None, "no top-level env block in the workflow"
    return {k: v.strip('"') for k, v in re.findall(r'  (\w+):\s*"?([^"\n]+)"?', block.group(1))}


@pytest.mark.parametrize(
    ("name", "reader"),
    [("Makefile", makefile_env), ("Dockerfile", dockerfile_env), ("ci.yml", workflow_env)],
)
def test_entry_point_declares_the_whole_envelope(
    name: str, reader: Callable[[], dict[str, str]]
) -> None:
    declared = reader()
    missing = {k: v for k, v in PINNED_ENV.items() if declared.get(k) != v}
    assert not missing, f"{name} is missing or contradicts: {missing}"


def test_entry_points_agree_with_each_other() -> None:
    pinned = set(PINNED_ENV)
    for name, reader in [
        ("Makefile", makefile_env),
        ("Dockerfile", dockerfile_env),
        ("ci.yml", workflow_env),
    ]:
        declared = {k: v for k, v in reader().items() if k in pinned}
        assert declared == dict(PINNED_ENV), f"{name} diverges from PINNED_ENV"
