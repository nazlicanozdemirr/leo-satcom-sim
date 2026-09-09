"""GNU Radio için zamanla değişen LEO uzay kanalı modeli.

Kompleks taban bant örneklerinin ``sqrt(watt)`` cinsinden normalize edildiği
kabul edilir. Böylece ``abs(x) ** 2`` sinyal gücünü watt cinsinden verir ve
termal gürültü doğrudan ``k * T_sys * B`` ile ölçeklenebilir.
"""

import math

import numpy as np
from scipy import signal

from gnuradio import analog, blocks, gr

from config import params


BOLTZMANN_J_PER_K = 1.380649e-23
_TWO_PI = 2.0 * math.pi


def _require_nonnegative(name, value):
    """Bir fiziksel büyüklüğün negatif olmadığını doğrula."""
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value < 0.0:
        raise ValueError(f"{name} sonlu ve sıfırdan büyük/eşit olmalı")
    return numeric_value


def _require_positive(name, value):
    """Bir fiziksel büyüklüğün pozitif olduğunu doğrula."""
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value <= 0.0:
        raise ValueError(f"{name} sonlu ve sıfırdan büyük olmalı")
    return numeric_value


class _TimeVaryingDoppler(gr.sync_block):
    """Anlık frekansı bir LEO geçiş profiline göre değiştiren rotator."""

    def __init__(self, samp_rate, doppler_max_hz, profile, pass_duration_s):
        """Doppler sınırını, profilini ve geçiş süresini yapılandır."""
        gr.sync_block.__init__(
            self,
            name="LEO time-varying Doppler",
            in_sig=[np.complex64],
            out_sig=[np.complex64],
        )
        if profile not in {"linear", "parabolic"}:
            raise ValueError("doppler_profile 'linear' veya 'parabolic' olmalı")
        self.samp_rate = _require_positive("samp_rate", samp_rate)
        self.doppler_max_hz = _require_nonnegative("doppler_max_hz", doppler_max_hz)
        if self.doppler_max_hz >= self.samp_rate / 2.0:
            raise ValueError("doppler_max_hz Nyquist frekansından küçük olmalı")
        self.profile = profile
        self.pass_duration_s = _require_positive("doppler_pass_duration_s", pass_duration_s)
        self._pass_samples = self.samp_rate * self.pass_duration_s
        self._sample_index = 0
        self._phase_rad = 0.0

    def _frequency_hz(self, sample_indices):
        """Örnek indisleri için lineer veya parabolik Doppler üret."""
        progress = np.clip(sample_indices / self._pass_samples, 0.0, 1.0)
        if self.profile == "linear":
            shape = 1.0 - 2.0 * progress
        else:
            shape = 1.0 - 2.0 * progress**2
        return self.doppler_max_hz * shape

    def work(self, input_items, output_items):
        """Girdiyi fazı sürekli, zamanla değişen Doppler rotatorüyle çarp."""
        source = input_items[0]
        destination = output_items[0]
        count = len(destination)
        indices = self._sample_index + np.arange(count, dtype=np.float64)

        if self.doppler_max_hz == 0.0:
            destination[:] = source
        else:
            frequency_hz = self._frequency_hz(indices)
            phase_steps = (_TWO_PI / self.samp_rate) * frequency_hz
            phases = self._phase_rad + np.cumsum(phase_steps)
            rotator = np.exp(1j * phases).astype(np.complex64)
            np.multiply(source, rotator, out=destination)
            self._phase_rad = float(np.remainder(phases[-1], _TWO_PI))

        self._sample_index += count
        return count


class _PhaseNoiseRandomWalk(gr.sync_block):
    """Her örnekte Gauss artımlı random-walk faz gürültüsü uygula."""

    def __init__(self, phase_noise_std, random_seed):
        """Faz artımı standart sapmasını radyan/örnek cinsinden ayarla."""
        gr.sync_block.__init__(
            self,
            name="LEO phase-noise random walk",
            in_sig=[np.complex64],
            out_sig=[np.complex64],
        )
        self.phase_noise_std = _require_nonnegative("phase_noise_std", phase_noise_std)
        self._rng = np.random.default_rng(int(random_seed))
        self._phase_rad = 0.0

    def work(self, input_items, output_items):
        """Random-walk fazını ilerlet ve kompleks örneklere uygula."""
        source = input_items[0]
        destination = output_items[0]
        count = len(destination)

        if self.phase_noise_std == 0.0:
            destination[:] = source
            return count

        increments = self._rng.normal(0.0, self.phase_noise_std, count)
        phases = self._phase_rad + np.cumsum(increments)
        rotator = np.exp(1j * phases).astype(np.complex64)
        np.multiply(source, rotator, out=destination)
        self._phase_rad = float(np.remainder(phases[-1], _TWO_PI))
        return count


class _LogNormalScintillation(gr.sync_block):
    """Alçak geçiren Gauss dB sürecinden log-normal genlik sönümlemesi üret."""

    def __init__(self, samp_rate, scintillation_std_db, cutoff_hz, random_seed):
        """Scintillation dB sapmasını ve yavaş değişim bant genişliğini ayarla."""
        gr.sync_block.__init__(
            self,
            name="LEO log-normal scintillation",
            in_sig=[np.complex64],
            out_sig=[np.complex64],
        )
        self.samp_rate = _require_positive("samp_rate", samp_rate)
        self.scintillation_std_db = _require_nonnegative(
            "scintillation_std_db", scintillation_std_db
        )
        self.cutoff_hz = _require_positive("scintillation_cutoff_hz", cutoff_hz)
        self._rng = np.random.default_rng(int(random_seed))

        # Birinci dereceden alçak geçiren AR(1); ölçek durağan dB std'sini korur.
        self._alpha = math.exp(-_TWO_PI * self.cutoff_hz / self.samp_rate)
        self._innovation_scale = math.sqrt(1.0 - self._alpha**2)
        self._filter_state = np.zeros(1, dtype=np.float64)

    def work(self, input_items, output_items):
        """Yavaş log-normal genlik katsayısını kompleks sinyale uygula."""
        source = input_items[0]
        destination = output_items[0]
        count = len(destination)

        if self.scintillation_std_db == 0.0:
            destination[:] = source
            return count

        innovations = self._rng.normal(0.0, self.scintillation_std_db, count)
        fading_db, self._filter_state = signal.lfilter(
            [self._innovation_scale],
            [1.0, -self._alpha],
            innovations,
            zi=self._filter_state,
        )
        amplitude = np.power(10.0, fading_db / 20.0).astype(np.float32)
        np.multiply(source, amplitude, out=destination)
        return count


class leo_channel_model(gr.hier_block2):
    """Yol kaybı, Doppler, faz gürültüsü, scintillation ve AWGN kanalı."""

    def __init__(
        self,
        samp_rate=params.samp_rate,
        t_sys_kelvin=params.t_sys_kelvin,
        signal_bandwidth_hz=params.signal_bandwidth_hz,
        phase_noise_std=params.phase_noise_std,
        doppler_max_hz=params.doppler_max_hz,
        doppler_profile=params.doppler_profile,
        scintillation_std_db=params.scintillation_std_db,
        path_loss_db=params.path_loss_db,
        doppler_pass_duration_s=params.doppler_pass_duration_s,
        scintillation_cutoff_hz=params.scintillation_cutoff_hz,
        random_seed=params.channel_random_seed,
    ):
        """LEO kanal etkilerini fiziksel parametreleriyle oluştur ve bağla."""
        gr.hier_block2.__init__(
            self,
            "LEO Channel Model",
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
        )

        self.samp_rate = _require_positive("samp_rate", samp_rate)
        self.t_sys_kelvin = _require_nonnegative("t_sys_kelvin", t_sys_kelvin)
        self.signal_bandwidth_hz = _require_nonnegative(
            "signal_bandwidth_hz", signal_bandwidth_hz
        )
        if self.signal_bandwidth_hz > self.samp_rate:
            raise ValueError("signal_bandwidth_hz samp_rate değerini aşmamalı")
        self.phase_noise_std = _require_nonnegative("phase_noise_std", phase_noise_std)
        self.doppler_max_hz = _require_nonnegative("doppler_max_hz", doppler_max_hz)
        self.scintillation_std_db = _require_nonnegative(
            "scintillation_std_db", scintillation_std_db
        )
        self.path_loss_db = _require_nonnegative("path_loss_db", path_loss_db)
        self.doppler_profile = str(doppler_profile)
        self.doppler_pass_duration_s = _require_positive(
            "doppler_pass_duration_s", doppler_pass_duration_s
        )
        self.scintillation_cutoff_hz = _require_positive(
            "scintillation_cutoff_hz", scintillation_cutoff_hz
        )
        self.random_seed = int(random_seed)
        if self.random_seed < 0:
            raise ValueError("random_seed sıfırdan büyük/eşit olmalı")

        self.path_loss_linear = 10.0 ** (-self.path_loss_db / 20.0)
        self.noise_power_w = (
            BOLTZMANN_J_PER_K * self.t_sys_kelvin * self.signal_bandwidth_hz
        )
        self.noise_voltage = math.sqrt(self.noise_power_w)

        self.path_loss = blocks.multiply_const_cc(self.path_loss_linear)
        self.doppler = _TimeVaryingDoppler(
            self.samp_rate,
            self.doppler_max_hz,
            self.doppler_profile,
            self.doppler_pass_duration_s,
        )
        self.phase_noise = _PhaseNoiseRandomWalk(
            self.phase_noise_std, self.random_seed
        )
        self.scintillation = _LogNormalScintillation(
            self.samp_rate,
            self.scintillation_std_db,
            self.scintillation_cutoff_hz,
            self.random_seed + 1,
        )
        self.noise_source = analog.noise_source_c(
            analog.GR_GAUSSIAN, self.noise_voltage, self.random_seed + 2
        )
        self.add_awgn = blocks.add_cc()

        self.connect(
            self,
            self.path_loss,
            self.doppler,
            self.phase_noise,
            self.scintillation,
            (self.add_awgn, 0),
            self,
        )
        self.connect(self.noise_source, (self.add_awgn, 1))
