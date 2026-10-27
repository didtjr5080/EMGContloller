# Rebuild: .venv/Scripts/python -m PyInstaller --noconfirm EMGController.spec
from pathlib import Path
import sys
import os
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
model = root / 'models' / 'pose_landmarker_lite.task'
if not model.is_file():
    raise SystemExit('Run python scripts/download_pose_model.py before building.')

datas = collect_data_files('mediapipe')
datas += [(str(model), 'models')]
datas += [(str(root / 'WorkOrder' / 'unilateral_curl_pilot.json'), 'protocols')]
a = Analysis(
    [str(root / 'scripts' / 'windows_entry.py')],
    pathex=[str(root / 'src')],
    datas=datas,
    hiddenimports=[],
    # Optional scientific/notebook stacks in the host environment are not used by Pose Tasks.
    excludes=['tensorflow', 'torch', 'jax', 'jaxlib', 'IPython', 'notebook', 'pytest',
              'scipy', 'pandas', 'numba', 'PyQt5', 'PySide2', 'PySide6', 'tkinter',
              'sphinx', 'docutils'],
    hooksconfig={'matplotlib': {'backends': ['Agg']}},
)
# Qt ships older CRT copies; use one installed CRT set for MediaPipe and Qt.
for index, (destination, source, kind) in enumerate(a.binaries):
    name = Path(destination).name
    if name.lower().startswith(('msvcp140', 'vcruntime140', 'concrt140')):
        runtime = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32' / name
        if not runtime.is_file():
            runtime = Path(sys.base_prefix) / name
        if runtime.is_file():
            a.binaries[index] = (destination, str(runtime), kind)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='EMGController',
          debug=False, strip=False, upx=False, console=False)
