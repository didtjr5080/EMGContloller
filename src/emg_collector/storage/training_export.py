"""Reproducible participant-first split and strictly causal feature export."""

import hashlib


def participant_splits(ids, seed):
    # Hash assignment is stable when visits or participants are added.
    output = {}
    for participant in sorted(set(ids)):
        value = (
            int(hashlib.sha256(f"{seed}:{participant}".encode()).hexdigest()[:8], 16)
            / 2**32
        )
        output[participant] = (
            "train" if value < 0.7 else ("validation" if value < 0.85 else "test")
        )
    return output


def causal_window(rows, end_ns, duration_ns, start_ns=None, key="host_receive_ns"):
    lower = max(end_ns - duration_ns, start_ns if start_ns is not None else 0)
    return [r for r in rows if lower <= int(r[key]) <= end_ns]


def export_training(dataset_root, output, **options):
    from emg_collector.storage.training_pipeline import export_training as generate

    return generate(dataset_root, output, **options)
