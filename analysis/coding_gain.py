"""BER CSV'sinden hedef-BER coding gain hesabı ve yarı-log grafik üretimi."""

import argparse
import csv
import math
from pathlib import Path

import numpy as np

from config import params


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "analysis" / "results"
DEFAULT_BER_PATH = DEFAULT_RESULTS_DIR / "ber_results.csv"
DEFAULT_GAIN_PATH = DEFAULT_RESULTS_DIR / "coding_gain.txt"
DEFAULT_PLOT_PATH = DEFAULT_RESULTS_DIR / "ber_curves.png"
CURVE_COLUMNS = {
    "uncoded": "ber_uncoded",
    "ldpc": "ber_ldpc",
    "viterbi": "ber_viterbi",
}


def theoretical_qpsk_ber(ebno_db):
    """Gray-QPSK/AWGN teorik BER'ini ``0.5*erfc(sqrt(Eb/No))`` ile hesapla."""
    values = np.asarray(ebno_db, dtype=np.float64)
    linear = 10.0 ** (values / 10.0)
    result = 0.5 * np.vectorize(math.erfc, otypes=[np.float64])(np.sqrt(linear))
    return float(result) if result.ndim == 0 else result


def load_ber_results(csv_path=DEFAULT_BER_PATH):
    """BER CSV satırlarını sayısal NumPy kolonlarına dönüştür."""
    path = Path(csv_path)
    with path.open("r", newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    if not rows:
        raise ValueError(
            f"BER sonucu yok: önce 'python -m analysis.ber_sweep --full' çalıştırın ({path})"
        )
    data = {
        "ebno_db": np.asarray([float(row["ebno_db"]) for row in rows]),
        "n_bits_simulated": np.asarray(
            [int(float(row["n_bits_simulated"])) for row in rows], dtype=np.int64
        ),
    }
    for curve_name, column in CURVE_COLUMNS.items():
        data[curve_name] = np.asarray(
            [float(row[column]) if row.get(column, "") else np.nan for row in rows],
            dtype=np.float64,
        )
    return data


def ebno_at_target(ebno_db, ber, target_ber=params.target_ber, n_bits=None):
    """Hedef BER kesişimini log10(BER) üzerinde doğrusal interpolasyonla bul."""
    x = np.asarray(ebno_db, dtype=np.float64).reshape(-1)
    y = np.asarray(ber, dtype=np.float64).reshape(-1)
    if len(x) != len(y) or len(x) < 2:
        raise ValueError("interpolasyon için eşit uzunlukta en az iki nokta gerekli")
    if not 0.0 < target_ber < 1.0:
        raise ValueError("target_ber (0,1) aralığında olmalı")
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    if n_bits is None:
        zero_floor = np.full_like(y, np.finfo(np.float64).tiny)
    else:
        counts = np.asarray(n_bits, dtype=np.float64).reshape(-1)[order]
        if len(counts) != len(y) or np.any(counts <= 0):
            raise ValueError("n_bits pozitif ve BER dizisiyle aynı uzunlukta olmalı")
        # Sıfır gözlenen hata için Jeffreys-benzeri 0.5/N çizim/interpolasyon tabanı.
        zero_floor = 0.5 / counts
    y = np.where(y == 0.0, zero_floor, y)
    valid = np.isfinite(x) & np.isfinite(y) & (y > 0.0) & (y < 1.0)
    x = x[valid]
    y = y[valid]
    if len(x) < 2:
        return float("nan")

    target_log = math.log10(target_ber)
    for index in range(len(x) - 1):
        first_log = math.log10(y[index])
        second_log = math.log10(y[index + 1])
        if (first_log - target_log) * (second_log - target_log) > 0.0:
            continue
        if math.isclose(first_log, second_log):
            return float((x[index] + x[index + 1]) / 2.0)
        fraction = (target_log - first_log) / (second_log - first_log)
        return float(x[index] + fraction * (x[index + 1] - x[index]))
    return float("nan")


def uncoded_theory_deviation_db(ebno_db, simulated_ber):
    """Her pozitif uncoded BER noktasının teorik eşdeğer Eb/No sapmasını hesapla."""
    x = np.asarray(ebno_db, dtype=np.float64)
    ber = np.asarray(simulated_ber, dtype=np.float64)
    valid = np.isfinite(x) & np.isfinite(ber) & (ber > 0.0) & (ber < 0.5)
    equivalent = np.full_like(ber, np.nan)
    for index in np.flatnonzero(valid):
        low_db, high_db = -30.0, 30.0
        for _ in range(80):
            midpoint = (low_db + high_db) / 2.0
            if theoretical_qpsk_ber(midpoint) > ber[index]:
                low_db = midpoint
            else:
                high_db = midpoint
        equivalent[index] = (low_db + high_db) / 2.0
    return x - equivalent


def analyze_coding_gain(
    ber_path=DEFAULT_BER_PATH,
    gain_path=DEFAULT_GAIN_PATH,
    plot_path=DEFAULT_PLOT_PATH,
    target_ber=params.target_ber,
):
    """Coding gain'i hesapla, teori sanity check yap ve metin/PNG sonuçlarını yaz."""
    data = load_ber_results(ber_path)
    crossings = {
        name: ebno_at_target(
            data["ebno_db"], values, target_ber, data["n_bits_simulated"]
        )
        for name, values in ((name, data[name]) for name in CURVE_COLUMNS)
        if np.count_nonzero(np.isfinite(values)) >= 2
    }
    uncoded_target = crossings.get("uncoded", float("nan"))
    ldpc_target = crossings.get("ldpc", float("nan"))
    coding_gain_db = uncoded_target - ldpc_target

    deviations = uncoded_theory_deviation_db(data["ebno_db"], data["uncoded"])
    finite_deviations = np.abs(deviations[np.isfinite(deviations)])
    maximum_deviation = (
        float(np.max(finite_deviations)) if len(finite_deviations) else float("nan")
    )
    warning = ""
    if np.isfinite(maximum_deviation) and maximum_deviation > 1.0:
        warning = (
            f"UYARI: uncoded QPSK eğrisi teoriden en fazla "
            f"{maximum_deviation:.3f} dB sapıyor (>1 dB); "
            "senkronizasyon/Eb-No ölçeklemesini kontrol edin."
        )
        print(warning)

    lines = [
        f"target_ber={target_ber:.6g}",
        f"ebno_uncoded_at_target_db={uncoded_target:.6g}",
        f"ebno_ldpc_at_target_db={ldpc_target:.6g}",
        f"coding_gain_db={coding_gain_db:.6g}",
    ]
    if "viterbi" in crossings:
        lines.append(f"ebno_viterbi_at_target_db={crossings['viterbi']:.6g}")
    lines.append(f"max_uncoded_theory_deviation_db={maximum_deviation:.6g}")
    if warning:
        lines.append(warning)
    report = "\n".join(lines) + "\n"
    print(report, end="")

    gain_output = Path(gain_path)
    plot_output = Path(plot_path)
    gain_output.parent.mkdir(parents=True, exist_ok=True)
    plot_output.parent.mkdir(parents=True, exist_ok=True)
    gain_output.write_text(report, encoding="utf-8")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(9, 6))
    colors = {"uncoded": "tab:blue", "ldpc": "tab:orange", "viterbi": "tab:green"}
    labels = {"uncoded": "Uncoded (sim)", "ldpc": "LDPC", "viterbi": "Viterbi K=7"}
    for name in CURVE_COLUMNS:
        values = data[name]
        valid = np.isfinite(values)
        if np.any(valid):
            display_values = np.where(
                values[valid] == 0.0,
                0.5 / data["n_bits_simulated"][valid],
                values[valid],
            )
            axis.semilogy(
                data["ebno_db"][valid],
                display_values,
                marker="o",
                color=colors[name],
                label=labels[name],
            )
    dense_ebno = np.linspace(data["ebno_db"].min(), data["ebno_db"].max(), 500)
    axis.semilogy(
        dense_ebno,
        theoretical_qpsk_ber(dense_ebno),
        "k--",
        linewidth=1.5,
        label="Uncoded QPSK theory",
    )
    axis.axhline(target_ber, color="0.4", linestyle=":", label=f"Target BER={target_ber:g}")
    if np.isfinite(coding_gain_db):
        axis.annotate(
            "",
            xy=(ldpc_target, target_ber),
            xytext=(uncoded_target, target_ber),
            arrowprops={"arrowstyle": "<->", "color": "crimson", "lw": 2},
        )
        axis.text(
            (ldpc_target + uncoded_target) / 2.0,
            target_ber * 1.6,
            f"Coding gain = {coding_gain_db:.2f} dB",
            color="crimson",
            ha="center",
        )
    axis.set_xlabel("Eb/No (dB, information bit)")
    axis.set_ylabel("Bit Error Rate")
    axis.set_title("LEO Satcom QPSK BER and Coding Gain")
    axis.grid(True, which="both", linestyle=":", alpha=0.7)
    axis.legend()
    figure.tight_layout()
    figure.savefig(plot_output, dpi=160)
    plt.close(figure)
    return coding_gain_db, crossings, maximum_deviation


def main():
    """CSV, hedef BER ve çıktı yollarını komut satırından işle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_BER_PATH)
    parser.add_argument("--target-ber", type=float, default=params.target_ber)
    parser.add_argument("--output", type=Path, default=DEFAULT_GAIN_PATH)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT_PATH)
    arguments = parser.parse_args()
    analyze_coding_gain(
        arguments.input,
        arguments.output,
        arguments.plot,
        arguments.target_ber,
    )


if __name__ == "__main__":
    main()
