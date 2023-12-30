"""The 60-second artefact: three costed findings, not a spaghetti diagram.

Run: python -m src.demo
"""

from __future__ import annotations

from .conformance import (
    check_quality, conformance, detect_loops, time_split, traces, variants,
)
from .generator import DESIGNED_PROCESS, generate

CASES = 50_000
#: The log covers one quarter, so annualise the cost.
ANNUALISE = 4.0


def main() -> None:
    events, truth = generate(cases=CASES, seed=20260911)

    print("\n  CLAIMSFLOW - what the average cycle time hides")
    print("  " + "=" * 70)
    print(f"  {CASES:,} claims, {len(events):,} events, one quarter of history.")

    issues = check_quality(events)
    print(f"  Data quality gate: {'PASS' if not issues else 'FAIL'} "
          f"({len(issues)} issues)\n")

    v = variants(events)
    conformant = v[tuple(DESIGNED_PROCESS)]
    print(f"  The designed process has {len(DESIGNED_PROCESS)} steps.")
    print(f"  The real process has {len(v)} distinct variants.")
    print(f"  Only {conformant:,} of {CASES:,} claims ({conformant / CASES:.0%}) "
          "follow the designed path.\n")

    alignments = conformance(events)
    mean_fitness = sum(a.fitness for a in alignments) / len(alignments)
    print(f"  Mean alignment fitness: {mean_fitness:.3f}")
    print("  (a number, not a picture - and it moves when the process improves)\n")

    print("  COSTED REWORK LOOPS")
    print("  " + "-" * 70)
    findings = detect_loops(events, annualise=ANNUALISE)
    total = 0.0
    for f in findings:
        total += f.annual_cost
        print(f"    {f.loop_id}  {f.rate:>5.0%} of claims   "
              f"+{f.added_days:.1f} days   GBP {f.cost_per_occurrence:>5.0f} each   "
              f"GBP {f.annual_cost:>10,.0f}/yr")
        print(f"        {' -> '.join(f.activities)}")
        print(f"        cause: {f.cause}")
    print(f"\n    total annual rework cost: GBP {total:,.0f}")

    largest = findings[0]
    print(f"\n    The largest, {largest.loop_id}, is a SEQUENCING problem:")
    print(f"    {largest.cause}.")
    print("    Requesting the estimate after the photos arrive removes it")
    print("    entirely, at no cost. That is a configuration change, not a")
    print("    headcount request.\n")

    split = time_split(events)
    waiting_share = split["waiting_days"] / (
        split["waiting_days"] + split["working_days"])
    print("  WAITING vs WORKING")
    print("  " + "-" * 70)
    print(f"    working time: {split['working_days']:>12,.0f} days")
    print(f"    waiting time: {split['waiting_days']:>12,.0f} days "
          f"({waiting_share:.0%} of elapsed)")
    print("    Most of the cycle is spent waiting for third parties, so hiring")
    print("    more assessors would not move the headline number. Separating")
    print("    the two is what stops the improvement effort going to the wrong")
    print("    place.\n")

    print("  Recovery against planted ground truth:")
    for f in findings:
        expected = truth[f"{f.loop_id}_rate"]
        print(f"    {f.loop_id}: measured {f.rate:.3f}  planted {expected:.3f}  "
              f"delta {abs(f.rate - expected):.4f}")
    print()


if __name__ == "__main__":
    main()
