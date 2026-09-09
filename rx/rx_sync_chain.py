"""TX, LEO kanal ve QPSK senkronizasyon zincirinin parametrik top block'u."""

import math
from dataclasses import dataclass

import numpy as np
from gnuradio import blocks, digital, filter, gr
from gnuradio.filter import firdes

from analysis.lock_detector import LockDecision, detect_lock
from channel.leo_channel_model import BOLTZMANN_J_PER_K, leo_channel_model
from config import params
from tx.tx_chain import make_rrc_taps, tx_chain


QPSK_BITS_PER_SYMBOL = 2


def ebno_to_noise_power(
    ebno_db,
    sps=params.sps,
    bits_per_symbol=QPSK_BITS_PER_SYMBOL,
    code_rate=1.0,
):
    """Bilgi-bit Eb/No'yu code rate duyarlı kompleks örnek gürültü gücüne çevir."""
    ebno_linear = 10.0 ** (float(ebno_db) / 10.0)
    if ebno_linear <= 0.0 or sps <= 0 or bits_per_symbol <= 0 or code_rate <= 0.0:
        raise ValueError(
            "Eb/No, sps, bits_per_symbol ve code_rate pozitif olmalı"
        )
    if code_rate > 1.0:
        raise ValueError("code_rate 1 değerini aşamaz")
    return float(sps) / (
        float(bits_per_symbol) * float(code_rate) * ebno_linear
    )


def ebno_to_effective_temperature(
    ebno_db,
    signal_bandwidth_hz=params.signal_bandwidth_hz,
    sps=params.sps,
    code_rate=1.0,
):
    """Hedef Eb/No gürültüsünü kanalın kTB modeli için eşdeğer T_sys'e dönüştür."""
    if signal_bandwidth_hz <= 0.0:
        raise ValueError("signal_bandwidth_hz pozitif olmalı")
    noise_power = ebno_to_noise_power(
        ebno_db, sps=sps, code_rate=code_rate
    )
    return noise_power / (BOLTZMANN_J_PER_K * float(signal_bandwidth_hz))


def make_rx_rrc_taps(
    samp_rate=params.samp_rate,
    sym_rate=params.sym_rate,
    rolloff=params.rrc_rolloff,
    ntaps=params.rrc_ntaps,
):
    """TX filtresiyle aynı şekle sahip birim kazançlı matched-RRC tapleri üret."""
    sps = float(samp_rate) / float(sym_rate)
    tx_taps = np.asarray(
        make_rrc_taps(samp_rate, sym_rate, sps, rolloff, ntaps),
        dtype=np.float64,
    )
    rx_taps = np.asarray(
        firdes.root_raised_cosine(1.0, samp_rate, sym_rate, rolloff, ntaps),
        dtype=np.float64,
    )
    decision_gain = float(np.dot(tx_taps, rx_taps))
    if not np.isfinite(decision_gain) or decision_gain == 0.0:
        raise ValueError("TX+RX RRC karar örneği kazancı sonlu ve sıfırdan farklı olmalı")
    return (rx_taps / decision_gain).tolist()


def coarse_qpsk_evm(symbols, discard_fraction=0.20):
    """Başlangıcı atıp en yakın ideal QPSK noktasına RMS mesafeyi hesapla."""
    received = np.asarray(symbols, dtype=np.complex64).reshape(-1)
    if not 0.0 <= discard_fraction < 1.0:
        raise ValueError("discard_fraction [0, 1) aralığında olmalı")
    received = received[int(len(received) * discard_fraction) :]
    if len(received) == 0:
        raise ValueError("EVM için sembol bulunamadı")

    # Sabit kanal/filtre kazancını ideal bir AGC gibi RMS=1 olacak şekilde kaldır.
    rms = math.sqrt(float(np.mean(np.abs(received.astype(np.complex128)) ** 2)))
    if rms == 0.0:
        raise ValueError("sıfır güçlü sembollerde EVM hesaplanamaz")
    received = received / rms
    level = 1.0 / math.sqrt(2.0)
    ideal = np.asarray(
        [
            complex(-level, -level),
            complex(level, -level),
            complex(-level, level),
            complex(level, level),
        ],
        dtype=np.complex64,
    )
    distances = np.min(np.abs(received[:, None] - ideal[None, :]), axis=1)
    return float(math.sqrt(np.mean(distances.astype(np.float64) ** 2)))


@dataclass(frozen=True)
class SyncResult:
    """Bir senkronizasyon koşusunun örneklerini ve kalite metriklerini tut."""

    synchronized_symbols: np.ndarray
    costas_frequency: np.ndarray
    costas_phase: np.ndarray
    costas_error: np.ndarray
    timing_error: np.ndarray
    decoded_bits: np.ndarray
    evm_rms: float
    lock: LockDecision


class rx_sync_chain(gr.hier_block2):
    """Matched RRC, 4. derece Costas, Gardner timing ve differential RX bloğu."""

    def __init__(
        self,
        samp_rate=params.samp_rate,
        sym_rate=params.sym_rate,
        sps=params.sps,
        rrc_rolloff=params.rrc_rolloff,
        rrc_ntaps=params.rrc_ntaps,
        costas_loop_bw=params.costas_loop_bw,
        timing_loop_bw=params.timing_loop_bw,
        differential=True,
    ):
        """Tek kompleks girişten bit çıkışı ve senkronizasyon metrikleri üret."""
        gr.hier_block2.__init__(
            self,
            "LEO RX Synchronization Chain",
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature.makev(
                6,
                6,
                [
                    gr.sizeof_char,
                    gr.sizeof_gr_complex,
                    gr.sizeof_float,
                    gr.sizeof_float,
                    gr.sizeof_float,
                    gr.sizeof_float,
                ],
            ),
        )
        self.samp_rate = float(samp_rate)
        self.sym_rate = float(sym_rate)
        self.sps = float(sps)
        self.costas_loop_bw = float(costas_loop_bw)
        self.timing_loop_bw = float(timing_loop_bw)
        self.differential = bool(differential)

        self.qpsk_constellation = digital.constellation_qpsk().base()
        self.rrc_taps = make_rx_rrc_taps(
            self.samp_rate, self.sym_rate, rrc_rolloff, rrc_ntaps
        )
        self.matched_filter = filter.fir_filter_ccf(1, self.rrc_taps)
        self.costas_loop = digital.costas_loop_cc(self.costas_loop_bw, 4, False)
        self.symbol_sync = digital.symbol_sync_cc(
            digital.TED_GARDNER,
            self.sps,
            self.timing_loop_bw,
            1.0,
            1.0,
            1.5,
            1,
            self.qpsk_constellation,
            digital.IR_MMSE_8TAP,
            128,
            [],
        )
        self.constellation_decoder = digital.constellation_decoder_cb(
            self.qpsk_constellation
        )
        # Faz 2 mod-4 encoder'ın karşılığı: mutlak Costas fazı artık gerekli değildir.
        self.differential_decoder = digital.diff_decoder_bb(4)
        pre_diff_code = list(self.qpsk_constellation.pre_diff_code())
        inverse_pre_diff = [pre_diff_code.index(value) for value in range(4)]
        self.inverse_pre_diff_mapper = digital.map_bb(inverse_pre_diff)
        self.unpack_dibits = blocks.unpack_k_bits_bb(2)

        self.connect(self, self.matched_filter, self.costas_loop, self.symbol_sync)
        if self.differential:
            self.connect(
                (self.symbol_sync, 0),
                self.constellation_decoder,
                self.differential_decoder,
                self.inverse_pre_diff_mapper,
                self.unpack_dibits,
                (self, 0),
            )
        else:
            self.connect(
                (self.symbol_sync, 0),
                self.constellation_decoder,
                self.unpack_dibits,
                (self, 0),
            )
        self.connect((self.symbol_sync, 0), (self, 1))
        self.connect((self.costas_loop, 1), (self, 2))
        self.connect((self.costas_loop, 2), (self, 3))
        self.connect((self.costas_loop, 3), (self, 4))
        self.connect((self.symbol_sync, 1), (self, 5))


class rx_sync_chain_top_block(gr.top_block):
    """Sonlu payload için TX → kanal → RX senkronizasyon deneyini çalıştır."""

    def __init__(
        self,
        ebno_db=6.0,
        payload_frames=1_000,
        random_seed=params.tx_random_seed,
        doppler_max_hz=8_000.0,
        phase_noise_std=0.0,
        scintillation_std_db=0.0,
        costas_loop_bw=params.costas_loop_bw,
        timing_loop_bw=params.timing_loop_bw,
    ):
        """Eb/No ve kanal etkileri dışarıdan ayarlanabilen deney top block'unu kur."""
        gr.top_block.__init__(self, "LEO RX Synchronization Simulation", catch_exceptions=True)
        if payload_frames < 1:
            raise ValueError("payload_frames en az 1 olmalı")
        self.ebno_db = float(ebno_db)
        rng = np.random.default_rng(int(random_seed))
        payload = rng.integers(
            0,
            2,
            size=int(payload_frames) * params.ldpc_k_short,
            dtype=np.uint8,
        )

        effective_t_sys = ebno_to_effective_temperature(
            self.ebno_db, code_rate=params.ldpc_code_rate
        )
        self.source = blocks.vector_source_b(payload.tolist(), repeat=False)
        self.transmitter = tx_chain()
        self.channel = leo_channel_model(
            samp_rate=params.samp_rate,
            t_sys_kelvin=effective_t_sys,
            signal_bandwidth_hz=params.signal_bandwidth_hz,
            phase_noise_std=phase_noise_std,
            doppler_max_hz=doppler_max_hz,
            doppler_profile="linear",
            scintillation_std_db=scintillation_std_db,
            path_loss_db=0.0,
            random_seed=int(random_seed) + 100,
        )
        self.receiver = rx_sync_chain(
            costas_loop_bw=costas_loop_bw,
            timing_loop_bw=timing_loop_bw,
        )

        self.bits_sink = blocks.vector_sink_b()
        self.symbols_sink = blocks.vector_sink_c()
        self.frequency_sink = blocks.vector_sink_f()
        self.phase_sink = blocks.vector_sink_f()
        self.costas_error_sink = blocks.vector_sink_f()
        self.timing_error_sink = blocks.vector_sink_f()

        self.connect(self.source, self.transmitter, self.channel, self.receiver)
        self.connect((self.receiver, 0), self.bits_sink)
        self.connect((self.receiver, 1), self.symbols_sink)
        self.connect((self.receiver, 2), self.frequency_sink)
        self.connect((self.receiver, 3), self.phase_sink)
        self.connect((self.receiver, 4), self.costas_error_sink)
        self.connect((self.receiver, 5), self.timing_error_sink)

    def result(self):
        """Çalışan top block'un sink verilerini SyncResult nesnesine dönüştür."""
        symbols = np.asarray(self.symbols_sink.data(), dtype=np.complex64)
        costas_error = np.asarray(self.costas_error_sink.data(), dtype=np.float32)
        timing_error = np.asarray(self.timing_error_sink.data(), dtype=np.float32)
        lock = detect_lock(costas_error, timing_error)
        return SyncResult(
            synchronized_symbols=symbols,
            costas_frequency=np.asarray(self.frequency_sink.data(), dtype=np.float32),
            costas_phase=np.asarray(self.phase_sink.data(), dtype=np.float32),
            costas_error=costas_error,
            timing_error=timing_error,
            decoded_bits=np.asarray(self.bits_sink.data(), dtype=np.uint8),
            evm_rms=coarse_qpsk_evm(symbols),
            lock=lock,
        )


def run_sync_simulation(ebno_db=6.0, **simulation_parameters):
    """Belirtilen Eb/No'da uçtan uca senkronizasyon simülasyonu çalıştır."""
    flowgraph = rx_sync_chain_top_block(ebno_db=ebno_db, **simulation_parameters)
    flowgraph.run()
    return flowgraph.result()


__all__ = [
    "SyncResult",
    "coarse_qpsk_evm",
    "ebno_to_effective_temperature",
    "ebno_to_noise_power",
    "run_sync_simulation",
    "rx_sync_chain",
    "rx_sync_chain_top_block",
]
