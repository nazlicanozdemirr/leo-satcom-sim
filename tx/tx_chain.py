"""LDPC kodlu, diferansiyel Gray-QPSK GNU Radio TX zinciri."""

import math
from pathlib import Path

import numpy as np
from gnuradio import blocks, digital, fec, filter, gr
from gnuradio.filter import firdes

from config import params
from tx.framing import FRAME_BITS, PN63_BITS, frame_codeword


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIST_PATH = PROJECT_ROOT / "data" / "ldpc_128_64_regular.alist"


def _validate_payload_bits(payload_bits):
    """Payload'u ikili byte dizisine çevir ve 64-bit blok hizasını doğrula."""
    payload = np.asarray(payload_bits, dtype=np.uint8).reshape(-1)
    if len(payload) == 0 or len(payload) % params.ldpc_k_short != 0:
        raise ValueError(f"payload uzunluğu {params.ldpc_k_short} bitin katı olmalı")
    if np.any(payload > 1):
        raise ValueError("payload yalnız 0 ve 1 değerlerinden oluşmalı")
    return payload


def _read_alist_dimensions(alist_path):
    """Alist başlığından kod uzunluğu n ve kontrol satırı sayısı m'yi oku."""
    with Path(alist_path).open("r", encoding="ascii") as alist_file:
        first_line = alist_file.readline().split()
    if len(first_line) != 2:
        raise ValueError(f"geçersiz alist başlığı: {alist_path}")
    return tuple(int(value) for value in first_line)


def make_rrc_taps(
    samp_rate=params.samp_rate,
    sym_rate=params.sym_rate,
    sps=params.sps,
    rolloff=params.rrc_rolloff,
    ntaps=params.rrc_ntaps,
):
    """SPS kazançlı interpolating root-raised-cosine filtre taplerini üret."""
    return firdes.root_raised_cosine(sps, samp_rate, sym_rate, rolloff, ntaps)


def unit_energy_qpsk_points(constellation=None):
    """GNU Radio QPSK noktalarını ortalama sembol enerjisi Es=1 olacak şekilde ölçekle."""
    constellation = constellation or digital.constellation_qpsk().base()
    points = np.asarray(constellation.points(), dtype=np.complex64)
    mean_energy = float(np.mean(np.abs(points.astype(np.complex128)) ** 2))
    if not np.isfinite(mean_energy) or mean_energy <= 0.0:
        raise ValueError("QPSK constellation enerjisi pozitif ve sonlu olmalı")
    return tuple((points / math.sqrt(mean_energy)).tolist())


class _FramePreambleInserter(gr.basic_block):
    """Her 128-bit LDPC codeword'u PN63 + codeword + pad çerçevesine dönüştür."""

    def __init__(self):
        """Sabit 128/192 frame oranlı GNU Radio basic block'u oluştur."""
        gr.basic_block.__init__(
            self,
            name="PN63 frame builder",
            in_sig=[np.uint8],
            out_sig=[np.uint8],
        )
        self.set_relative_rate(FRAME_BITS / params.ldpc_n_short)
        self.set_output_multiple(FRAME_BITS)

    def forecast(self, noutput_items, ninputs):
        """İstenen çıktı için gerekli tam LDPC codeword girdi sayısını bildir."""
        frame_count = max(1, math.ceil(noutput_items / FRAME_BITS))
        return [frame_count * params.ldpc_n_short] * ninputs

    def general_work(self, input_items, output_items):
        """Tam codeword'ları preamble ve QPSK hizalama bitiyle çerçevele."""
        source = input_items[0]
        destination = output_items[0]
        input_frames = len(source) // params.ldpc_n_short
        output_frames = len(destination) // FRAME_BITS
        frame_count = min(input_frames, output_frames)

        for frame_index in range(frame_count):
            input_start = frame_index * params.ldpc_n_short
            output_start = frame_index * FRAME_BITS
            codeword = source[input_start : input_start + params.ldpc_n_short]
            destination[output_start : output_start + FRAME_BITS] = frame_codeword(codeword)

        consumed = frame_count * params.ldpc_n_short
        self.consume(0, consumed)
        return frame_count * FRAME_BITS


class tx_chain(gr.hier_block2):
    """64-bit payload bloklarını RRC şekillendirilmiş QPSK örneklerine çevir."""

    def __init__(
        self,
        alist_path=DEFAULT_ALIST_PATH,
        samp_rate=params.samp_rate,
        sym_rate=params.sym_rate,
        sps=params.sps,
        rrc_rolloff=params.rrc_rolloff,
        rrc_ntaps=params.rrc_ntaps,
    ):
        """Yeniden kullanılabilir LDPC → frame → DQPSK → RRC hier block kur."""
        gr.hier_block2.__init__(
            self,
            "LEO TX Chain",
            gr.io_signature(1, 1, gr.sizeof_char),
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
        )
        self.alist_path = Path(alist_path).resolve()
        self.samp_rate = float(samp_rate)
        self.sym_rate = float(sym_rate)
        self.sps = int(sps)
        self.rrc_rolloff = float(rrc_rolloff)
        self.rrc_ntaps = int(rrc_ntaps)

        if not self.alist_path.is_file():
            raise FileNotFoundError(f"LDPC alist bulunamadı: {self.alist_path}")
        alist_n, alist_m = _read_alist_dimensions(self.alist_path)
        if (alist_n, alist_n - alist_m) != (
            params.ldpc_n_short,
            params.ldpc_k_short,
        ):
            raise ValueError("alist boyutları config/params.py ile uyuşmuyor")
        if self.sps != self.samp_rate // self.sym_rate:
            raise ValueError("sps, samp_rate // sym_rate değerine eşit olmalı")
        if self.rrc_ntaps % 2 != 1:
            raise ValueError("rrc_ntaps tek sayı olmalı")

        self.ldpc_encoder_object = fec.ldpc_encoder_make(str(self.alist_path))
        self.ldpc_encoder = fec.extended_encoder(
            encoder_obj_list=self.ldpc_encoder_object,
            threading=None,
            puncpat="11",
        )
        self.frame_builder = _FramePreambleInserter()
        self.pack_dibits = blocks.pack_k_bits_bb(2)

        self.qpsk_constellation = digital.constellation_qpsk().base()
        self.qpsk_points = unit_energy_qpsk_points(self.qpsk_constellation)
        # Gray bit etiketlerini diferansiyel faz artımı indekslerine dönüştürür.
        self.pre_diff_mapper = digital.map_bb(self.qpsk_constellation.pre_diff_code())
        # Costas loop'un dört olası mutlak fazını alıcıda mod-4 farkla giderir.
        self.differential_encoder = digital.diff_encoder_bb(4)
        self.qpsk_mapper = digital.chunks_to_symbols_bc(
            self.qpsk_points, 1
        )

        self.rrc_taps = make_rrc_taps(
            self.samp_rate,
            self.sym_rate,
            self.sps,
            self.rrc_rolloff,
            self.rrc_ntaps,
        )
        self.rrc_filter = filter.interp_fir_filter_ccf(self.sps, self.rrc_taps)

        self.connect(
            self,
            self.ldpc_encoder,
            self.frame_builder,
            self.pack_dibits,
            self.pre_diff_mapper,
            self.differential_encoder,
            self.qpsk_mapper,
            self.rrc_filter,
            self,
        )


class tx_chain_top_block(gr.top_block):
    """Sonlu payload'u TX zincirinden geçirip bellekte yakalayan top block."""

    def __init__(self, payload_bits, **tx_parameters):
        """Payload kaynağı, yeniden kullanılabilir TX hier block ve sink oluştur."""
        gr.top_block.__init__(self, "LEO TX Chain Runner", catch_exceptions=True)
        payload = _validate_payload_bits(payload_bits)
        self.source = blocks.vector_source_b(payload.tolist(), repeat=False)
        self.transmitter = tx_chain(**tx_parameters)
        self.sink = blocks.vector_sink_c()
        self.connect(self.source, self.transmitter, self.sink)

    def output_samples(self):
        """Top block çalıştıktan sonra yakalanan complex64 TX örneklerini döndür."""
        return np.asarray(self.sink.data(), dtype=np.complex64)


def generate_tx_samples(payload_bits, **tx_parameters):
    """Bir veya daha çok 64-bit payload frame'i için TX örnekleri üret."""
    flowgraph = tx_chain_top_block(payload_bits, **tx_parameters)
    flowgraph.run()
    return flowgraph.output_samples()


__all__ = [
    "DEFAULT_ALIST_PATH",
    "PN63_BITS",
    "generate_tx_samples",
    "make_rrc_taps",
    "unit_energy_qpsk_points",
    "tx_chain",
    "tx_chain_top_block",
]
