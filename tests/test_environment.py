"""Faz 0 ortam ve ortak yapılandırma smoke testleri."""

import re
import unittest


class TestEnvironment(unittest.TestCase):
    """Temel çalışma ortamının kullanıma hazır olduğunu doğrula."""

    def test_gnuradio_310_or_newer_is_available(self):
        """GNU Radio import edilebilmeli ve sürümü en az 3.10 olmalı."""
        try:
            from gnuradio import gr
        except ImportError as exc:
            self.fail(
                "GNU Radio import edilemedi. Önce environment.yml ile ortamı "
                f"kurun. Ayrıntı: {exc}"
            )

        version_text = gr.version()
        match = re.search(r"(\d+)\.(\d+)", version_text)
        self.assertIsNotNone(match, f"GNU Radio sürümü çözümlenemedi: {version_text}")
        version = tuple(int(part) for part in match.groups())
        self.assertGreaterEqual(version, (3, 10), f"GNU Radio 3.10+ gerekli: {version_text}")

    def test_shared_parameters_are_importable(self):
        """Ortak parametreler proje kökünden import edilebilmeli."""
        from config import params

        self.assertEqual(params.samp_rate, 2_000_000)
        self.assertEqual(params.sym_rate, 500_000)
        self.assertEqual(params.sps, 4)
        self.assertEqual(params.rrc_ntaps, 45)
        self.assertEqual(params.ldpc_n_short * params.ldpc_code_rate, params.ldpc_k_short)
        self.assertEqual(params.ebno_sweep_db, list(range(-2, 11)))
        self.assertEqual(params.rrc_ntaps % 2, 1)


if __name__ == "__main__":
    unittest.main()

