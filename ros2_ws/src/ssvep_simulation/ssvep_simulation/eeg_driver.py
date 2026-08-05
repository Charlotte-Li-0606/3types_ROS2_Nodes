"""Simulated raw EEG publisher.

The real hardware driver will eventually replace this node. The simulation
keeps the same public output: frames of multi-channel EEG samples at 250 Hz.
"""

import math

import numpy as np
import rclpy
from rclpy.node import Node

from ssvep_interfaces.msg import EEGFrame, StimulusState

from .logging_utils import create_file_logger


class EEGDriver(Node):
    """Generate a repeatable SSVEP-like EEG stream with configurable noise."""

    def __init__(self):
        super().__init__("eeg_driver")

        self._sampling_rate = float(
            self.declare_parameter("sampling_rate", 250.0).value
        )
        self._channel_count = int(self.declare_parameter("channel_count", 8).value)
        self._frame_samples = int(self.declare_parameter("frame_samples", 10).value)
        self._signal_amplitude = float(
            self.declare_parameter("signal_amplitude", 1.0).value
        )
        self._noise_std = float(self.declare_parameter("noise_std", 0.35).value)
        log_file = self.declare_parameter(
            "log_file", "logs/runtime/ssvep_simulation.log.txt"
        ).value
        self._file_logger, self._log_path = create_file_logger(
            "eeg_driver", log_file
        )

        self._current_frequency = 10.0
        self._active = True
        self._sample_index = 0
        self._frames_since_log = 0
        self._rng = np.random.default_rng(20260804)
        self._channel_gain = np.linspace(0.8, 1.2, self._channel_count)
        self._channel_phase = np.linspace(0.0, math.pi / 3.0, self._channel_count)

        self._publisher = self.create_publisher(EEGFrame, "/eeg/raw", 20)
        self.create_subscription(
            StimulusState,
            "/ssvep/stimulus",
            self._stimulus_callback,
            10,
        )
        period = self._frame_samples / self._sampling_rate
        self._timer = self.create_timer(period, self._publish_frame)

        message = (
            f"publishing {self._channel_count} channels at "
            f"{self._sampling_rate:.1f} Hz; log={self._log_path}"
        )
        self.get_logger().info(message)
        self._file_logger.info(message)

    def _stimulus_callback(self, msg: StimulusState):
        self._current_frequency = float(msg.frequency)
        self._active = bool(msg.active)

    def _publish_frame(self):
        sample_numbers = np.arange(self._frame_samples) + self._sample_index
        time_axis = sample_numbers / self._sampling_rate

        if self._active and self._current_frequency > 0.0:
            fundamental = np.sin(
                2.0 * np.pi * self._current_frequency * time_axis[:, None]
                + self._channel_phase[None, :]
            )
            harmonic = 0.25 * np.sin(
                4.0 * np.pi * self._current_frequency * time_axis[:, None]
                + self._channel_phase[None, :]
            )
            ssvep = self._signal_amplitude * (fundamental + harmonic)
        else:
            ssvep = np.zeros((self._frame_samples, self._channel_count))

        # A small slow drift makes the signal less artificial while the
        # configurable white noise lets users inspect signal-quality methods.
        drift = 0.08 * np.sin(2.0 * np.pi * 1.0 * time_axis[:, None])
        noise = self._rng.normal(
            0.0, self._noise_std, size=(self._frame_samples, self._channel_count)
        )
        eeg = (ssvep + drift + noise) * self._channel_gain[None, :]

        msg = EEGFrame()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "simulated_eeg"
        msg.sampling_rate = self._sampling_rate
        msg.channel_count = self._channel_count
        msg.samples_per_channel = self._frame_samples
        msg.values = eeg.astype(np.float32).ravel().tolist()
        self._publisher.publish(msg)

        self._sample_index += self._frame_samples
        self._frames_since_log += 1
        if self._frames_since_log >= int(self._sampling_rate / self._frame_samples * 5):
            self._file_logger.info(
                "published %d samples; stimulus=%.1f Hz; noise_std=%.3f",
                self._sample_index,
                self._current_frequency if self._active else 0.0,
                self._noise_std,
            )
            self._frames_since_log = 0


def main(args=None):
    rclpy.init(args=args)
    node = EEGDriver()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
