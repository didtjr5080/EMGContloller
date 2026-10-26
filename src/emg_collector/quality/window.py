"""PILOT signal policy; file integrity and usable coverage are different checks."""

from pydantic import Field, model_validator
from emg_collector.multimodal.schema import Record


class QualityPolicy(Record):
    version: str = "emg-quality-1"
    status: str = "PILOT"
    basis: str = "Engineering pilot candidates; requires study-specific validation"
    expected_rate_hz: float = Field(default=500, gt=0)
    minimum_rate_hz: float = Field(default=450, gt=0)
    maximum_rate_hz: float = Field(default=550, gt=0)
    minimum_coverage: float = Field(default=0.9, gt=0, le=1)
    maximum_gap_ns: int = Field(default=20_000_000, gt=0)
    maximum_clipping_ratio: float = Field(default=0.05, ge=0, le=1)
    maximum_uncertainty_ns: int = Field(default=50_000_000, ge=0)
    maximum_decision_latency_ns: int = Field(default=500_000_000, gt=0)
    allow_epoch_crossing: bool = False

    @model_validator(mode="after")
    def check_rates(self):
        if not self.minimum_rate_hz <= self.expected_rate_hz <= self.maximum_rate_hz:
            raise ValueError("expected rate must fall inside allowed rate range")
        return self


def window_quality(samples, start_ns, end_ns, policy=None):
    p = policy or QualityPolicy()
    duration = end_ns - start_ns
    if duration <= 0:
        raise ValueError("window requires a positive duration")
    times = sorted(
        set(
            int(s["measurement_host_ns"])
            for s in samples
            if s.get("measurement_host_ns") is not None
            and start_ns <= int(s["measurement_host_ns"]) <= end_ns
        )
    )
    interval = 1e9 / p.expected_rate_hz
    covered = 0
    right = start_ns
    for t in times:
        left = max(start_ns, t - interval / 2)
        edge = min(end_ns, t + interval / 2)
        covered += max(0, edge - max(left, right))
        right = max(right, edge)
    gaps = [b - a for a, b in zip([start_ns, *times], [*times, end_ns])]
    values = [
        int(s[k]) for s in samples for k in ("s1_env", "s1_raw", "s2_env", "s2_raw")
    ]
    clipping = sum(v in (0, 4095) for v in values) / len(values) if values else None
    epochs = {int(s["epoch_id"]) for s in samples}
    coverage = covered / duration
    rate = max(0, len(times) - 1) * 1e9 / duration
    alignment = (
        "aligned"
        if samples and all(s.get("alignment_status") == "aligned" for s in samples)
        else "alignment_unverified"
    )
    reasons = []
    if not p.minimum_rate_hz <= rate <= p.maximum_rate_hz:
        reasons.append("sample_rate_out_of_range")
    if coverage < p.minimum_coverage:
        reasons.append("coverage_insufficient")
    if max(gaps, default=duration) > p.maximum_gap_ns:
        reasons.append("gap_exceeded")
    if clipping is None or clipping > p.maximum_clipping_ratio:
        reasons.append("clipping_exceeded")
    if len(epochs) > 1 and not p.allow_epoch_crossing:
        reasons.append("epoch_crossing")
    if alignment != "aligned":
        reasons.append("alignment_unverified")
    return {
        "expected_samples": round(duration * p.expected_rate_hz / 1e9) + 1,
        "observed_samples": len(samples),
        "unique_timestamps": len(times),
        "coverage_ratio": coverage,
        "actual_rate_hz": rate,
        "max_gap_ns": max(gaps, default=duration),
        "clipping_ratio": clipping,
        "epoch_count": len(epochs),
        "alignment_status": alignment,
        "reasons": reasons,
        "eligible": not reasons,
        "policy_version": p.version,
    }
