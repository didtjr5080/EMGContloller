"""Windowed executable entry point; --self-test checks the frozen distribution."""

import argparse
import json
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="EMGController desktop collector")
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument(
        "--legacy-v2",
        action="store_true",
        help="Open the legacy biceps/brachioradialis collector",
    )
    parser.add_argument("--self-test", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args()
    try:
        if args.self_test:
            from emg_collector.packaging_check import check_distribution

            check_distribution(args.self_test)
            return 0
        from emg_collector.app import run

        return run(args.dataset_root, legacy_v2=args.legacy_v2)
    except Exception:
        detail = traceback.format_exc()
        if args.self_test:
            args.self_test.parent.mkdir(parents=True, exist_ok=True)
            args.self_test.write_text(
                json.dumps({"ok": False, "error": detail}, indent=2), encoding="utf-8"
            )
        else:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            # Keep the application alive while the modal error dialog is open.
            app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841
            QMessageBox.critical(None, "EMGController 시작 실패", detail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
