"""Faz 3 Costas/Gardner senkronizasyon zinciri otomatik testleri."""

import unittest

import numpy as np

from analysis.lock_detector import detect_lock, variance_trend
from config import params

try:
    from gnuradio import gr  # noqa: F401
except ImportError:
    gr = None
    run_sync_simulation = None
else:
    from rx.rx_sync_chain import run_sync_simulation


class TestLockDetector(unittest.TestCase):
    """GNU Radio gerektirmeyen kilit karar mantığını doğrula."""

    def test_low_variance_tail_is_locked(self):
        """Her iki hata akışının sakin son penceresini kilitli kabul et."""
        rng = np.random.default_rng(3_103)
        acquisition = rng.normal(0.0, 0.8, 512)
        locked = rng.normal(
            0.0,
            0.01,
            params.lock_window_size * params.lock_error_average_span,
        )
        costas_error = np.concatenate((acquisition, locked))
        timing_error = np.concatenate((acquisition * 0.5, locked * 0.5))

        decision = detect_lock(costas_error, timing_error)

        self.assertTrue(decision.locked)
        self.assertLess(decision.costas_variance, params.costas_lock_var_threshold)
        self.assertLess(decision.timing_variance, params.timing_lock_var_threshold)


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestSynchronizationChain(unittest.TestCase):
    """Eb/No=6 dB uçtan uca senkronizasyon performansını doğrula."""

    @classmethod
    def setUpClass(cls):
        """Pahalı GNU Radio simülasyonunu test sınıfı için yalnız bir kez çalıştır."""
        cls.result = run_sync_simulation(
            ebno_db=6.0,
            payload_frames=1_000,
            doppler_max_hz=8_000.0,
            phase_noise_std=0.0,
            scintillation_std_db=0.0,
        )

    def test_costas_error_variance_decreases(self):
        """Costas hata varyansının ilk yüzde 10'dan son yüzde 10'a düştüğünü doğrula."""
        first_variance, last_variance = variance_trend(
            self.result.costas_error, fraction=0.10
        )
        self.assertLess(
            last_variance,
            first_variance,
            f"Costas varyansı azalmadı: first={first_variance}, last={last_variance}",
        )
        self.assertTrue(self.result.lock.locked, self.result.lock)

    def test_synchronized_symbols_have_low_coarse_evm(self):
        """Senkron sembollerin ideal QPSK noktalarına RMS mesafesini sınırla."""
        self.assertGreater(len(self.result.synchronized_symbols), 1_000)
        self.assertLess(self.result.evm_rms, params.sync_evm_threshold)


if __name__ == "__main__":
    unittest.main()
