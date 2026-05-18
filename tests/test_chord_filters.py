from __future__ import annotations

import cv2
import numpy as np

from pipeline.chords.models import ChordToken
from pipeline.chords.token_filters import filter_probable_non_chords


def test_filters_circled_rehearsal_marks_but_keeps_uncircled_single_letter_chords() -> None:
    image = np.full((100, 120, 3), 255, dtype=np.uint8)
    cv2.circle(image, (28, 28), 18, (0, 0, 0), 2)

    kept, filtered = filter_probable_non_chords(
        tokens=[
            ChordToken("8", "B", (20, 18, 36, 40), confidence=0.9),
            ChordToken("F", "F", (72, 10, 84, 28), confidence=0.9),
        ],
        image=image,
        geometry={
            "systems": [
                {"index": 1, "bbox": [0, 60, 120, 90]},
            ]
        },
    )

    assert [token.text_norm for token in kept] == ["F"]
    assert len(filtered) == 1
    assert filtered[0]["reason"] == "circled_rehearsal_mark"


def test_filters_single_letter_glyphs_that_touch_the_staff() -> None:
    kept, filtered = filter_probable_non_chords(
        tokens=[
            ChordToken("e", "E", (20, 20, 40, 61), confidence=0.9),
            ChordToken("F", "F", (72, 10, 84, 28), confidence=0.9),
        ],
        image=np.full((100, 120, 3), 255, dtype=np.uint8),
        geometry={
            "systems": [
                {"index": 1, "bbox": [0, 60, 120, 90]},
            ]
        },
    )

    assert [token.text_norm for token in kept] == ["F"]
    assert len(filtered) == 1
    assert filtered[0]["reason"] == "single_letter_touches_staff"
    assert filtered[0]["metrics"]["token_bottom_to_staff_top_px"] == -1.0
