"""GRC adapter for the Phase 1 LEO channel."""

import inspect
import numpy as np
from gnuradio import gr
from channel.leo_channel_model import leo_channel_model


class blk(gr.basic_block):
    """Expose AWGN-only defaults for the FEC/EVM view."""

    def __new__(cls, t_sys_kelvin=1.0):
        """Return the tested reusable GNU Radio hierarchy."""
        if any(frame.function == "extract" for frame in inspect.stack()):
            return super().__new__(cls)
        return leo_channel_model(
            t_sys_kelvin=t_sys_kelvin,
            doppler_max_hz=0.0,
            phase_noise_std=0.0,
            scintillation_std_db=0.0,
            path_loss_db=0.0,
        )

    def __init__(self, t_sys_kelvin=1.0):
        """Expose the factory signature to GRC."""
        gr.basic_block.__init__(
            self,
            "LEO Channel Model",
            in_sig=[np.complex64],
            out_sig=[np.complex64],
        )