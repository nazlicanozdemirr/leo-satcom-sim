"""TX çerçeveleme için GNU Radio'dan bağımsız PN63 yardımcıları."""

from config import params


PN63_BITS = tuple(params.preamble_bits)
FRAME_PAD_BITS = params.frame_pad_bits
FRAME_BITS = params.preamble_len + params.ldpc_n_short + FRAME_PAD_BITS


def frame_codeword(codeword_bits):
    """128-bit LDPC codeword önüne PN63, sonuna QPSK pad biti ekle."""
    codeword = tuple(int(bit) for bit in codeword_bits)
    if len(codeword) != params.ldpc_n_short:
        raise ValueError(f"codeword tam {params.ldpc_n_short} bit olmalı")
    if any(bit not in (0, 1) for bit in codeword):
        raise ValueError("codeword yalnız 0 ve 1 değerlerinden oluşmalı")
    return PN63_BITS + codeword + (0,) * FRAME_PAD_BITS

