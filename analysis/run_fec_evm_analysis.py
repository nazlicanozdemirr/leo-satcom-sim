"""LDPC/Viterbi BER ve QPSK EVM sonuçlarını CSV olarak üret."""

import argparse
import csv
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).with_name("fec_evm_results.csv")
DECODER_TYPES = ("uncoded", "ldpc", "viterbi")
FIELDNAMES = (
    "ebno_db",
    "decoder_type",
    "pre_fec_ber",
    "post_fec_ber",
    "evm_rms_percent",
    "cluster_-I-Q",
    "cluster_+I-Q",
    "cluster_-I+Q",
    "cluster_+I+Q",
    "decoded_payload_bits",
)


def run_analysis(ebno_values=(0.0, 8.0, 10.0), payload_frames=1_000):
    """Her Eb/No ve decoder çifti için tam zinciri çalıştırıp satırlar üret."""
    from rx.rx_full_chain import run_full_simulation

    rows = []
    for ebno_db in ebno_values:
        for decoder_type in DECODER_TYPES:
            result = run_full_simulation(
                ebno_db=float(ebno_db),
                decoder_type=decoder_type,
                payload_frames=int(payload_frames),
                doppler_max_hz=0.0,
                phase_noise_std=0.0,
                scintillation_std_db=0.0,
            )
            histogram = result.evm.histogram
            rows.append(
                {
                    "ebno_db": result.ebno_db,
                    "decoder_type": result.decoder_type,
                    "pre_fec_ber": result.pre_fec_ber,
                    "post_fec_ber": result.post_fec_ber,
                    "evm_rms_percent": result.evm.evm_rms_percent,
                    "cluster_-I-Q": histogram["-I-Q"],
                    "cluster_+I-Q": histogram["+I-Q"],
                    "cluster_-I+Q": histogram["-I+Q"],
                    "cluster_+I+Q": histogram["+I+Q"],
                    "decoded_payload_bits": len(result.decoded_payload),
                }
            )
    return rows


def write_results(rows, output_path=DEFAULT_OUTPUT):
    """Analiz satırlarını kararlı sütun sırasıyla CSV dosyasına yaz."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return output


def main():
    """Komut satırı seçeneklerini işle, deneyleri çalıştır ve CSV'yi kaydet."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ebno", nargs="+", type=float, default=[0.0, 8.0, 10.0])
    parser.add_argument("--frames", type=int, default=1_000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    rows = run_analysis(arguments.ebno, arguments.frames)
    print(write_results(rows, arguments.output))


if __name__ == "__main__":
    main()
