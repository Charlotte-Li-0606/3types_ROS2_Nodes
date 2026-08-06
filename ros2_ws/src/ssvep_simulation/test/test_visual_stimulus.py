import unittest

from ssvep_simulation.ssvep_visual_stimulus import SSVEPVisualStimulus


class TestVisualStimulusTargets(unittest.TestCase):
    def test_zero_selects_all_four_targets(self):
        targets = SSVEPVisualStimulus._select_targets(0.0)
        self.assertEqual([target[0] for target in targets], [10.0, 14.0, 18.0, 22.0])

    def test_each_decoder_frequency_selects_one_target(self):
        for frequency in (10.0, 14.0, 18.0, 22.0):
            with self.subTest(frequency=frequency):
                targets = SSVEPVisualStimulus._select_targets(frequency)
                self.assertEqual(len(targets), 1)
                self.assertEqual(targets[0][0], frequency)

    def test_unsupported_frequency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "10, 14, 18, 22"):
            SSVEPVisualStimulus._select_targets(8.0)


if __name__ == "__main__":
    unittest.main()
