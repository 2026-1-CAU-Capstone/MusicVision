# Chord Chart Processing API

MusicVision exposes a separate chord-chart pipeline for Real Book-style chart
grids. It does not run HOMR and does not produce MusicXML.

```text
POST /chords/chart/process
GET  /omr/jobs/{job_id}/chord-chart
```

The endpoint accepts raster uploads:

```text
.png
.jpg
.jpeg
```

## Pipeline

```text
upload
  -> load image
  -> OCR chart text
  -> detect chart rows and measure cells from barlines
  -> classify tokens as chords, repeat symbols, endings, sections, or navigation
  -> normalize chord symbols
  -> resolve percent repeats against the previous measure
  -> write chord_chart.json and chord_chart_overlay.png
```

## Supported Chart Features

The first implementation is designed for clean grid charts like the samples under
`resources/chord_charts/`:

- section markers such as `A`, `B`, and `C`
- time signatures such as `4/4`
- repeat boundaries
- first/second endings
- percent signs meaning repeat the previous measure
- navigation text such as `Fine` and `D.C. al 2nd ending`
- slash chords written inline or stacked vertically
- jazz glyph notation and everyday linear notation

The chord normalizer accepts common equivalents such as:

```text
Abm7b5
Abmin7b5
Ab-7b5
Abø7
Bb△7
BbΔ7
G-7/F
Bb6/F
```

Those are normalized into everyday linear `text_norm` values such as `Abm7b5`,
`Bbmaj7`, `Gm7/F`, and `Bb6/F`.

## Payload Shape

`chord_chart.json` keeps the same broad page/system/measure shape as
`chord_assignments.json`, but it stores chart-specific flow symbols.

```json
{
  "job_id": "demo-chart",
  "source_file": "cherokee_chord_chart.jpg",
  "source_type": "chord_chart",
  "pipeline": "chart_grid_ocr",
  "title": "Cherokee",
  "composer": "Ray Noble",
  "style": "Up Tempo Swing",
  "time_signature": {
    "text_raw": "4/4",
    "numerator": 4,
    "denominator": 4,
    "source": "ocr",
    "confidence": 0.92
  },
  "beats_per_bar": 4,
  "flow": {
    "repeat_groups": [
      {
        "start_measure_index": 1,
        "end_measure_index": 16,
        "section": "A"
      }
    ],
    "endings": [
      {
        "number": 1,
        "start_measure_index": 13,
        "end_measure_index": 16,
        "section": "A"
      }
    ],
    "navigation": [
      {
        "type": "fine",
        "text_raw": "Fine",
        "measure_index": 20,
        "section": "A"
      }
    ]
  },
  "pages": [
    {
      "page": 1,
      "assignment_source": "chart_grid_detection",
      "systems": [
        {
          "index": 1,
          "section": "A",
          "measures": [
            {
              "index": 1,
              "row_measure_index": 1,
              "section": "A",
              "left_boundary": { "kind": "start_repeat" },
              "right_boundary": { "kind": "single" },
              "chords": [
                {
                  "text_raw": "Bb6",
                  "text_norm": "Bb6",
                  "text_display": "Bb6",
                  "beat": 1,
                  "components": {
                    "root": "B",
                    "accidental": "b",
                    "quality": "major",
                    "extensions": ["6"],
                    "alterations": [],
                    "bass": null
                  }
                }
              ],
              "symbols": [],
              "navigation": []
            }
          ]
        }
      ]
    }
  ],
  "chart_ocr": {
    "backend": "easyocr",
    "accepted_tokens": [],
    "rejected_hits": [],
    "unassigned_tokens": [],
    "detected_symbols": []
  },
  "warnings": []
}
```

Percent-repeat measures preserve both the written symbol and the resolved chord
copy:

```json
{
  "symbols": [
    {
      "type": "repeat_previous_measure",
      "text_raw": "%",
      "resolved_from_measure_index": 3
    }
  ],
  "resolved_chords": [
    {
      "text_norm": "Ebmaj7",
      "derived_from_measure_index": 3
    }
  ]
}
```

## Current Limits

This parser is intentionally chart-specific. It is not a lyrics-over-chords
parser and it does not infer a complete performed playback order yet. The
`flow` block records repeats, endings, and navigation symbols so a later pass can
expand playback form explicitly.
