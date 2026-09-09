"""Coherent QPSK quadrant-resolution consistency regressions."""

import unittest

import numpy as np

try:
    from gnuradio import gr  # noqa: F401
except ImportError:
    gr = None
else:
    from analysis.phase_ambiguity_check import run_spot_check
    from rx.rx_full_chain import (
        DECODER_TYPES,
        _QPSKPhaseAmbiguityFrameExtractor,
        run_full_simulation,
        rx_full_chain,
    )


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestCoherentPhaseAmbiguity(unittest.TestCase):
    """Require one PN63 resolver and correct quadrant choice in every path."""

    def test_all_decoder_paths_share_the_same_resolver(self):
        """Uncoded, LDPC and Viterbi coherent RX paths use the PN63 resolver."""
        for decoder_type in DECODER_TYPES:
            with self.subTest(decoder_type=decoder_type):
                receiver = rx_full_chain(decoder_type, differential=False)
                self.assertIsInstance(
                    receiver.frame_extractor,
                    _QPSKPhaseAmbiguityFrameExtractor,
                )

    def test_all_quadrants_are_resolved_for_all_decoder_paths(self):
        """A forced 0/90/180/270-degree lock is corrected before every decoder."""
        for quadrant in range(4):
            for decoder_type in DECODER_TYPES:
                with self.subTest(quadrant=quadrant, decoder_type=decoder_type):
                    result = run_full_simulation(
                        10.0,
                        decoder_type=decoder_type,
                        payload_frames=30,
                        differential_coding=False,
                        carrier_phase_offset_rad=quadrant * np.pi / 2.0,
                        doppler_max_hz=0.0,
                        phase_noise_std=0.0,
                        scintillation_std_db=0.0,
                    )
                    self.assertGreaterEqual(len(result.selected_phase_rotations), 29)
                    self.assertTrue(
                        np.all(result.selected_phase_rotations == quadrant),
                        result.selected_phase_rotations,
                    )
                    self.assertLess(result.post_fec_ber, 0.01)

    def test_low_snr_high_ber_frame_rate_stays_below_two_percent(self):
        """PN63 rotation decisions remain reliable at -2 and 0 dB."""
        for ebno_db in (-2.0, 0.0):
            for decoder_type in DECODER_TYPES:
                with self.subTest(ebno_db=ebno_db, decoder_type=decoder_type):
                    report = run_spot_check(decoder_type, ebno_db, frames=500)
                    self.assertGreaterEqual(report.detected_frames, 499)
                    self.assertLess(report.high_ber_rate, 0.02, report)


if __name__ == "__main__":
    unittest.main()
