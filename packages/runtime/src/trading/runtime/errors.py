"""Exceptions raised when the determinism envelope is violated."""

from __future__ import annotations


class DeterminismError(RuntimeError):
    """The process cannot guarantee reproducible results.

    Raised rather than warned. Section 2 of the specification makes
    non-determinism a CI failure and a release stop, so a violated envelope is
    never something the caller may continue past.
    """


class ProvenanceError(RuntimeError):
    """The process cannot establish what code and image it is running.

    Raised when the runtime is containerized but no image digest was injected.
    An experiment that records a null digest while actually running inside a
    container is unreproducible in a way no later audit can detect, so this is
    fatal at startup rather than recorded as a caveat.
    """
