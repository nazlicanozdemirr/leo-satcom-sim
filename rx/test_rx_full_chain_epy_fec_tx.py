"""GRC adapter for the selectable Phase 4 FEC transmitter."""

import inspect
import numpy as np
from gnuradio import gr
from rx.rx_full_chain import fec_tx_chain


class blk(gr.basic_block):
    """Expose matching LDPC or convolutional coding."""

    def __new__(cls, decoder_type="ldpc"):
        """Return the tested reusable GNU Radio hierarchy."""
        if any(frame.function == "extract" for frame in inspect.stack()):
            return super().__new__(cls)
        return fec_tx_chain(decoder_type=decoder_type)

    def __init__(self, decoder_type="ldpc"):
        """Expose the factory signature to GRC."""
        gr.basic_block.__init__(
            self,
            "Selectable FEC TX Chain",
            in_sig=[np.uint8],
            out_sig=[np.complex64],
        )