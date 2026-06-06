from __future__ import annotations

from typing import Any


def build_public_chord_chart_payload(
    result_payload: dict[str, Any],
) -> dict[str, Any]:
    measures = _iter_measures(result_payload)
    return {
        "job_id": result_payload.get("job_id"),
        "source_file": result_payload.get("source_file"),
        "source_type": result_payload.get("source_type"),
        "title": result_payload.get("title"),
        "composer": result_payload.get("composer"),
        "style": result_payload.get("style"),
        "time_signature": _public_time_signature(
            result_payload.get("time_signature") or {}
        ),
        "beats_per_bar": result_payload.get("beats_per_bar"),
        "measure_count": len(measures),
        "chords": _public_chords(measures),
        "flow": _public_flow(result_payload.get("flow") or {}),
        "warnings": result_payload.get("warnings") or [],
    }


def _iter_measures(result_payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        measure
        for page in result_payload.get("pages") or []
        for system in page.get("systems") or []
        for measure in system.get("measures") or []
    ]


def _public_chords(measures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chords: list[dict[str, Any]] = []
    for measure in measures:
        section = measure.get("section")
        measure_index = measure.get("index")
        for chord in measure.get("chords") or []:
            text = chord.get("text_norm") or chord.get("text_raw")
            if not text:
                continue
            chords.append(
                {
                    "kind": "chord",
                    "text": text,
                    "measure_index": measure_index,
                    "beat": chord.get("beat"),
                    "section": section,
                    "source": "direct",
                }
            )

        for chord in measure.get("resolved_chords") or []:
            text = chord.get("text_norm") or chord.get("text_raw")
            if not text:
                continue
            payload = {
                "kind": "chord",
                "text": text,
                "measure_index": measure_index,
                "beat": chord.get("beat"),
                "section": section,
                "source": "repeat_previous_measure",
            }
            if chord.get("derived_from_measure_index") is not None:
                payload["derived_from_measure_index"] = chord.get(
                    "derived_from_measure_index"
                )
            chords.append(payload)

    return chords


def _public_flow(flow: dict[str, Any]) -> dict[str, Any]:
    return {
        "sections": [
            _copy_keys(
                section,
                ("section", "start_measure_index", "end_measure_index"),
            )
            for section in flow.get("sections") or []
        ],
        "repeat_groups": [
            _copy_keys(
                repeat_group,
                ("start_measure_index", "end_measure_index", "section"),
            )
            for repeat_group in flow.get("repeat_groups") or []
        ],
        "endings": [
            _copy_keys(
                ending,
                ("number", "start_measure_index", "end_measure_index", "section"),
            )
            for ending in flow.get("endings") or []
        ],
        "navigation": [_public_navigation(item) for item in flow.get("navigation") or []],
    }


def _copy_keys(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if payload.get(key) is not None}


def _public_time_signature(time_signature: dict[str, Any]) -> dict[str, Any]:
    return _copy_keys(time_signature, ("numerator", "denominator"))


def _public_navigation(navigation: dict[str, Any]) -> dict[str, Any]:
    payload = _copy_keys(
        navigation,
        ("type", "measure_index", "section", "target_ending"),
    )
    if navigation.get("text_raw") is not None:
        payload["text"] = navigation.get("text_raw")
    return payload
