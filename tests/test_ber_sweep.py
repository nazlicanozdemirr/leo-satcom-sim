"""Faz 5 Eb/No dönüşümü, coding-gain matematiği ve pipeline smoke testleri."""

import math
import unittest

import numpy as np

from analysis.ber_sweep import (
    code_rate_for_mode,
    noise_power_for_ebno,
    run_ber_sweep,
)
from analysis.coding_gain import (
    ebno_at_target,
    theoretical_qpsk_ber,
    uncoded_theory_deviation_db,
)
from config import params

try:
    from gnuradio import gr  # noqa: F401
except ImportError:
    gr = None


class TestEbNoAndCodingGainMath(unittest.TestCase):
    """GNU Radio gerektirmeyen Eb/No ve log-BER yardımcılarını doğrula."""

    def test_rate_half_noise_power_is_twice_uncoded(self):
        """Aynı bilgi-bit Eb/No'da rate-1/2 yolun iki kat gürültü gücü kullandığını doğrula."""
        uncoded = noise_power_for_ebno(6.0, code_rate_for_mode("uncoded"))
        coded = noise_power_for_ebno(6.0, code_rate_for_mode("ldpc"))
        self.assertAlmostEqual(coded / uncoded, 2.0, places=12)

    def test_noise_power_uses_sample_to_symbol_rate(self):
        """QPSK uncoded 0 dB dönüşümünün sps/2 sonucunu verdiğini doğrula."""
        measured = noise_power_for_ebno(
            0.0,
            1.0,
            samp_rate=params.samp_rate,
            sym_rate=params.sym_rate,
            sps=params.sps,
        )
        self.assertAlmostEqual(measured, params.sps / 2.0, places=12)

    def test_theoretical_qpsk_value_at_zero_db(self):
        """Teorik Gray-QPSK BER formülünün 0 dB referans değerini doğrula."""
        expected = 0.5 * math.erfc(1.0)
        self.assertAlmostEqual(theoretical_qpsk_ber(0.0), expected, places=12)

    def test_log_ber_interpolation(self):
        """1e-4 ve 1e-6 arasındaki 1e-5 hedefinin orta Eb/No'ya düştüğünü doğrula."""
        crossing = ebno_at_target([4.0, 6.0], [1e-4, 1e-6], target_ber=1e-5)
        self.assertAlmostEqual(crossing, 5.0, places=12)

    def test_theory_deviation_is_zero_for_theory_samples(self):
        """Teorik eğrinin kendisine göre Eb/No sapmasının sıfır olduğunu doğrula."""
        ebno = np.asarray([0.0, 2.0, 4.0, 6.0])
        deviation = uncoded_theory_deviation_db(ebno, theoretical_qpsk_ber(ebno))
        np.testing.assert_allclose(deviation, 0.0, atol=1e-9)


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestQuickBERSweepPipeline(unittest.TestCase):
    """Küçük Monte Carlo koşusuyla pipeline seçeneklerinin kırılmadığını doğrula."""

    def test_ebno_formulas_and_waveform_energy_are_identical(self):
        """İki Eb/No formülünü ve birim enerjili QPSK/RRC karar kazancını doğrula."""
        from rx.rx_sync_chain import ebno_to_noise_power, make_rx_rrc_taps
        from tx.tx_chain import make_rrc_taps, unit_energy_qpsk_points

        for ebno_db in (0.0, 4.0, 8.0, 10.0):
            sweep_power = noise_power_for_ebno(ebno_db, 1.0)
            receiver_power = ebno_to_noise_power(ebno_db, code_rate=1.0)
            self.assertEqual(sweep_power, receiver_power)
            self.assertEqual(sweep_power.hex(), receiver_power.hex())

        points = np.asarray(unit_energy_qpsk_points(), dtype=np.complex128)
        self.assertAlmostEqual(float(np.mean(np.abs(points) ** 2)), 1.0, places=6)
        decision_gain = float(
            np.dot(
                np.asarray(make_rrc_taps(), dtype=np.float64),
                np.asarray(make_rx_rrc_taps(), dtype=np.float64),
            )
        )
        self.assertEqual(decision_gain, 1.0)

    def test_quick_sweep_runs_all_end_to_end_chains(self):
        """Tek Eb/No'da uncoded, LDPC ve Viterbi yollarının sonuç ürettiğini doğrula."""
        rows, measurements = run_ber_sweep(
            ebno_values=[8.0],
            min_bits=params.quick_bits_per_point,
            batch_frames=250,
            include_viterbi=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {measurement.decoder_type for measurement in measurements},
            {"uncoded", "ldpc", "viterbi"},
        )
        for measurement in measurements:
            self.assertGreaterEqual(measurement.bits, params.quick_bits_per_point)
            self.assertGreaterEqual(measurement.errors, 0)
            self.assertTrue(np.isfinite(measurement.ber))
            self.assertTrue(0.0 <= measurement.ber <= 1.0)


if __name__ == "__main__":
    unittest.main()
