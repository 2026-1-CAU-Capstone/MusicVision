# Chord Chart Processing API

MusicVision exposes a separate chord-chart pipeline for Real Book-style chart
grids. It does not run HOMR and does not produce MusicXML.

For the design and implementation history behind this API, see
[`chord_chart_processing_changelog.md`](chord_chart_processing_changelog.md).
For local runtime baselines, see
[`chord_chart_processing_performance.md`](chord_chart_processing_performance.md).

```text
POST /chords/chart/process
POST /chords/chart/dev/process
POST /chords/chart/prod/process
GET  /omr/jobs/{job_id}/chord-chart
```

All chart processing endpoints accept raster uploads:

```text
.png
.jpg
.jpeg
.webp
```

## Pipeline

```text
upload
  -> preprocess image
  -> load image
  -> OCR chart text
  -> detect chart rows and measure cells from barlines
  -> scan chart rows and selected chord subregions when needed
  -> classify tokens as chords, repeat symbols, endings, sections, or navigation
  -> normalize chord symbols
  -> resolve percent repeats against the previous measure
  -> write chord_chart.json, chord_chart_debug.json, and overlays
```

`POST /chords/chart/process` runs synchronously and returns the chart payload
inline. `POST /chords/chart/dev/process` and
`POST /chords/chart/prod/process` queue the same pipeline and return
`202 Accepted`; callback completion payloads include `chord_chart_path`.

The dev/prod chart endpoints require `X-OMR-API-Key`. The prod chart endpoint
also requires a request `callback_url` whose host matches the configured
`OMR_CALLBACK_URL` host.

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
Aø7
Bb△7
Eb-△7
G-7/F
Bb6/F
```

Those are normalized into everyday linear `text_norm` values such as `Abm7b5`,
`Am7b5`, `Bbmaj7`, `EbmMaj7`, `Gm7/F`, and `Bb6/F`.

## Payload Shape

`chord_chart.json` is the public contract for the Spring Boot backend and
frontend. It intentionally contains only the final chart result: chart metadata,
the final chord stream, section/repeat/ending/navigation flow, and warnings.

Parser evidence, OCR tokens, coordinates, raw/corrected fragments, and overlay
diagnostics are kept in `chord_chart_debug.json` for MusicVision debugging. The
backend should not depend on `chord_chart_debug.json`.

`POST /chords/chart/process` returns the same public payload inline under
`chord_chart` and stores it at `chord_chart_path`. Async dev/prod endpoints
return a queued job response; after completion, Spring Boot should fetch the same
payload through `GET /omr/jobs/{job_id}/chord-chart`.

```json
{
  "job_id": "demo-chart",
  "source_file": "cherokee_chord_chart.jpg",
  "source_type": "chord_chart",
  "title": "Cherokee",
  "composer": "Ray Noble",
  "style": "Up Tempo Swing",
  "time_signature": {
    "numerator": 4,
    "denominator": 4
  },
  "beats_per_bar": 4,
  "measure_count": 36,
  "chords": [
    {
      "kind": "chord",
      "text": "Bb6",
      "measure_index": 1,
      "beat": 1,
      "section": "A",
      "source": "direct"
    },
    {
      "kind": "chord",
      "text": "%",
      "measure_index": 2,
      "beat": 1,
      "section": "A",
      "source": "repeat_previous_measure",
      "derived_from_measure_index": 1
    },
    {
      "kind": "chord",
      "text": "G7b9",
      "measure_index": 14,
      "beat": 2,
      "section": "A",
      "source": "direct"
    }
  ],
  "flow": {
    "sections": [
      {
        "section": "A",
        "start_measure_index": 1,
        "end_measure_index": 20
      },
      {
        "section": "B",
        "start_measure_index": 21,
        "end_measure_index": 36
      }
    ],
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
        "measure_index": 20,
        "section": "A",
        "text": "Fine"
      },
      {
        "type": "dc_al_ending",
        "measure_index": 36,
        "section": "B",
        "target_ending": 2,
        "text": "D.C. al 2nd ending"
      }
    ]
  },
  "warnings": []
}
```

### Public Fields

Top-level fields:

- `job_id`: MusicVision job id.
- `source_file`: original upload filename.
- `source_type`: always `"chord_chart"`.
- `title`, `composer`, `style`: chart metadata when detected or inferred.
- `time_signature`: currently `numerator` and `denominator`.
- `beats_per_bar`: numeric beat count used for chord placement.
- `measure_count`: number of detected chart measures.
- `chords`: final chord events in reading order.
- `flow`: section, repeat, ending, and navigation structure.
- `warnings`: non-fatal processing warnings.

Chord event fields:

- `kind`: currently `"chord"`.
- `text`: final normalized chord symbol. Percent-repeat measures use `"%"`.
- `measure_index`: 1-based chart measure index.
- `beat`: beat position inside the measure. Multi-chord measures may use later
  beats, for example beat `2`.
- `section`: section label such as `"A"` or `"B"` when known.
- `source`: `"direct"` for written chords or `"repeat_previous_measure"` for `%`.
- `derived_from_measure_index`: present only for repeat-derived events.

Flow fields:

- `flow.sections[]`: section spans.
- `flow.repeat_groups[]`: detected repeat spans.
- `flow.endings[]`: first/second ending spans.
- `flow.navigation[]`: navigation marks such as `Fine` and
  `D.C. al 2nd ending`.

Percent-repeat measures expose the written repeat symbol to the frontend by
returning `text: "%"`. The repeated musical source remains available through
`source` and `derived_from_measure_index`:

```json
{
  "kind": "chord",
  "text": "%",
  "measure_index": 2,
  "beat": 1,
  "section": "A",
  "source": "repeat_previous_measure",
  "derived_from_measure_index": 1
}
```

### Debug Artifact

`chord_chart_debug.json` is not part of the Spring Boot contract. It may include:

- `pages`, `systems`, and `measures`
- full parsed chord components
- `chart_ocr.accepted_tokens`, `rejected_hits`, and `unassigned_tokens`
- semantic crop fragments for `root`, `root_accidental`, and suffix regions
- raw OCR text, corrected text, confidences, and bounding boxes
- parser strategy metadata

This file is allowed to change as the OCR strategy changes.

## Current Limits

This parser is intentionally chart-specific. It is not a lyrics-over-chords
parser and it does not infer a complete performed playback order yet. The
`flow` block records repeats, endings, and navigation symbols so a later pass can
expand playback form explicitly.
