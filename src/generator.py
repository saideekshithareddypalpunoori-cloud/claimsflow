"""Synthetic claims event log with seeded rework loops of KNOWN cost.

Built first, deliberately. Process mining produces a persuasive picture from
any event log, and a spaghetti diagram is persuasive whether or not it is
right. Seeding the loops here - with a frequency and a cost chosen in advance -
is what lets the analysis be scored rather than admired.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

# The DESIGNED process. Conformance is measured against this, not against
# whatever the discovery algorithm happens to produce.
DESIGNED_PROCESS: tuple[str, ...] = (
    "register",
    "triage",
    "assign_handler",
    "request_photos",
    "receive_photos",
    "request_estimate",
    "receive_estimate",
    "assess",
    "approve",
    "pay",
    "close",
)

#: Staff cost per activity occurrence, in GBP. Explicit so the cost figures can
#: be challenged rather than taken on faith.
ACTIVITY_COST: dict[str, float] = {
    "register": 8.0,
    "triage": 12.0,
    "assign_handler": 6.0,
    "request_photos": 9.0,
    "receive_photos": 4.0,
    "request_estimate": 11.0,
    "receive_estimate": 5.0,
    "assess": 45.0,
    "approve": 18.0,
    "pay": 7.0,
    "close": 4.0,
}

#: Working days each activity adds to cycle time.
ACTIVITY_DAYS: dict[str, float] = {
    "register": 0.1, "triage": 0.3, "assign_handler": 0.5,
    "request_photos": 0.2, "receive_photos": 2.5,
    "request_estimate": 0.2, "receive_estimate": 3.0,
    "assess": 1.2, "approve": 0.8, "pay": 0.5, "close": 0.1,
}


@dataclass(frozen=True)
class SeededLoop:
    """A rework loop planted at a known rate, with a known cause."""

    loop_id: str
    #: The activities repeated when the loop fires.
    activities: tuple[str, ...]
    #: Fraction of claims affected.
    rate: float
    #: The condition that triggers it, for root-cause validation.
    cause: str

    @property
    def cost_per_occurrence(self) -> float:
        return sum(ACTIVITY_COST[a] for a in self.activities)

    @property
    def days_per_occurrence(self) -> float:
        return sum(ACTIVITY_DAYS[a] for a in self.activities)


SEEDED_LOOPS: tuple[SeededLoop, ...] = (
    SeededLoop(
        "L3",
        ("request_estimate", "receive_estimate", "assess"),
        0.22,
        "estimate requested before photos arrived, so the assessor could not "
        "validate it and had to re-request",
    ),
    SeededLoop(
        "L1",
        ("request_photos", "receive_photos"),
        0.11,
        "first photo set was unusable (lighting/angle)",
    ),
    SeededLoop(
        "L2",
        ("assess", "approve"),
        0.06,
        "approval limit exceeded, referred to a senior handler",
    ),
)


@dataclass(frozen=True)
class Event:
    case_id: str
    activity: str
    timestamp: float  # working days since case start
    resource: str


def generate(
    cases: int = 50_000, seed: int = 20260911,
) -> tuple[list[Event], dict[str, float]]:
    """Return (events, ground_truth)."""
    rnd = random.Random(seed)
    events: list[Event] = []
    handlers = [f"handler_{i:02d}" for i in range(12)]
    claim_types = ["motor_minor", "motor_major", "theft", "windscreen"]
    # Occurrences and cases-affected are DIFFERENT numbers once a loop can
    # fire more than once in a case, and conflating them is a classic
    # process-mining reporting error: "22% of claims" and "0.28 loops per
    # claim" are both true and mean different things.
    loop_counts: dict[str, int] = {loop.loop_id: 0 for loop in SEEDED_LOOPS}
    loop_cases: dict[str, int] = {loop.loop_id: 0 for loop in SEEDED_LOOPS}

    for i in range(cases):
        case_id = f"CLM-{i:06d}"
        handler = rnd.choice(handlers)
        claim_type = rnd.choice(claim_types)
        t = 0.0
        trace: list[str] = []
        fired_in_case: set[str] = set()

        for activity in DESIGNED_PROCESS:
            trace.append(activity)
            # After appending, decide whether a loop rooted here fires.
            for loop in SEEDED_LOOPS:
                if activity != loop.activities[-1]:
                    continue
                # Rework repeats. A generator that fires each loop at most once
                # produces a handful of variants and understates the cost; real
                # claims go round twice, and occasionally three times.
                fires = 0
                while fires < 3 and rnd.random() < loop.rate:
                    fires += 1
                    loop_counts[loop.loop_id] += 1
                    trace.extend(loop.activities)
                if fires:
                    fired_in_case.add(loop.loop_id)

        for loop_id in fired_in_case:
            loop_cases[loop_id] += 1

        for activity in trace:
            # Small noise so timestamps are not perfectly uniform.
            t += ACTIVITY_DAYS[activity] * rnd.uniform(0.7, 1.4)
            events.append(Event(case_id, activity, round(t, 4), handler))

        # Type is not stored on the event; it drives resource choice only,
        # keeping the log shaped like a real extract.
        _ = claim_type

    ground_truth: dict[str, float] = {}
    for loop in SEEDED_LOOPS:
        #: share of CASES touched by this loop at least once
        ground_truth[f"{loop.loop_id}_rate"] = loop_cases[loop.loop_id] / cases
        #: total firings, which is what drives cost
        ground_truth[f"{loop.loop_id}_occurrences"] = loop_counts[loop.loop_id]
        ground_truth[f"{loop.loop_id}_cost"] = (
            loop_counts[loop.loop_id] * loop.cost_per_occurrence
        )
        ground_truth[f"{loop.loop_id}_days"] = loop.days_per_occurrence
    ground_truth["cases"] = cases
    return events, ground_truth
