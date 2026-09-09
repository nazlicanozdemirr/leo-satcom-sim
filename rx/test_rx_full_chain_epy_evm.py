"""GRC adapter for analysis.evm_calc.EVMStreamBlock."""

from analysis.evm_calc import EVMStreamBlock


class blk(EVMStreamBlock):
    """Expose rolling QPSK EVM percentage."""

    def __init__(self, window_size=1000):
        """Construct the shared EVM measurement block."""
        super().__init__(window_size=window_size)