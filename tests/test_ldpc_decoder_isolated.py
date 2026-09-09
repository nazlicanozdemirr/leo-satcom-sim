"""GNU Radio LDPC decoder'ını RX senkronizasyonundan bağımsız doğrula."""

import math
import unittest

import numpy as np

from config import params

try:
    from gnuradio import blocks, fec, gr
except ImportError:
    gr = None
else:
    from rx.rx_full_chain import _make_encoder_block
    from tx.tx_chain import DEFAULT_ALIST_PATH


@unittest.skipUnless(gr is not None, "GNU Radio 3.10+ kurulu değil")
class TestIsolatedLDPCDecoder(unittest.TestCase):
    """Bilinen codeword üzerine sentetik AWGN ekleyerek LDPC BP yolunu sınar."""

    @staticmethod
    def _encode(payload):
        """64-bit payload bloklarını GNU Radio alist encoder'ıyla kodla."""
        flowgraph = gr.top_block()
        source = blocks.vector_source_b(payload.tolist(), repeat=False)
        _, encoder = _make_encoder_block("ldpc", DEFAULT_ALIST_PATH)
        sink = blocks.vector_sink_b()
        flowgraph.connect(source, encoder, sink)
        flowgraph.run()
        return np.asarray(sink.data(), dtype=np.uint8)

    @staticmethod
    def _decode(metrics):
        """128'lik soft metrik bloklarını GNU Radio LDPC BP decoder'ına ver."""
        flowgraph = gr.top_block()
        source = blocks.vector_source_f(metrics.astype(np.float32).tolist(), repeat=False)
        decoder_object = fec.ldpc_decoder.make(
            str(DEFAULT_ALIST_PATH), params.ldpc_max_iterations
        )
        decoder = fec.extended_decoder(
            decoder_obj_list=decoder_object,
            threading=None,
            ann=None,
            puncpat="11",
            integration_period=10_000,
        )
        sink = blocks.vector_sink_b()
        flowgraph.connect(source, decoder, sink)
        flowgraph.run()
        return np.asarray(sink.data(), dtype=np.uint8)

    def test_soft_awgn_metrics_reduce_ber(self):
        """8 dB bilgi-bit Eb/No eşdeğerinde soft BP'nin BER'i düşürdüğünü doğrula."""
        rng = np.random.default_rng(20_260_903)
        payload = rng.integers(0, 2, 4_000 * params.ldpc_k_short, dtype=np.uint8)
        codeword = self._encode(payload)
        ebno_linear = 10.0 ** (8.0 / 10.0)
        coded_symbol_ebno = params.ldpc_code_rate * ebno_linear
        component_std = math.sqrt(1.0 / (2.0 * coded_symbol_ebno))
        bipolar_codeword = 2.0 * codeword.astype(np.float64) - 1.0
        metrics = bipolar_codeword + rng.normal(
            0.0, component_std, len(codeword)
        )
        hard_bits = (metrics >= 0.0).astype(np.uint8)
        decoded = self._decode(metrics)
        hard_metrics = params.ldpc_hard_llr_magnitude * (
            2.0 * hard_bits.astype(np.float64) - 1.0
        )
        hard_decoded = self._decode(hard_metrics)
        pre_ber = float(np.mean(hard_bits != codeword))
        post_ber = float(np.mean(decoded != payload[: len(decoded)]))
        hard_post_ber = float(
            np.mean(hard_decoded != payload[: len(hard_decoded)])
        )
        print(
            f"isolated LDPC at 8 dB: pre={pre_ber:.9g}, "
            f"soft_post={post_ber:.9g}, hard_L3_post={hard_post_ber:.9g}, "
            f"sigma={component_std:.9g}"
        )
        self.assertLess(post_ber, pre_ber)
        self.assertLess(hard_post_ber, pre_ber)


if __name__ == "__main__":
    unittest.main()
