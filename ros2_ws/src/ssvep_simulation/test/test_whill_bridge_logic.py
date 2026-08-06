import json
import math
from types import SimpleNamespace
import unittest

from ssvep_simulation.ssvep_whill_bridge import (
    WhillBridgeLogic,
    serialize_payload,
    stamp_to_nanoseconds,
)


class TestWhillBridgeLogic(unittest.TestCase):
    def setUp(self):
        self.logic = WhillBridgeLogic()
        self.logic.update_quality("good", stamp_ns=1)

    def _command(
        self,
        direction="forward",
        valid=True,
        confidence=0.91,
        stamp_ns=100,
        monotonic_now=1.0,
    ):
        return self.logic.process_command(
            direction=direction,
            valid=valid,
            confidence=confidence,
            stamp_ns=stamp_ns,
            monotonic_now=monotonic_now,
        )

    def test_two_results_accept_then_same_direction_refreshes(self):
        self.assertIsNone(self._command(stamp_ns=101, monotonic_now=1.0))
        accepted = self._command(stamp_ns=102, monotonic_now=1.1)
        refreshed = self._command(stamp_ns=103, monotonic_now=1.2)

        self.assertEqual(accepted["sequence"], 1)
        self.assertEqual(accepted["stamp_ns"], 102)
        self.assertEqual(accepted["command"], "direction")
        self.assertEqual(accepted["direction"], "forward")
        self.assertEqual(accepted["confidence"], 0.91)
        self.assertIs(accepted["valid"], True)
        self.assertEqual(accepted["quality"], "good")
        self.assertEqual(refreshed["sequence"], 2)
        self.assertEqual(refreshed["direction"], "forward")

    def test_each_direction_can_be_accepted(self):
        for direction in ("forward", "backward", "left", "right"):
            with self.subTest(direction=direction):
                logic = WhillBridgeLogic()
                logic.update_quality("fair", stamp_ns=1)
                first = logic.process_command(
                    direction, True, 0.80, 10, 1.0
                )
                second = logic.process_command(
                    direction, True, 0.80, 20, 1.1
                )
                self.assertIsNone(first)
                self.assertEqual(second["direction"], direction)
                self.assertEqual(second["quality"], "fair")

    def test_direction_change_requires_two_new_matching_results(self):
        self._command(monotonic_now=1.0)
        forward = self._command(monotonic_now=1.1)
        first_left = self._command(
            "left", stamp_ns=201, monotonic_now=1.2
        )
        second_left = self._command(
            "left", stamp_ns=202, monotonic_now=1.3
        )

        self.assertEqual(forward["sequence"], 1)
        self.assertIsNone(first_left)
        self.assertEqual(second_left["sequence"], 2)
        self.assertEqual(second_left["direction"], "left")

    def test_documented_stop_reasons_and_strict_sequence(self):
        payloads = [
            self._command("idle", valid=False, stamp_ns=1),
            self._command("stop", valid=False, stamp_ns=2),
            self._command("forward", valid=False, stamp_ns=3),
            self._command("forward", confidence=0.50, stamp_ns=4),
            self._command("unsupported", valid=True, stamp_ns=5),
        ]
        self.logic.update_quality("poor", stamp_ns=6)
        payloads.append(
            self._command("forward", confidence=0.91, stamp_ns=7)
        )

        self.assertEqual(
            [payload["sequence"] for payload in payloads],
            [1, 2, 3, 4, 5, 6],
        )
        self.assertEqual(
            [payload["reason"] for payload in payloads],
            [
                "ssvep_idle",
                "explicit_stop",
                "ssvep_invalid",
                "low_confidence",
                "ssvep_invalid",
                "poor_signal_quality",
            ],
        )

    def test_poor_quality_stops_an_active_direction_immediately(self):
        self._command(monotonic_now=1.0)
        accepted = self._command(monotonic_now=1.1)
        stopped = self.logic.update_quality("poor", stamp_ns=999)

        self.assertEqual(accepted["command"], "direction")
        self.assertEqual(stopped["sequence"], 2)
        self.assertEqual(stopped["stamp_ns"], 999)
        self.assertEqual(stopped["reason"], "poor_signal_quality")
        self.assertIsNone(self.logic.current_direction)

    def test_timeout_uses_bridge_stamp_and_only_publishes_once(self):
        self._command(monotonic_now=10.0)
        accepted = self._command(monotonic_now=10.1)

        self.assertIsNone(
            self.logic.check_timeout(monotonic_now=11.0, stamp_ns=1000)
        )
        stopped = self.logic.check_timeout(
            monotonic_now=11.11, stamp_ns=1234
        )
        repeated = self.logic.check_timeout(
            monotonic_now=20.0, stamp_ns=5678
        )

        self.assertEqual(accepted["sequence"], 1)
        self.assertEqual(stopped["sequence"], 2)
        self.assertEqual(stopped["stamp_ns"], 1234)
        self.assertEqual(stopped["reason"], "command_timeout")
        self.assertIsNone(repeated)

    def test_final_stop_increments_sequence(self):
        invalid = self._command("forward", valid=False, stamp_ns=10)
        final = self.logic.final_stop(stamp_ns=20)
        self.assertEqual(invalid["sequence"], 1)
        self.assertEqual(final["sequence"], 2)
        self.assertEqual(final["reason"], "bridge_shutdown")

    def test_stamp_conversion_and_strict_json(self):
        stamp = SimpleNamespace(sec=1_786_000_000, nanosec=123_456_789)
        stamp_ns = stamp_to_nanoseconds(stamp)
        self.assertEqual(stamp_ns, 1_786_000_000_123_456_789)

        self._command(monotonic_now=1.0)
        payload = self._command(
            confidence=2.0, stamp_ns=stamp_ns, monotonic_now=1.1
        )
        encoded = serialize_payload(payload)
        decoded = json.loads(encoded)
        self.assertEqual(decoded, payload)
        self.assertEqual(decoded["confidence"], 1.0)
        self.assertTrue(0.0 <= decoded["confidence"] <= 1.0)
        with self.assertRaises(ValueError):
            serialize_payload({"bad": math.nan})

    def test_non_finite_confidence_stops(self):
        payload = self._command(confidence=math.nan)
        self.assertEqual(payload["reason"], "low_confidence")

    def test_invalid_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            WhillBridgeLogic(min_confidence=1.1)
        with self.assertRaises(ValueError):
            WhillBridgeLogic(required_consecutive_results=0)
        with self.assertRaises(ValueError):
            WhillBridgeLogic(command_timeout_sec=0.0)
        with self.assertRaises(ValueError):
            WhillBridgeLogic(allowed_quality=[])


if __name__ == "__main__":
    unittest.main()
