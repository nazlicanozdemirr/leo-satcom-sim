"""Compare the simulated (128,64) LDPC BER with digitized literature curves."""

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import params


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_PATH = PROJECT_ROOT / "data" / "literature_reference.csv"
DEFAULT_BER_PATH = PROJECT_ROOT / "analysis" / "results" / "ber_results.csv"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "analysis" / "results"
DEFAULT_PLOT_PATH = DEFAULT_RESULTS_DIR / "literature_comparison.png"
DEFAULT_TABLE_PATH = DEFAULT_RESULTS_DIR / "literature_difference.csv"
DEFAULT_SUMMARY_PATH = DEFAULT_RESULTS_DIR / "literature_comparison.txt"
TARGET_ERROR_RATES = (1e-2, 1e-3, 1e-4, 1e-5)
WATERFALL_RATES = (1e-2, 1e-3, 1e-4)


@dataclass(frozen=True)
class LiteratureComparisonResult:
    """Paths and aggregate class-consistency statistics from the comparison."""

    plot_path: Path
    table_path: Path
    summary_path: Path
    tolerance_db: float
    worst_waterfall_median_offset_db: float
    class_consistent: bool


def log_error_crossing(ebno_db, error_rate, target):
    """Interpolate Eb/No at a target error rate, linearly in log10(error)."""
    x = np.asarray(ebno_db, dtype=np.float64)
    y = np.asarray(error_rate, dtype=np.float64)
    valid = np.isfinite(x) & np.isfinite(y) & (y > 0.0)
    x, y = x[valid], y[valid]
    order = np.argsort(x)
    x, y = x[order], y[order]
    log_target = np.log10(float(target))
    for index in range(len(x) - 1):
        left, right = np.log10(y[index]), np.log10(y[index + 1])
        if min(left, right) <= log_target <= max(left, right) and left != right:
            fraction = (log_target - left) / (right - left)
            return float(x[index] + fraction * (x[index + 1] - x[index]))
    return float("nan")


def load_literature(path=DEFAULT_REFERENCE_PATH):
    """Load digitized error curves and the separate Shannon-limit record."""
    curves = {}
    shannon_limit = float(params.shannon_limit_r05_db)
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["metric"] == "limit":
                shannon_limit = float(row["ebno_db"])
                continue
            curves.setdefault(row["source_label"], []).append(
                (float(row["ebno_db"]), float(row["error_rate"]), row["metric"])
            )
    return curves, shannon_limit


def load_simulated_ldpc(path=DEFAULT_BER_PATH):
    """Read non-zero LDPC BER samples from the completed Monte Carlo sweep."""
    ebno, ber = [], []
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            value = float(row["ber_ldpc"])
            ebno.append(float(row["ebno_db"]))
            ber.append(value)
    return np.asarray(ebno), np.asarray(ber)


def compare_curves(sim_ebno, sim_ber, literature_curves, tolerance_db):
    """Build target-rate offsets; waterfall medians define class consistency."""
    rows = []
    source_medians = {}
    for label, samples in literature_curves.items():
        reference_ebno = np.asarray([sample[0] for sample in samples])
        reference_error = np.asarray([sample[1] for sample in samples])
        metric = samples[0][2]
        waterfall_offsets = []
        for target in TARGET_ERROR_RATES:
            simulated = log_error_crossing(sim_ebno, sim_ber, target)
            reference = log_error_crossing(reference_ebno, reference_error, target)
            offset = simulated - reference
            in_waterfall = target in WATERFALL_RATES
            if in_waterfall and np.isfinite(offset):
                waterfall_offsets.append(abs(offset))
            rows.append(
                {
                    "source_label": label,
                    "reference_metric": metric,
                    "target_error_rate": target,
                    "simulated_ber_ebno_db": simulated,
                    "reference_ebno_db": reference,
                    "sim_minus_reference_db": offset,
                    "region": "waterfall" if in_waterfall else "tail_diagnostic",
                    "within_tolerance": (
                        bool(abs(offset) <= tolerance_db)
                        if np.isfinite(offset)
                        else False
                    ),
                }
            )
        source_medians[label] = float(np.median(waterfall_offsets))
    return rows, source_medians


def write_difference_table(rows, path=DEFAULT_TABLE_PATH):
    """Write per-source target-rate Eb/No differences to CSV."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return output


def plot_comparison(
    sim_ebno,
    sim_ber,
    literature_curves,
    shannon_limit_db,
    output_path=DEFAULT_PLOT_PATH,
):
    """Plot simulated BER, digitized CER/BLER curves and the capacity wall."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(10, 6.5))
    positive = sim_ber > 0.0
    axis.semilogy(
        sim_ebno[positive],
        sim_ber[positive],
        "o-",
        linewidth=2.2,
        label="This project: (128,64) regular LDPC BER",
    )
    styles = ("s--", "^--", "d--")
    for style, (label, samples) in zip(styles, literature_curves.items()):
        x = [sample[0] for sample in samples]
        y = [sample[1] for sample in samples]
        metric = samples[0][2]
        axis.semilogy(x, y, style, linewidth=1.5, markersize=5, label=f"{label} ({metric})")
    axis.axvline(
        shannon_limit_db,
        color="black",
        linestyle=":",
        linewidth=1.7,
        label=f"Rate-1/2 Shannon limit ({shannon_limit_db:.2f} dB)",
    )
    axis.set_xlim(0.0, 10.2)
    axis.set_ylim(1e-6, 1.0)
    axis.set_xlabel("Eb/N0 (dB)")
    axis.set_ylabel("Error rate (BER versus digitized CER/BLER)")
    axis.set_title("Short-block (128,64) regular LDPC class comparison")
    axis.grid(True, which="both", linestyle=":", alpha=0.55)
    axis.legend(fontsize=8, loc="lower left")
    axis.text(
        0.99,
        0.98,
        "Literature CER/BLER >= same-code BER;\nshown dB gaps are conservative lower bounds.",
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=8,
    )
    figure.tight_layout()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=180)
    plt.close(figure)
    return output


def analyze_literature(
    reference_path=DEFAULT_REFERENCE_PATH,
    ber_path=DEFAULT_BER_PATH,
    tolerance_db=params.literature_tolerance_db,
):
    """Run comparison and persist its plot, difference table and summary."""
    curves, shannon_limit = load_literature(reference_path)
    sim_ebno, sim_ber = load_simulated_ldpc(ber_path)
    rows, medians = compare_curves(sim_ebno, sim_ber, curves, float(tolerance_db))
    table_path = write_difference_table(rows)
    plot_path = plot_comparison(sim_ebno, sim_ber, curves, shannon_limit)
    worst_median = max(medians.values())
    consistent = bool(worst_median <= float(tolerance_db))
    summary_lines = [
        f"literature_tolerance_db={float(tolerance_db):.6g}",
        f"shannon_limit_r05_db={shannon_limit:.6g}",
        f"worst_waterfall_median_offset_db={worst_median:.6g}",
        f"class_consistent={str(consistent).lower()}",
        "metric_gap_interpretation=conservative_lower_bound",
    ]
    summary_lines.extend(
        f"{label}_waterfall_median_abs_offset_db={value:.6g}"
        for label, value in medians.items()
    )
    DEFAULT_SUMMARY_PATH.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))
    print(table_path)
    print(plot_path)
    return LiteratureComparisonResult(
        plot_path=plot_path,
        table_path=table_path,
        summary_path=DEFAULT_SUMMARY_PATH,
        tolerance_db=float(tolerance_db),
        worst_waterfall_median_offset_db=worst_median,
        class_consistent=consistent,
    )


def main():
    """CLI entry point for the literature class-consistency analysis."""
    analyze_literature()


if __name__ == "__main__":
    main()
