"""Costas ve sembol zamanlama hata akışlarından kilit kararı üret."""

from dataclasses import dataclass

import numpy as np

from config import params


@dataclass(frozen=True)
class LockDecision:
    """İki senkronizasyon döngüsünün son-pencere kilit özetini tut."""

    locked: bool
    costas_variance: float
    timing_variance: float
    window_size: int


def _tail_variance(samples, window_size, average_span=1):
    """Son N grup ortalamasının varyansını karar gürültüsünü bastırarak hesapla."""
    values = np.asarray(samples, dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values)]
    required = int(window_size) * int(average_span)
    if average_span < 1:
        raise ValueError("average_span en az 1 olmalı")
    if len(values) < required:
        raise ValueError(f"varyans için en az {required} sonlu örnek gerekli")
    averaged = values[-required:].reshape(window_size, average_span).mean(axis=1)
    return float(np.var(averaged))


def detect_lock(
    costas_error,
    timing_error,
    window_size=params.lock_window_size,
    costas_threshold=params.costas_lock_var_threshold,
    timing_threshold=params.timing_lock_var_threshold,
    average_span=params.lock_error_average_span,
):
    """Her iki hata varyansı da eşiğin altındaysa kilit kararı ver."""
    if window_size < 2:
        raise ValueError("window_size en az 2 olmalı")
    if costas_threshold < 0.0 or timing_threshold < 0.0:
        raise ValueError("kilit varyansı eşikleri negatif olamaz")

    costas_variance = _tail_variance(costas_error, window_size, average_span)
    timing_variance = _tail_variance(timing_error, window_size, average_span)
    return LockDecision(
        locked=(
            costas_variance < costas_threshold
            and timing_variance < timing_threshold
        ),
        costas_variance=costas_variance,
        timing_variance=timing_variance,
        window_size=window_size,
    )


def variance_trend(samples, fraction=0.10):
    """Bir hata akışının ilk ve son dilim varyanslarını döndür."""
    values = np.asarray(samples, dtype=np.float64).reshape(-1)
    values = values[np.isfinite(values)]
    if not 0.0 < fraction <= 0.5:
        raise ValueError("fraction (0, 0.5] aralığında olmalı")
    segment_size = max(2, int(len(values) * fraction))
    if len(values) < 2 * segment_size:
        raise ValueError("varyans trendi için yeterli örnek yok")
    return float(np.var(values[:segment_size])), float(np.var(values[-segment_size:]))
