# LEO Satellite Communications Simulator

A GNU Radio and Python simulation of a coded QPSK link for low-Earth-orbit satellite communications. The project models the channel, transmitter, synchronization chain, FEC paths, and BER/EVM validation workflow end to end.

## Scope

- LEO channel effects: free-space loss, Doppler, phase noise, scintillation, and thermal noise.
- PN63 framing with normalized QPSK and root-raised-cosine pulse shaping.
- Costas carrier recovery, Gardner timing recovery, and synchronization quality checks.
- Uncoded, convolutional/Viterbi, and regular `(128, 64)` LDPC paths.
- Automated BER sweeps, coding-gain calculations, EVM analysis, and literature comparison.

## Verified results

The checked-in full sweep reports:

- maximum uncoded-QPSK theory deviation: **0.1135 dB**;
- LDPC coding gain at `BER = 1e-5`: **1.8865 dB**;
- worst median waterfall offset in the literature comparison: **1.4889 dB** against a **2.0 dB** project tolerance.

These are simulation results for the configured models, not hardware performance claims. See [`analysis/results/final_report.md`](analysis/results/final_report.md) for the full run record.

## Repository layout

- `channel/` — parameterized LEO channel model.
- `tx/` — framing, coding, modulation, and transmit flowgraphs.
- `rx/` — synchronization, receive flowgraphs, and decoder integration.
- `analysis/` — BER, EVM, coding-gain, and literature-analysis tools.
- `tests/` — unit and GNU Radio integration tests.
- `config/` — centralized simulation parameters.
- `data/` — LDPC matrix and digitized comparison data.

## Environment

The recommended setup uses Conda so GNU Radio and scientific Python packages come from the same channel:

```bash
conda env create -f environment.yml
conda activate leo-satcom-sim
```

For an existing GNU Radio 3.10+ environment:

```bash
python -m pip install -r requirements.txt
```

## Test and analysis

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python -m analysis.ber_sweep --help
python -m analysis.coding_gain --help
```

The complete BER sweep is computationally heavier than the unit tests. Generated plots and CSV reports are retained to make the published result traceable.

## Literature references

Comparison data was digitized from published figures; the original papers are linked rather than redistributed:

- M. Liva et al., [*Code Design for Short Blocks: A Survey*](https://arxiv.org/abs/1610.00873).
- A. Elkelesh et al., [*Decoder-in-the-Loop: Genetic Optimization-Based LDPC Code Design*](https://arxiv.org/abs/1903.03128).

The comparison is a class-consistency check because the referenced curves use CER/BLER while this project reports BER, and the parity-check matrices and decoder settings are not identical.

## License

Released under the [MIT License](LICENSE).
