"""``trading`` — the command line for snapshots and, later, experiments.

Every command that produces data takes its clock as an argument rather than
reading one. That is not pedantry: a normalization run that stamps wall-clock
times produces different bytes every time, which would make the golden fixture
worthless and a snapshot id unstable. Passing the times in is what lets an
operator reproduce a colleague's snapshot exactly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from trading.market_data.normalize import NormalizationContext
from trading.market_data.pipeline import run
from trading.market_data.snapshot.builder import load_manifest, verify_snapshot
from trading.market_data.snapshot.reader import SnapshotReader
from trading.schemas.io import KnowledgeTimePolicy
from trading.schemas.time import parse_rfc3339_ns

app = typer.Typer(
    name="trading",
    help="Research platform operations. No command here can reach a broker.",
    no_args_is_help=True,
)
snapshot_app = typer.Typer(help="Build, verify and inspect content-addressed snapshots.")
app.add_typer(snapshot_app, name="snapshot")


@snapshot_app.command("build")
def snapshot_build(
    raw: Annotated[Path, typer.Option(help="Raw partition root, containing trades/ and quotes/.")],
    reference: Annotated[Path, typer.Option(help="Reference bundle for the session.")],
    out: Annotated[Path, typer.Option(help="Snapshot root to write.")],
    receive_time: Annotated[str, typer.Option(help="When the bytes were received (RFC-3339).")],
    process_time: Annotated[str, typer.Option(help="When normalization ran (RFC-3339).")],
    as_of: Annotated[str, typer.Option(help="Instant up to which data is known (RFC-3339).")],
    publication_lag_ns: Annotated[
        int, typer.Option(help="Venue-to-knowledge lag. Declared until M7 measures it.")
    ] = 250_000,
    partition_id: Annotated[str, typer.Option(help="Provenance stamped on every row.")] = "",
    event_time_source: Annotated[
        str, typer.Option(help="participant | sip | vendor_unknown.")
    ] = "vendor_unknown",
    venue_coverage: Annotated[str, typer.Option(help="sip | iex_only.")] = "iex_only",
    calendar_version: Annotated[str, typer.Option(help="Exchange calendar version.")] = "",
) -> None:
    """Normalize a raw partition and seal a snapshot.

    Defaults are the conservative ones: an unmeasured publication lag, an unknown
    timestamp source, and IEX coverage. Each blocks promotion rather than
    silently flattering a result, so overriding one is a deliberate claim.
    """
    context = NormalizationContext(
        receive_time=parse_rfc3339_ns(receive_time),
        process_time=parse_rfc3339_ns(process_time),
        publication_lag_ns=publication_lag_ns,
        raw_partition_id=partition_id or raw.as_posix(),
        event_time_source=event_time_source,
        venue_coverage=venue_coverage,
        knowledge_policy=KnowledgeTimePolicy.BACKFILL,
    )
    result = run(
        raw,
        reference,
        out,
        context,
        as_of=parse_rfc3339_ns(as_of),
        calendar_version=calendar_version,
    )

    typer.echo(f"snapshot_id {result.snapshot_id}")
    for receipt in sorted(result.receipts, key=lambda r: r.contract):
        typer.echo(
            f"  {receipt.contract:24} {receipt.row_count:>8} rows  "
            f"content {receipt.content_sha256[:12]}"
        )
    if venue_coverage == "iex_only":
        typer.secho(
            "  note: iex_only coverage -- these quotes are not the NBBO, so the "
            "quote-replay fill model will refuse them (D11).",
            fg=typer.colors.YELLOW,
        )


@snapshot_app.command("verify")
def snapshot_verify(
    root: Annotated[Path, typer.Option(help="Snapshot root to check.")],
) -> None:
    """Check that a snapshot's bytes still match its manifest."""
    manifest = load_manifest(root)
    findings = verify_snapshot(manifest, root)
    if findings:
        for finding in findings:
            typer.secho(f"  {finding}", fg=typer.colors.RED, err=True)
        typer.secho(f"{len(findings)} problem(s) in {root}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    typer.echo(
        f"snapshot {manifest.snapshot_id()[:12]} intact: "
        f"{len(manifest.files)} file(s) match the manifest"
    )


@snapshot_app.command("show")
def snapshot_show(
    root: Annotated[Path, typer.Option(help="Snapshot root to inspect.")],
) -> None:
    """Print a snapshot's identity and contents."""
    reader = SnapshotReader(root)
    typer.echo(f"snapshot_id {reader.snapshot_id}")
    typer.echo(f"calendar    {reader.manifest.calendar_version or '(unset)'}")
    for entry in reader.manifest.files:
        typer.echo(
            f"  {entry.path}\n"
            f"      {entry.contract} v{entry.contract_version}  "
            f"{entry.row_count} rows  content {entry.content_sha256[:12]}"
        )


def cli() -> None:
    app()


if __name__ == "__main__":
    cli()
