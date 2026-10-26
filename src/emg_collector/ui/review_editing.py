"""Review editing and assessment modes, separate from video playback."""

import json
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QInputDialog, QTableWidgetItem
from emg_collector.labeling.edits import edit_attempts
from emg_collector.labeling.review_contract import (
    independent_assessments,
    disagreement_fields,
    decision_payload,
)
from emg_collector.multimodal.schema import Attempt, SetRecord, Termination


class ReviewEditing:
    def _table_attempts(self):
        result = []
        for row in range(self.table.rowCount()):
            values = [self.table.item(row, col).text() for col in range(7)]
            result.append(
                Attempt(
                    attempt_id=values[0],
                    set_id=self.data["sets"][0].set_id,
                    start_ns=int(values[1]),
                    end_ns=int(values[2]),
                    validity=values[3],
                    reasons=json.loads(values[4]),
                    rom_deg=float(values[5]) if values[5] else None,
                    phases=json.loads(values[6]),
                    provisional=False,
                )
            )
        return result

    def _current_record(self):
        failure = self.failure.currentData()
        if failure == "__invalid_reference__":
            raise ValueError(
                "선택한 실패 시도가 삭제·변경되었습니다. 실패 시도를 다시 선택하세요."
            )
        record = self.data["sets"][0].model_copy(
            update={
                "termination_reason": Termination(self.reason.currentData()),
                "failure_attempt_id": None if failure == "__none__" else failure,
                "failure_attempt_observed": (
                    False if failure == "__none__" else (True if failure else None)
                ),
                "review_status": "provisional",
                "censoring_status": "unreviewed",
            }
        )
        return SetRecord.model_validate(record.model_dump())

    def _render(self, sets, attempts):
        record = sets[0]
        self.table.blockSignals(True)
        self.table.setRowCount(len(attempts))
        for i, a in enumerate(attempts):
            values = [
                a.attempt_id,
                a.start_ns,
                a.end_ns,
                a.validity,
                json.dumps(a.reasons),
                a.rom_deg if a.rom_deg is not None else "",
                json.dumps(a.phases),
            ]
            for j, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if j == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(i, j, item)
        self.table.blockSignals(False)
        self.failure.clear()
        self.failure.addItem("실패 시도 확인 불가", None)
        self.failure.addItem("실패 시도 없음", "__none__")
        for a in attempts:
            if a.validity == "invalid":
                self.failure.addItem(a.attempt_id, a.attempt_id)
        target = (
            "__none__"
            if record.failure_attempt_observed is False
            else record.failure_attempt_id
        )
        index = self.failure.findData(target)
        if index < 0:
            self.failure.addItem(
                "실패 시도 재선택 필요 (삭제·분할·변경됨)", "__invalid_reference__"
            )
            index = self.failure.count() - 1
        self.failure.setCurrentIndex(index)
        self.reason.setCurrentIndex(
            max(
                0,
                self.reason.findData(
                    record.termination_reason.value
                    if record.termination_reason
                    else "other"
                ),
            )
        )

    def _sync_failure(self, *args):
        if self.data is None:
            return
        try:
            attempts = self._table_attempts()
        except (ValueError, AttributeError):
            return
        selected = self.failure.currentData()
        self.failure.clear()
        self.failure.addItem("실패 시도 확인 불가", None)
        self.failure.addItem("실패 시도 없음", "__none__")
        for a in attempts:
            if a.validity == "invalid":
                self.failure.addItem(a.attempt_id, a.attempt_id)
        index = self.failure.findData(selected)
        if index < 0:
            self.failure.addItem(
                "실패 시도 재선택 필요 (삭제·분할·변경됨)", "__invalid_reference__"
            )
            index = self.failure.count() - 1
        self.failure.setCurrentIndex(index)

    def _populate_assessments(self, history):
        assessments = independent_assessments(history, self.current_evidence)
        self.assessments = {a["assessment_id"]: a for a in assessments}
        for combo in (self.assessment_a, self.assessment_b):
            combo.blockSignals(True)
            combo.clear()
            for a in assessments:
                combo.addItem(
                    a["assessment_id"][:12] + " / " + a["reviewer_id"],
                    a["assessment_id"],
                )
            combo.blockSignals(False)
        if self.assessment_b.count() > 1:
            self.assessment_b.blockSignals(True)
            self.assessment_b.setCurrentIndex(1)
            self.assessment_b.blockSignals(False)

    def _mode_changed(self, *args):
        if self.data is None or not hasattr(self, "current_evidence"):
            return
        mode = self.mode.currentData()
        adjust = mode == "adjudication"
        for combo in (self.assessment_a, self.assessment_b):
            combo.setEnabled(adjust)
        self.comparison.setVisible(adjust)
        self.adjudication.setEnabled(adjust)
        self.adjudication.setChecked(False)
        self.objective.setChecked(False)
        self.edit_operations = []
        if adjust:
            a = self.assessments.get(self.assessment_a.currentData())
            b = self.assessments.get(self.assessment_b.currentData())
            if a and b:
                self.comparison.setPlainText(
                    json.dumps(
                        {
                            "불일치 항목": disagreement_fields(a, b),
                            "평가 1": decision_payload(a),
                            "평가 2": decision_payload(b),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                self._render(
                    [SetRecord.model_validate(s) for s in a["sets"]],
                    [Attempt.model_validate(x) for x in a["attempts"]],
                )
            self.status.setText(
                "서로 다른 검토자의 완료된 독립 평가 두 건을 선택하고 불일치 근거를 기록하세요."
            )
        elif mode == "independent":
            self._render(self.data["sets"], self.data["attempts"])
            self.status.setText(
                "독립 판정: 원 자동 결과에서 시작합니다. 이전 사람 판정은 숨깁니다. 로컬 검토자 ID만으로 신원을 인증하지 않습니다."
            )
        else:
            self._render(
                self.data.get("effective_sets", self.data["sets"]),
                self.data.get("effective_attempts", self.data["attempts"]),
            )
            self.status.setText("초안은 객관적 독립 평가 수에 포함하지 않습니다.")

    def _saved(self, result):
        entry = result["entry"]
        self.expected_revision = entry["revision"]
        self.current_evidence = entry["evidence"]
        self.data["history"].append(entry)
        self.data["effective_sets"] = [
            SetRecord.model_validate(s) for s in entry["sets"]
        ]
        self.data["effective_attempts"] = [
            Attempt.model_validate(a) for a in entry["attempts"]
        ]
        self._populate_assessments(self.data["history"])
        self._mode_changed()
        self.reviewer.clear()
        self.revision_reason.clear()
        self._message(
            f"revision {entry['revision']} 저장: {entry['sets'][0]['review_status']}; 다음 독립 판정은 원 자동 결과부터 시작합니다."
        )

    def _edit(self, operation):
        if self.data is None:
            return
        try:
            attempts = self._table_attempts()
            record = self._current_record()
            rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
            ids = [attempts[i].attempt_id for i in rows]
            options = {}
            duration = (self.end - self.origin) / 1e9
            if operation == "add":
                start, ok = QInputDialog.getDouble(
                    self, "시도 추가", "시작 시각 (세션 초)", 0, 0, duration, 6
                )
                if not ok:
                    return
                end, ok = QInputDialog.getDouble(
                    self,
                    "시도 추가",
                    "종료 시각 (세션 초)",
                    min(start + 1, duration),
                    0,
                    duration,
                    6,
                )
                if not ok:
                    return
                options = dict(
                    set_id=record.set_id,
                    start_ns=self.origin + round(start * 1e9),
                    end_ns=self.origin + round(end * 1e9),
                )
            elif operation == "split":
                if len(rows) != 1:
                    raise ValueError("분할할 시도 한 개를 선택하세요.")
                a = attempts[rows[0]]
                point, ok = QInputDialog.getDouble(
                    self,
                    "시도 분할",
                    "분할 시각 (세션 초)",
                    ((a.start_ns + a.end_ns) / 2 - self.origin) / 1e9,
                    (a.start_ns - self.origin) / 1e9,
                    (a.end_ns - self.origin) / 1e9,
                    6,
                )
                if not ok:
                    return
                options["split_ns"] = self.origin + round(point * 1e9)
            updated, edit = edit_attempts(attempts, operation, ids, **options)
            self.edit_operations.append(edit)
            self._render([record], updated)
        except (ValueError, AttributeError) as exc:
            self.status.setText(str(exc))
