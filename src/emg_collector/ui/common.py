"""Shared presentation for collection and review dialogs."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
)

from emg_collector.multimodal.schema import Termination

TERMINATION_LABELS = {
    Termination.technical_failure: "기술적 실패 (자세 기준 미달)",
    Termination.voluntary_stop: "자발적 중단",
    Termination.pain_discomfort: "통증·불편감",
    Termination.equipment_failure: "장비 이상",
    Termination.tracking_failure: "자세 추적 실패",
    Termination.protocol_deviation: "측정 절차 이탈",
    Termination.planned_stop: "계획된 종료",
    Termination.other: "기타",
}


def prepare_resizable_dialog(dialog, width=1200, height=800):
    dialog.setWindowFlags(
        (dialog.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        & ~Qt.WindowType.WindowContextHelpButtonHint
    )
    dialog.setSizeGripEnabled(True)
    dialog.setMinimumSize(640, 480)
    screen = dialog.screen()
    if screen:
        available = screen.availableGeometry()
        width = min(width, max(640, available.width() - 32))
        height = min(height, max(480, available.height() - 64))
    dialog.resize(width, height)


class VideoPreview(QLabel):
    """Keep the original frame while allowing the layout to shrink its preview."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._source = QPixmap()
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setPixmap(self, pixmap):
        self._source = pixmap
        self._scale_frame()

    def _scale_frame(self):
        if not self._source.isNull():
            super().setPixmap(
                self._source.scaled(
                    self.contentsRect().size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_frame()


class WrappingCheckBox(QCheckBox):
    """Wrap the full consent/check text without losing checkbox interaction."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setAccessibleName(text)
        self.label = QLabel(text, self)
        self.label.setWordWrap(True)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        indicator = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
        layout.setContentsMargins(indicator + 6, 0, 0, 0)
        layout.addWidget(self.label)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize()

    def hitButton(self, point):
        return self.rect().contains(point)


def wrap_form_labels(form):
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    for row in range(form.rowCount()):
        for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
            item = form.itemAt(row, role)
            if item and isinstance(item.widget(), QLabel):
                item.widget().setWordWrap(True)
