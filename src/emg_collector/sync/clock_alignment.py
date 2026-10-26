from bisect import bisect_right
import numpy as np


def fit_clock(observations):
    """Fit per epoch, retaining receive latency in residuals (not exposure sync)."""
    if len(observations) < 3 or observations[-1][0] <= observations[0][0]:
        return {
            "method": "software_receive_linear_fit",
            "status": "insufficient_data",
            "offset_ns": None,
            "drift_ppm": None,
            "residual_rms_ns": None,
        }
    x = np.asarray([r[0] * 1000 for r in observations], dtype=np.float64)
    y = np.asarray([r[1] for r in observations], dtype=np.float64)
    origin_x, origin_y = x[0], y[0]
    slope, intercept = np.polyfit(x - origin_x, y - origin_y, 1)
    residual = y - (origin_y + intercept + slope * (x - origin_x))
    return {
        "method": "software_receive_linear_fit",
        "status": "estimated_unvalidated",
        "offset_ns": float(origin_y + intercept - slope * origin_x),
        "drift_ppm": float((slope - 1) * 1e6),
        "residual_rms_ns": float(np.sqrt(np.mean(residual**2))),
        "residual_max_ns": float(np.max(np.abs(residual))),
        "physical_sync_error_ms": None,
        "latency_bias_ns": None,
    }


def align_previous(rows, target_ns, max_gap_ns, key="capture_host_ns"):
    """Causal previous-neighbor; never use future frames or bridge long gaps."""
    if max_gap_ns < 0:
        raise ValueError("maximum gap must be nonnegative")
    index = bisect_right([r[key] for r in rows], target_ns) - 1
    if index < 0 or target_ns - rows[index][key] > max_gap_ns:
        return None
    return rows[index]
