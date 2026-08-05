"""VisionBCI BLE UUIDs and EEG packet parsing.

The parser is deliberately independent of ROS 2 and Bleak so captured packets
can be checked offline on any Python 3 system.
"""

from typing import List, Sequence


EEG_SERVICE_UUID = "f0001680-0451-4000-b000-000000000000"
CONFIGURATION_CHARACTERISTIC_UUID = "f0001681-0451-4000-b000-000000000000"
EEG_NOTIFICATION_CHARACTERISTIC_UUID = "f0001682-0451-4000-b000-000000000000"

EEG_PAYLOAD_START = 2
EEG_PAYLOAD_END = 122
CHANNEL_COUNT = 8
SAMPLES_PER_PACKET = 5
BYTES_PER_CHANNEL = 3
SCALE_FACTOR = 0.02235
MINIMUM_PACKET_LENGTH = EEG_PAYLOAD_END


class VisionBCIPacketError(ValueError):
    """Raised when a BLE notification cannot contain one complete EEG frame."""


def decode_signed_24bit_big_endian(raw_value: Sequence[int]) -> int:
    """Decode exactly three bytes as a signed, big-endian 24-bit integer."""
    raw_bytes = bytes(raw_value)
    if len(raw_bytes) != BYTES_PER_CHANNEL:
        raise VisionBCIPacketError(
            f"expected {BYTES_PER_CHANNEL} bytes, got {len(raw_bytes)}"
        )

    value = int.from_bytes(raw_bytes, byteorder="big", signed=False)
    if value & 0x800000:
        value -= 1 << 24
    return value


def parse_eeg_packet(data: Sequence[int]) -> List[List[float]]:
    """Parse one notification into five sample-major rows of eight channels.

    VisionBCI notifications are normally about 147 bytes long. Only bytes
    ``data[2:122]`` are EEG, so trailing protocol fields are accepted and
    ignored. Returned rows preserve this order::

        sample_0_ch_0 ... sample_0_ch_7
        sample_1_ch_0 ... sample_1_ch_7
    """
    packet = bytes(data)
    if len(packet) < MINIMUM_PACKET_LENGTH:
        raise VisionBCIPacketError(
            f"packet too short: expected at least {MINIMUM_PACKET_LENGTH} bytes, "
            f"got {len(packet)}"
        )

    payload = packet[EEG_PAYLOAD_START:EEG_PAYLOAD_END]
    expected_payload_length = (
        SAMPLES_PER_PACKET * CHANNEL_COUNT * BYTES_PER_CHANNEL
    )
    if len(payload) != expected_payload_length:
        raise VisionBCIPacketError(
            f"invalid EEG payload length: expected {expected_payload_length}, "
            f"got {len(payload)}"
        )

    samples: List[List[float]] = []
    offset = 0
    for _sample_index in range(SAMPLES_PER_PACKET):
        channels = []
        for _channel_index in range(CHANNEL_COUNT):
            raw_value = payload[offset:offset + BYTES_PER_CHANNEL]
            channels.append(
                decode_signed_24bit_big_endian(raw_value) * SCALE_FACTOR
            )
            offset += BYTES_PER_CHANNEL
        samples.append(channels)
    return samples


def flatten_sample_major(samples: Sequence[Sequence[float]]) -> List[float]:
    """Flatten sample rows in the order required by ``EEGFrame.values``."""
    if len(samples) != SAMPLES_PER_PACKET:
        raise VisionBCIPacketError(
            f"expected {SAMPLES_PER_PACKET} samples, got {len(samples)}"
        )

    flattened = []
    for sample in samples:
        if len(sample) != CHANNEL_COUNT:
            raise VisionBCIPacketError(
                f"expected {CHANNEL_COUNT} channels, got {len(sample)}"
            )
        flattened.extend(float(value) for value in sample)
    return flattened
