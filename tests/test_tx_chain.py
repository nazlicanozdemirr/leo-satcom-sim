"""Faz 2 LDPC ve TX çerçeveleme doğrulama testleri."""

import unittest
from pathlib import Path

import numpy as np

from config import params
from data.generate_ldpc_alist import gf2_rank
from tx.framing import FRAME_BITS, PN63_BITS, frame_codeword


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALIST_PATH = PROJECT_ROOT / "data" / "ldpc_128_64_regular.alist"

try:
    from gnuradio import blocks, fec, gr
except ImportError:
    blocks = None
    fec = None
    gr = None


def _parse_alist(path):
    """Test için alist dosyasını sütun ve satır komşuluklarına ayır."""
    lines = Path(path).read_text(encoding="ascii").splitlines()
    n_cols, n_rows = (int(value) for value in lines[0].split())
    max_col_weight, max_row_weight = (int(value) for value in lines[1].split())
    col_weights = [int(value) for value in lines[2].split()]
    row_weights = [int(value) for value in lines[3].split()]
    column_lines = lines[4 : 4 + n_cols]
    row_lines = lines[4 + n_cols : 4 + n_cols + n_rows]
    columns = [
        [int(value) - 1 for value in line.split()[: col_weights[index]]]
        for index, line in enumerate(column_lines)
    ]
    rows = [
        [int(value) - 1 for value in line.split()[: row_weights[index]]]
        for index, line in enumerate(row_lines)
    ]
    return n_cols, n_rows, max_col_weight, max_row_weight, columns, rows


class TestTxChain(unittest.TestCase):
    """LDPC boyutlarını ve PN63 frame yerleşimini doğrula."""

    def test_alist_is_full_rank_regular_rate_half(self):
        """Alist matrisinin tam-rank (3,6)-regular (128,64) olduğunu doğrula."""
        n_cols, n_rows, max_cw, max_rw, columns, rows = _parse_alist(ALIST_PATH)
        self.assertEqual((n_cols, n_cols - n_rows), (128, 64))
        self.assertEqual((max_cw, max_rw), (3, 6))
        self.assertTrue(all(len(column) == 3 for column in columns))
        self.assertTrue(all(len(row) == 6 for row in rows))
        row_masks = [sum(1 << column for column in row) for row in rows]
        self.assertEqual(gf2_rank(row_masks, n_cols), n_rows)

    def test_preamble_correlation_peaks_at_frame_start(self):
        """PN63 korelasyon tepesinin frame'in sıfırıncı bitinde olduğunu doğrula."""
        codeword = tuple((index * 5 + 1) % 2 for index in range(params.ldpc_n_short))
        frame = np.asarray(frame_codeword(codeword), dtype=np.int8)
        preamble = np.asarray(PN63_BITS, dtype=np.int8)
        bipolar_frame = 2 * frame - 1
        bipolar_preamble = 2 * preamble - 1
        correlation = np.correlate(bipolar_frame, bipolar_preamble, mode="valid")

        self.assertEqual(len(frame), FRAME_BITS)
        self.assertEqual(int(np.argmax(correlation)), 0)
        self.assertEqual(int(correlation[0]), params.preamble_len)
        np.testing.assert_array_equal(frame[: params.preamble_len], preamble)

    @unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
    def test_gnuradio_ldpc_encoder_outputs_128_bits(self):
        """GNU Radio LDPC encoder'ın bir 64-bit bloktan 128 bit ürettiğini doğrula."""
        payload = [index & 1 for index in range(params.ldpc_k_short)]
        flowgraph = gr.top_block()
        source = blocks.vector_source_b(payload, repeat=False)
        encoder_object = fec.ldpc_encoder_make(str(ALIST_PATH))
        encoder = fec.extended_encoder(
            encoder_obj_list=encoder_object,
            threading=None,
            puncpat="11",
        )
        sink = blocks.vector_sink_b()
        flowgraph.connect(source, encoder, sink)
        flowgraph.run()
        codeword = np.asarray(sink.data(), dtype=np.uint8)

        self.assertEqual(len(codeword), params.ldpc_n_short)
        self.assertTrue(np.all(codeword <= 1))
        _, _, _, _, _, rows = _parse_alist(ALIST_PATH)
        syndrome = [int(np.bitwise_xor.reduce(codeword[row])) for row in rows]
        self.assertFalse(any(syndrome), "GNU Radio codeword H·c = 0 koşulunu sağlamıyor")


if __name__ == "__main__":
    unittest.main()
