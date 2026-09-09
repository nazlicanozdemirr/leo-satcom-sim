"""Faz 4 FEC decode ve QPSK EVM analiz testleri."""

import math
import unittest

import numpy as np

from analysis.evm_calc import QPSK_POINTS, calculate_evm
from config import params

try:
    from gnuradio import gr  # noqa: F401
except ImportError:
    gr = None
    run_full_simulation = None
else:
    from rx.rx_full_chain import run_full_simulation


def _awgn_qpsk(ebno_db, symbols_per_point=2_500, seed=4_000):
    """Saf EVM testleri için dengeli ideal QPSK üzerine kompleks AWGN ekle."""
    ideal = np.tile(QPSK_POINTS, int(symbols_per_point))
    rng = np.random.default_rng(int(seed))
    ebno_linear = 10.0 ** (float(ebno_db) / 10.0)
    complex_noise_power = 1.0 / (2.0 * ebno_linear)
    component_std = math.sqrt(complex_noise_power / 2.0)
    noise = rng.normal(0.0, component_std, len(ideal)) + 1j * rng.normal(
        0.0, component_std, len(ideal)
    )
    return (ideal + noise).astype(np.complex64)


class TestEVMCalculation(unittest.TestCase):
    """GNU Radio gerektirmeyen EVM formülü, trendi ve histogramı doğrula."""

    def test_ideal_qpsk_has_zero_evm_and_balanced_histogram(self):
        """İdeal dört noktanın EVM'inin sıfır ve sayımlarının eşit olduğunu doğrula."""
        symbols = np.tile(QPSK_POINTS, 1_000)
        result = calculate_evm(symbols, window_size=1_000)
        self.assertAlmostEqual(result.evm_rms_percent, 0.0, places=6)
        self.assertEqual(list(result.histogram.values()), [1_000] * 4)
        self.assertEqual(len(result.trend_percent), 4)

    def test_evm_decreases_from_zero_to_ten_db(self):
        """10 dB EVM'in aynı veri/tohumla 0 dB EVM'den anlamlı düşük olduğunu doğrula."""
        low = calculate_evm(_awgn_qpsk(0.0, seed=4_010))
        high = calculate_evm(_awgn_qpsk(10.0, seed=4_010))
        self.assertLess(high.evm_rms_percent, 0.60 * low.evm_rms_percent)

    def test_high_ebno_cluster_counts_are_balanced(self):
        """10 dB'de dört karar kümesinin aşırı dengesiz olmadığını doğrula."""
        histogram = calculate_evm(_awgn_qpsk(10.0, seed=4_020)).histogram
        counts = np.asarray(list(histogram.values()), dtype=np.float64)
        self.assertLess((counts.max() - counts.min()) / counts.mean(), 0.10)


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestFullFECChain(unittest.TestCase):
    """Gerçek GNU Radio TX/kanal/senkronizasyon/FEC zincirini doğrula."""

    @classmethod
    def setUpClass(cls):
        """Ortak LDPC ve EVM koşularını sınıf başına yalnız bir kez çalıştır."""
        cls.ldpc_8_db = run_full_simulation(
            ebno_db=8.0,
            decoder_type="ldpc",
            payload_frames=2_000,
            doppler_max_hz=0.0,
        )
        cls.evm_0_db = run_full_simulation(
            ebno_db=0.0,
            decoder_type="viterbi",
            payload_frames=500,
            doppler_max_hz=0.0,
        )
        cls.evm_10_db = run_full_simulation(
            ebno_db=10.0,
            decoder_type="viterbi",
            payload_frames=500,
            doppler_max_hz=0.0,
        )

    def test_ldpc_post_decode_ber_is_clearly_lower(self):
        """8 dB'de LDPC sonrası BER'in decode öncesinden belirgin düşük olduğunu doğrula."""
        self.assertTrue(np.isfinite(self.ldpc_8_db.pre_fec_ber))
        self.assertTrue(np.isfinite(self.ldpc_8_db.post_fec_ber))
        self.assertGreater(self.ldpc_8_db.pre_fec_ber, 0.0)
        self.assertLess(
            self.ldpc_8_db.post_fec_ber,
            0.75 * self.ldpc_8_db.pre_fec_ber,
        )

    def test_full_chain_evm_decreases_with_ebno(self):
        """Tam zincirde 10 dB EVM'in 0 dB değerinden düşük olduğunu doğrula."""
        self.assertLess(
            self.evm_10_db.evm.evm_rms_percent,
            self.evm_0_db.evm.evm_rms_percent,
        )

    def test_full_chain_qpsk_clusters_are_balanced(self):
        """Yüksek Eb/No senkron sembollerinin dört kümeye dengeli dağıldığını doğrula."""
        counts = np.asarray(
            list(self.evm_10_db.evm.histogram.values()), dtype=np.float64
        )
        self.assertLess((counts.max() - counts.min()) / counts.mean(), 0.20)


if __name__ == "__main__":
    unittest.main()
