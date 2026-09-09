#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: LEO Full RX FEC and EVM
# Author: LEO Satcom Sim
# Description: Phase 4 TX to channel to synchronization to FEC decode visualization
# GNU Radio version: 3.10.12.0

from PyQt5 import Qt
from gnuradio import qtgui
from gnuradio import blocks
from gnuradio import gr
from gnuradio.filter import firdes
from gnuradio.fft import window
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import eng_notation
import random
from config import params
from channel.leo_channel_model import BOLTZMANN_J_PER_K
from rx.rx_full_chain import code_rate_for
import sip
import test_rx_full_chain_epy_channel as epy_channel  # embedded python block
import test_rx_full_chain_epy_evm as epy_evm  # embedded python block
import test_rx_full_chain_epy_fec_tx as epy_fec_tx  # embedded python block
import test_rx_full_chain_epy_full_rx as epy_full_rx  # embedded python block
import threading



class test_rx_full_chain(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "LEO Full RX FEC and EVM", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("LEO Full RX FEC and EVM")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
        self.top_scroll_layout = Qt.QVBoxLayout()
        self.setLayout(self.top_scroll_layout)
        self.top_scroll = Qt.QScrollArea()
        self.top_scroll.setFrameStyle(Qt.QFrame.NoFrame)
        self.top_scroll_layout.addWidget(self.top_scroll)
        self.top_scroll.setWidgetResizable(True)
        self.top_widget = Qt.QWidget()
        self.top_scroll.setWidget(self.top_widget)
        self.top_layout = Qt.QVBoxLayout(self.top_widget)
        self.top_grid_layout = Qt.QGridLayout()
        self.top_layout.addLayout(self.top_grid_layout)

        self.settings = Qt.QSettings("gnuradio/flowgraphs", "test_rx_full_chain")

        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)
        self.flowgraph_started = threading.Event()

        ##################################################
        # Variables
        ##################################################
        self.ebno_db = ebno_db = 8.0
        self.decoder_type = decoder_type = "ldpc"
        self.samp_rate = samp_rate = params.samp_rate
        self.payload_bits = payload_bits = tuple(random.Random(params.tx_random_seed).choices((0, 1), k=params.ldpc_k_short * 1000))
        self.effective_t_sys = effective_t_sys = (params.sps / (2.0 * code_rate_for(decoder_type) * 10.0**(ebno_db / 10.0))) / (BOLTZMANN_J_PER_K * params.signal_bandwidth_hz)

        ##################################################
        # Blocks
        ##################################################

        self.qtgui_number_sink_evm = qtgui.number_sink(
            gr.sizeof_float,
            0.05,
            qtgui.NUM_GRAPH_HORIZ,
            1,
            None # parent
        )
        self.qtgui_number_sink_evm.set_update_time(0.10)
        self.qtgui_number_sink_evm.set_title("QPSK EVM")

        labels = ['RMS EVM', '', '', '', '',
            '', '', '', '', '']
        units = ['%', '', '', '', '',
            '', '', '', '', '']
        colors = [("blue", "red"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"),
            ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black"), ("black", "black")]
        factor = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]

        for i in range(1):
            self.qtgui_number_sink_evm.set_min(i, 0)
            self.qtgui_number_sink_evm.set_max(i, 100)
            self.qtgui_number_sink_evm.set_color(i, colors[i][0], colors[i][1])
            if len(labels[i]) == 0:
                self.qtgui_number_sink_evm.set_label(i, "Data {0}".format(i))
            else:
                self.qtgui_number_sink_evm.set_label(i, labels[i])
            self.qtgui_number_sink_evm.set_unit(i, units[i])
            self.qtgui_number_sink_evm.set_factor(i, factor[i])

        self.qtgui_number_sink_evm.enable_autoscale(False)
        self._qtgui_number_sink_evm_win = sip.wrapinstance(self.qtgui_number_sink_evm.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._qtgui_number_sink_evm_win)
        self.qtgui_const_sink_x_0 = qtgui.const_sink_c(
            4096, #size
            "Synchronized QPSK", #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_const_sink_x_0.set_update_time(0.10)
        self.qtgui_const_sink_x_0.set_y_axis((-2), 2)
        self.qtgui_const_sink_x_0.set_x_axis((-2), 2)
        self.qtgui_const_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, qtgui.TRIG_SLOPE_POS, 0.0, 0, "")
        self.qtgui_const_sink_x_0.enable_autoscale(True)
        self.qtgui_const_sink_x_0.enable_grid(True)
        self.qtgui_const_sink_x_0.enable_axis_labels(True)


        labels = ['Synchronized QPSK', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        styles = [0, 0, 0, 0, 0,
            0, 0, 0, 0, 0]
        markers = [0, 0, 0, 0, 0,
            0, 0, 0, 0, 0]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_const_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_const_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_const_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_const_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_const_sink_x_0.set_line_style(i, styles[i])
            self.qtgui_const_sink_x_0.set_line_marker(i, markers[i])
            self.qtgui_const_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_const_sink_x_0_win = sip.wrapinstance(self.qtgui_const_sink_x_0.qwidget(), Qt.QWidget)
        self.top_layout.addWidget(self._qtgui_const_sink_x_0_win)
        self.epy_full_rx = epy_full_rx.blk(decoder_type=decoder_type)
        self.epy_fec_tx = epy_fec_tx.blk(decoder_type=decoder_type)
        self.epy_evm = epy_evm.EVMStreamBlock(window_size=params.evm_window_symbols)
        self.epy_channel = epy_channel.blk(t_sys_kelvin=effective_t_sys)
        self.blocks_vector_source_x_0 = blocks.vector_source_b((0, 0, 0), True, 1, [])
        self.blocks_throttle2_0 = blocks.throttle( gr.sizeof_gr_complex*1, samp_rate, True, 0 if "auto" == "auto" else max( int(float(0.1) * samp_rate) if "auto" == "time" else int(0.1), 1) )
        self.blocks_null_sink_payload = blocks.null_sink(gr.sizeof_char*1)
        self.blocks_null_sink_codeword = blocks.null_sink(gr.sizeof_char*1)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.blocks_throttle2_0, 0), (self.epy_channel, 0))
        self.connect((self.blocks_vector_source_x_0, 0), (self.epy_fec_tx, 0))
        self.connect((self.epy_channel, 0), (self.epy_full_rx, 0))
        self.connect((self.epy_evm, 0), (self.qtgui_number_sink_evm, 0))
        self.connect((self.epy_fec_tx, 0), (self.blocks_throttle2_0, 0))
        self.connect((self.epy_full_rx, 2), (self.blocks_null_sink_codeword, 0))
        self.connect((self.epy_full_rx, 0), (self.blocks_null_sink_payload, 0))
        self.connect((self.epy_full_rx, 1), (self.epy_evm, 0))
        self.connect((self.epy_full_rx, 1), (self.qtgui_const_sink_x_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("gnuradio/flowgraphs", "test_rx_full_chain")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def get_ebno_db(self):
        return self.ebno_db

    def set_ebno_db(self, ebno_db):
        self.ebno_db = ebno_db
        self.set_effective_t_sys((params.sps / (2.0 * code_rate_for(self.decoder_type) * 10.0**(self.ebno_db / 10.0))) / (BOLTZMANN_J_PER_K * params.signal_bandwidth_hz))

    def get_decoder_type(self):
        return self.decoder_type

    def set_decoder_type(self, decoder_type):
        self.decoder_type = decoder_type
        self.set_effective_t_sys((params.sps / (2.0 * code_rate_for(self.decoder_type) * 10.0**(self.ebno_db / 10.0))) / (BOLTZMANN_J_PER_K * params.signal_bandwidth_hz))

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self.blocks_throttle2_0.set_sample_rate(self.samp_rate)

    def get_payload_bits(self):
        return self.payload_bits

    def set_payload_bits(self, payload_bits):
        self.payload_bits = payload_bits

    def get_effective_t_sys(self):
        return self.effective_t_sys

    def set_effective_t_sys(self, effective_t_sys):
        self.effective_t_sys = effective_t_sys




def main(top_block_cls=test_rx_full_chain, options=None):

    qapp = Qt.QApplication(sys.argv)

    tb = top_block_cls()

    tb.start()
    tb.flowgraph_started.set()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()

if __name__ == '__main__':
    main()
