from __future__ import annotations

from dataclasses import dataclass
import re

import cv2
import numpy as np


@dataclass(frozen=True)
class _SuffixComponent:
    x: int
    y: int
    width: int
    height: int
    area: int
    contour: np.ndarray
    aspect: float
    fill: float
    solidity: float
    fine_vertices: int
    coarse_vertices: int

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2.0


def normalize_suffix_ocr_text(text: str, image: np.ndarray | None) -> str:
    """Use cheap visual cues in a suffix crop to correct OCR confusions."""
    if image is None:
        return text

    compact = re.sub(r"\s+", "", text or "").strip(".,;:!|[](){}")
    if not compact:
        return text

    if compact in {"77", "777"} and suffix_has_minor_dash(image):
        return "-7"
    if compact in {"76", "776"} and suffix_has_minor_dash(image):
        return "-6"

    zero_seventh = compact in {"07", "0z", "0Z", "O7", "Oz", "o7", "oz"}
    zero_only = compact in {"0", "O", "o"}
    if zero_seventh or zero_only:
        extension = "7" if zero_seventh else ""
        zero_like_shape = classify_zero_like_suffix(image)
        if zero_like_shape == "half_diminished":
            return f"\u00f8{extension}"
        if zero_like_shape == "diminished":
            return f"\u00b0{extension}"
        if zero_like_shape == "triangle":
            return f"\u25b3{extension}"

    return text


def classify_zero_like_suffix(image: np.ndarray) -> str | None:
    binary = _binary_suffix_crop(image)
    if binary is None:
        return None

    component = _left_zero_like_component(binary)
    if component is None:
        return None
    if _component_is_triangle(component):
        return "triangle"
    if _component_is_circle_like(component):
        if _component_has_center_slash(binary, component):
            return "half_diminished"
        return "diminished"
    return None


def suffix_has_minor_dash(image: np.ndarray) -> bool:
    binary = _binary_suffix_crop(image)
    if binary is None:
        return False

    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    crop_height, crop_width = binary.shape[:2]
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 8:
            continue
        aspect = width / max(float(height), 1.0)
        center_x = x + width / 2.0
        center_y = y + height / 2.0
        if (
            aspect >= 2.0
            and width >= max(8, crop_width * 0.08)
            and height <= max(8, crop_height * 0.18)
            and center_x <= crop_width * 0.52
            and crop_height * 0.18 <= center_y <= crop_height * 0.82
        ):
            return True

    return False


def suffix_has_half_diminished(image: np.ndarray) -> bool:
    return classify_zero_like_suffix(image) == "half_diminished"


def suffix_has_diminished_circle(image: np.ndarray) -> bool:
    return classify_zero_like_suffix(image) in {"diminished", "half_diminished"}


def suffix_has_triangle(image: np.ndarray) -> bool:
    return classify_zero_like_suffix(image) == "triangle"


def _binary_suffix_crop(image: np.ndarray) -> np.ndarray | None:
    if image.size == 0:
        return None
    if image.ndim == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _threshold, binary = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    return binary


def _left_zero_like_component(binary: np.ndarray) -> _SuffixComponent | None:
    components = _zero_like_components(binary)
    if not components:
        return None
    return min(components, key=lambda component: (component.x, component.y))


def _zero_like_components(binary: np.ndarray) -> list[_SuffixComponent]:
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    crop_height, crop_width = binary.shape[:2]
    components: list[_SuffixComponent] = []

    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 24 or width < 8 or height < 8:
            continue
        center_x = x + width / 2.0
        center_y = y + height / 2.0
        if center_x > crop_width * 0.48:
            continue
        if center_y < crop_height * 0.30 or center_y > crop_height * 0.90:
            continue
        aspect = width / max(float(height), 1.0)
        if aspect > 1.75:
            continue
        fill = area / max(float(width * height), 1.0)
        if fill <= 0.08:
            continue

        component_labels = labels[y : y + height, x : x + width]
        component_mask = np.where(component_labels == index, 255, 0).astype(np.uint8)
        contours, _hierarchy = cv2.findContours(
            component_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        perimeter = cv2.arcLength(contour, closed=True)
        if perimeter <= 0:
            continue
        fine = cv2.approxPolyDP(contour, 0.03 * perimeter, closed=True)
        coarse = cv2.approxPolyDP(contour, 0.08 * perimeter, closed=True)
        contour_area = cv2.contourArea(contour)
        hull_area = cv2.contourArea(cv2.convexHull(contour))
        solidity = contour_area / max(float(hull_area), 1.0)

        components.append(
            _SuffixComponent(
                x=int(x),
                y=int(y),
                width=int(width),
                height=int(height),
                area=int(area),
                contour=contour,
                aspect=float(aspect),
                fill=float(fill),
                solidity=float(solidity),
                fine_vertices=len(fine),
                coarse_vertices=len(coarse),
            )
        )

    return components


def _component_is_triangle(component: _SuffixComponent) -> bool:
    if component.coarse_vertices == 3:
        return True
    if component.coarse_vertices == 4:
        return component.solidity <= 0.74
    return False


def _component_is_circle_like(component: _SuffixComponent) -> bool:
    rounded_four_vertex = (
        component.coarse_vertices == 4 and component.solidity >= 0.82
    )
    if component.fine_vertices < 5 and not rounded_four_vertex:
        return False
    if component.coarse_vertices < 5 and not rounded_four_vertex:
        return False
    if not (0.45 <= component.aspect <= 1.55):
        return False
    return 0.12 <= component.fill <= 0.78


def _component_has_center_slash(
    binary: np.ndarray,
    component: _SuffixComponent,
) -> bool:
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180.0,
        threshold=12,
        minLineLength=max(10, int(min(binary.shape[:2]) * 0.12)),
        maxLineGap=6,
    )
    if lines is None:
        return False

    for line in lines[:, 0]:
        x0, y0, x1, y1 = [float(value) for value in line]
        dx = x1 - x0
        dy = y1 - y0
        length = float(np.hypot(dx, dy))
        if length < max(10.0, min(component.width, component.height) * 0.40):
            continue
        if _point_to_segment_distance(
            component.center_x,
            component.center_y,
            x0,
            y0,
            x1,
            y1,
        ) > max(3.0, min(component.width, component.height) * 0.18):
            continue
        if _line_spans_component(x0, y0, x1, y1, component):
            return True

    return False


def _line_spans_component(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    component: _SuffixComponent,
) -> bool:
    overlap_x = max(
        0.0,
        min(max(x0, x1), component.x + component.width) - max(min(x0, x1), component.x),
    )
    overlap_y = max(
        0.0,
        min(max(y0, y1), component.y + component.height)
        - max(min(y0, y1), component.y),
    )
    return (
        overlap_x >= component.width * 0.35
        and overlap_y >= component.height * 0.12
    ) or (
        overlap_y >= component.height * 0.35
        and overlap_x >= component.width * 0.12
    )


def _point_to_segment_distance(
    px: float,
    py: float,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> float:
    dx = x1 - x0
    dy = y1 - y0
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return float(np.hypot(px - x0, py - y0))

    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_squared))
    closest_x = x0 + t * dx
    closest_y = y0 + t * dy
    return float(np.hypot(px - closest_x, py - closest_y))
