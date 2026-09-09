"""Preamble ayırma ve seçilebilir LDPC/Viterbi FEC içeren tam QPSK alıcı."""

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from gnuradio import blocks, digital, fec, filter, gr

from analysis.evm_calc import EVMAnalysis, calculate_evm
from channel.leo_channel_model import BOLTZMANN_J_PER_K, leo_channel_model
from config import params
from rx.rx_sync_chain import (
    ebno_to_effective_temperature,
    make_rx_rrc_taps,
    rx_sync_chain,
)
from tx.framing import FRAME_PAD_BITS, PN63_BITS
from tx.tx_chain import DEFAULT_ALIST_PATH, make_rrc_taps, unit_energy_qpsk_points


DECODER_TYPES = ("uncoded", "ldpc", "viterbi")
DEFAULT_PREAMBLE_MAX_ERRORS = 7
QPSK_ROTATION_CORRECTION_PERMUTATIONS = np.asarray(
    [
        [0, 1, 2, 3],
        [2, 0, 3, 1],
        [3, 2, 1, 0],
        [1, 3, 0, 2],
    ],
    dtype=np.uint8,
)


def validate_decoder_type(decoder_type):
    """Decoder seçimini normalize et ve desteklenen üç değerden biri olduğunu doğrula."""
    normalized = str(decoder_type).strip().lower()
    if normalized not in DECODER_TYPES:
        raise ValueError(f"decoder_type {DECODER_TYPES} değerlerinden biri olmalı")
    return normalized


def codeword_bits_for(decoder_type):
    """Uncoded ve rate-1/2 kodlu yolların frame başına bit sayısını döndür."""
    normalized = validate_decoder_type(decoder_type)
    return (
        params.ldpc_k_short
        if normalized == "uncoded"
        else params.ldpc_n_short
    )


def code_rate_for(decoder_type):
    """Eb/No dönüşümü için seçilen yolun bilgi-bit kod oranını döndür."""
    return 1.0 if validate_decoder_type(decoder_type) == "uncoded" else float(
        params.ldpc_code_rate
    )


def _make_encoder_object(decoder_type, alist_path):
    """Uncoded veya seçilen rate-1/2 yol için generic encoder nesnesi oluştur."""
    if decoder_type == "uncoded":
        return None
    if decoder_type == "ldpc":
        return fec.ldpc_encoder_make(str(alist_path))
    return fec.cc_encoder_make(
        params.ldpc_k_short,
        params.viterbi_constraint_length,
        params.viterbi_rate_inverse,
        list(params.viterbi_polynomials),
        0,
        fec.CC_STREAMING,
        False,
    )


def _make_decoder_object(decoder_type, alist_path, max_iterations):
    """Seçilen kod için LDPC belief-propagation veya K=7 Viterbi decoder oluştur."""
    if decoder_type == "ldpc":
        # GNU Radio 3.10'daki ldpc_decoder, sum-product/BP uygular ve
        # ldpc_encoder_make'in alist sistematik-bit permütasyonunu geri alır.
        decoder = fec.ldpc_decoder.make(str(alist_path), int(max_iterations))
        return decoder, None
    decoder = fec.cc_decoder.make(
        params.ldpc_k_short,
        params.viterbi_constraint_length,
        params.viterbi_rate_inverse,
        list(params.viterbi_polynomials),
        0,
        -1,
        fec.CC_STREAMING,
        False,
    )
    return decoder, None


def _make_encoder_block(decoder_type, alist_path):
    """Uncoded copy veya seçilmiş Extended FEC encoder bloğunu oluştur."""
    encoder_object = _make_encoder_object(decoder_type, alist_path)
    if encoder_object is None:
        return encoder_object, blocks.copy(gr.sizeof_char)
    return encoder_object, fec.extended_encoder(
        encoder_obj_list=encoder_object,
        threading=None,
        puncpat="11",
    )


class _PreambleFrameInserter(gr.basic_block):
    """Seçilen codeword boyutuna PN63 ve QPSK hizalama biti ekle."""

    def __init__(self, codeword_bits):
        """Sabit giriş/çıkış frame oranıyla genel PN63 builder oluştur."""
        gr.basic_block.__init__(
            self,
            name="Configurable PN63 frame builder",
            in_sig=[np.uint8],
            out_sig=[np.uint8],
        )
        self.codeword_bits = int(codeword_bits)
        if self.codeword_bits < 1:
            raise ValueError("codeword_bits en az 1 olmalı")
        self.frame_bits = len(PN63_BITS) + self.codeword_bits + FRAME_PAD_BITS
        if self.frame_bits % 2:
            raise ValueError("PN63 frame uzunluğu QPSK dibit sınırına oturmalı")
        self.set_relative_rate(self.frame_bits / self.codeword_bits)
        self.set_output_multiple(self.frame_bits)

    def forecast(self, noutput_items, ninputs):
        """İstenen tam frame çıktısı için gerekli codeword bitlerini bildir."""
        frame_count = max(1, noutput_items // self.frame_bits)
        return [frame_count * self.codeword_bits] * ninputs

    def general_work(self, input_items, output_items):
        """Tam codeword'ları PN63 + codeword + pad düzeninde üret."""
        source = input_items[0]
        destination = output_items[0]
        frame_count = min(
            len(source) // self.codeword_bits,
            len(destination) // self.frame_bits,
        )
        preamble = np.asarray(PN63_BITS, dtype=np.uint8)
        for frame_index in range(frame_count):
            input_start = frame_index * self.codeword_bits
            output_start = frame_index * self.frame_bits
            destination[output_start : output_start + len(PN63_BITS)] = preamble
            codeword_start = output_start + len(PN63_BITS)
            destination[codeword_start : codeword_start + self.codeword_bits] = source[
                input_start : input_start + self.codeword_bits
            ]
            destination[
                codeword_start + self.codeword_bits : output_start + self.frame_bits
            ] = 0
        consumed = frame_count * self.codeword_bits
        self.consume(0, consumed)
        return frame_count * self.frame_bits


class _PreambleCodewordExtractor(gr.basic_block):
    """PN63 korelasyonuyla frame'lerden yapılandırılmış codeword boyutunu ayır."""

    def __init__(
        self,
        codeword_bits=params.ldpc_n_short,
        max_preamble_errors=DEFAULT_PREAMBLE_MAX_ERRORS,
        maintain_fixed_cadence=False,
    ):
        """İzin verilen preamble bit hatasını ve akış durumunu ayarla."""
        gr.basic_block.__init__(
            self,
            name="PN63 frame synchronizer and codeword extractor",
            in_sig=[np.uint8],
            out_sig=[np.uint8],
        )
        self.max_preamble_errors = int(max_preamble_errors)
        self.codeword_bits = int(codeword_bits)
        self.maintain_fixed_cadence = bool(maintain_fixed_cadence)
        if self.codeword_bits < 1:
            raise ValueError("codeword_bits en az 1 olmalı")
        self.frame_bits = len(PN63_BITS) + self.codeword_bits + FRAME_PAD_BITS
        if not 0 <= self.max_preamble_errors < len(PN63_BITS) // 2:
            raise ValueError("max_preamble_errors geçersiz")
        self._threshold = len(PN63_BITS) - self.max_preamble_errors
        self._input_buffer = []
        self._stream_buffer_start = 0
        self._pending_output = deque()
        self._expect_codeword = False
        self._frame_locked = False
        self.frames_detected = 0
        self.frame_start_positions = []
        self.set_output_multiple(self.codeword_bits)
        self.set_relative_rate(self.codeword_bits / self.frame_bits)

    def forecast(self, noutput_items, ninputs):
        """Bekleyen codeword yoksa en az bir yeni bit talep et."""
        return [0 if self._pending_output else 1] * ninputs

    def _search_and_extract(self):
        """Tamponda preamble ara ve tamamlanan codeword'ları çıkış kuyruğuna taşı."""
        preamble = np.asarray(PN63_BITS, dtype=np.uint8)
        while True:
            if not self._expect_codeword:
                if len(self._input_buffer) < len(PN63_BITS):
                    return
                if self._frame_locked and self.maintain_fixed_cadence:
                    # İlk acquisition sonrasında sabit frame uzunluğu, gürültülü bir
                    # preamble yüzünden sonraki payload'ların kaymasını engeller.
                    match_start = 0
                else:
                    latest_start = len(self._input_buffer) - len(PN63_BITS)
                    match_start = None
                    for start in range(latest_start + 1):
                        candidate = self._input_buffer[start : start + len(PN63_BITS)]
                        matches = int(np.count_nonzero(np.asarray(candidate) == preamble))
                        if matches >= self._threshold:
                            match_start = start
                            break
                    if match_start is None:
                        discard = len(self._input_buffer) - (len(PN63_BITS) - 1)
                        del self._input_buffer[:discard]
                        self._stream_buffer_start += discard
                        return
                    self._frame_locked = True
                self.frame_start_positions.append(
                    self._stream_buffer_start + match_start
                )
                discard = match_start + len(PN63_BITS)
                del self._input_buffer[:discard]
                self._stream_buffer_start += discard
                self._expect_codeword = True

            needed = self.codeword_bits + FRAME_PAD_BITS
            if len(self._input_buffer) < needed:
                return
            self._pending_output.extend(self._input_buffer[: self.codeword_bits])
            del self._input_buffer[:needed]
            self._stream_buffer_start += needed
            self.frames_detected += 1
            self._expect_codeword = False

    def general_work(self, input_items, output_items):
        """Yeni bitleri tüket, frame'leri çıkar ve yalnız tam codeword üret."""
        source = input_items[0]
        destination = output_items[0]
        if len(source):
            self._input_buffer.extend(int(bit) & 1 for bit in source)
            self.consume(0, len(source))
            self._search_and_extract()

        available = min(len(self._pending_output), len(destination))
        produced = (available // self.codeword_bits) * self.codeword_bits
        for index in range(produced):
            destination[index] = self._pending_output.popleft()
        return produced


def correct_qpsk_rotation_bits(bits, rotation_quadrants):
    """Dibitleri seçilen 90° Costas rotasyonunun ters permütasyonuyla düzelt."""
    values = np.asarray(bits, dtype=np.uint8).reshape(-1)
    if len(values) % 2:
        raise ValueError("QPSK rotasyon düzeltmesi için bit sayısı çift olmalı")
    quadrant = int(rotation_quadrants)
    if not 0 <= quadrant < 4:
        raise ValueError("rotation_quadrants 0, 1, 2 veya 3 olmalı")
    dibits = values.reshape(-1, 2)
    indices = 2 * dibits[:, 0] + dibits[:, 1]
    corrected = QPSK_ROTATION_CORRECTION_PERMUTATIONS[quadrant, indices]
    output = np.empty(len(values), dtype=np.uint8)
    output[0::2] = corrected >> 1
    output[1::2] = corrected & 1
    return output


class _QPSKPhaseAmbiguityFrameExtractor(gr.basic_block):
    """PN63'ü dört Costas rotasyonunda karşılaştırıp düzeltilmiş codeword çıkar."""

    def __init__(
        self,
        codeword_bits,
        max_preamble_errors=params.phase_resolver_max_preamble_errors,
        min_score_margin=params.phase_resolver_min_score_margin,
    ):
        """Düşük-SNR PN63 skor sınırlarını ve frame durumunu yapılandır."""
        gr.basic_block.__init__(
            self,
            name="PN63 QPSK phase ambiguity resolver",
            in_sig=[np.uint8],
            out_sig=[np.uint8],
        )
        self.codeword_bits = int(codeword_bits)
        self.frame_bits = len(PN63_BITS) + self.codeword_bits + FRAME_PAD_BITS
        self.max_preamble_errors = int(max_preamble_errors)
        self.min_score_margin = int(min_score_margin)
        if self.frame_bits % 2:
            raise ValueError("QPSK frame bit sayısı çift olmalı")
        if not 0 <= self.max_preamble_errors < len(PN63_BITS) // 2:
            raise ValueError("phase resolver preamble hata sınırı geçersiz")
        if self.min_score_margin < 0:
            raise ValueError("phase resolver skor marjı negatif olamaz")
        self._input_buffer = []
        self._stream_buffer_start = 0
        self._pending_output = deque()
        self._acquired = False
        self._tracked_rotation = None
        self.frames_detected = 0
        self.low_confidence_frames = 0
        self.frame_start_positions = []
        self.selected_rotations = []
        self.preamble_error_counts = []
        self.set_output_multiple(self.codeword_bits)
        self.set_relative_rate(self.codeword_bits / self.frame_bits)

    def forecast(self, noutput_items, ninputs):
        """Bekleyen codeword yoksa en az bir yeni bit talep et."""
        return [0 if self._pending_output else 1] * ninputs

    def _discard(self, count):
        """Tampon önekini ve karşılık gelen mutlak bit konumunu birlikte ilerlet."""
        del self._input_buffer[:count]
        self._stream_buffer_start += int(count)

    def _search_and_extract(self):
        """Tam frame adaylarında dört rotasyonu skorlayıp güvenilir olanları çıkar."""
        preamble = np.asarray(PN63_BITS, dtype=np.uint8)
        while True:
            required = self.frame_bits if self._acquired else 2 * self.frame_bits
            if len(self._input_buffer) < required:
                return
            latest_start = len(self._input_buffer) - self.frame_bits
            # The performance path has known symbol timing.  After acquisition,
            # preserve exact frame cadence instead of re-searching noisy payload
            # bits and accidentally inserting/deleting a frame boundary.
            max_start = min(latest_start, 0 if self._acquired else self.frame_bits)
            candidates = []
            for start in range(max_start + 1):
                if (self._stream_buffer_start + start) % 2:
                    continue
                raw_frame = np.asarray(
                    self._input_buffer[start : start + self.frame_bits],
                    dtype=np.uint8,
                )
                corrected_frames = [
                    correct_qpsk_rotation_bits(raw_frame, quadrant)
                    for quadrant in range(4)
                ]
                scores = np.asarray(
                    [
                        np.count_nonzero(frame[: len(preamble)] != preamble)
                        for frame in corrected_frames
                    ],
                    dtype=np.int64,
                )
                order = np.argsort(scores)
                best_rotation = int(order[0])
                margin = int(scores[order[1]] - scores[order[0]])
                candidates.append(
                    (
                        int(scores[best_rotation]),
                        -margin,
                        start,
                        best_rotation,
                        corrected_frames[best_rotation],
                    )
                )
            if not candidates:
                self._discard(2)
                self._acquired = False
                return

            errors, negative_margin, start, rotation, corrected_frame = min(
                candidates, key=lambda candidate: candidate[:4]
            )
            confident = (
                errors <= self.max_preamble_errors
                and -negative_margin >= self.min_score_margin
            )
            if not confident and not self._acquired:
                self._discard(2)
                self._acquired = False
                continue
            if not confident:
                # One unusually noisy PN63 must not delete a whole codeword.
                # Hold the previous quadrant only when the four-way score has no
                # useful margin; otherwise its best rotation can track a slip.
                self.low_confidence_frames += 1
                if (
                    -negative_margin < self.min_score_margin
                    and self._tracked_rotation is not None
                ):
                    rotation = int(self._tracked_rotation)
                    raw_frame = np.asarray(
                        self._input_buffer[start : start + self.frame_bits],
                        dtype=np.uint8,
                    )
                    corrected_frame = correct_qpsk_rotation_bits(
                        raw_frame, rotation
                    )
                    errors = int(
                        np.count_nonzero(
                            corrected_frame[: len(preamble)] != preamble
                        )
                    )

            self.frame_start_positions.append(self._stream_buffer_start + start)
            self.selected_rotations.append(rotation)
            self.preamble_error_counts.append(errors)
            codeword_start = len(PN63_BITS)
            self._pending_output.extend(
                corrected_frame[codeword_start : codeword_start + self.codeword_bits]
            )
            self.frames_detected += 1
            self._discard(start + self.frame_bits)
            self._acquired = True
            self._tracked_rotation = rotation

    def general_work(self, input_items, output_items):
        """Yeni bitleri tamponla ve yalnız tam, fazı çözülmüş codeword'lar üret."""
        source = input_items[0]
        destination = output_items[0]
        if len(source):
            self._input_buffer.extend(int(bit) & 1 for bit in source)
            self.consume(0, len(source))
            self._search_and_extract()
        available = min(len(self._pending_output), len(destination))
        produced = (available // self.codeword_bits) * self.codeword_bits
        for index in range(produced):
            destination[index] = self._pending_output.popleft()
        return produced


class fec_tx_chain(gr.hier_block2):
    """Uncoded, LDPC veya convolutional ortak PN63/DQPSK/RRC verici zinciri."""

    def __init__(
        self,
        decoder_type="ldpc",
        alist_path=DEFAULT_ALIST_PATH,
        differential=None,
    ):
        """Decoder seçimine karşılık gelen encoder ile TX hierarchy kur."""
        gr.hier_block2.__init__(
            self,
            "Selectable FEC TX Chain",
            gr.io_signature(1, 1, gr.sizeof_char),
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
        )
        self.decoder_type = validate_decoder_type(decoder_type)
        self.differential = (
            self.decoder_type != "uncoded"
            if differential is None
            else bool(differential)
        )
        self.codeword_bits = codeword_bits_for(self.decoder_type)
        self.alist_path = Path(alist_path).resolve()
        if self.decoder_type == "ldpc" and not self.alist_path.is_file():
            raise FileNotFoundError(f"LDPC alist bulunamadı: {self.alist_path}")

        self.encoder_object, self.encoder = _make_encoder_block(
            self.decoder_type, self.alist_path
        )
        self.frame_builder = _PreambleFrameInserter(self.codeword_bits)
        self.pack_dibits = blocks.pack_k_bits_bb(2)
        self.constellation = digital.constellation_qpsk().base()
        self.qpsk_points = unit_energy_qpsk_points(self.constellation)
        self.pre_diff_mapper = digital.map_bb(self.constellation.pre_diff_code())
        self.diff_encoder = digital.diff_encoder_bb(4)
        self.mapper = digital.chunks_to_symbols_bc(self.qpsk_points, 1)
        self.rrc = filter.interp_fir_filter_ccf(params.sps, make_rrc_taps())
        self.connect(self, self.encoder, self.frame_builder, self.pack_dibits)
        if not self.differential:
            # Teorik 0.5*erfc(sqrt(Eb/N0)) eğrisi koherent QPSK içindir.
            self.connect(self.pack_dibits, self.mapper)
        else:
            # Kodlu uzay-link yolları Costas loop'un mod-4 belirsizliğini giderir.
            self.connect(
                self.pack_dibits,
                self.pre_diff_mapper,
                self.diff_encoder,
                self.mapper,
            )
        self.connect(self.mapper, self.rrc, self)


class _CoherentPerformanceQPSKReceiver(gr.hier_block2):
    """Known-timing matched filter plus a real fourth-order Costas loop."""

    def __init__(self, costas_loop_bw=params.performance_costas_loop_bw):
        """Produce coherent hard bits, corrected symbols and Costas metrics."""
        gr.hier_block2.__init__(
            self,
            "Coherent Performance QPSK Receiver",
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
        self.constellation = digital.constellation_qpsk().base()
        self.matched_filter = filter.fir_filter_ccf(
            params.sps, make_rx_rrc_taps()
        )
        self.costas_loop = digital.costas_loop_cc(float(costas_loop_bw), 4, False)
        self.constellation_decoder = digital.constellation_decoder_cb(
            self.constellation
        )
        self.unpack_dibits = blocks.unpack_k_bits_bb(2)
        self.zero_timing_error = blocks.multiply_const_ff(0.0)
        self.connect(self, self.matched_filter, self.costas_loop)
        self.connect(
            (self.costas_loop, 0),
            self.constellation_decoder,
            self.unpack_dibits,
            (self, 0),
        )
        self.connect((self.costas_loop, 0), (self, 1))
        self.connect((self.costas_loop, 1), (self, 2))
        self.connect((self.costas_loop, 2), (self, 3))
        self.connect((self.costas_loop, 3), (self, 4))
        self.connect((self.costas_loop, 3), self.zero_timing_error, (self, 5))


class rx_full_chain(gr.hier_block2):
    """Faz 3 senkronizasyonuna PN63 frame ayırma ve seçilebilir FEC decode ekle."""

    def __init__(
        self,
        decoder_type="ldpc",
        alist_path=DEFAULT_ALIST_PATH,
        ldpc_max_iterations=params.ldpc_max_iterations,
        max_preamble_errors=DEFAULT_PREAMBLE_MAX_ERRORS,
        differential=None,
        costas_loop_bw=params.costas_loop_bw,
    ):
        """Kompleks örneklerden payload, sembol ve decode-öncesi codeword üret."""
        gr.hier_block2.__init__(
            self,
            "LEO Full RX Chain",
            gr.io_signature(1, 1, gr.sizeof_gr_complex),
            gr.io_signature.makev(
                3,
                3,
                [gr.sizeof_char, gr.sizeof_gr_complex, gr.sizeof_char],
            ),
        )
        self.decoder_type = validate_decoder_type(decoder_type)
        self.differential = (
            self.decoder_type != "uncoded"
            if differential is None
            else bool(differential)
        )
        self.codeword_bits = codeword_bits_for(self.decoder_type)
        self.alist_path = Path(alist_path).resolve()
        self.ldpc_max_iterations = int(ldpc_max_iterations)
        if self.ldpc_max_iterations < 1:
            raise ValueError("ldpc_max_iterations en az 1 olmalı")

        if self.differential:
            # Reusable link mode retains Gardner timing and differential decoding.
            self.synchronizer = rx_sync_chain(
                differential=True,
                costas_loop_bw=costas_loop_bw,
            )
        else:
            self.synchronizer = _CoherentPerformanceQPSKReceiver()
        self.costas_frequency_sink = blocks.vector_sink_f()
        self.costas_phase_sink = blocks.vector_sink_f()
        self.costas_error_sink = blocks.vector_sink_f()
        self.timing_error_sink = blocks.vector_sink_f()
        self.connect((self.synchronizer, 2), self.costas_frequency_sink)
        self.connect((self.synchronizer, 3), self.costas_phase_sink)
        self.connect((self.synchronizer, 4), self.costas_error_sink)
        self.connect((self.synchronizer, 5), self.timing_error_sink)
        if self.differential:
            self.frame_extractor = _PreambleCodewordExtractor(
                self.codeword_bits,
                max_preamble_errors,
                maintain_fixed_cadence=False,
            )
        else:
            self.frame_extractor = _QPSKPhaseAmbiguityFrameExtractor(
                self.codeword_bits
            )

        self.connect(self, self.synchronizer)
        self.raw_bits_sink = blocks.vector_sink_b()
        self.connect((self.synchronizer, 0), self.raw_bits_sink)
        self.connect((self.synchronizer, 0), self.frame_extractor)
        self.connect((self.frame_extractor, 0), (self, 2))
        if self.decoder_type == "uncoded":
            self.decoder_object = None
            self.ldpc_matrix = None
            self.decoder = None
            self.connect(self.frame_extractor, (self, 0))
        else:
            self.byte_to_float = blocks.char_to_float(1, 1.0)
            # GNU Radio BP metriği: hard bit 0 -> -L, hard bit 1 -> +L.
            metric_magnitude = (
                float(params.ldpc_hard_llr_magnitude)
                if self.decoder_type == "ldpc"
                else 1.0
            )
            if metric_magnitude <= 0.0:
                raise ValueError("FEC hard metrik büyüklüğü pozitif olmalı")
            self.to_bipolar = blocks.multiply_const_ff(2.0 * metric_magnitude)
            self.center_bipolar = blocks.add_const_ff(-metric_magnitude)
            self.decoder_object, self.ldpc_matrix = _make_decoder_object(
                self.decoder_type,
                self.alist_path,
                self.ldpc_max_iterations,
            )
            self.decoder = fec.extended_decoder(
                decoder_obj_list=self.decoder_object,
                threading=None,
                ann=None,
                puncpat="11",
                integration_period=10_000,
            )
            self.connect(
                self.frame_extractor,
                self.byte_to_float,
                self.to_bipolar,
                self.center_bipolar,
                self.decoder,
                (self, 0),
            )
        self.connect((self.synchronizer, 1), (self, 1))


@dataclass(frozen=True)
class FullChainResult:
    """Tam zincirin BER, EVM ve sembol/codeword çıktılarını tut."""

    decoder_type: str
    ebno_db: float
    transmitted_payload: np.ndarray
    transmitted_codewords: np.ndarray
    received_codewords: np.ndarray
    decoded_payload: np.ndarray
    synchronized_symbols: np.ndarray
    costas_frequency: np.ndarray
    costas_phase: np.ndarray
    costas_error: np.ndarray
    timing_error: np.ndarray
    costas_sample_rate_hz: float
    frame_start_positions: np.ndarray
    received_frame_indices: np.ndarray
    selected_phase_rotations: np.ndarray
    preamble_error_counts: np.ndarray
    pre_fec_ber: float
    post_fec_ber: float
    pre_fec_errors: int
    pre_fec_bits: int
    post_fec_errors: int
    post_fec_bits: int
    evm: EVMAnalysis


@dataclass(frozen=True)
class BERMeasurement:
    """Blok hizalamasından sonra hata, bit ve BER değerlerini tut."""

    errors: int
    bits: int
    ber: float
    reference_skip_blocks: int
    received_skip_blocks: int


def measure_block_aligned_ber(
    reference, received, block_size, max_offset_blocks=32
):
    """Kayıp acquisition frame'lerini tolere ederek blok-hizalı BER ölç."""
    expected = np.asarray(reference, dtype=np.uint8).reshape(-1)
    observed = np.asarray(received, dtype=np.uint8).reshape(-1)
    expected = expected[: len(expected) // block_size * block_size]
    observed = observed[: len(observed) // block_size * block_size]
    if len(expected) == 0 or len(observed) == 0:
        return BERMeasurement(0, 0, float("nan"), 0, 0)

    best = None
    limit = int(max_offset_blocks)
    expected_blocks = len(expected) // block_size
    observed_blocks = len(observed) // block_size
    minimum_overlap_blocks = max(1, min(expected_blocks, observed_blocks) - limit)
    for expected_skip in range(min(limit, len(expected) // block_size - 1) + 1):
        for observed_skip in range(min(limit, len(observed) // block_size - 1) + 1):
            left = expected[expected_skip * block_size :]
            right = observed[observed_skip * block_size :]
            count = min(len(left), len(right))
            count = count // block_size * block_size
            if count < minimum_overlap_blocks * block_size:
                continue
            errors = int(np.count_nonzero(left[:count] != right[:count]))
            ber = errors / count
            candidate = (ber, -count, errors, expected_skip, observed_skip)
            if best is None or candidate < best[0]:
                best = (
                    candidate,
                    BERMeasurement(
                        errors,
                        count,
                        ber,
                        expected_skip,
                        observed_skip,
                    ),
                )
    return BERMeasurement(0, 0, float("nan"), 0, 0) if best is None else best[1]


def _block_aligned_ber(reference, received, block_size, max_offset_blocks=32):
    """Geriye uyumluluk için yalnız blok-hizalı BER değerini döndür."""
    return measure_block_aligned_ber(
        reference, received, block_size, max_offset_blocks
    ).ber


def measure_frame_indexed_ber(
    reference,
    received,
    block_size,
    frame_positions,
    frame_bits,
    max_initial_skip=64,
):
    """PN63 başlangıç konumlarıyla kayıp frame'leri atlayarak BER hesapla."""
    expected = np.asarray(reference, dtype=np.uint8).reshape(-1)
    observed = np.asarray(received, dtype=np.uint8).reshape(-1)
    expected = expected[: len(expected) // block_size * block_size]
    observed = observed[: len(observed) // block_size * block_size]
    positions = np.asarray(frame_positions, dtype=np.int64).reshape(-1)
    observed_blocks = len(observed) // block_size
    frame_count = min(observed_blocks, len(positions))
    if len(expected) == 0 or frame_count == 0:
        return BERMeasurement(0, 0, float("nan"), 0, 0)

    expected_blocks = expected.reshape(-1, block_size)
    observed_blocks_array = observed[: frame_count * block_size].reshape(
        -1, block_size
    )
    relative_indices = np.rint(
        (positions[:frame_count] - positions[0]) / float(frame_bits)
    ).astype(np.int64)
    best = None
    for initial_skip in range(min(int(max_initial_skip), len(expected_blocks) - 1) + 1):
        expected_indices = relative_indices + initial_skip
        valid = (expected_indices >= 0) & (expected_indices < len(expected_blocks))
        if not np.any(valid):
            continue
        left = expected_blocks[expected_indices[valid]]
        right = observed_blocks_array[valid]
        errors = int(np.count_nonzero(left != right))
        bits = int(left.size)
        candidate = (errors / bits, -bits, errors, initial_skip)
        if best is None or candidate < best[0]:
            best = (
                candidate,
                BERMeasurement(errors, bits, errors / bits, initial_skip, 0),
            )
    return BERMeasurement(0, 0, float("nan"), 0, 0) if best is None else best[1]


def align_received_frame_indices(
    reference,
    received,
    block_size,
    max_initial_skip=128,
    max_frame_gap=128,
):
    """Alınan codeword'ları Hamming uzaklığıyla monoton TX frame indekslerine hizala."""
    expected = np.asarray(reference, dtype=np.uint8).reshape(-1, block_size)
    observed = np.asarray(received, dtype=np.uint8).reshape(-1, block_size)
    if len(expected) == 0 or len(observed) == 0:
        return np.empty(0, dtype=np.int64)
    indices = []
    previous = -1
    for block in observed:
        start = previous + 1
        span = max_initial_skip if previous < 0 else max_frame_gap
        stop = min(len(expected), start + int(span) + 1)
        if start >= stop:
            break
        distances = np.count_nonzero(expected[start:stop] != block, axis=1)
        selected = start + int(np.argmin(distances))
        indices.append(selected)
        previous = selected
    return np.asarray(indices, dtype=np.int64)


def frame_indices_from_cadence(frame_positions, frame_bits):
    """Map coherent known-timing frame positions to absolute TX frame indices."""
    positions = np.asarray(frame_positions, dtype=np.int64).reshape(-1)
    frame_bits = int(frame_bits)
    if len(positions) == 0:
        return np.empty(0, dtype=np.int64)
    if frame_bits < 1:
        raise ValueError("frame_bits en az 1 olmalı")
    residues = np.mod(positions, frame_bits)
    origin = int(np.bincount(residues, minlength=frame_bits).argmax())
    indices = np.rint((positions - origin) / float(frame_bits)).astype(np.int64)
    return indices[indices >= 0]


def codeword_symbols_from_frames(symbols, frame_positions, codeword_bits):
    """PN63/pad bias'ını dışlayıp tam dibitli codeword QPSK sembollerini seç."""
    values = np.asarray(symbols, dtype=np.complex64).reshape(-1)
    selected = []
    for position in np.asarray(frame_positions, dtype=np.int64).reshape(-1):
        codeword_start_bit = int(position) + params.preamble_len
        codeword_end_bit = codeword_start_bit + int(codeword_bits)
        first_even_bit = codeword_start_bit + (codeword_start_bit % 2)
        last_even_bit = codeword_end_bit - (codeword_end_bit % 2)
        start_symbol = first_even_bit // 2
        stop_symbol = last_even_bit // 2
        if 0 <= start_symbol < stop_symbol <= len(values):
            selected.append(values[start_symbol:stop_symbol])
    return np.concatenate(selected) if selected else np.empty(0, dtype=np.complex64)


class rx_full_chain_top_block(gr.top_block):
    """Seçilebilir FEC ile sonlu TX → kanal → tam RX deneyi."""

    def __init__(
        self,
        ebno_db=8.0,
        decoder_type="ldpc",
        payload_frames=1_000,
        random_seed=params.tx_random_seed,
        doppler_max_hz=0.0,
        phase_noise_std=0.0,
        scintillation_std_db=0.0,
        noise_power_w=None,
        differential_coding=params.performance_differential_coding,
        carrier_phase_offset_rad=0.0,
        costas_loop_bw=params.costas_loop_bw,
    ):
        """Karşılaştırılabilir payload ve kanal parametreleriyle top block kur."""
        gr.top_block.__init__(self, "LEO Full RX Simulation", catch_exceptions=True)
        self.decoder_type = validate_decoder_type(decoder_type)
        self.ebno_db = float(ebno_db)
        self.differential_coding = bool(differential_coding)
        if int(payload_frames) < 1:
            raise ValueError("payload_frames en az 1 olmalı")
        rng = np.random.default_rng(int(random_seed))
        self.payload = rng.integers(
            0,
            2,
            size=int(payload_frames) * params.ldpc_k_short,
            dtype=np.uint8,
        )
        if noise_power_w is None:
            effective_t_sys = ebno_to_effective_temperature(
                self.ebno_db, code_rate=code_rate_for(self.decoder_type)
            )
        else:
            noise_power_w = float(noise_power_w)
            if noise_power_w < 0.0:
                raise ValueError("noise_power_w negatif olamaz")
            effective_t_sys = noise_power_w / (
                BOLTZMANN_J_PER_K * params.signal_bandwidth_hz
            )

        self.source = blocks.vector_source_b(self.payload.tolist(), repeat=False)
        self.transmitter = fec_tx_chain(
            self.decoder_type, differential=differential_coding
        )
        self.reference_encoder_object, self.reference_encoder = _make_encoder_block(
            self.decoder_type, DEFAULT_ALIST_PATH
        )
        self.channel = leo_channel_model(
            samp_rate=params.samp_rate,
            t_sys_kelvin=effective_t_sys,
            signal_bandwidth_hz=params.signal_bandwidth_hz,
            phase_noise_std=phase_noise_std,
            doppler_max_hz=doppler_max_hz,
            doppler_profile="linear",
            scintillation_std_db=scintillation_std_db,
            path_loss_db=0.0,
            random_seed=int(random_seed) + 400,
        )
        self.carrier_phase_rotator = blocks.multiply_const_cc(
            complex(np.exp(1j * float(carrier_phase_offset_rad)))
        )
        self.receiver = rx_full_chain(
            decoder_type=self.decoder_type,
            differential=differential_coding,
            costas_loop_bw=costas_loop_bw,
        )

        self.reference_codeword_sink = blocks.vector_sink_b()
        self.decoded_sink = blocks.vector_sink_b()
        self.symbol_sink = blocks.vector_sink_c()
        self.received_codeword_sink = blocks.vector_sink_b()

        self.connect(
            self.source,
            self.transmitter,
            self.channel,
            self.carrier_phase_rotator,
            self.receiver,
        )
        self.connect(self.source, self.reference_encoder, self.reference_codeword_sink)
        self.connect((self.receiver, 0), self.decoded_sink)
        self.connect((self.receiver, 1), self.symbol_sink)
        self.connect((self.receiver, 2), self.received_codeword_sink)

    def result(self):
        """Sink verilerinden hizalanmış BER ve acquisition-sonrası EVM üret."""
        transmitted_codewords = np.asarray(
            self.reference_codeword_sink.data(), dtype=np.uint8
        )
        received_codewords = np.asarray(
            self.received_codeword_sink.data(), dtype=np.uint8
        )
        decoded = np.asarray(self.decoded_sink.data(), dtype=np.uint8)
        symbols = np.asarray(self.symbol_sink.data(), dtype=np.complex64)
        frame_positions = self.receiver.frame_extractor.frame_start_positions
        codeword_symbols = codeword_symbols_from_frames(
            symbols, frame_positions, self.receiver.codeword_bits
        )
        stable_symbols = (
            codeword_symbols
            if len(codeword_symbols)
            else symbols[int(0.20 * len(symbols)) :]
        )
        costas_frequency = np.asarray(
            self.receiver.costas_frequency_sink.data(), dtype=np.float32
        )
        costas_phase = np.asarray(
            self.receiver.costas_phase_sink.data(), dtype=np.float32
        )
        costas_error = np.asarray(
            self.receiver.costas_error_sink.data(), dtype=np.float32
        )
        timing_error = np.asarray(
            self.receiver.timing_error_sink.data(), dtype=np.float32
        )
        if self.differential_coding:
            frame_indices = align_received_frame_indices(
                transmitted_codewords,
                received_codewords,
                self.receiver.codeword_bits,
            )
        else:
            frame_bits = (
                params.preamble_len
                + self.receiver.codeword_bits
                + params.frame_pad_bits
            )
            frame_indices = frame_indices_from_cadence(
                frame_positions, frame_bits
            )
        received_frame_count = min(
            len(frame_indices), len(received_codewords) // self.receiver.codeword_bits
        )
        transmitted_blocks = transmitted_codewords.reshape(
            -1, self.receiver.codeword_bits
        )
        received_blocks = received_codewords.reshape(
            -1, self.receiver.codeword_bits
        )[:received_frame_count]
        pre_errors = int(
            np.count_nonzero(
                transmitted_blocks[frame_indices[:received_frame_count]]
                != received_blocks
            )
        )
        pre_bits = int(received_blocks.size)
        pre_fec = BERMeasurement(
            pre_errors,
            pre_bits,
            pre_errors / pre_bits if pre_bits else float("nan"),
            int(frame_indices[0]) if len(frame_indices) else 0,
            0,
        )
        decoded_blocks = decoded.reshape(-1, params.ldpc_k_short)
        decoded_frame_count = min(len(frame_indices), len(decoded_blocks))
        payload_blocks = self.payload.reshape(-1, params.ldpc_k_short)
        post_errors = int(
            np.count_nonzero(
                payload_blocks[frame_indices[:decoded_frame_count]]
                != decoded_blocks[:decoded_frame_count]
            )
        )
        post_bits = int(decoded_frame_count * params.ldpc_k_short)
        post_fec = BERMeasurement(
            post_errors,
            post_bits,
            post_errors / post_bits if post_bits else float("nan"),
            int(frame_indices[0]) if len(frame_indices) else 0,
            0,
        )
        return FullChainResult(
            decoder_type=self.decoder_type,
            ebno_db=self.ebno_db,
            transmitted_payload=self.payload.copy(),
            transmitted_codewords=transmitted_codewords,
            received_codewords=received_codewords,
            decoded_payload=decoded,
            synchronized_symbols=symbols,
            costas_frequency=costas_frequency,
            costas_phase=costas_phase,
            costas_error=costas_error,
            timing_error=timing_error,
            costas_sample_rate_hz=(
                float(params.samp_rate)
                if self.differential_coding
                else float(params.sym_rate)
            ),
            frame_start_positions=np.asarray(frame_positions, dtype=np.int64),
            received_frame_indices=frame_indices,
            selected_phase_rotations=np.asarray(
                getattr(self.receiver.frame_extractor, "selected_rotations", []),
                dtype=np.int8,
            ),
            preamble_error_counts=np.asarray(
                getattr(self.receiver.frame_extractor, "preamble_error_counts", []),
                dtype=np.int16,
            ),
            pre_fec_ber=pre_fec.ber,
            post_fec_ber=post_fec.ber,
            pre_fec_errors=pre_fec.errors,
            pre_fec_bits=pre_fec.bits,
            post_fec_errors=post_fec.errors,
            post_fec_bits=post_fec.bits,
            evm=calculate_evm(stable_symbols),
        )


def run_full_simulation(ebno_db=8.0, decoder_type="ldpc", **parameters):
    """Tam zinciri çalıştır ve karşılaştırmaya hazır FullChainResult döndür."""
    flowgraph = rx_full_chain_top_block(
        ebno_db=ebno_db, decoder_type=decoder_type, **parameters
    )
    flowgraph.run()
    return flowgraph.result()


__all__ = [
    "DECODER_TYPES",
    "BERMeasurement",
    "FullChainResult",
    "code_rate_for",
    "codeword_bits_for",
    "fec_tx_chain",
    "run_full_simulation",
    "rx_full_chain",
    "rx_full_chain_top_block",
    "validate_decoder_type",
    "measure_block_aligned_ber",
]
