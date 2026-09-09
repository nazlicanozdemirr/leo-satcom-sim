"""Senkronize QPSK sembolleri için RMS EVM ve küme dağılımı analizi."""

from collections import deque
from dataclasses import dataclass
import math

import numpy as np

from config import params


QPSK_LEVEL = 1.0 / math.sqrt(2.0)
QPSK_POINTS = np.asarray(
    [
        complex(-QPSK_LEVEL, -QPSK_LEVEL),
        complex(QPSK_LEVEL, -QPSK_LEVEL),
        complex(-QPSK_LEVEL, QPSK_LEVEL),
        complex(QPSK_LEVEL, QPSK_LEVEL),
    ],
    dtype=np.complex64,
)
QPSK_POINT_LABELS = ("-I-Q", "+I-Q", "-I+Q", "+I+Q")


@dataclass(frozen=True)
class EVMAnalysis:
    """Toplam EVM, pencere trendi ve QPSK küme histogramını tut."""

    evm_rms_percent: float
    trend_percent: np.ndarray
    histogram: dict
    decided_symbols: np.ndarray
    error_vectors: np.ndarray
    window_size: int


def _as_finite_symbols(symbols):
    """Girdiyi sonlu, tek boyutlu complex64 sembol dizisine dönüştür."""
    values = np.asarray(symbols, dtype=np.complex64).reshape(-1)
    values = values[np.isfinite(values.real) & np.isfinite(values.imag)]
    if len(values) == 0:
        raise ValueError("EVM hesabı için en az bir sonlu sembol gerekli")
    return values


def nearest_qpsk_points(symbols):
    """Her alınan sembol için en yakın ideal QPSK noktasını ve indeksini bul."""
    values = _as_finite_symbols(symbols)
    distances = np.abs(values[:, None] - QPSK_POINTS[None, :])
    indices = np.argmin(distances, axis=1)
    return QPSK_POINTS[indices], indices.astype(np.int8)


def evm_rms_percent(symbols):
    """RMS EVM'i ideal sembol ortalama gücüne göre yüzde olarak hesapla."""
    values = _as_finite_symbols(symbols)
    decided, _ = nearest_qpsk_points(values)
    error = values - decided
    numerator = float(np.mean(np.abs(error.astype(np.complex128)) ** 2))
    denominator = float(np.mean(np.abs(decided.astype(np.complex128)) ** 2))
    if denominator == 0.0:
        raise ValueError("ideal sembol gücü sıfır olamaz")
    return 100.0 * math.sqrt(numerator / denominator)


def evm_trend_percent(symbols, window_size=params.evm_window_symbols):
    """Ardışık, örtüşmeyen pencereler için RMS EVM yüzdelerini döndür."""
    values = _as_finite_symbols(symbols)
    window_size = int(window_size)
    if window_size < 1:
        raise ValueError("window_size en az 1 olmalı")
    return np.asarray(
        [evm_rms_percent(values[start : start + window_size])
         for start in range(0, len(values), window_size)],
        dtype=np.float64,
    )


def qpsk_cluster_histogram(symbols):
    """En yakın dört QPSK noktasına düşen sembol sayılarını etiketli döndür."""
    _, indices = nearest_qpsk_points(symbols)
    counts = np.bincount(indices, minlength=len(QPSK_POINTS))
    return {
        label: int(count)
        for label, count in zip(QPSK_POINT_LABELS, counts, strict=True)
    }


def calculate_evm(symbols, window_size=params.evm_window_symbols):
    """Tek çağrıda toplam EVM, trend, karar noktaları ve histogram üret."""
    values = _as_finite_symbols(symbols)
    decided, _ = nearest_qpsk_points(values)
    return EVMAnalysis(
        evm_rms_percent=evm_rms_percent(values),
        trend_percent=evm_trend_percent(values, window_size=window_size),
        histogram=qpsk_cluster_histogram(values),
        decided_symbols=decided,
        error_vectors=values - decided,
        window_size=int(window_size),
    )


try:
    from gnuradio import gr
except ImportError:  # Saf NumPy analizinin GNU Radio olmadan da kullanılmasını sağlar.
    gr = None


if gr is not None:

    class EVMStreamBlock(gr.sync_block):
        """Kayan pencereli QPSK EVM yüzdesini Number Sink için akış olarak üret."""

        def __init__(self, window_size=params.evm_window_symbols):
            """Kompleks giriş ve float EVM çıkışlı ölçüm bloğunu oluştur."""
            gr.sync_block.__init__(
                self,
                name="QPSK rolling EVM (%)",
                in_sig=[np.complex64],
                out_sig=[np.float32],
            )
            self.window_size = int(window_size)
            if self.window_size < 1:
                raise ValueError("window_size en az 1 olmalı")
            self._error_power = deque()
            self._error_sum = 0.0

        def work(self, input_items, output_items):
            """Her sembolde en yakın-nokta hatasını kayan pencereye ekle."""
            source = input_items[0]
            destination = output_items[0]
            count = min(len(source), len(destination))
            for index, symbol in enumerate(source[:count]):
                nearest = QPSK_POINTS[int(np.argmin(np.abs(symbol - QPSK_POINTS)))]
                error_power = float(abs(symbol - nearest) ** 2)
                self._error_power.append(error_power)
                self._error_sum += error_power
                if len(self._error_power) > self.window_size:
                    self._error_sum -= self._error_power.popleft()
                destination[index] = 100.0 * math.sqrt(
                    self._error_sum / len(self._error_power)
                )
            return count

else:

    class EVMStreamBlock:
        """GNU Radio bulunmadığında açıklayıcı hata veren akış bloğu vekili."""

        def __init__(self, *args, **kwargs):
            """Eksik GNU Radio bağımlılığını çağrı anında bildir."""
            raise ImportError("EVMStreamBlock için GNU Radio 3.10+ gerekli")


__all__ = [
    "EVMAnalysis",
    "EVMStreamBlock",
    "QPSK_POINT_LABELS",
    "QPSK_POINTS",
    "calculate_evm",
    "evm_rms_percent",
    "evm_trend_percent",
    "nearest_qpsk_points",
    "qpsk_cluster_histogram",
]
