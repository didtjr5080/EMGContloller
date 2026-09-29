import pytest

from emg_collector.acquisition.time_unwrapper import TimeUnwrapper


def test_unwrap_handles_single_rollover_and_stays_monotonic():
    unwrapper = TimeUnwrapper()
    raw_sequence = [4294965000, 4294967000, 1000, 3000]

    results = [unwrapper.unwrap(t) for t in raw_sequence]

    unwrapped_values = [r.value_us for r in results]
    assert unwrapped_values == sorted(unwrapped_values)
    for earlier, later in zip(unwrapped_values, unwrapped_values[1:]):
        assert later > earlier

    assert unwrapper.wrap_count == 1
    assert [r.wrapped for r in results] == [False, False, True, False]
    assert not any(r.reboot_detected for r in results)


def test_unwrap_detects_reboot_instead_of_wrapping():
    unwrapper = TimeUnwrapper()
    unwrapper.unwrap(50_000_000)  # 50 s into a long-running session
    unwrapper.unwrap(51_000_000)

    result = unwrapper.unwrap(2_000)  # timer reset near zero: a reboot, not a wrap

    assert result.reboot_detected is True
    assert result.wrapped is False
    assert unwrapper.wrap_count == 0
    # Value must not silently jump backwards for downstream consumers.
    assert result.value_us == 51_000_000


def test_unwrap_flags_small_backward_jitter_without_wrap_or_reboot():
    unwrapper = TimeUnwrapper()
    unwrapper.unwrap(1_000_000)
    result = unwrapper.unwrap(999_500)  # 500us of backward jitter

    assert result.regression is True
    assert result.wrapped is False
    assert result.reboot_detected is False
    assert result.value_us == 1_000_000


def test_unwrap_rejects_out_of_range_input():
    unwrapper = TimeUnwrapper()
    with pytest.raises(ValueError):
        unwrapper.unwrap(-1)
    with pytest.raises(ValueError):
        unwrapper.unwrap(2**32)
