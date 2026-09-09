"""8 dB Costas cycle-slip ve koherent pre-FEC BER regresyonları."""

import math
import unittest

import numpy as np

from analysis.sync_quality import costas_samples_per_frame, detect_cycle_slips
from config import params

try:
    from gnuradio import gr  # noqa: F401
except ImportError:
    gr = None
else:
    from rx.rx_full_chain import run_full_simulation


class TestCycleSlipDetector(unittest.TestCase):
    """Phase düzeltme izindeki quadrant sıçraması algılamasını doğrula."""

    def test_detects_synthetic_pi_over_two_jump(self):
        """İkinci frame'deki pi/2 basamağını tek slip'li frame olarak bul."""
        samples_per_frame = 384
        phase = np.zeros(4 * samples_per_frame, dtype=np.float64)
        phase[2 * samples_per_frame + 40 :] = np.pi / 2.0
        report = detect_cycle_slips(phase, samples_per_frame)
        self.assertEqual(report.frames_with_slip, 1)
        np.testing.assert_array_equal(report.frame_indices, [2])


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestEightDbSynchronizationQuality(unittest.TestCase):
    """Koherent AWGN referansında Costas kalitesini ve ham BER'i sınar."""

    @classmethod
    def setUpClass(cls):
        """Ortak 8 dB koşusunu test sınıfı için yalnız bir kez çalıştır."""
        cls.result = run_full_simulation(
            8.0,
            decoder_type="ldpc",
            payload_frames=2_000,
            doppler_max_hz=0.0,
            differential_coding=False,
        )

    def test_pre_fec_ber_is_within_fifty_percent_of_theory(self):
        """Ham BER'in rate-1/2 koherent QPSK teorisinin ±%50 bandında olduğunu doğrula."""
        coded_bit_ebno = params.ldpc_code_rate * 10.0 ** (8.0 / 10.0)
        theoretical = 0.5 * math.erfc(math.sqrt(coded_bit_ebno))
        self.assertGreaterEqual(self.result.pre_fec_ber, 0.5 * theoretical)
        self.assertLessEqual(self.result.pre_fec_ber, 1.5 * theoretical)

    def test_cycle_slip_rate_is_below_one_percent(self):
        """No-Doppler 8 dB koşusunda quadrant slip oranını yüzde birin altında tut."""
        frame_bits = params.preamble_len + params.ldpc_n_short + params.frame_pad_bits
        samples_per_frame = costas_samples_per_frame(self.result, frame_bits)
        report = detect_cycle_slips(self.result.costas_phase, samples_per_frame)
        self.assertLess(report.frame_slip_rate, 0.01, report)


if __name__ == "__main__":
    unittest.main()
