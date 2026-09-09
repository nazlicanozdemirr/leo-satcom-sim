"""Costas acquisition, cycle-slip ve frame-bazlı ham BER kalite analizi."""

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import params


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_PATH = PROJECT_ROOT / "analysis" / "results" / "costas_trace_8db.png"


@dataclass(frozen=True)
class CycleSlipReport:
    """Phase düzeltme izinde bulunan ayrık sıçramaları ve frame indekslerini tut."""

    event_sample_indices: np.ndarray
    frame_indices: np.ndarray
    total_frames: int

    @property
    def frames_with_slip(self):
        """En az bir cycle slip içeren frame sayısını döndür."""
        return int(len(self.frame_indices))

    @property
    def frame_slip_rate(self):
        """Cycle-slip bulunan frame oranını döndür."""
        return self.frames_with_slip / self.total_frames if self.total_frames else 0.0


@dataclass(frozen=True)
class FrameErrorProfile:
    """Algılanmış frame'lerin başlangıç zamanı ve codeword hata sayılarını tut."""

    start_positions_bits: np.ndarray
    start_times_s: np.ndarray
    transmitted_indices: np.ndarray
    bit_errors: np.ndarray
    bits_per_frame: int


def costas_samples_per_frame(result, frame_bits):
    """Return Costas metric samples in one QPSK frame for this RX architecture."""
    symbols_per_frame = int(frame_bits) / 2.0
    return max(
        1,
        int(round(symbols_per_frame * result.costas_sample_rate_hz / params.sym_rate)),
    )


def detect_cycle_slips(
    phase_rad,
    samples_per_frame,
    threshold_rad=params.cycle_slip_jump_threshold_rad,
    jump_span_samples=params.cycle_slip_jump_span_symbols * params.sps,
):
    """Birkaç semboldeki sarılmış phase değişimi eşik üstündeyse cycle slip bul."""
    phase = np.asarray(phase_rad, dtype=np.float64).reshape(-1)
    phase = phase[np.isfinite(phase)]
    samples_per_frame = int(samples_per_frame)
    jump_span_samples = int(jump_span_samples)
    threshold_rad = float(threshold_rad)
    if samples_per_frame < 1 or jump_span_samples < 1:
        raise ValueError("samples_per_frame ve jump_span_samples en az 1 olmalı")
    if not 0.0 < threshold_rad <= np.pi:
        raise ValueError("threshold_rad (0, pi] aralığında olmalı")
    if len(phase) <= jump_span_samples:
        return CycleSlipReport(
            np.empty(0, dtype=np.int64),
            np.empty(0, dtype=np.int64),
            int(np.ceil(len(phase) / samples_per_frame)),
        )

    phase_jump = np.angle(
        np.exp(1j * (phase[jump_span_samples:] - phase[:-jump_span_samples]))
    )
    candidates = np.flatnonzero(np.abs(phase_jump) >= threshold_rad)
    if len(candidates):
        group_starts = np.r_[0, np.flatnonzero(np.diff(candidates) > jump_span_samples) + 1]
        events = candidates[group_starts] + jump_span_samples
    else:
        events = np.empty(0, dtype=np.int64)
    frame_indices = np.unique(events // samples_per_frame).astype(np.int64)
    return CycleSlipReport(
        event_sample_indices=np.asarray(events, dtype=np.int64),
        frame_indices=frame_indices,
        total_frames=int(np.ceil(len(phase) / samples_per_frame)),
    )


def frame_error_profile(result, frame_bits):
    """PN63 konumlarıyla her alınan codeword'un doğru TX frame hatasını hesapla."""
    from rx.rx_full_chain import codeword_bits_for

    block_size = codeword_bits_for(result.decoder_type)
    transmitted = np.asarray(result.transmitted_codewords, dtype=np.uint8).reshape(
        -1, block_size
    )
    received = np.asarray(result.received_codewords, dtype=np.uint8).reshape(
        -1, block_size
    )
    positions = np.asarray(result.frame_start_positions, dtype=np.int64)[: len(received)]
    transmitted_indices = np.asarray(result.received_frame_indices, dtype=np.int64)[
        : len(received)
    ]
    frame_count = min(len(transmitted_indices), len(received), len(positions))
    transmitted_indices = transmitted_indices[:frame_count]
    received = received[:frame_count]
    positions = positions[:frame_count]
    valid = transmitted_indices < len(transmitted)
    errors = np.count_nonzero(
        transmitted[transmitted_indices[valid]] != received[valid], axis=1
    )
    valid_positions = positions[valid]
    return FrameErrorProfile(
        start_positions_bits=valid_positions,
        start_times_s=valid_positions / (2.0 * params.sym_rate),
        transmitted_indices=transmitted_indices[valid],
        bit_errors=errors.astype(np.int64),
        bits_per_frame=block_size,
    )


def ber_for_mask(profile, mask):
    """Frame maskesindeki toplam codeword bit hatası ve BER'i döndür."""
    selected = np.asarray(mask, dtype=bool)
    if len(selected) != len(profile.bit_errors) or not np.any(selected):
        return 0, 0, float("nan")
    errors = int(np.sum(profile.bit_errors[selected]))
    bits = int(np.count_nonzero(selected) * profile.bits_per_frame)
    return errors, bits, errors / bits


def save_costas_trace(result, output_path=DEFAULT_TRACE_PATH, plot_frames=8):
    """İlk birkaç frame'in ham detector-error ve phase düzeltme izini PNG'ye yaz."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    frame_bits = params.frame_pad_bits + params.preamble_len + params.ldpc_n_short
    samples_per_frame = costas_samples_per_frame(result, frame_bits)
    count = min(len(result.costas_error), int(plot_frames) * samples_per_frame)
    time_ms = np.arange(count, dtype=np.float64) * 1e3 / result.costas_sample_rate_hz
    figure, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(time_ms, result.costas_error[:count], linewidth=0.7)
    axes[0].set_ylabel("Raw detector error")
    axes[0].grid(True, linestyle=":", alpha=0.6)
    axes[1].plot(time_ms, result.costas_phase[:count], linewidth=0.8)
    axes[1].set_ylabel("Phase estimate (rad)")
    axes[1].set_xlabel("Time (ms)")
    axes[1].grid(True, linestyle=":", alpha=0.6)
    figure.suptitle("8 dB Costas trace (first frames)")
    figure.tight_layout()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=160)
    plt.close(figure)
    return output


def main():
    """8 dB differential RX koşusunu warm-up ve cycle-slip sınıflarıyla raporla."""
    from rx.rx_full_chain import run_full_simulation

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ebno", type=float, default=8.0)
    parser.add_argument("--frames", type=int, default=2_000)
    parser.add_argument("--warmup-ms", type=float, default=24.49)
    parser.add_argument("--plot", type=Path, default=DEFAULT_TRACE_PATH)
    arguments = parser.parse_args()
    result = run_full_simulation(
        arguments.ebno,
        decoder_type="ldpc",
        payload_frames=arguments.frames,
        doppler_max_hz=0.0,
        differential_coding=True,
    )
    frame_bits = params.preamble_len + params.ldpc_n_short + params.frame_pad_bits
    samples_per_frame = costas_samples_per_frame(result, frame_bits)
    slips = detect_cycle_slips(result.costas_phase, samples_per_frame)
    profile = frame_error_profile(result, frame_bits)
    warmup = profile.start_times_s < arguments.warmup_ms / 1e3
    rx_frame_indices = profile.start_positions_bits // frame_bits
    slip_mask = np.isin(rx_frame_indices, slips.frame_indices)
    print("before_warmup", ber_for_mask(profile, warmup))
    print("after_warmup", ber_for_mask(profile, ~warmup))
    print("slip_frames", slips.frames_with_slip, slips.total_frames, slips.frame_slip_rate)
    print("with_slip", ber_for_mask(profile, slip_mask))
    print("without_slip", ber_for_mask(profile, ~slip_mask))
    print(save_costas_trace(result, arguments.plot))


if __name__ == "__main__":
    main()
