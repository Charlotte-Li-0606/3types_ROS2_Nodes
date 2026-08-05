"""Simulated SSVEP stimulus-state publisher."""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from ssvep_interfaces.msg import StimulusState

from .logging_utils import create_file_logger


class SSVEPStimulus(Node):
    """Publish the frequency currently shown by a simulated visual stimulus."""

    def __init__(self):
        super().__init__("ssvep_stimulus")

        self._frequencies = [10.0, 14.0, 18.0, 22.0]
        self._modes = {
            10.0: "forward",
            14.0: "backward",
            18.0: "left",
            22.0: "right",
        }
        self._auto_cycle = bool(self.declare_parameter("auto_cycle", True).value)
        self._cycle_seconds = float(
            self.declare_parameter("cycle_seconds", 6.0).value
        )
        self._frequency = float(self.declare_parameter("frequency", 10.0).value)
        self._mode = str(self.declare_parameter("mode", "forward").value)
        log_file = self.declare_parameter(
            "log_file", "logs/runtime/ssvep_simulation.log.txt"
        ).value
        self._file_logger, self._log_path = create_file_logger(
            "ssvep_stimulus", log_file
        )

        self._cycle_index = self._nearest_frequency_index(self._frequency)
        self._last_cycle_time = time.monotonic()
        self._last_published = None

        self._publisher = self.create_publisher(
            StimulusState, "/ssvep/stimulus", 10
        )
        self.create_subscription(
            String,
            "/ssvep/stimulus/select",
            self._selection_callback,
            10,
        )
        self._timer = self.create_timer(0.1, self._publish_state)

        message = (
            f"started; auto_cycle={self._auto_cycle}; "
            f"frequencies={self._frequencies}; log={self._log_path}"
        )
        self.get_logger().info(message)
        self._file_logger.info(message)

    def _nearest_frequency_index(self, frequency: float) -> int:
        distances = [abs(candidate - frequency) for candidate in self._frequencies]
        return int(distances.index(min(distances)))

    def _selection_callback(self, msg: String):
        """Accept JSON (frequency/mode) or a plain frequency/mode string."""
        raw = msg.data.strip()
        if not raw:
            return

        frequency = None
        mode = None
        try:
            selection = json.loads(raw)
            if isinstance(selection, dict):
                frequency = selection.get("frequency")
                mode = selection.get("mode")
            else:
                frequency = selection
        except json.JSONDecodeError:
            try:
                frequency = float(raw)
            except ValueError:
                mode = raw.lower()

        if mode is not None:
            mode = str(mode).lower()
            for candidate, candidate_mode in self._modes.items():
                if candidate_mode == mode:
                    frequency = candidate
                    break

        if frequency is None:
            self.get_logger().warning(f"cannot parse stimulus selection: {raw}")
            return

        try:
            frequency = float(frequency)
        except (TypeError, ValueError):
            self.get_logger().warning(f"invalid stimulus frequency: {frequency}")
            return

        index = self._nearest_frequency_index(frequency)
        self._cycle_index = index
        self._frequency = self._frequencies[index]
        self._mode = self._modes[self._frequency]
        self._last_cycle_time = time.monotonic()
        self._auto_cycle = False
        self._file_logger.info(
            "manual selection: %.1f Hz (%s)", self._frequency, self._mode
        )

    def _publish_state(self):
        now = time.monotonic()
        if self._auto_cycle and now - self._last_cycle_time >= self._cycle_seconds:
            self._cycle_index = (self._cycle_index + 1) % len(self._frequencies)
            self._frequency = self._frequencies[self._cycle_index]
            self._mode = self._modes[self._frequency]
            self._last_cycle_time = now

        msg = StimulusState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "simulated_stimulus"
        msg.frequency = self._frequency
        msg.mode = self._mode
        msg.active = True
        self._publisher.publish(msg)

        state = (self._frequency, self._mode)
        if state != self._last_published:
            message = f"active stimulus {self._frequency:.1f} Hz ({self._mode})"
            self.get_logger().info(message)
            self._file_logger.info(message)
            self._last_published = state


def main(args=None):
    rclpy.init(args=args)
    node = SSVEPStimulus()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
