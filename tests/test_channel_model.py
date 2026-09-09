"""LEO kanal modelinin AWGN ve Doppler otomatik doğrulama testleri."""

import math
import unittest

import numpy as np

try:
    from gnuradio import blocks, gr
except ImportError:
    blocks = None
    gr = None
    BOLTZMANN_J_PER_K = 1.380649e-23
    leo_channel_model = None
else:
    from channel.leo_channel_model import BOLTZMANN_J_PER_K, leo_channel_model


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestLeoChannelModel(unittest.TestCase):
    """Kanalın ölçülen istatistiklerini teorik değerlerle karşılaştır."""

    @staticmethod
    def _run_channel(samples, **channel_parameters):
        """Sonlu kompleks vektörü kanaldan geçirip NumPy dizisi döndür."""
        flowgraph = gr.top_block()
        source = blocks.vector_source_c(np.asarray(samples, dtype=np.complex64).tolist())
        channel = leo_channel_model(**channel_parameters)
        sink = blocks.vector_sink_c()
        flowgraph.connect(source, channel, sink)
        flowgraph.run()
        return np.asarray(sink.data(), dtype=np.complex64)

    @staticmethod
    def _fft_peak_hz(samples, samp_rate):
        """Hann pencereli FFT'nin en güçlü kompleks frekansını hesapla."""
        window = np.hanning(len(samples))
        spectrum = np.fft.fftshift(np.fft.fft(samples * window))
        frequencies = np.fft.fftshift(np.fft.fftfreq(len(samples), 1.0 / samp_rate))
        return float(frequencies[np.argmax(np.abs(spectrum))])

    def test_awgn_snr_matches_k_t_b(self):
        """Yalnız AWGN etkinken ölçülen SNR'nin kTB hesabını doğrula."""
        samp_rate = 200_000.0
        bandwidth_hz = 100_000.0
        t_sys_kelvin = 290.0
        signal_amplitude = np.float32(1e-6)
        sample_count = 1 << 18
        transmitted = np.full(sample_count, signal_amplitude, dtype=np.complex64)

        received = self._run_channel(
            transmitted,
            samp_rate=samp_rate,
            t_sys_kelvin=t_sys_kelvin,
            signal_bandwidth_hz=bandwidth_hz,
            phase_noise_std=0.0,
            doppler_max_hz=0.0,
            scintillation_std_db=0.0,
            path_loss_db=0.0,
            random_seed=12_345,
        )

        noise = received - transmitted[: len(received)]
        measured_noise_power = float(np.mean(np.abs(noise.astype(np.complex128)) ** 2))
        signal_power = float(signal_amplitude**2)
        theoretical_noise_power = BOLTZMANN_J_PER_K * t_sys_kelvin * bandwidth_hz
        measured_snr_db = 10.0 * math.log10(signal_power / measured_noise_power)
        theoretical_snr_db = 10.0 * math.log10(signal_power / theoretical_noise_power)

        self.assertAlmostEqual(measured_snr_db, theoretical_snr_db, delta=0.5)

    def test_doppler_profiles_follow_expected_fft_track(self):
        """Lineer ve parabolik Doppler izlerini kısa-zaman FFT ile doğrula."""
        samp_rate = 32_000.0
        pass_duration_s = 1.0
        doppler_max_hz = 2_000.0
        transmitted = np.ones(int(samp_rate * pass_duration_s), dtype=np.complex64)
        fft_size = 512

        for profile in ("linear", "parabolic"):
            with self.subTest(profile=profile):
                received = self._run_channel(
                    transmitted,
                    samp_rate=samp_rate,
                    t_sys_kelvin=0.0,
                    signal_bandwidth_hz=samp_rate / 2.0,
                    phase_noise_std=0.0,
                    doppler_max_hz=doppler_max_hz,
                    doppler_profile=profile,
                    scintillation_std_db=0.0,
                    path_loss_db=0.0,
                    doppler_pass_duration_s=pass_duration_s,
                    random_seed=54_321,
                )

                measured_hz = []
                expected_hz = []
                for progress in (0.125, 0.5, 0.875):
                    center = int(progress * samp_rate * pass_duration_s)
                    segment = received[center - fft_size // 2 : center + fft_size // 2]
                    measured_hz.append(self._fft_peak_hz(segment, samp_rate))
                    shape = 1.0 - 2.0 * progress
                    if profile == "parabolic":
                        shape = 1.0 - 2.0 * progress**2
                    expected_hz.append(doppler_max_hz * shape)

                np.testing.assert_allclose(measured_hz, expected_hz, atol=150.0, rtol=0.0)
                self.assertGreater(measured_hz[0], measured_hz[1])
                self.assertGreater(measured_hz[1], measured_hz[2])


if __name__ == "__main__":
    unittest.main()
