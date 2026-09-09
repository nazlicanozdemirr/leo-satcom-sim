"""Exercise PN63 quadrant resolution and report frame-level BER outliers."""

import argparse
from dataclasses import dataclass

import numpy as np

from analysis.sync_quality import frame_error_profile
from config import params
from rx.rx_full_chain import DECODER_TYPES, codeword_bits_for, run_full_simulation


@dataclass(frozen=True)
class AmbiguitySpotCheck:
    """Summary of one decoder/Eb-No coherent ambiguity run."""

    decoder_type: str
    ebno_db: float
    requested_frames: int
    detected_frames: int
    high_ber_frames: int
    high_ber_rate: float
    aggregate_pre_fec_ber: float
    rotation_histogram: tuple


def run_spot_check(
    decoder_type,
    ebno_db,
    frames=500,
    carrier_phase_offset_rad=np.pi / 2.0,
    random_seed=params.tx_random_seed,
):
    """Run coherent RX and count frames whose codeword BER exceeds 0.3."""
    result = run_full_simulation(
        ebno_db,
        decoder_type=decoder_type,
        payload_frames=int(frames),
        random_seed=int(random_seed),
        doppler_max_hz=0.0,
        phase_noise_std=0.0,
        scintillation_std_db=0.0,
        differential_coding=False,
        carrier_phase_offset_rad=float(carrier_phase_offset_rad),
    )
    frame_bits = (
        params.preamble_len
        + codeword_bits_for(decoder_type)
        + params.frame_pad_bits
    )
    profile = frame_error_profile(result, frame_bits)
    frame_ber = profile.bit_errors / profile.bits_per_frame
    high_ber = int(np.count_nonzero(frame_ber > 0.3))
    histogram = np.bincount(
        result.selected_phase_rotations.astype(np.int64), minlength=4
    )[:4]
    detected = int(len(frame_ber))
    return AmbiguitySpotCheck(
        decoder_type=str(decoder_type),
        ebno_db=float(ebno_db),
        requested_frames=int(frames),
        detected_frames=detected,
        high_ber_frames=high_ber,
        high_ber_rate=high_ber / detected if detected else float("nan"),
        aggregate_pre_fec_ber=float(result.pre_fec_ber),
        rotation_histogram=tuple(int(value) for value in histogram),
    )


def main():
    """Print low-SNR spot-check rows for all coherent decoder paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=500)
    parser.add_argument("--ebno", type=float, nargs="+", default=[-2.0, 0.0])
    parser.add_argument("--decoders", nargs="+", default=list(DECODER_TYPES))
    parser.add_argument("--phase-quadrant", type=int, default=1)
    arguments = parser.parse_args()
    phase = (int(arguments.phase_quadrant) % 4) * np.pi / 2.0
    for ebno_db in arguments.ebno:
        for decoder_type in arguments.decoders:
            report = run_spot_check(
                decoder_type,
                ebno_db,
                frames=arguments.frames,
                carrier_phase_offset_rad=phase,
            )
            print(report)


if __name__ == "__main__":
    main()
