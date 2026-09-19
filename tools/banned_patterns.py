"""Static checks for the invariants that lint rules cannot express.

Four decisions in the implementation plan are cheap to state and expensive to
retrofit, and each has a syntactic signature this checker rejects at CI time:

======  ========  ==============================================================
Code    Decision  Rule
======  ========  ==============================================================
TRD001  D3        No bare ``datetime`` annotations in library code.
TRD002  D5        No ad-hoc joins in ``packages/features`` outside ``pit.py``.
TRD003  D6        No joins keyed on ticker or symbol.
TRD004  D9        No unseeded or module-level randomness.
======  ========  ==============================================================

Ruff covers the call-site half of D3 through its ``DTZ`` rules and the legacy
numpy global generator through ``NPY002``; this checker covers what those cannot
see. A bare ``datetime`` *annotation* is the case ruff misses, and it is the one
that matters: section 41 lists look-ahead as the first failure mode, and a
timestamp field whose type permits a naive value is how a decision clock silently
shifts at a DST boundary.

An escape hatch exists but costs something: ``# allow: TRD00N reason`` on the
offending line suppresses it, and the reason is mandatory. A rule that cannot be
suppressed gets deleted the first time it is wrong; one suppressed without
explanation stops meaning anything.

Usage::

    python tools/banned_patterns.py [path ...]
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parent.parent

#: Library code. Tests and tools legitimately construct bad values to prove the
#: checks fire, so they are excluded rather than exempted line by line.
SCAN_GLOBS: Final = ("packages/*/src/**/*.py", "apps/*/src/**/*.py")

#: The one module permitted to perform a raw join: it *is* the sanctioned join.
PIT_MODULE: Final = "pit.py"

#: The one module permitted to construct a generator: it derives them from the
#: recorded experiment seed.
SEEDS_MODULE: Final = "seeds.py"

_JOIN_METHODS: Final = frozenset({"join", "join_asof", "merge", "merge_sorted"})
_JOIN_KEY_ARGS: Final = frozenset({"on", "left_on", "right_on", "by", "by_left", "by_right"})
_TICKER_KEYS: Final = frozenset({"symbol", "ticker", "sym"})
_GENERATOR_FACTORIES: Final = frozenset({"default_rng", "Generator", "RandomState"})

_ALLOW_RE: Final = re.compile(r"#\s*allow:\s*(TRD\d{3})\s+(?P<reason>\S.*)$")


@dataclass(frozen=True, slots=True)
class Violation:
    path: Path
    line: int
    col: int
    code: str
    message: str

    def render(self) -> str:
        rel = self.path.relative_to(ROOT) if self.path.is_absolute() else self.path
        return f"{rel}:{self.line}:{self.col + 1}: {self.code} {self.message}"


def _allowed_codes(source_lines: list[str], line: int) -> set[str]:
    """Return codes suppressed on a line by an ``# allow:`` comment with a reason."""
    if not 1 <= line <= len(source_lines):
        return set()
    match = _ALLOW_RE.search(source_lines[line - 1])
    return {match.group(1)} if match else set()


def _annotation_mentions_datetime(node: ast.expr) -> ast.expr | None:
    """Return the offending sub-node if an annotation permits a bare datetime.

    Walks structurally rather than with :func:`ast.walk` so that a qualified name
    can be judged as a whole. ``datetime.date`` and ``datetime.timedelta`` are
    fine; blindly descending would find the ``datetime`` module reference inside
    them and flag every date field in the system.
    """
    if isinstance(node, ast.Attribute):
        if node.attr == "datetime":
            return node
        if isinstance(node.value, ast.Name) and node.value.id == "datetime":
            return None  # some other member of the datetime module
        return _annotation_mentions_datetime(node.value)

    if isinstance(node, ast.Name):
        return node if node.id == "datetime" else None

    # String annotations, whether quoted by hand or left over from a codebase
    # that predates `from __future__ import annotations`.
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return None
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return None
        return node if _annotation_mentions_datetime(parsed.body) is not None else None

    # Containers: Optional[...], X | None, dict[str, ...], tuple[...].
    for child in ast.iter_child_nodes(node):
        if (
            isinstance(child, ast.expr)
            and (found := _annotation_mentions_datetime(child)) is not None
        ):
            return found
    return None


class _Checker(ast.NodeVisitor):
    def __init__(self, path: Path, source_lines: list[str]) -> None:
        self.path = path
        self.lines = source_lines
        self.violations: list[Violation] = []
        self._in_features = "packages/features/src" in path.as_posix()
        self._is_pit = path.name == PIT_MODULE
        self._is_seeds = path.name == SEEDS_MODULE

    def _report(self, node: ast.AST, code: str, message: str) -> None:
        line = getattr(node, "lineno", 0)
        if code in _allowed_codes(self.lines, line):
            return
        self.violations.append(
            Violation(
                path=self.path,
                line=line,
                col=getattr(node, "col_offset", 0),
                code=code,
                message=message,
            )
        )

    # -- TRD001 -----------------------------------------------------------
    def _check_annotation(self, annotation: ast.expr | None) -> None:
        if annotation is None:
            return
        if (offender := _annotation_mentions_datetime(annotation)) is not None:
            self._report(
                offender,
                "TRD001",
                "bare 'datetime' annotation: use the nanosecond int64 timestamp type "
                "from trading.schemas.time (D3). A naive datetime here shifts decision "
                "clocks at DST boundaries.",
            )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_annotation(node.annotation)
        self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> None:
        self._check_annotation(node.annotation)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_annotation(node.returns)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_annotation(node.returns)
        self.generic_visit(node)

    # -- TRD004 (imports) -------------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "random" or alias.name.startswith("random."):
                self._report(
                    node,
                    "TRD004",
                    "stdlib 'random' is process-global and unseeded: derive a named "
                    "stream from SeedEnvelope instead (D9).",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "random":
            self._report(
                node,
                "TRD004",
                "stdlib 'random' is process-global and unseeded: derive a named "
                "stream from SeedEnvelope instead (D9).",
            )
        self.generic_visit(node)

    # -- TRD002 / TRD003 / TRD004 (calls) ---------------------------------
    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            self._check_join(node, node.func)
            self._check_generator(node, node.func)
        self._check_join_keys(node)
        self.generic_visit(node)

    def _check_join(self, node: ast.Call, func: ast.Attribute) -> None:
        if func.attr not in _JOIN_METHODS:
            return
        if self._in_features and not self._is_pit:
            self._report(
                node,
                "TRD002",
                f"'.{func.attr}()' in packages/features: route every join through "
                "as_of_join() in pit.py, which raises when a right-hand row has "
                "knowledge_time > decision_time (D5).",
            )

    def _check_join_keys(self, node: ast.Call) -> None:
        for keyword in node.keywords:
            if keyword.arg not in _JOIN_KEY_ARGS:
                continue
            for key in _string_literals(keyword.value):
                if key.lower() in _TICKER_KEYS:
                    self._report(
                        keyword.value,
                        "TRD003",
                        f"join keyed on {key!r}: tickers are reused and reassigned, so "
                        "key on instrument_id and resolve through ticker_history (D6).",
                    )

    def _check_generator(self, node: ast.Call, func: ast.Attribute) -> None:
        if func.attr not in _GENERATOR_FACTORIES:
            return
        if not _is_numpy_random(func.value):
            return
        if self._is_seeds:
            return
        self._report(
            node,
            "TRD004",
            f"'np.random.{func.attr}()' constructs a generator outside "
            "trading.runtime.seeds: obtain one from SeedEnvelope.stream(name) so it "
            "descends from the recorded experiment seed (D9).",
        )


def _is_numpy_random(node: ast.expr) -> bool:
    """Match ``np.random``, ``numpy.random`` or a bare ``random`` module attribute."""
    if isinstance(node, ast.Attribute) and node.attr == "random":
        return isinstance(node.value, ast.Name) and node.value.id in {"np", "numpy"}
    return isinstance(node, ast.Name) and node.id == "random"


def _string_literals(node: ast.expr) -> Iterator[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            yield from _string_literals(element)


def check_source(path: Path, source: str) -> list[Violation]:
    """Return every violation in one module's source."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Violation(
                path=path,
                line=exc.lineno or 0,
                col=(exc.offset or 1) - 1,
                code="TRD000",
                message=f"could not parse: {exc.msg}",
            )
        ]
    checker = _Checker(path, source.splitlines())
    checker.visit(tree)
    return sorted(checker.violations, key=lambda v: (v.line, v.col, v.code))


def check_path(path: Path) -> list[Violation]:
    return check_source(path, path.read_text(encoding="utf-8"))


def discover(roots: list[Path]) -> list[Path]:
    if roots:
        return sorted(
            p for root in roots for p in ([root] if root.is_file() else root.rglob("*.py"))
        )
    return sorted({p for glob in SCAN_GLOBS for p in ROOT.glob(glob)})


def main(argv: list[str]) -> int:
    paths = discover([Path(a) for a in argv])
    violations = [v for path in paths for v in check_path(path)]
    for violation in violations:
        print(violation.render())
    if violations:
        print(f"\n{len(violations)} banned pattern(s) across {len(paths)} file(s).")
        return 1
    print(f"banned-pattern check: clean across {len(paths)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
