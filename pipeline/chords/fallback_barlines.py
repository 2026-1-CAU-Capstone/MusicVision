from __future__ import annotations

from typing import NamedTuple

import cv2
import numpy as np

from pipeline.chords.models import merge_close_values


class _StaffBand(NamedTuple):
    y_top: int
    y_bot: int
    height: int


def _to_gray(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return image


def _detect_staff_lines(gray: np.ndarray) -> tuple[np.ndarray, list[_StaffBand]]:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    horizontal_length = max(gray.shape[1] // 8, 40)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_length, 1))
    staff_mask = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)

    row_sums = np.sum(staff_mask > 0, axis=1)
    staff_rows = np.where(row_sums > gray.shape[1] * 0.15)[0]
    if len(staff_rows) == 0:
        return staff_mask, []

    line_groups: list[tuple[int, int]] = []
    start = int(staff_rows[0])
    previous = int(staff_rows[0])
    for row in staff_rows[1:]:
        row = int(row)
        if row - previous > 3:
            line_groups.append((start, previous))
            start = row
        previous = row
    line_groups.append((start, previous))

    average_line_height = np.mean([bottom - top + 1 for top, bottom in line_groups])
    max_intra_gap = max(int(average_line_height * 6), 18)

    bands: list[_StaffBand] = []
    band_start = line_groups[0][0]
    band_end = line_groups[0][1]
    for line_group in line_groups[1:]:
        if line_group[0] - band_end <= max_intra_gap:
            band_end = line_group[1]
            continue

        height = band_end - band_start
        if height >= 10:
            bands.append(_StaffBand(band_start, band_end, height))
        band_start = line_group[0]
        band_end = line_group[1]

    height = band_end - band_start
    if height >= 10:
        bands.append(_StaffBand(band_start, band_end, height))

    return staff_mask, bands


def _estimate_staff_line_thickness(staff_mask: np.ndarray) -> float:
    row_sums = np.sum(staff_mask > 0, axis=1)
    staff_rows = np.where(row_sums > staff_mask.shape[1] * 0.15)[0]
    if len(staff_rows) == 0:
        return 1.0

    groups: list[list[int]] = [[int(staff_rows[0])]]
    for row in staff_rows[1:]:
        row = int(row)
        if row - groups[-1][-1] <= 3:
            groups[-1].append(row)
        else:
            groups.append([row])

    return float(np.median([len(group) for group in groups]))


def _cluster_x_positions(
    items: list[tuple[float, int]],
    *,
    tol: float,
) -> list[list[tuple[float, int]]]:
    clusters: list[list[tuple[float, int]]] = []

    for x, band_index in sorted(items, key=lambda item: item[0]):
        best_index: int | None = None
        best_distance: float | None = None

        for index, cluster in enumerate(clusters):
            center = float(np.mean([value[0] for value in cluster]))
            distance = abs(x - center)
            if distance <= tol and (best_distance is None or distance < best_distance):
                best_index = index
                best_distance = distance

        if best_index is None:
            clusters.append([(float(x), band_index)])
        else:
            clusters[best_index].append((float(x), band_index))

    return clusters


def detect_barlines_cv(
    image: np.ndarray,
    *,
    max_width: int = 12,
    min_density: float = 0.3,
) -> tuple[list[tuple[float, float, float]], np.ndarray]:
    gray = _to_gray(image)
    staff_mask, bands = _detect_staff_lines(gray)
    if not bands:
        return [], np.zeros_like(gray)

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cleaned = cv2.subtract(binary, staff_mask)

    staff_line_height = _estimate_staff_line_thickness(staff_mask)
    close_height = max(3, int(round(staff_line_height * 2.0 + 1.0)))
    if close_height % 2 == 0:
        close_height += 1
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, close_height))
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)

    band_rois: list[tuple[float, float, int]] = []
    local_barlines: list[tuple[float, float, float]] = []
    edge_margin = max(4, int(round(gray.shape[1] * 0.01)))

    for band in bands:
        y0, y1, band_height = band
        pad = max(int(band_height * 0.1), 3)
        expanded_y0 = max(0, y0 - pad)
        expanded_y1 = min(gray.shape[0], y1 + pad)
        band_rois.append((float(expanded_y0), float(expanded_y1), int(band_height)))

        roi = cleaned[expanded_y0:expanded_y1, :]
        if roi.size == 0:
            continue

        candidate_height = max(3, int(round(float(band_height) * 0.75)))
        candidate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, candidate_height))
        vertical = cv2.morphologyEx(roi, cv2.MORPH_OPEN, candidate_kernel)

        label_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            (vertical > 0).astype(np.uint8),
            8,
        )

        candidates: list[dict[str, float | int]] = []
        for label in range(1, label_count):
            x, _y, width, height, _area = [int(value) for value in stats[label]]
            if height < candidate_height or width > max_width:
                continue

            center_x = float(x + (width - 1) / 2.0)
            if center_x < edge_margin or center_x > gray.shape[1] - edge_margin:
                continue

            integer_x = int(round(center_x))
            left = max(0, integer_x - 8)
            right = min(roi.shape[1], integer_x + 9)
            neighbour = roi[:, left:right].copy()
            cut_start = max(0, integer_x - 1 - left)
            cut_end = min(right - left, integer_x + 2 - left)
            neighbour[:, cut_start:cut_end] = 0
            side_ink = int(np.count_nonzero(neighbour))

            center = roi[:, max(0, integer_x - 1) : min(roi.shape[1], integer_x + 2)] > 0
            occupancy = float(np.any(center, axis=1).sum()) / float(max(roi.shape[0], 1))
            if occupancy < min_density:
                continue

            candidates.append(
                {
                    "x": center_x,
                    "w": int(width),
                    "h": int(height),
                    "side_ink": side_ink,
                    "occupancy": occupancy,
                }
            )

        for candidate in candidates:
            parallel = sum(
                1
                for other in candidates
                if other is not candidate and abs(float(other["x"]) - float(candidate["x"])) <= 4.0
            )
            candidate["score"] = (
                2.0 * float(candidate["occupancy"])
                + 0.4 * min(float(candidate["h"]) / max(float(band_height), 1.0), 1.3)
                + (0.6 if int(candidate["w"]) >= 2 else 0.0)
                + (0.8 if parallel else 0.0)
                - min(float(candidate["side_ink"]) / 35.0, 2.0)
            )

        minimum_spacing = max(24, int(round(float(band_height) * 2.0)))
        kept: list[dict[str, float | int]] = []
        for candidate in sorted(candidates, key=lambda item: float(item["score"]), reverse=True):
            if float(candidate["score"]) < 1.1:
                continue
            if any(abs(float(candidate["x"]) - float(other["x"])) < minimum_spacing for other in kept):
                continue
            kept.append(candidate)

        for candidate in kept:
            local_barlines.append(
                (float(candidate["x"]), float(expanded_y0), float(expanded_y1))
            )

    aligned_candidates: list[tuple[float, int]] = []
    for band_index, (expanded_y0, expanded_y1, band_height) in enumerate(band_rois):
        roi = binary[int(expanded_y0) : int(expanded_y1), :]
        if roi.size == 0:
            continue

        kernel_height = max(3, int(round(float(band_height) * 0.8)))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_height))
        vertical = cv2.morphologyEx(roi, cv2.MORPH_OPEN, vertical_kernel)

        label_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            (vertical > 0).astype(np.uint8),
            8,
        )
        for label in range(1, label_count):
            x, _y, width, height, _area = [int(value) for value in stats[label]]
            if width > max_width or height < kernel_height:
                continue
            aligned_candidates.append((float(x + (width - 1) / 2.0), band_index))

    aligned_barlines: list[tuple[float, float, float]] = []
    support_needed = max(2, int(np.ceil(len(bands) * 0.75)))
    aligned_clusters = _cluster_x_positions(
        aligned_candidates,
        tol=max(3.0, float(max_width) / 3.0),
    )

    strong_x_positions: list[float] = []
    for cluster in aligned_clusters:
        band_support = len({band_index for _x, band_index in cluster})
        if band_support >= support_needed:
            strong_x_positions.append(float(np.mean([x for x, _band_index in cluster])))

    strong_x_positions = merge_close_values(
        strong_x_positions,
        tol=max(2.0, float(max_width) / 2.0),
    )
    if len(strong_x_positions) >= 4:
        for expanded_y0, expanded_y1, _band_height in band_rois:
            for x in strong_x_positions:
                aligned_barlines.append((x, expanded_y0, expanded_y1))

    result = aligned_barlines if aligned_barlines else local_barlines
    result.sort(key=lambda barline: (barline[1], barline[0]))
    return result, cleaned
