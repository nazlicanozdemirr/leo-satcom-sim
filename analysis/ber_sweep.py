"""Uncoded, LDPC ve Viterbi QPSK için batched Monte Carlo BER taraması."""

import argparse
import csv
from dataclasses import dataclass
import math
from pathlib import Path

from config import params


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_PATH = PROJECT_ROOT / "analysis" / "results" / "ber_results.csv"
RESULT_COLUMNS = (
    "ebno_db",
    "ber_uncoded",
    "ber_ldpc",
    "ber_viterbi",
    "n_bits_simulated",
)
SIMULATION_MODES = ("uncoded", "ldpc", "viterbi")
QPSK_BITS_PER_SYMBOL = 2


@dataclass(frozen=True)
class MonteCarloPoint:
    """Tek Eb/No ve decoder için birikimli Monte Carlo sonucunu tut."""

    ebno_db: float
    decoder_type: str
    errors: int
    bits: int
    ber: float
    frames: int
    batches: int
    noise_power: float


def code_rate_for_mode(decoder_type):
    """Uncoded için 1, iki rate-1/2 FEC yolu için ortak kod oranını döndür."""
    normalized = str(decoder_type).strip().lower()
    if normalized not in SIMULATION_MODES:
        raise ValueError(f"decoder_type {SIMULATION_MODES} değerlerinden biri olmalı")
    return 1.0 if normalized == "uncoded" else float(params.ldpc_code_rate)


def noise_power_for_ebno(
    ebno_db,
    code_rate,
    samp_rate=params.samp_rate,
    sym_rate=params.sym_rate,
    sps=params.sps,
    bits_per_symbol=QPSK_BITS_PER_SYMBOL,
):
    """Bilgi-bit Eb/No'dan kompleks örnek başına AWGN gücünü hesapla.

    Birim enerjili QPSK için ``Eb = Es/(R*log2(M))`` ve örneklenmiş kompleks
    gürültü için ``sigma² = N0*Fs/Rs`` kullanılır. Böylece sonuç
    ``sps/(R*2*EbNo)`` olur; ``Fs/Rs`` ile yapılandırılmış ``sps`` ayrıca
    birbirine karşı doğrulanır.
    """
    samp_rate = float(samp_rate)
    sym_rate = float(sym_rate)
    sps = float(sps)
    code_rate = float(code_rate)
    bits_per_symbol = float(bits_per_symbol)
    if samp_rate <= 0.0 or sym_rate <= 0.0 or sps <= 0.0:
        raise ValueError("samp_rate, sym_rate ve sps pozitif olmalı")
    if not 0.0 < code_rate <= 1.0 or bits_per_symbol <= 0.0:
        raise ValueError("code_rate (0,1], bits_per_symbol pozitif olmalı")
    derived_sps = samp_rate / sym_rate
    if not math.isclose(derived_sps, sps, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("sps, samp_rate/sym_rate ile uyuşmuyor")
    ebno_linear = 10.0 ** (float(ebno_db) / 10.0)
    n0 = 1.0 / (code_rate * bits_per_symbol * ebno_linear)
    return n0 * derived_sps


def simulate_ber_point(
    ebno_db,
    decoder_type,
    min_bits,
    batch_frames=params.monte_carlo_batch_frames,
    random_seed=params.tx_random_seed,
):
    """Bir Eb/No noktasında batch'leri hedef bilgi-bit sayısına kadar biriktir."""
    from rx.rx_full_chain import run_full_simulation

    decoder_type = str(decoder_type).strip().lower()
    code_rate = code_rate_for_mode(decoder_type)
    noise_power = noise_power_for_ebno(ebno_db, code_rate)
    min_bits = int(min_bits)
    batch_frames = int(batch_frames)
    if min_bits < 1 or batch_frames < 1:
        raise ValueError("min_bits ve batch_frames en az 1 olmalı")

    errors = 0
    bits = 0
    frames = 0
    batches = 0
    max_batches = 4 * math.ceil(min_bits / (batch_frames * params.ldpc_k_short)) + 8
    while bits < min_bits:
        # Her batch acquisition ve filtre geçicilerini aşacak kadar uzun tutulur.
        frames_this_batch = batch_frames
        result = run_full_simulation(
            ebno_db=float(ebno_db),
            decoder_type=decoder_type,
            payload_frames=frames_this_batch,
            random_seed=int(random_seed) + batches * 10_007,
            doppler_max_hz=0.0,
            phase_noise_std=0.0,
            scintillation_std_db=0.0,
            noise_power_w=noise_power,
            differential_coding=params.performance_differential_coding,
        )
        if result.post_fec_bits <= 0:
            print(
                f"UYARI: {decoder_type} Eb/No={ebno_db} batch={batches}: "
                "frame kilidi yok, bağımsız sonraki batch deneniyor."
            )
        else:
            errors += int(result.post_fec_errors)
            bits += int(result.post_fec_bits)
        frames += frames_this_batch
        batches += 1
        if batches > max_batches:
            raise RuntimeError("Monte Carlo hedef bit sayısına makul batch sayısında ulaşamadı")

    return MonteCarloPoint(
        ebno_db=float(ebno_db),
        decoder_type=decoder_type,
        errors=errors,
        bits=bits,
        ber=errors / bits,
        frames=frames,
        batches=batches,
        noise_power=noise_power,
    )


def run_ber_sweep(
    ebno_values=params.ebno_sweep_db,
    min_bits=params.min_bits_per_point,
    batch_frames=params.monte_carlo_batch_frames,
    include_viterbi=True,
    random_seed=params.tx_random_seed,
    decoder_types=None,
):
    """Tüm Eb/No noktalarında uncoded, LDPC ve isteğe bağlı Viterbi BER ölç."""
    rows = []
    measurements = []
    if decoder_types is None:
        modes = ["uncoded", "ldpc"] + (["viterbi"] if include_viterbi else [])
    else:
        modes = [str(value).strip().lower() for value in decoder_types]
        if not modes or any(value not in SIMULATION_MODES for value in modes):
            raise ValueError(f"decoder_types yalnız {SIMULATION_MODES} değerlerini içerebilir")
        if "uncoded" not in modes:
            raise ValueError("BER CSV referansı için decoder_types içinde uncoded gerekli")
    for point_index, ebno_db in enumerate(ebno_values):
        point_results = {}
        for mode_index, decoder_type in enumerate(modes):
            measurement = simulate_ber_point(
                ebno_db,
                decoder_type,
                min_bits,
                batch_frames=batch_frames,
                random_seed=int(random_seed) + point_index * 1_000_003 + mode_index,
            )
            measurements.append(measurement)
            point_results[decoder_type] = measurement
            print(
                f"Eb/No={float(ebno_db):5.1f} dB {decoder_type:8s}: "
                f"BER={measurement.ber:.6g} "
                f"({measurement.errors}/{measurement.bits}, "
                f"noise={measurement.noise_power:.6g})"
            )
        rows.append(
            {
                "ebno_db": float(ebno_db),
                "ber_uncoded": point_results["uncoded"].ber,
                "ber_ldpc": (
                    point_results["ldpc"].ber if "ldpc" in point_results else ""
                ),
                "ber_viterbi": (
                    point_results["viterbi"].ber
                    if "viterbi" in point_results
                    else ""
                ),
                "n_bits_simulated": min(result.bits for result in point_results.values()),
            }
        )
    return rows, measurements


def write_ber_results(rows, output_path=DEFAULT_RESULTS_PATH):
    """BER tarama satırlarını istenen sabit CSV şemasıyla kaydet."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return output


def main():
    """Quick veya full Monte Carlo modunu seçip BER CSV'sini üret."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--quick",
        action="store_true",
        help=f"hızlı koşu ({params.quick_bits_per_point} bit/nokta, varsayılan)",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help=f"ölçüm koşusu ({params.min_bits_per_point} bit/nokta)",
    )
    parser.add_argument("--bits", type=int, help="quick/full bit sayısını geçersiz kıl")
    parser.add_argument("--ebno", nargs="+", type=float, default=params.ebno_sweep_db)
    parser.add_argument("--batch-frames", type=int, default=params.monte_carlo_batch_frames)
    parser.add_argument("--no-viterbi", action="store_true")
    parser.add_argument(
        "--decoders",
        nargs="+",
        choices=SIMULATION_MODES,
        help="kalibrasyon için ör. '--decoders uncoded'; varsayılan tüm yollar",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    arguments = parser.parse_args()
    requested_bits = arguments.bits or (
        params.min_bits_per_point if arguments.full else params.quick_bits_per_point
    )
    rows, _ = run_ber_sweep(
        arguments.ebno,
        min_bits=requested_bits,
        batch_frames=arguments.batch_frames,
        include_viterbi=not arguments.no_viterbi,
        decoder_types=arguments.decoders,
    )
    print(write_ber_results(rows, arguments.output))


if __name__ == "__main__":
    main()
