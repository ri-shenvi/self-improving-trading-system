# Vendor timestamp mapping — Alpaca (D1)

**Status: draft, unverified against live payloads.** Every row marked *verify*
must be confirmed against captured messages before `packages/schemas` freezes at
M1. This document is a decision record, not a transcription of vendor docs.

## Why this exists before any schema

Section 6 requires six timestamps on every record. Five are recoverable after the
fact. One is not: `knowledge_time`, the earliest moment the system could have
known a value, is the field point-in-time correctness rests on, and it cannot be
reconstructed from stored data if it was wrong at ingestion.

The specific failure this document exists to prevent: if a vendor field believed
to be a venue timestamp is actually an *ingest* timestamp, every `knowledge_time`
in the system is wrong, the true value is unrecoverable, and every backtest built
before the discovery is worthless. That is D1's "cost of error", and it is why
the mapping is written down and reviewed before the first schema, rather than
inferred field by field while writing a connector.

## Feed scope

Alpaca offers two stock feeds. The plan starts on **IEX** and upgrades to **SIP**
later (D11).

IEX carries only IEX-executed prints and IEX's own quote — roughly 2–3% of
consolidated volume. An IEX quote is **not the NBBO**. Every normalized quote row
therefore carries `venue_coverage ∈ {iex_only, sip}`, and the quote-replay fill
model refuses to run on `iex_only` data. Nothing downstream may infer coverage
from context.

## Mapping

`event_time` comes from the vendor. `receive_time` and `process_time` are stamped
by our gateway — they are facts about our pipeline and appear in no payload.
`knowledge_time` is **derived**, never copied, per the rules below.

| Dataset | Vendor field | → | Notes |
|---|---|---|---|
| Trade | `t` | `event_time` | RFC-3339, nanosecond precision. *Verify:* participant/SIP timestamp, not Alpaca ingest. |
| Trade | `i`, `x`, `p`, `s`, `c`, `z` | trade id, exchange, price, size, conditions, tape | Condition codes decide which prints are eligible for bars and VWAP (D12). |
| Trade correction | correction message | `revision_time` | Original and corrected values both retained; the original is never overwritten (§8). |
| Trade cancel/error | cancel message | `revision_time` | Must remove the print from derived bars without mutating prior snapshots. |
| Quote | `t` | `event_time` | *Verify:* venue timestamp. |
| Quote | `bp`,`bs`,`bx`,`ap`,`as`,`ax`,`c`,`z` | bid/ask price, size, venue, conditions, tape | Locked and crossed states flagged, not discarded (§10). |
| Bar | `t` | bar window start | We build bars from trades (D12); vendor bars are kept only as a reconciliation sample. |
| Updated bar | late-revision bar | `revision_time` | Arrives after the window closed; must not silently alter an existing snapshot. |
| Trading status | `t`, status and reason codes | `event_time` | Halts and resumptions gate order eligibility in replay (§26). |
| LULD | `t`, limit up, limit down | `event_time` | Bands make orders non-executable; simulated fills outside them are invalid. |
| Corporate action | announcement date | `knowledge_time` | The date the action became *knowable*. |
| Corporate action | ex/effective date | `effective_time` | The date it becomes economically effective. Conflating the two is survivorship bias with extra steps. |
| Shortability / ETB | snapshot capture time | `knowledge_time` | No historical series exists, so we accrue one from M7 (D14). |

## Deriving `knowledge_time`

This is the part that cannot be copied from a field, and the part most likely to
be got wrong quietly.

**Live capture.** `knowledge_time = receive_time`, stamped when the gateway
accepts the message. This is true by construction and needs no calibration.

**Historical backfill.** `receive_time` is when *we* backfilled, which may be
years after the event. Using it would let a feature read a value at a decision
time when the real system could not have had it — leakage that looks like edge.
Using `event_time` instead is the opposite error: it assumes zero-latency
delivery and credits the strategy with information it could not have acted on.

So for backfilled data:

```
knowledge_time = event_time + publication_lag(dataset, feed)
```

where `publication_lag` is **measured from live capture**, versioned, and
recorded in the snapshot manifest. Until a live measurement exists, the lag is a
declared conservative constant and every snapshot built with it is marked as
carrying an unmeasured lag. A strategy whose result depends on the value of that
constant has not been validated; that is a finding, not a nuisance.

Corollary: **no vendor backfill timestamp may ever be used as a decision-time
input** (§7, news and filings row). The rule is enforced at the schema boundary,
not by reviewer attention.

## Open questions to close before M1

1. Is Alpaca's trade/quote `t` the participant timestamp or the SIP timestamp?
   They differ by the SIP's own processing latency, which matters at the
   sub-second horizons the platform targets.
2. Do corrections and cancel/error messages carry the original event's timestamp,
   the correction's, or both? `revision_time` needs the correction's; resolving
   the correction against the original needs the original's.
3. Does the historical REST API return identical values to the live stream for
   the same interval, including conditions and corrections? Any disagreement is a
   vendor reconciliation finding (§10) and must be characterized before a
   snapshot is released.
4. On IEX, are trade conditions populated identically to SIP? Bar construction
   (D12) filters on them, so a difference changes every derived bar.
5. What is the observed distribution of `receive_time − event_time` per dataset?
   This is the empirical `publication_lag`, and it is also the latency
   distribution §17 requires for p50/p95/stressed backtest reruns.

Each question is answered by captured evidence committed alongside the connector
at M7, not by reading documentation.
