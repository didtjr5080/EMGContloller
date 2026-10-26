import pytest
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPixmap

from emg_collector.app import create_main_window
from emg_collector.multimodal.schema import Termination
from emg_collector.ui.common import TERMINATION_LABELS, WrappingCheckBox


def test_all_termination_choices_are_korean_and_keep_schema_values(qtbot, tmp_path):
    window = create_main_window(tmp_path / "localized")
    qtbot.addWidget(window)
    assert set(TERMINATION_LABELS) == set(Termination)
    for reason in Termination:
        index = window.reason.findData(reason.value)
        assert index > 0
        window.reason.setCurrentIndex(index)
        assert window.reason.currentText() == TERMINATION_LABELS[reason]
        assert window.reason.currentData() == reason.value


def test_wrapped_consent_preserves_full_text_and_clickable_label(qtbot):
    text = "자세 좌표 수집 동의 (영상 미저장 시에도 연구자료로 저장)"
    checkbox = WrappingCheckBox(text)
    qtbot.addWidget(checkbox)
    checkbox.resize(180, 80)
    checkbox.show()
    assert checkbox.accessibleName() == text and checkbox.label.text() == text
    qtbot.mouseClick(
        checkbox,
        Qt.MouseButton.LeftButton,
        pos=QPoint(checkbox.width() - 10, checkbox.height() // 2),
    )
    assert checkbox.isChecked()


@pytest.mark.parametrize("size", [(800, 600), (640, 480)])
def test_collection_can_shrink_with_live_preview_and_stop_buttons_visible(
    qtbot, tmp_path, size
):
    window = create_main_window(tmp_path / "compact")
    qtbot.addWidget(window)
    frame = QPixmap(1920, 1080)
    frame.fill(Qt.GlobalColor.blue)
    window.video.setPixmap(frame)
    window.resize(*size)
    window.show()
    qtbot.wait(30)
    assert window.width() <= size[0] and window.height() <= size[1]
    assert window.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
    assert window.isSizeGripEnabled()
    preview = window.video.pixmap()
    assert preview.width() <= window.video.contentsRect().width()
    assert preview.height() <= window.video.contentsRect().height()
    assert preview.width() / preview.height() == pytest.approx(16 / 9, abs=0.03)
    for button in (window.stop_button, window.pain_button):
        rect = QRect(button.mapTo(window, QPoint(0, 0)), button.size())
        assert window.rect().contains(rect)
        assert button.isVisibleTo(window)
    assert window.controls_scroll.verticalScrollBar().maximum() > 0
    # Growing and shrinking again must rescale from the original frame.
    window.resize(1100, 700)
    qtbot.wait(10)
    window.resize(*size)
    qtbot.wait(10)
    assert window.width() <= size[0] and window.height() <= size[1]
