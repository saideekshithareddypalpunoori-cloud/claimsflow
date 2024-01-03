"""Recover each seeded loop's frequency within 1% and its cost within 5%."""

from __future__ import annotations

import unittest

from src.conformance import (
    align, check_quality, conformance, detect_loops, time_split, traces,
    variants,
)
from src.generator import (
    ACTIVITY_COST, DESIGNED_PROCESS, SEEDED_LOOPS, Event, generate,
)

CASES = 20_000


class BaseLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.truth = generate(cases=CASES, seed=7)
        cls.findings = {f.loop_id: f for f in detect_loops(cls.events)}


class TestRecovery(BaseLog):
    def test_loop_rates_recover_within_one_percent(self):
        for loop in SEEDED_LOOPS:
            with self.subTest(loop=loop.loop_id):
                expected = self.truth[f"{loop.loop_id}_rate"]
                actual = self.findings[loop.loop_id].rate
                self.assertAlmostEqual(
                    actual, expected, delta=0.01,
                    msg=f"{loop.loop_id}: expected {expected:.3f}, "
                        f"measured {actual:.3f}",
                )

    def test_loop_costs_recover_within_five_percent(self):
        for loop in SEEDED_LOOPS:
            with self.subTest(loop=loop.loop_id):
                expected = self.truth[f"{loop.loop_id}_cost"]
                actual = self.findings[loop.loop_id].annual_cost
                self.assertLessEqual(
                    abs(actual - expected) / max(expected, 1.0), 0.05,
                    f"{loop.loop_id}: expected {expected:,.0f}, "
                    f"measured {actual:,.0f}",
                )

    def test_added_days_per_occurrence_match_the_design(self):
        for loop in SEEDED_LOOPS:
            self.assertAlmostEqual(
                self.findings[loop.loop_id].added_days,
                self.truth[f"{loop.loop_id}_days"], places=6,
            )

    def test_the_largest_loop_is_ranked_first(self):
        ranked = detect_loops(self.events)
        self.assertEqual(ranked[0].loop_id, "L3",
                         "the costliest loop must lead the report")

    def test_each_finding_carries_its_root_cause(self):
        for f in self.findings.values():
            self.assertGreater(len(f.cause), 20)
            self.assertIn("GBP", f.summary())


class TestConformance(BaseLog):
    def test_a_perfectly_conformant_trace_has_fitness_one(self):
        inserted, missing = align(list(DESIGNED_PROCESS))
        self.assertEqual(inserted, [])
        self.assertEqual(missing, [])

    def test_a_repeated_block_is_reported_as_inserted(self):
        trace = list(DESIGNED_PROCESS[:3]) + ["triage"] + list(DESIGNED_PROCESS[3:])
        inserted, missing = align(trace)
        self.assertEqual(inserted, ["triage"])
        self.assertEqual(missing, [])

    def test_a_skipped_step_is_reported_as_missing(self):
        trace = [a for a in DESIGNED_PROCESS if a != "close"]
        inserted, missing = align(trace)
        self.assertEqual(missing, ["close"])

    def test_most_cases_deviate_which_is_the_finding(self):
        alignments = conformance(self.events)
        deviating = sum(1 for a in alignments if a.inserted or a.missing)
        self.assertGreater(deviating / len(alignments), 0.25,
                           "the seeded loops should show up as deviations")

    def test_fitness_is_between_zero_and_one(self):
        for a in conformance(self.events)[:2_000]:
            self.assertGreaterEqual(a.fitness, 0.0)
            self.assertLessEqual(a.fitness, 1.0)

    def test_the_real_process_has_far_more_variants_than_the_designed_one(self):
        v = variants(self.events)
        self.assertGreater(len(v), 10,
                           "an 11-step process does not run 11 steps in practice")
        self.assertEqual(
            v[tuple(DESIGNED_PROCESS)],
            sum(1 for t in traces(self.events).values()
                if tuple(t) == tuple(DESIGNED_PROCESS)),
        )


class TestDataQuality(BaseLog):
    def test_a_clean_log_passes_every_check(self):
        self.assertEqual(check_quality(self.events), [])

    def test_non_monotonic_timestamps_are_caught(self):
        bad = list(self.events[:200])
        bad[5] = Event(bad[5].case_id, bad[5].activity, -1.0, bad[5].resource)
        issues = [i.check for i in check_quality(bad)]
        self.assertIn("monotonic_timestamps", issues)

    def test_an_unknown_activity_is_caught(self):
        bad = list(self.events[:200])
        bad.append(Event("CLM-000000", "mystery_step", 99.0, "handler_00"))
        self.assertIn("known_activities", [i.check for i in check_quality(bad)])

    def test_a_truncated_case_is_caught(self):
        bad = [e for e in self.events[:400] if e.activity != "register"]
        self.assertIn("complete_cases", [i.check for i in check_quality(bad)])

    def test_duplicate_events_are_caught(self):
        bad = list(self.events[:200])
        bad.append(bad[0])
        self.assertIn("no_duplicates", [i.check for i in check_quality(bad)])


class TestTimeSplit(BaseLog):
    def test_waiting_time_is_separated_from_working_time(self):
        split = time_split(self.events)
        self.assertGreater(split["waiting_days"], 0)
        self.assertGreater(split["working_days"], 0)

    def test_waiting_dominates_which_changes_the_intervention(self):
        # If most of the cycle time is spent waiting for a third party, hiring
        # more assessors does nothing. That is the point of the split.
        split = time_split(self.events)
        self.assertGreater(split["waiting_days"], split["working_days"] * 0.5)


class TestCostModel(BaseLog):
    def test_every_activity_has_an_explicit_cost(self):
        for activity in DESIGNED_PROCESS:
            self.assertIn(activity, ACTIVITY_COST)

    def test_cost_per_occurrence_is_the_sum_of_its_activities(self):
        for loop in SEEDED_LOOPS:
            self.assertAlmostEqual(
                self.findings[loop.loop_id].cost_per_occurrence,
                sum(ACTIVITY_COST[a] for a in loop.activities),
            )


if __name__ == "__main__":
    unittest.main()
