"""GRC adapter for the complete Phase 4 receiver."""

import inspect
import numpy as np
from gnuradio import gr
from rx.rx_full_chain import rx_full_chain


class blk(gr.basic_block):
    """Expose synchronized symbols and selected FEC output."""

    def __new__(cls, decoder_type="ldpc"):
        """Return the tested reusable GNU Radio hierarchy."""
        if any(frame.function == "extract" for frame in inspect.stack()):
            return super().__new__(cls)
        return rx_full_chain(decoder_type=decoder_type)

    def __init__(self, decoder_type="ldpc"):
        """Expose the factory signature to GRC."""
        gr.basic_block.__init__(
            self,
            "LEO Full RX Chain",
            in_sig=[np.complex64],
            out_sig=[np.uint8, np.complex64, np.uint8],
        )