"""Offline tests for the confirmed VisionBCI EEG packet format."""

import unittest

from ssvep_simulation.visionbci_protocol import (
    CHANNEL_COUNT,
    SCALE_FACTOR,
    SAMPLES_PER_PACKET,
    VisionBCIPacketError,
    decode_signed_24bit_big_endian,
    flatten_sample_major,
    parse_eeg_packet,
)


def encode_signed_24bit(value: int) -> bytes:
    if not -(1 << 23) <= value < (1 << 23):
        raise ValueError("outside signed 24-bit range")
    unsigned = value if value >= 0 else value + (1 << 24)
    return unsigned.to_bytes(3, byteorder="big", signed=False)


class VisionBCIProtocolTest(unittest.TestCase):
    def test_signed_24bit_boundaries(self):
        self.assertEqual(decode_signed_24bit_big_endian(b"\x00\x00\x00"), 0)
        self.assertEqual(decode_signed_24bit_big_endian(b"\x00\x00\x01"), 1)
        self.assertEqual(decode_signed_24bit_big_endian(b"\x7f\xff\xff"), 8388607)
        self.assertEqual(decode_signed_24bit_big_endian(b"\xff\xff\xff"), -1)
        self.assertEqual(decode_signed_24bit_big_endian(b"\x80\x00\x00"), -8388608)

    def test_packet_shape_scale_nonzero_and_sample_major_order(self):
        raw_values = [index - 20 for index in range(40)]
        payload = b"".join(encode_signed_24bit(value) for value in raw_values)
        packet = b"\xaa\x55" + payload + bytes(25)
        self.assertEqual(len(packet), 147)

        samples = parse_eeg_packet(packet)
        self.assertEqual(len(samples), SAMPLES_PER_PACKET)
        self.assertTrue(all(len(row) == CHANNEL_COUNT for row in samples))
        self.assertTrue(any(value != 0.0 for row in samples for value in row))

        flattened = flatten_sample_major(samples)
        self.assertEqual(len(flattened), 40)
        expected = [value * SCALE_FACTOR for value in raw_values]
        for actual, wanted in zip(flattened, expected):
            self.assertAlmostEqual(actual, wanted, places=9)

        self.assertAlmostEqual(samples[0][7], raw_values[7] * SCALE_FACTOR)
        self.assertAlmostEqual(samples[1][0], raw_values[8] * SCALE_FACTOR)

    def test_short_packet_is_rejected(self):
        with self.assertRaises(VisionBCIPacketError):
            parse_eeg_packet(bytes(121))


if __name__ == "__main__":
    unittest.main()
