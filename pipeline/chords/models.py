from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable


BBox = tuple[float, float, float, float]


def bbox_center(box: BBox) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def merge_close_values(values: Iterable[float], tol: float = 2.0) -> list[float]:
    sorted_values = sorted(values)
    if not sorted_values:
        return []

    merged = [sorted_values[0]]
    for value in sorted_values[1:]:
        if abs(value - merged[-1]) <= tol:
            merged[-1] = (merged[-1] + value) / 2.0
        else:
            merged.append(value)
    return merged


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def quantize_beat(cx: float, mx0: float, mx1: float, beats_per_bar: int) -> int:
    if mx1 <= mx0:
        return 1

    position = (cx - mx0) / (mx1 - mx0)
    position = max(0.0, min(0.999999, position))
    return int(position * beats_per_bar) + 1


@dataclass
class ChordToken:
    text_raw: str
    text_norm: str
    bbox: BBox
    confidence: float | None = None
    system_index: int | None = None

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0


@dataclass
class MeasureChord:
    text_raw: str
    text_norm: str
    bbox: BBox
    beat: int


@dataclass
class Measure:
    index: int
    row_index: int
    col_index: int
    bbox: BBox
    chords: list[MeasureChord]


@dataclass
class SystemRow:
    index: int
    y_center: float
    y_top: float
    y_bottom: float
    bbox: BBox
    measures: list[Measure]
