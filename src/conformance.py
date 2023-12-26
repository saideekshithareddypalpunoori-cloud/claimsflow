"""Conformance checking, rework counting, and costing.

Checks every case against the DESIGNED process (alignment and a per-case
fitness score), counts occurrences of known candidate rework loops, and
attaches days and staff cost to each one so the findings can be ranked. The
candidate loops are supplied (SEEDED_LOOPS in the generator); this module
counts and costs them but does not discover loops from the log.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from .generator import (
    ACTIVITY_COST, ACTIVITY_DAYS, DESIGNED_PROCESS, SEEDED_LOOPS, Event,
)


# ---------------------------------------------------------------------------
# Data quality. Runs BEFORE any analysis, and fails loudly.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QualityIssue:
    check: str
    detail: str
    affected_cases: int


def check_quality(events: list[Event]) -> list[QualityIssue]:
    """A process map built on a dirty event log is confidently wrong.

    These four checks catch the failures that silently distort a discovered
    model: non-monotonic timestamps invent loops that never happened, orphan
    cases truncate real ones, and duplicate case-activity-timestamp triples
    inflate frequencies.
    """
    issues: list[QualityIssue] = []
    by_case: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_case[e.case_id].append(e)

    non_monotonic = 0
    for case, evs in by_case.items():
        for a, b in zip(evs, evs[1:]):
            if b.timestamp < a.timestamp:
                non_monotonic += 1
                break
    if non_monotonic:
        issues.append(QualityIssue(
            "monotonic_timestamps",
            "events out of order within a case; this manufactures loops that "
            "did not occur",
            non_monotonic,
        ))

    unknown = {e.activity for e in events} - set(ACTIVITY_COST)
    if unknown:
        issues.append(QualityIssue(
            "known_activities", f"unrecognised activities: {sorted(unknown)}",
            len(unknown),
        ))

    incomplete = sum(
        1 for evs in by_case.values() if evs[0].activity != DESIGNED_PROCESS[0]
    )
    if incomplete:
        issues.append(QualityIssue(
            "complete_cases",
            "cases that do not begin at the process start - probably an "
            "extract window that cuts through live cases",
            incomplete,
        ))

    seen: set[tuple[str, str, float]] = set()
    duplicates = 0
    for e in events:
        key = (e.case_id, e.activity, e.timestamp)
        if key in seen:
            duplicates += 1
        seen.add(key)
    if duplicates:
        issues.append(QualityIssue(
            "no_duplicates", "duplicate case/activity/timestamp triples inflate "
            "activity frequencies", duplicates,
        ))
    return issues


# ---------------------------------------------------------------------------
# Traces and variants
# ---------------------------------------------------------------------------

def traces(events: list[Event]) -> dict[str, list[str]]:
    by_case: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_case[e.case_id].append(e)
    return {
        case: [e.activity for e in sorted(evs, key=lambda x: x.timestamp)]
        for case, evs in by_case.items()
    }


def variants(events: list[Event]) -> Counter[tuple[str, ...]]:
    return Counter(tuple(t) for t in traces(events).values())


# ---------------------------------------------------------------------------
# Alignment-based conformance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Alignment:
    case_id: str
    #: Activities in the trace that are not expected at that point.
    inserted: tuple[str, ...]
    #: Designed activities that never occurred.
    missing: tuple[str, ...]
    fitness: float


def align(trace: list[str], designed: tuple[str, ...] = DESIGNED_PROCESS) -> (
    tuple[list[str], list[str]]
):
    """Greedy alignment of a trace against the designed sequence.

    Returns (inserted, missing). Real conformance checking solves this
    optimally with A*; the greedy version is exact for the repeat-insertion
    deviations this process actually exhibits, and the README says so rather
    than implying a stronger guarantee.
    """
    inserted: list[str] = []
    i = 0
    for activity in trace:
        if i < len(designed) and activity == designed[i]:
            i += 1
        else:
            inserted.append(activity)
    missing = list(designed[i:])
    return inserted, missing


def conformance(events: list[Event]) -> list[Alignment]:
    out: list[Alignment] = []
    for case, trace in traces(events).items():
        inserted, missing = align(trace)
        total = len(trace) + len(missing)
        fitness = 1.0 - (len(inserted) + len(missing)) / total if total else 1.0
        out.append(Alignment(case, tuple(inserted), tuple(missing), fitness))
    return out


# ---------------------------------------------------------------------------
# Rework loops, costed
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoopFinding:
    loop_id: str
    activities: tuple[str, ...]
    occurrences: int
    cases_affected: int
    rate: float
    added_days: float
    cost_per_occurrence: float
    annual_cost: float
    cause: str

    def summary(self) -> str:
        return (
            f"{self.loop_id}: {self.rate:.0%} of claims, +{self.added_days:.1f} "
            f"days and GBP {self.cost_per_occurrence:.0f} each, "
            f"GBP {self.annual_cost:,.0f}/yr - {self.cause}"
        )


def detect_loops(events: list[Event], annualise: float = 1.0) -> list[LoopFinding]:
    """Count repeats of the known candidate loops (SEEDED_LOOPS) and cost them.

    The loop patterns are supplied, not mined from the traces.
    """
    all_traces = traces(events)
    total_cases = len(all_traces)
    findings: list[LoopFinding] = []

    for loop in SEEDED_LOOPS:
        occurrences = 0
        cases = 0
        n = len(loop.activities)
        for trace in all_traces.values():
            hits = 0
            for i in range(len(trace) - n + 1):
                if tuple(trace[i:i + n]) != loop.activities:
                    continue
                # A repeat only counts as rework if the same sub-sequence
                # already appeared earlier in the trace.
                if tuple(loop.activities) in [
                    tuple(trace[j:j + n]) for j in range(i)
                ]:
                    hits += 1
            if hits:
                cases += 1
                occurrences += hits

        cost_each = sum(ACTIVITY_COST[a] for a in loop.activities)
        days_each = sum(ACTIVITY_DAYS[a] for a in loop.activities)
        findings.append(LoopFinding(
            loop_id=loop.loop_id,
            activities=loop.activities,
            occurrences=occurrences,
            cases_affected=cases,
            rate=cases / total_cases if total_cases else 0.0,
            added_days=days_each,
            cost_per_occurrence=cost_each,
            annual_cost=occurrences * cost_each * annualise,
            cause=loop.cause,
        ))
    return sorted(findings, key=lambda f: -f.annual_cost)


# ---------------------------------------------------------------------------
# Waiting vs working time
# ---------------------------------------------------------------------------

#: Activities where the clock runs while the organisation waits for someone
#: else. Fixing a wait is a different intervention from fixing a bottleneck,
#: and conflating them sends the improvement effort to the wrong place.
WAITING_ACTIVITIES = {"receive_photos", "receive_estimate"}


def time_split(events: list[Event]) -> dict[str, float]:
    working = sum(
        ACTIVITY_DAYS[a] for t in traces(events).values() for a in t
        if a not in WAITING_ACTIVITIES
    )
    waiting = sum(
        ACTIVITY_DAYS[a] for t in traces(events).values() for a in t
        if a in WAITING_ACTIVITIES
    )
    return {"working_days": working, "waiting_days": waiting}
