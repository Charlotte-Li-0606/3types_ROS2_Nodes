"""SSVEP decoder node publishing direction, confidence, and signal quality."""

from collections import deque

import numpy as np
import rclpy
from rclpy.node import Node

from ssvep_interfaces.msg import EEGFrame, SignalQuality, SSVEPCommand, StimulusState

from .logging_utils import create_file_logger
from .signal_processing import estimate_quality, fbcca_scores


class SSVEPDecoder(Node):
    """Buffer EEG frames and perform periodic FBCCA-style classification."""

    def __init__(self):
        super().__init__("ssvep_decoder")

        self._window_seconds = float(
            self.declare_parameter("window_seconds", 3.0).value
        )
        self._analysis_period = float(
            self.declare_parameter("analysis_period", 0.5).value
        )
        self._min_confidence = float(
            self.declare_parameter("min_confidence", 0.40).value
        )
        self._frequencies = [10.0, 14.0, 18.0, 22.0]
        self._direction_by_frequency = {
            10.0: "forward",
            14.0: "backward",
            18.0: "left",
            22.0: "right",
        }
        log_file = self.declare_parameter(
            "log_file", "logs/runtime/ssvep_simulation.log.txt"
        ).value
        self._file_logger, self._log_path = create_file_logger(
            "ssvep_decoder", log_file
        )

        self._sampling_rate = 250.0
        self._channel_count = 8
        self._samples = deque()
        self._max_samples = int(self._window_seconds * self._sampling_rate)
        self._last_stimulus = None
        self._analysis_count = 0

        self._command_publisher = self.create_publisher(
            SSVEPCommand, "/ssvep/command", 10
        )
        self._quality_publisher = self.create_publisher(
            SignalQuality, "/ssvep/quality", 10
        )
        self.create_subscription(EEGFrame, "/eeg/raw", self._eeg_callback, 20)
        self.create_subscription(
            StimulusState,
            "/ssvep/stimulus",
            self._stimulus_callback,
            10,
        )
        self._timer = self.create_timer(self._analysis_period, self._analyze)

        message = (
            f"started; window={self._window_seconds:.1f}s; "
            f"targets={self._frequencies}; log={self._log_path}"
        )
        self.get_logger().info(message)
        self._file_logger.info(message)

    def _stimulus_callback(self, msg: StimulusState):
        self._last_stimulus = (float(msg.frequency), str(msg.mode), bool(msg.active))

    def _eeg_callback(self, msg: EEGFrame):
        channel_count = int(msg.channel_count)
        samples_per_channel = int(msg.samples_per_channel)
        if channel_count <= 0 or samples_per_channel <= 0:
            return
        expected_values = channel_count * samples_per_channel
        if len(msg.values) != expected_values:
            self.get_logger().warning(
                f"discarding malformed EEG frame: expected {expected_values} "
                f"values, got {len(msg.values)}"
            )
            return

        frame = np.asarray(msg.values, dtype=float).reshape(
            samples_per_channel, channel_count
        )
        self._sampling_rate = float(msg.sampling_rate)
        self._channel_count = channel_count
        self._max_samples = max(
            32, int(round(self._window_seconds * self._sampling_rate))
        )
        self._samples.extend(frame.tolist())
        while len(self._samples) > self._max_samples:
            self._samples.popleft()

    def _analyze(self):
        if len(self._samples) < self._max_samples:
            return

        eeg = np.asarray(self._samples, dtype=float)
        scores = fbcca_scores(eeg, self._sampling_rate, self._frequencies)
        order = np.argsort(scores)[::-1]
        best_index = int(order[0])
        second_index = int(order[1])
        best_frequency = self._frequencies[best_index]

        # Softmax confidence is easy for downstream consumers to interpret and
        # is independent of the absolute scale of CCA scores.
        logits = 12.0 * (scores - np.max(scores))
        probabilities = np.exp(logits)
        probabilities /= np.sum(probabilities) + 1e-12
        confidence = float(np.clip(probabilities[best_index], 0.0, 1.0))
        valid = confidence >= self._min_confidence
        direction = (
            self._direction_by_frequency[best_frequency] if valid else "idle"
        )

        command = SSVEPCommand()
        command.header.stamp = self.get_clock().now().to_msg()
        command.header.frame_id = "ssvep_decoder"
        command.direction = direction
        command.detected_frequency = best_frequency
        command.confidence = confidence
        command.valid = valid
        self._command_publisher.publish(command)

        snr_db, signal_rms, noise_rms, quality_label = estimate_quality(
            eeg, self._sampling_rate, best_frequency
        )
        quality = SignalQuality()
        quality.header.stamp = command.header.stamp
        quality.header.frame_id = "ssvep_decoder"
        quality.snr_db = float(snr_db)
        quality.signal_rms = float(signal_rms)
        quality.noise_rms = float(noise_rms)
        quality.quality = quality_label
        self._quality_publisher.publish(quality)

        self._analysis_count += 1
        if self._analysis_count == 1 or self._analysis_count % 4 == 0:
            stimulus = self._last_stimulus[0] if self._last_stimulus else None
            self._file_logger.info(
                "detected %.1f Hz -> %s, confidence=%.2f, "
                "quality=%s, snr_db=%.2f, scores=%s, stimulus=%s",
                best_frequency,
                direction,
                confidence,
                quality_label,
                snr_db,
                np.round(scores, 4).tolist(),
                stimulus,
            )


def main(args=None):
    rclpy.init(args=args)
    node = SSVEPDecoder()
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
