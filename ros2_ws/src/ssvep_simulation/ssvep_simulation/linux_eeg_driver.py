"""Linux BlueZ/Bleak driver for the VisionBCI EEG headset."""

import asyncio
import csv
from datetime import datetime, timezone
import inspect
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time
from typing import Optional

from bleak import BleakClient, BleakScanner
import rclpy
from rclpy.node import Node
from rclpy.time import Time

from ssvep_interfaces.msg import EEGFrame

from .logging_utils import create_file_logger
from .visionbci_protocol import (
    CHANNEL_COUNT,
    CONFIGURATION_CHARACTERISTIC_UUID,
    EEG_NOTIFICATION_CHARACTERISTIC_UUID,
    EEG_SERVICE_UUID,
    SAMPLES_PER_PACKET,
    flatten_sample_major,
    parse_eeg_packet,
)


SAMPLING_RATE = 250.0


class LinuxEEGDriver(Node):
    """Discover a VisionBCI headset and publish verified EEG notifications."""

    def __init__(self):
        super().__init__("linux_eeg_driver")

        self._device_name = str(
            self.declare_parameter("device_name", "").value
        ).strip()
        self._device_name_prefix = str(
            self.declare_parameter("device_name_prefix", "VIS_BCI_").value
        ).strip()
        self._device_address = str(
            self.declare_parameter("device_address", "").value
        ).strip()
        self._scan_timeout = max(
            1.0, float(self.declare_parameter("scan_timeout", 10.0).value)
        )
        self._connect_timeout = max(
            1.0, float(self.declare_parameter("connect_timeout", 15.0).value)
        )
        self._reconnect_delay = max(
            0.5, float(self.declare_parameter("reconnect_delay", 3.0).value)
        )
        self._notification_timeout = max(
            0.5,
            float(self.declare_parameter("notification_timeout", 3.0).value),
        )
        configuration_hex = str(
            self.declare_parameter("configuration_hex", "").value
        ).strip()
        try:
            self._configuration_payload = (
                bytes.fromhex(configuration_hex) if configuration_hex else b""
            )
        except ValueError as exc:
            raise ValueError(
                "configuration_hex must contain complete hexadecimal bytes"
            ) from exc

        runtime_log = str(
            self.declare_parameter(
                "log_file", "logs/runtime/linux_eeg_driver.log.txt"
            ).value
        )
        data_log = str(
            self.declare_parameter("data_file", "logs/eeg_latest.txt").value
        )
        self._file_logger, self._log_path = create_file_logger(
            "linux_eeg_driver", runtime_log
        )
        self._data_path = self._resolve_path(data_log)
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
        self._data_stream = self._data_path.open(
            "w", encoding="utf-8", newline="", buffering=1
        )
        self._data_writer = csv.writer(self._data_stream, delimiter="\t")
        self._data_writer.writerow(
            ["timestamp"] + [f"EEG_{index}" for index in range(1, 9)]
        )

        self._publisher = self.create_publisher(EEGFrame, "/eeg/raw", 20)
        self._packet_queue = Queue(maxsize=500)
        self._status_queue = Queue()
        self._stop_event = threading.Event()
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._connected = False
        self._last_notification_monotonic: Optional[float] = None
        self._first_valid_notification = False
        self._last_parse_error_log = 0.0
        self._last_queue_error_log = 0.0

        self._rate_start: Optional[float] = None
        self._rate_samples_after_first = 0
        self._last_rate_report: Optional[float] = None
        self._total_samples = 0

        self._drain_timer = self.create_timer(0.005, self._drain_queues)
        self._ble_thread = threading.Thread(
            target=self._ble_thread_main,
            name="visionbci_ble",
            daemon=True,
        )
        self._ble_thread.start()

        selector = self._device_address or self._device_name
        if not selector:
            selector = f"name prefix {self._device_name_prefix!r}"
        message = (
            f"started Linux BlueZ/Bleak scan for {selector}; "
            f"publishing /eeg/raw; data={self._data_path}; log={self._log_path}"
        )
        self.get_logger().info(message)
        self._file_logger.info(message)

    @staticmethod
    def _resolve_path(configured_path: str) -> Path:
        path = Path(configured_path).expanduser()
        return path if path.is_absolute() else Path.cwd() / path

    def _queue_status(self, level: str, message: str):
        self._status_queue.put((level, message))

    def _ble_thread_main(self):
        loop = asyncio.new_event_loop()
        self._async_loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._ble_reconnect_loop())
        except Exception as exc:  # pragma: no cover - defensive thread boundary
            self._queue_status("error", f"BLE worker stopped unexpectedly: {exc}")
        finally:
            self._connected = False
            self._async_loop = None
            loop.close()

    async def _ble_reconnect_loop(self):
        while not self._stop_event.is_set():
            device = await self._discover_device()
            if device is None:
                await self._wait_for_retry()
                continue

            await self._connect_and_stream(device)
            if not self._stop_event.is_set():
                await self._wait_for_retry()

    async def _discover_device(self):
        try:
            devices = await BleakScanner.discover(timeout=self._scan_timeout)
        except Exception as exc:
            self._queue_status("error", f"device discovery failure: {exc}")
            return None

        for device in devices:
            name = (device.name or "").strip()
            address = (device.address or "").strip()
            if self._device_address:
                matched = address.lower() == self._device_address.lower()
            elif self._device_name:
                matched = name == self._device_name
            else:
                matched = bool(name) and name.startswith(self._device_name_prefix)
            if matched:
                self._queue_status(
                    "info", f"device discovered: name={name!r}, address={address}"
                )
                return device

        self._queue_status(
            "warning",
            "device discovery failure: no matching VisionBCI device found "
            f"during {self._scan_timeout:.1f}s scan",
        )
        return None

    async def _connect_and_stream(self, device):
        client = BleakClient(
            device,
            disconnected_callback=self._disconnected_callback,
            timeout=self._connect_timeout,
        )
        notification_started = False
        verified_connection = False
        try:
            await client.connect()
            if not await self._client_is_connected(client):
                raise RuntimeError("Bleak connect returned without a connected link")

            verified_connection = True
            self._connected = True
            self._queue_status(
                "info",
                f"connection verified: name={device.name!r}, "
                f"address={device.address}",
            )

            services = client.services
            if services.get_service(EEG_SERVICE_UUID) is None:
                raise RuntimeError(f"EEG service not found: {EEG_SERVICE_UUID}")
            if services.get_characteristic(CONFIGURATION_CHARACTERISTIC_UUID) is None:
                raise RuntimeError(
                    "configuration characteristic not found: "
                    f"{CONFIGURATION_CHARACTERISTIC_UUID}"
                )
            if services.get_characteristic(
                EEG_NOTIFICATION_CHARACTERISTIC_UUID
            ) is None:
                raise RuntimeError(
                    "EEG notification characteristic not found: "
                    f"{EEG_NOTIFICATION_CHARACTERISTIC_UUID}"
                )
            self._queue_status(
                "info",
                "verified VisionBCI EEG service, configuration characteristic, "
                "and notification characteristic",
            )

            if self._configuration_payload:
                await client.write_gatt_char(
                    CONFIGURATION_CHARACTERISTIC_UUID,
                    self._configuration_payload,
                    response=True,
                )
                self._queue_status(
                    "info",
                    "configuration write verified by BlueZ: "
                    f"{len(self._configuration_payload)} bytes",
                )
            else:
                self._queue_status(
                    "info",
                    "configuration characteristic verified; no write performed "
                    "because configuration_hex is empty",
                )

            self._last_notification_monotonic = time.monotonic()
            await client.start_notify(
                EEG_NOTIFICATION_CHARACTERISTIC_UUID,
                self._notification_callback,
            )
            notification_started = True
            self._queue_status(
                "info",
                "notification subscription active; waiting for a valid EEG packet",
            )

            while not self._stop_event.is_set():
                if not await self._client_is_connected(client):
                    break
                last_notification = self._last_notification_monotonic
                if (
                    last_notification is not None
                    and time.monotonic() - last_notification
                    > self._notification_timeout
                ):
                    self._queue_status(
                        "error",
                        "notification interruption: no EEG notification received for "
                        f"{self._notification_timeout:.1f}s; reconnecting",
                    )
                    break
                await asyncio.sleep(0.1)
        except Exception as exc:
            stage = "connection/stream failure" if verified_connection else "connection failure"
            self._queue_status("error", f"{stage}: {exc}")
        finally:
            self._connected = False
            if notification_started and await self._client_is_connected(client):
                try:
                    await client.stop_notify(EEG_NOTIFICATION_CHARACTERISTIC_UUID)
                except Exception as exc:
                    self._queue_status(
                        "warning", f"notification shutdown warning: {exc}"
                    )
            if await self._client_is_connected(client):
                try:
                    await client.disconnect()
                except Exception as exc:
                    self._queue_status("warning", f"disconnection failure: {exc}")
            if verified_connection:
                self._queue_status("info", "VisionBCI BLE link disconnected")

    @staticmethod
    async def _client_is_connected(client) -> bool:
        connected = client.is_connected
        if inspect.isawaitable(connected):
            connected = await connected
        return bool(connected)

    def _disconnected_callback(self, _client):
        self._connected = False
        if self._stop_event.is_set():
            self._queue_status("info", "BlueZ reported requested disconnection")
        else:
            self._queue_status("warning", "BlueZ reported unexpected disconnection")

    def _notification_callback(self, _sender, data: bytearray):
        received_monotonic = time.monotonic()
        received_wall = time.time()
        self._last_notification_monotonic = received_monotonic
        try:
            samples = parse_eeg_packet(data)
        except ValueError as exc:
            if received_monotonic - self._last_parse_error_log >= 1.0:
                self._queue_status(
                    "error",
                    f"discarded malformed EEG notification ({len(data)} bytes): {exc}",
                )
                self._last_parse_error_log = received_monotonic
            return

        try:
            self._packet_queue.put_nowait(
                (received_monotonic, received_wall, samples)
            )
        except Full:
            if received_monotonic - self._last_queue_error_log >= 1.0:
                self._queue_status(
                    "error", "EEG packet queue full; dropping notification"
                )
                self._last_queue_error_log = received_monotonic
            return

        if not self._first_valid_notification:
            self._first_valid_notification = True
            self._queue_status(
                "info",
                "sampling verified: received first valid EEG notification "
                f"({len(data)} bytes, {SAMPLES_PER_PACKET} samples, "
                f"{CHANNEL_COUNT} channels)",
            )

    async def _wait_for_retry(self):
        deadline = time.monotonic() + self._reconnect_delay
        while not self._stop_event.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)

    def _drain_queues(self):
        while True:
            try:
                level, message = self._status_queue.get_nowait()
            except Empty:
                break
            if level == "error":
                if rclpy.ok():
                    self.get_logger().error(message)
                self._file_logger.error(message)
            elif level == "warning":
                if rclpy.ok():
                    self.get_logger().warning(message)
                self._file_logger.warning(message)
            else:
                if rclpy.ok():
                    self.get_logger().info(message)
                self._file_logger.info(message)

        while True:
            try:
                received_monotonic, received_wall, samples = (
                    self._packet_queue.get_nowait()
                )
            except Empty:
                break
            self._publish_packet(received_monotonic, received_wall, samples)

    def _publish_packet(self, received_monotonic, received_wall, samples):
        first_sample_wall = received_wall - (
            (SAMPLES_PER_PACKET - 1) / SAMPLING_RATE
        )
        message = EEGFrame()
        message.header.stamp = Time(
            nanoseconds=int(first_sample_wall * 1_000_000_000)
        ).to_msg()
        message.header.frame_id = "visionbci_eeg"
        message.sampling_rate = SAMPLING_RATE
        message.channel_count = CHANNEL_COUNT
        message.samples_per_channel = SAMPLES_PER_PACKET
        message.values = flatten_sample_major(samples)
        if rclpy.ok():
            self._publisher.publish(message)

        for sample_index, channels in enumerate(samples):
            sample_time = first_sample_wall + sample_index / SAMPLING_RATE
            timestamp = datetime.fromtimestamp(
                sample_time, tz=timezone.utc
            ).isoformat(timespec="microseconds").replace("+00:00", "Z")
            self._data_writer.writerow(
                [timestamp] + [f"{float(value):.8f}" for value in channels]
            )
        self._data_stream.flush()

        self._total_samples += SAMPLES_PER_PACKET
        if self._rate_start is None:
            self._rate_start = received_monotonic
            self._last_rate_report = received_monotonic
        else:
            self._rate_samples_after_first += SAMPLES_PER_PACKET
            elapsed = received_monotonic - self._rate_start
            if (
                self._last_rate_report is not None
                and received_monotonic - self._last_rate_report >= 5.0
                and elapsed > 0.0
            ):
                measured_rate = self._rate_samples_after_first / elapsed
                self._file_logger.info(
                    "sampling rate measured %.2f Hz; total_samples=%d",
                    measured_rate,
                    self._total_samples,
                )
                if rclpy.ok():
                    self.get_logger().info(
                        f"sampling rate measured {measured_rate:.2f} Hz; "
                        f"total_samples={self._total_samples}"
                    )
                self._last_rate_report = received_monotonic

    def stop(self):
        """Stop BLE activity and close the latest-data file."""
        self._stop_event.set()
        loop = self._async_loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: None)
        if self._ble_thread.is_alive():
            self._ble_thread.join(timeout=max(5.0, self._connect_timeout + 1.0))
        self._drain_queues()
        if self._ble_thread.is_alive():
            message = "BLE worker did not stop before shutdown timeout"
            self.get_logger().warning(message)
            self._file_logger.warning(message)
        self._data_stream.close()


def main(args=None):
    rclpy.init(args=args)
    node = LinuxEEGDriver()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
