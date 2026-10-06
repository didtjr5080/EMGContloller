"""Parse raw ESP32 serial lines into validated samples, with diagnostics.

Only lines with exactly five comma-separated integer fields (time_us plus
4 ADC channels from the two MyoWare 2.0 sensors), all ADC values within
the ADC's valid range, are accepted as samples. Everything else is
classified and counted, never silently dropped without a trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from emg_collector.config import (
    ADC_MAX_VALUE,
    ADC_MIN_VALUE,
    SERIAL_FIELD_COUNT,
    SERIAL_HEADER_LINE,
)


@dataclass(frozen=True)
class ParsedSample:
    time_us: int
    biceps_env: int
    biceps_raw: int
    brachio_env: int
    brachio_raw: int


@dataclass
class ParserDiagnostics:
    valid_rows: int = 0
    header_lines: int = 0
    blank_lines: int = 0
    boot_message_lines: int = 0
    malformed_rows: int = 0
    out_of_range_rows: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "valid_rows": self.valid_rows,
            "header_lines": self.header_lines,
            "blank_lines": self.blank_lines,
            "boot_message_lines": self.boot_message_lines,
            "malformed_rows": self.malformed_rows,
            "out_of_range_rows": self.out_of_range_rows,
        }


class LineParser:
    """Incrementally parses ``time_us,biceps_env,biceps_raw,brachio_env,brachio_raw``
    lines, accumulating diagnostics."""

    def __init__(self) -> None:
        self.diagnostics = ParserDiagnostics()

    def parse_line(self, line: str) -> ParsedSample | None:
        stripped = line.strip()

        if not stripped:
            self.diagnostics.blank_lines += 1
            return None

        if stripped == SERIAL_HEADER_LINE:
            self.diagnostics.header_lines += 1
            return None

        if "," not in stripped:
            # ESP32 boot/log noise (e.g. "rst:0x1 (POWERON_RESET)").
            self.diagnostics.boot_message_lines += 1
            return None

        parts = stripped.split(",")
        if len(parts) != SERIAL_FIELD_COUNT:
            self.diagnostics.malformed_rows += 1
            return None

        try:
            time_us, biceps_env, biceps_raw, brachio_env, brachio_raw = (
                int(p) for p in parts
            )
        except ValueError:
            self.diagnostics.malformed_rows += 1
            return None

        if time_us < 0:
            self.diagnostics.malformed_rows += 1
            return None

        channel_values = (biceps_env, biceps_raw, brachio_env, brachio_raw)
        if any(not (ADC_MIN_VALUE <= value <= ADC_MAX_VALUE) for value in channel_values):
            self.diagnostics.out_of_range_rows += 1
            return None

        self.diagnostics.valid_rows += 1
        return ParsedSample(
            time_us=time_us,
            biceps_env=biceps_env,
            biceps_raw=biceps_raw,
            brachio_env=brachio_env,
            brachio_raw=brachio_raw,
        )

    def parse_lines(self, lines: list[str]) -> list[ParsedSample]:
        samples: list[ParsedSample] = []
        for line in lines:
            sample = self.parse_line(line)
            if sample is not None:
                samples.append(sample)
        return samples
