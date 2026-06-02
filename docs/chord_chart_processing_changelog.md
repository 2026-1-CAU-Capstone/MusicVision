# Chord Chart Processing Changelog

This file records the design and implementation history for MusicVision's
chord-chart processing branch. It is separate from the sheet-music chord
processing notes because this pipeline does not run HOMR, does not produce
MusicXML, and has to understand chart-flow notation as well as chord symbols.

## Current document map

- `docs/sheet_music_chord_processing.md` documents printed chords on sheet music.
- `docs/sheet_music_chord_processing_changelog.md` tracks that sheet-music branch.
- `docs/chord_charts.md` documents the chord-chart API contract and payload shape.
- `docs/chord_chart_processing_changelog.md` tracks this chord-chart branch.
- `docs/chord_chart_processing_performance.md` tracks local runtime measurements.

## 2026-06-02 - Initial chord-chart API design

### Starting point

MusicVision already had a chord-only sheet-music API:

```text
POST /chords/sheet-music/process
```

That endpoint is still sheet-music oriented. It uses HOMR visual geometry,
assigns OCR-read chord symbols to staff measures, and writes
`chord_assignments.json`.

The chord-chart samples under `resources/chord_charts/` were different enough to
justify a separate branch:

- chart grids are the primary geometry, not staves
- barlines define measure cells directly
- the image may not contain notes, staves, or MusicXML-worthy notation
- the payload needs chart-flow symbols such as repeats, endings, `%`, `Fine`,
  and `D.C. al ...`
- chord symbols may be written with jazz glyphs, stacked slash-bass notation, or
  everyday linear notation

The design goal was therefore not "reuse the sheet-music OCR endpoint with a few
flags." The goal was a separate chart parser with a DTO that resembles
`chord_assignments.json` where useful, but models chart-specific semantics
directly.

### Initial API boundary

Added a synchronous chart endpoint:

```text
POST /chords/chart/process
```

Added a retrieval endpoint for the generated structured artifact:

```text
GET /omr/jobs/{job_id}/chord-chart
```

The endpoint accepts raster uploads, skips HOMR, and writes:

```text
chord_chart.json
chord_chart_overlay.png
```

The job-status response was extended with `chord_chart_path` so callers can tell
whether a completed job produced a chart artifact.

### DTO shape

The chart payload keeps the same broad page/system/measure shape used by the
sheet-music chord assignment payload:

```text
pages[]
  systems[]
    measures[]
      chords[]
```

The chart DTO then adds fields that only make sense for chord charts:

- `source_type: "chord_chart"`
- `pipeline: "chart_grid_ocr"`
- `time_signature`
- `beats_per_bar`
- measure-level `symbols`
- measure-level `navigation`
- `flow.repeat_groups`
- `flow.endings`
- `flow.navigation`
- `chart_ocr.accepted_tokens`
- `chart_ocr.rejected_hits`
- `chart_ocr.unassigned_tokens`
- `chart_ocr.detected_symbols`

Each chord still includes a normalized `text_norm` plus parsed components:

```json
{
  "text_raw": "Bb△7",
  "text_norm": "Bbmaj7",
  "components": {
    "root": "B",
    "accidental": "b",
    "quality": "major",
    "extensions": ["7"],
    "alterations": [],
    "bass": null
  }
}
```

The important design choice was to preserve written chart symbols separately from
resolved musical meaning. For example, a percent-repeat measure keeps the `%`
symbol and also receives `resolved_chords` copied from the previous measure.

### Initial implementation steps

Added a new `pipeline/chord_charts/` package:

- `chord_symbol.py` parses and normalizes chart chord symbols.
- `ocr_backend.py` extracts chart OCR tokens.
- `parser.py` detects the chart grid, assigns OCR tokens to measure cells, and
  builds `chord_chart.json`.
- `overlay.py` renders a diagnostic chart overlay.

Added export and service support:

- `pipeline/export.py` writes `chord_chart.json`.
- `app/services/omr_service.py` runs the chart pipeline.
- `app/api/endpoints/omr.py` exposes processing and retrieval routes.
- `app/schemas/omr.py` defines the chart response schema.
- `app/services/job_service.py` persists the chart artifact path.

Added docs and tests:

- `docs/chord_charts.md`
- API integration doc updates under `docs/api/`
- API route tests
- parser tests for grid symbols and flow
- symbol-normalization tests

### Initial parser strategy

The first parser was intentionally geometry-first:

1. Convert the image to grayscale and threshold it.
2. Use vertical morphology to find barline-like components.
3. Cluster vertical components into chart rows.
4. Convert each row's barlines into measure cells.
5. Classify OCR tokens into time signatures, section markers, endings,
   navigation, repeat symbols, slash bass notes, and chord symbols.
6. Assign chord tokens to the nearest measure cell.
7. Resolve `%` measures against the previous resolved measure.
8. Emit both structured JSON and an overlay image.

That approach was chosen because clean Real Book-style charts expose reliable
measure geometry even when OCR is noisy. Barlines are often easier to detect
than chord text, so they make a stable scaffold for interpreting the rest.

### Initial chart features supported

The initial pass was built to cover the requested chart features:

- repeat marks from boundary dots and double barlines
- split endings such as `[1` and `[2`
- section markers such as `A`, `B`, and `C`
- percent signs meaning "same as previous measure"
- navigation text such as `Fine` and `D.C. al 2nd ending`
- time signatures such as `4/4`
- measures containing one or more chords
- inline slash chords such as `G-7/F`
- stacked slash-bass notation where the bass note appears below the chord

## 2026-06-02 - Robust symbol and layout fixes from `After You've Gone`

### Problem report

The first real `After You've Gone` run showed that the broad DTO and grid parser
were useful, but EasyOCR produced many wrong chord reads. The main recurring
issues were:

- flats in chords such as `Ab7` and `Gb7`
- minor dashes in `F-7`, `Eb-6`, and `D-7`
- complete recognition of `D-7`
- measures with two chords
- triangle major-seventh notation in `Bb△7` and `Eb△7`
- slash chords such as `G-7/F` and `Bb6/F`
- the `6` in `Bb6`
- diminished `o` versus half-diminished slashed `ø`

The important pattern was that the chart notation was not always read as a
linear string. OCR often saw the visual pieces independently:

- `Eb△7` became variants such as `Elz`.
- `Bb△7` became variants such as `Bhz`, `Baz`, `Bzz`, or `B4z`.
- `Ab7` became `Az`.
- `Bb6` became `Bs`.
- `A-7` could become `A` plus nearby non-chord fragments such as `U/`.
- `G-7 G-7/F` could become `G61`, `0-7`, `0-`, and a lower `F`.
- `Bb6/F` could become `Bp`, a separate `6`, and a lower `e` that visually
  represented the bass `F`.

So the fix could not be a list of measure numbers. It needed to make the parser
better at using local OCR context and notation layout.

### OCR changes

The chart OCR backend was expanded from whole-cell OCR to multiple per-cell
regions:

- full cell
- top portion
- bottom portion
- left half
- right half
- low portion

The crop now extends farther below the detected row while staying above the next
row. This helps stacked slash-bass notation because the bass note is often below
the main chord text and can sit outside the strict barline height.

Each token keeps its `source`, so the parser can prefer cell-level OCR when it
is available and still preserve page-level diagnostics.

### Symbol-normalization changes

`pipeline/chord_charts/chord_symbol.py` was updated to normalize both everyday
linear notation and common chart/OCR spellings.

Examples:

```text
Bb△7    -> Bbmaj7
Eb-△7   -> EbmMaj7
Abm7b5  -> Abm7b5
Ab-7b5  -> Abm7b5
Bb6/F   -> Bb6/F
```

Observed OCR repairs were added only when they described reusable visual
patterns:

```text
Elz, Ebaz        -> flat/triangle major-seventh shapes
Bhz, Baz, Bzz    -> Bb major-seventh shapes
B4z              -> Bb major-seventh with triangle/7 confusion
Bp               -> Bb root fragment
Az               -> Ab7 when the OCR read flat+7 as z-like text
Bs               -> Bb6
Fz               -> F7
Fz5              -> F7#5
0D113, D113      -> D7b13
G719             -> G7b9
```

A deliberately too-broad repair was rejected during testing: globally treating
`0-7` as `Gm7` fixed one stacked `G-7/F` case, but it also broke true `D-7`
measures where OCR produced a nearby `0-7` fragment. That logic was moved out of
the symbol normalizer and into parser context, where geometry can decide whether
the fragment is part of an existing chord or a second chord in the measure.

### Parser context changes

`MeasureCell` now keeps the OCR tokens assigned to that measure. After initial
token classification, the parser groups chords and raw OCR tokens by x-position.
Within each group, it can infer missing chord information from nearby fragments.

This repairs cases where OCR produced a partial chord plus extra evidence:

- `A` with a nearby minor/seventh-looking fragment becomes `Am7`.
- `F-` plus a seventh cue becomes `Fm7`.
- a standalone `6` near a flat-root fragment helps preserve `Bb6`.
- major-seventh candidates win over weaker dominant-seventh reads when triangle
  cues are present.

The parser then deduplicates overlapping OCR candidates by score. The scoring
prefers richer and more explicit chord parses:

- accidentals
- non-major qualities
- extensions
- alterations
- slash bass notes
- major-seventh readings

### Rootless minor-fragment changes

Rootless fragments such as `0-7` and `0-` are now contextual.

If the fragment is close to an already-detected chord group, it is treated as
evidence for that chord. This protects `D-7`, where OCR may produce both `D-7`
and `0-7` in the same x-region.

If the fragment is separated later in the same measure, the parser may borrow
the root from the earlier same-measure chord and create a repeated minor chord.
That repairs the chart pattern:

```text
G-7 G-7/F
```

where OCR can see the second `G-7` mostly as `0-` plus a lower `F`.

### Stacked slash-bass changes

Stacked slash-bass notation is handled as layout, not only as text.

The parser now checks each measure for a visible diagonal slash in the lower
portion of the cell. When a lower single-letter root appears under an upper
chord and the slash geometry is present, that lower root can attach as the bass:

```text
Gm7 + lower F  -> Gm7/F
Bb6 + lower F  -> Bb6/F
```

This also handles an observed OCR case where a lower `F` was read as `e`. That
repair is only allowed when the visual slash is present and the token is in the
lower bass position, so it stays tied to stacked slash notation instead of
becoming a global `e -> F` rule.

### Regression tests added

The test suite now covers:

- chart glyph notation and everyday linear notation
- OCR repairs for flat/triangle/seventh spellings
- section markers, repeat symbols, endings, navigation, and percent repeats
- fragmented quality recovery such as `A` plus a nearby minor/seventh cue
- stacked `Bb6/F` bass recovery
- contextual rootless fragments that help `D-7` without turning it into `Gm7`
- repeated rootless minor fragments that recover `Gm7 Gm7/F`

## Current `After You've Gone` result

The regenerated chart output matches the supplied chord sequence, normalized
into linear symbols:

```text
Ebmaj7  %  Ebm6  Ab7
Bbmaj7  %  Dm7   G7
C7      %  F7    %
Bb6     %  Fm7   Bb7
Ebmaj7  %  Ebm6  Ab7
Bbmaj7  %  Dm7   G7
Cm7     G7 Cm7   EbmMaj7 Ab7
Bbmaj7  Am7 D7   Gm7 Gm7/F  Edim7
Bb6/F   G7 Cm7   F7
Bb6     %  Fm7   Bb7
```

The output uses normalized forms:

- `△7` becomes `maj7`
- `-` becomes `m`
- `o7` becomes `dim7`
- `%` measures keep a repeat symbol and receive `resolved_chords`

Verification at the time of this entry:

```text
.venv\Scripts\python.exe -m pytest
47 passed
```

The real chart regeneration was CPU-bound because EasyOCR ran without a GPU.

## 2026-06-03 - Preserve job history by rejecting duplicate job IDs

The processing endpoints now fail fast when a requested `job_id` already has a
directory under `storage/jobs`. This prevents a later run from overwriting
existing uploads, outputs, status files, or overlays.

The API returns:

```text
409 Conflict
job_id already exists. Use a new job_id to preserve existing job artifacts.
```

This was added after a reviewed `After You've Gone` run was regenerated into the
same `storage/jobs` folder, which erased the previous artifact snapshot and made
it harder to compare improvement history.

Verification:

```text
.venv\Scripts\python.exe -m pytest tests\test_api.py
```

## 2026-06-03 - Added dev/prod async chord-chart endpoints

Chord-chart processing now has async dev/prod routes alongside the synchronous
route:

```text
POST /chords/chart/process
POST /chords/chart/dev/process
POST /chords/chart/prod/process
```

The dev/prod endpoints queue the chart pipeline and return `202 Accepted`.
Completion and failure callbacks use the same callback sender as the OMR async
endpoints. Completed chart callbacks include `chord_chart_path`.

Both chart async endpoints require `X-OMR-API-Key` and fail closed if
`OMR_API_KEY` is not configured. The prod chart endpoint uses the same callback
host whitelist as `POST /omr/prod/process`: the request `callback_url` must be an
absolute `http(s)` URL whose host matches `OMR_CALLBACK_URL`.

Verification:

```text
.venv\Scripts\python.exe -m pytest tests\test_api.py
```

## 2026-06-03 - Filtered lowercase `a` from split `D.C. al ...` navigation

Some OCR runs split `D.C. al 2nd ending` into separate tokens. In that case the
lowercase `a` from `al` could be parsed as an `A` chord, sometimes after slash
recovery as `A/A`.

This did not irreparably damage the chart payload: it was a localized false
positive in one measure's `chords` list. It did not alter the detected grid, job
status, artifact paths, or any previously parsed chord cells. If the full
navigation phrase was also detected, the `flow.navigation` data remained usable.

The parser now removes a lowercase `a` chord candidate when it appears in the
lower navigation area of a measure and nearby OCR contains navigation context
such as `D.C.`, `al`, or `ending`. This keeps real uppercase `A` chord symbols
available while filtering the common split-navigation artifact.

Verification:

```text
.venv\Scripts\python.exe -m pytest tests\test_chord_chart_parser.py tests\test_chord_chart_symbols.py
```

## Current limits

The chord-chart parser is still designed for clean grid charts. It is not a
lyrics-over-chords parser, and it does not yet expand a complete playback order
from repeats/endings/navigation. The `flow` block preserves those symbols so a
future form-expansion pass can reason over them explicitly.

Future improvements should be driven by additional reviewed charts. The
preferred pattern is to add reusable OCR/layout repairs and regression tests,
rather than hardcoding song-specific measure fixes.
