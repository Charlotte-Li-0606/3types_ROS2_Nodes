"""Safely translate decoded SSVEP state into WHILL controller JSON.

This bridge publishes an abstract String command only.  It does not connect to
WHILL hardware, a motor controller, or any physical actuator.
"""

import json
import math
import signal
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String

from ssvep_interfaces.msg import SignalQuality, SSVEPCommand

from .logging_utils import create_file_logger


ALLOWED_DIRECTIONS = {"forward", "backward", "left", "right"}
NANOSECONDS_PER_SECOND = 1_000_000_000


def stamp_to_nanoseconds(stamp) -> int:
    """Convert a builtin_interfaces/Time-compatible object to nanoseconds."""
    return (
        int(stamp.sec) * NANOSECONDS_PER_SECOND
        + int(stamp.nanosec)
    )


def serialize_payload(payload: dict) -> str:
    """Return strict, compact JSON (NaN and infinity are rejected)."""
    return json.dumps(payload, separators=(",", ":"), allow_nan=False)


def _request_keyboard_interrupt(_signum, _frame):
    """Turn SIGTERM into the same orderly path used for Ctrl-C."""
    raise KeyboardInterrupt


class WhillBridgeLogic:
    """ROS-independent command filter and sequence-number state machine."""

    def __init__(
        self,
        min_confidence=0.75,
        required_consecutive_results=2,
        command_timeout_sec=1.0,
        allowed_quality=("fair", "good"),
    ):
        self.min_confidence = float(min_confidence)
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0")

        self.required_consecutive_results = int(required_consecutive_results)
        if self.required_consecutive_results < 1:
            raise ValueError("required_consecutive_results must be at least 1")

        self.command_timeout_sec = float(command_timeout_sec)
        if self.command_timeout_sec <= 0.0:
            raise ValueError("command_timeout_sec must be greater than 0")

        self.allowed_quality = {
            str(value).strip().lower() for value in allowed_quality
        }
        if not self.allowed_quality:
            raise ValueError("allowed_quality must contain at least one value")

        self.sequence = 0
        self.quality = "unknown"
        self.current_direction = None
        self.candidate_direction = None
        self.candidate_count = 0
        self.last_valid_monotonic = None
        self.timeout_published = False

    @staticmethod
    def _normalize_confidence(confidence):
        value = float(confidence)
        if not math.isfinite(value):
            return 0.0
        return min(1.0, max(0.0, value))

    def _number(self, payload):
        self.sequence += 1
        return {"sequence": self.sequence, **payload}

    def _clear_motion_state(self):
        self.current_direction = None
        self.candidate_direction = None
        self.candidate_count = 0
        self.last_valid_monotonic = None

    def _stop(self, stamp_ns, reason):
        self._clear_motion_state()
        return self._number(
            {
                "stamp_ns": int(stamp_ns),
                "command": "stop",
                "reason": str(reason),
            }
        )

    def _direction(self, stamp_ns, direction, confidence):
        return self._number(
            {
                "stamp_ns": int(stamp_ns),
                "command": "direction",
                "direction": direction,
                "confidence": confidence,
                "valid": True,
                "quality": self.quality,
            }
        )

    def update_quality(self, quality, stamp_ns):
        """Update quality and stop immediately if active motion becomes unsafe."""
        self.quality = str(quality).strip().lower() or "unknown"
        motion_pending_or_active = (
            self.current_direction is not None
            or self.candidate_direction is not None
        )
        if self.quality not in self.allowed_quality and motion_pending_or_active:
            return self._stop(stamp_ns, "poor_signal_quality")
        return None

    def process_command(
        self,
        direction,
        valid,
        confidence,
        stamp_ns,
        monotonic_now,
    ):
        """Apply safety rules and return a JSON-ready payload or ``None``."""
        direction = str(direction).strip().lower()
        confidence = self._normalize_confidence(confidence)

        # Explicit semantic stop states take precedence even when valid is
        # false, matching the documented idle and stop mappings.
        if direction == "idle":
            return self._stop(stamp_ns, "ssvep_idle")
        if direction == "stop":
            return self._stop(stamp_ns, "explicit_stop")
        if not bool(valid) or direction not in ALLOWED_DIRECTIONS:
            return self._stop(stamp_ns, "ssvep_invalid")
        if confidence < self.min_confidence:
            return self._stop(stamp_ns, "low_confidence")
        if self.quality not in self.allowed_quality:
            return self._stop(stamp_ns, "poor_signal_quality")

        self.last_valid_monotonic = float(monotonic_now)
        self.timeout_published = False

        if direction == self.current_direction:
            self.candidate_direction = None
            self.candidate_count = 0
            return self._direction(stamp_ns, direction, confidence)

        if direction == self.candidate_direction:
            self.candidate_count += 1
        else:
            self.candidate_direction = direction
            self.candidate_count = 1

        if self.candidate_count < self.required_consecutive_results:
            return None

        self.current_direction = direction
        self.candidate_direction = None
        self.candidate_count = 0
        return self._direction(stamp_ns, direction, confidence)

    def check_timeout(self, monotonic_now, stamp_ns):
        """Return one timeout stop when an active/pending command expires."""
        motion_pending_or_active = (
            self.current_direction is not None
            or self.candidate_direction is not None
        )
        if (
            not motion_pending_or_active
            or self.last_valid_monotonic is None
            or self.timeout_published
        ):
            return None
        age = float(monotonic_now) - self.last_valid_monotonic
        if age <= self.command_timeout_sec:
            return None

        self.timeout_published = True
        return self._stop(stamp_ns, "command_timeout")

    def final_stop(self, stamp_ns):
        """Build the one final stop requested during orderly node shutdown."""
        return self._stop(stamp_ns, "bridge_shutdown")


class SSVEPWhillBridge(Node):
    """ROS2 bridge from SSVEP commands and quality to WHILL controller JSON."""

    def __init__(self):
        super().__init__("ssvep_whill_bridge")

        min_confidence = float(
            self.declare_parameter("min_confidence", 0.75).value
        )
        required_results = int(
            self.declare_parameter("required_consecutive_results", 2).value
        )
        timeout_sec = float(
            self.declare_parameter("command_timeout_sec", 1.0).value
        )
        allowed_quality = list(
            self.declare_parameter(
                "allowed_quality", ["fair", "good"]
            ).value
        )
        log_file = str(
            self.declare_parameter(
                "log_file", "logs/runtime/ssvep_whill_bridge.log.txt"
            ).value
        )

        self._logic = WhillBridgeLogic(
            min_confidence=min_confidence,
            required_consecutive_results=required_results,
            command_timeout_sec=timeout_sec,
            allowed_quality=allowed_quality,
        )
        self._file_logger, self._log_path = create_file_logger(
            "ssvep_whill_bridge", log_file
        )
        self._shutdown_stop_sent = False

        output_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._publisher = self.create_publisher(
            String, "/whill/controller/bci_input", output_qos
        )
        self.create_subscription(
            SSVEPCommand,
            "/ssvep/command",
            self._command_callback,
            10,
        )
        self.create_subscription(
            SignalQuality,
            "/ssvep/quality",
            self._quality_callback,
            10,
        )
        timer_period = max(0.02, min(0.1, timeout_sec / 4.0))
        self._timeout_timer = self.create_timer(
            timer_period, self._timeout_callback
        )

        startup = (
            "started; input=/ssvep/command,/ssvep/quality; "
            "output=/whill/controller/bci_input; "
            f"min_confidence={min_confidence:.2f}; "
            f"required_consecutive_results={required_results}; "
            f"command_timeout_sec={timeout_sec:.2f}; "
            f"allowed_quality={sorted(self._logic.allowed_quality)}; "
            f"log={self._log_path}; hardware_connection=none"
        )
        self.get_logger().info(startup)
        self._file_logger.info(startup)

    def _ros_now_ns(self):
        return int(self.get_clock().now().nanoseconds)

    def _quality_callback(self, msg: SignalQuality):
        payload = self._logic.update_quality(
            msg.quality, self._ros_now_ns()
        )
        if payload is not None:
            self._publish_payload(
                payload,
                confidence=None,
                quality=self._logic.quality,
            )

    def _command_callback(self, msg: SSVEPCommand):
        confidence = WhillBridgeLogic._normalize_confidence(msg.confidence)
        payload = self._logic.process_command(
            direction=msg.direction,
            valid=msg.valid,
            confidence=msg.confidence,
            stamp_ns=stamp_to_nanoseconds(msg.header.stamp),
            monotonic_now=time.monotonic(),
        )
        if payload is None:
            pending = (
                "rejected direction pending confirmation; "
                f"direction={str(msg.direction).lower()}; "
                f"consecutive={self._logic.candidate_count}/"
                f"{self._logic.required_consecutive_results}; "
                f"confidence={confidence:.3f}; "
                f"quality={self._logic.quality}"
            )
            self.get_logger().info(pending)
            self._file_logger.info(pending)
            return

        self._publish_payload(
            payload,
            confidence=confidence,
            quality=self._logic.quality,
        )

    def _timeout_callback(self):
        payload = self._logic.check_timeout(
            time.monotonic(), self._ros_now_ns()
        )
        if payload is not None:
            self._publish_payload(
                payload,
                confidence=None,
                quality=self._logic.quality,
            )

    def _publish_payload(self, payload, confidence, quality):
        message = String()
        message.data = serialize_payload(payload)
        self._publisher.publish(message)

        sequence = payload["sequence"]
        if payload["command"] == "direction":
            event = (
                "accepted direction; "
                f"sequence={sequence}; direction={payload['direction']}; "
                f"confidence={payload['confidence']:.3f}; "
                f"quality={payload['quality']}"
            )
            self.get_logger().info(event)
            self._file_logger.info(event)
            return

        reason = payload["reason"]
        detail = (
            f"sequence={sequence}; reason={reason}; "
            f"confidence={confidence if confidence is not None else 'n/a'}; "
            f"quality={quality}"
        )
        if reason == "low_confidence":
            event = f"low-confidence stop; {detail}"
            self.get_logger().warning(event)
            self._file_logger.warning(event)
        elif reason == "poor_signal_quality":
            event = f"poor-quality stop; {detail}"
            self.get_logger().warning(event)
            self._file_logger.warning(event)
        elif reason == "command_timeout":
            event = f"timeout stop; {detail}"
            self.get_logger().warning(event)
            self._file_logger.warning(event)
        elif reason == "bridge_shutdown":
            event = f"final shutdown stop; {detail}"
            self.get_logger().info(event)
            self._file_logger.info(event)
        else:
            event = f"invalid-command stop; {detail}"
            self.get_logger().warning(event)
            self._file_logger.warning(event)

    def publish_final_stop(self):
        if self._shutdown_stop_sent:
            return
        self._shutdown_stop_sent = True
        payload = self._logic.final_stop(self._ros_now_ns())
        self._publish_payload(
            payload,
            confidence=None,
            quality=self._logic.quality,
        )


def main(args=None):
    # Keep the ROS context alive until the final safety stop has been sent.
    # Python's normal SIGINT handler raises KeyboardInterrupt; launch uses
    # SIGTERM as a later shutdown stage, so route that signal through the same
    # orderly path.
    rclpy.init(args=args, signal_handler_options=SignalHandlerOptions.NO)
    node = SSVEPWhillBridge()
    signal.signal(signal.SIGTERM, _request_keyboard_interrupt)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.publish_final_stop()
            rclpy.spin_once(node, timeout_sec=0.05)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
