"""Deterministik tam-rank (3,6)-regular LDPC alist matrisi üreticisi.

Bu geliştirme kodu CCSDS 131.0-B-3 matrisinin kısaltılmış bir kopyası değildir.
MacKay'in düzenli iki-parçalı çizge yapısını izleyen, karşılaştırılabilir ve
tamamen yeniden üretilebilir bir rate-1/2 araştırma kodudur.
"""

import argparse
import random
from pathlib import Path


DEFAULT_OUTPUT = Path(__file__).with_name("ldpc_128_64_regular.alist")
DEFAULT_SEED = 131_003
N_COLS = 128
N_ROWS = 64
COLUMN_WEIGHT = 3
ROW_WEIGHT = 6


def gf2_rank(rows, width):
    """Bit maskeleriyle gösterilen ikili matrisin GF(2) rank değerini bul."""
    work = list(rows)
    rank = 0
    for column in range(width):
        pivot = next(
            (candidate for candidate in range(rank, len(work)) if (work[candidate] >> column) & 1),
            None,
        )
        if pivot is None:
            continue
        work[rank], work[pivot] = work[pivot], work[rank]
        for row in range(len(work)):
            if row != rank and ((work[row] >> column) & 1):
                work[row] ^= work[rank]
        rank += 1
        if rank == len(work):
            break
    return rank


def generate_regular_matrix(seed=DEFAULT_SEED, max_attempts=100_000):
    """Tam-rank, sütun derecesi 3 ve satır derecesi 6 olan H matrisi üret."""
    rng = random.Random(seed)
    row_sockets = [row for row in range(N_ROWS) for _ in range(ROW_WEIGHT)]

    for _ in range(max_attempts):
        rng.shuffle(row_sockets)
        columns = [
            sorted(row_sockets[start : start + COLUMN_WEIGHT])
            for start in range(0, len(row_sockets), COLUMN_WEIGHT)
        ]
        if any(len(set(column)) != COLUMN_WEIGHT for column in columns):
            continue

        row_masks = [0] * N_ROWS
        for column_index, column_rows in enumerate(columns):
            for row_index in column_rows:
                row_masks[row_index] |= 1 << column_index
        if gf2_rank(row_masks, N_COLS) == N_ROWS:
            return columns

    raise RuntimeError(f"{max_attempts} denemede tam-rank düzenli matris üretilemedi")


def format_alist(columns):
    """Sütun komşuluk listesini klasik 1-based alist metnine dönüştür."""
    rows = [[] for _ in range(N_ROWS)]
    for column_index, column_rows in enumerate(columns):
        for row_index in column_rows:
            rows[row_index].append(column_index)

    lines = [
        f"{N_COLS} {N_ROWS}",
        f"{COLUMN_WEIGHT} {ROW_WEIGHT}",
        " ".join([str(COLUMN_WEIGHT)] * N_COLS),
        " ".join([str(ROW_WEIGHT)] * N_ROWS),
    ]
    lines.extend(" ".join(str(row + 1) for row in column) for column in columns)
    lines.extend(" ".join(str(column + 1) for column in row) for row in rows)
    return "\n".join(lines) + "\n"


def write_alist(output_path=DEFAULT_OUTPUT, seed=DEFAULT_SEED):
    """Üretilen LDPC matrisini belirtilen alist dosyasına yaz."""
    output_path = Path(output_path)
    columns = generate_regular_matrix(seed=seed)
    output_path.write_text(format_alist(columns), encoding="ascii")
    return output_path


def main():
    """Komut satırı seçeneklerini işle ve alist dosyasını yeniden üret."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args()
    generated = write_alist(arguments.output, arguments.seed)
    print(generated)


if __name__ == "__main__":
    main()

