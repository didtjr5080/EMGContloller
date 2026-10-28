# MediaPipe storage verification — 2026-10-28

Real acquisition generates unvalidated software clock fits. Previously the combined
CSV required validated alignment, so its angles were blank even when pose metrics
were recorded separately.

The combined CSV now associates angles using the measurement estimate, falling back
to host receipt time when no estimate exists. It preserves `alignment_unverified`
and records `pose_alignment_basis` and `pose_alignment_host_ns`. It does not claim
physical synchronization. Future/stale frames and tracking failures remain excluded.
The default strict behavior of `labeled_rows` and training alignment checks remains.

Camera dependency import errors now enter the controller's normal fault handling.

Validation:

- 55 tests passed across test_multimodal_integration.py, test_sample_labels.py,
  test_live_preflight.py and test_review_fix_contracts.py.
- 27 tests passed across test_multimodal.py and test_sample_labels.py.
- Added real-profile writer tests verify finalized CSV contents with estimated and
  missing clock mappings, unverified status, EMG values and saved angles.
- Actual MediaPipe model loaded and ran inference on a blank frame successfully.
- Installed project multimodal dependencies in .venv and downloaded official Pose
  Lite model; SHA-256 matched the expected value.
- No physical ESP32/camera recording or person-image accuracy validation performed.
- Follow-up: rebuilt dist/EMGController.exe with the storage fix; packaged self-test
  and portable execution both passed. See WINDOWS_EXE_BUILD.md for artifact hash.
