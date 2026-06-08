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

## 2026-06-07 - Glyph-specific semantic OCR and root-anchor multi-chord probing

### OCR-level glyph normalization trials

The Autumn Leaves and Cherokee charts showed repeated OCR confusions that were
not isolated spelling mistakes. The pipeline now handles those cases at the
OCR-crop boundary or in semantic assembly diagnostics instead of relying only on
late chord-string cleanup.

Observed glyph cases and current handling:

- A minor dash before `7` or `6` can be read as another `7`, producing `77` or
  `76`. `suffix_lower_right` crops now run visual suffix normalization before
  semantic assembly, so a crop with visible horizontal dash evidence can emit
  `-7` or `-6` before chord grammar sees the token.
- A triangle major-seventh mark, diminished circle, and half-diminished slashed
  circle can all look like OCR text `0`, `07`, or `47`. The visual suffix helper
  checks the suffix crop image for triangle, circle, and slash evidence so `07`
  can become `maj7`, `dim7`, or `m7b5` based on pixels instead of a single text
  rule.
- Numeric flat and sharp confusions are repaired only when the text pattern is
  specific enough: `719` becomes `7b9`, `7113` becomes `7b13`, and `745`
  becomes `7#5`.
- Root OCR is constrained to root letters only. The root crop can still return
  spillover text such as `Ba`, `BG`, or `Gl`, but semantic assembly only uses the
  first root letter from the root crop. Accidentals and suffixes must come from
  their own crops.

The design boundary is: root crops vote on root letters, accidental crops vote
on accidentals, and suffix crops vote on suffix bodies. This prevents a root
crop from deciding accidental or suffix content just because the crop includes
nearby glyphs.

### Full-measure wide OCR trial and replacement

The first multi-chord attempt added full-measure wide semantic regions:

```text
root_wide
root_accidental_wide
suffix_wide
```

Those regions recovered the second chord in Autumn Leaves measures where page
OCR had enough evidence to select a suspicious measure. However, Body and Soul
exposed a structural problem: full-measure root OCR can return merged root text
such as `DG`, and full-measure suffix OCR can return text from multiple chord
symbols. Treating those wide tokens as final semantic assembly evidence can
create false chords.

The current approach keeps the wide idea only as a probe:

```text
root_anchor_scan
```

`root_anchor_scan` uses root-only OCR across selected multi-chord measures. Its
output is not passed directly to final chord assembly. Instead, merged root-only
tokens such as `DG` are split into likely root anchors, and those anchor centers
define local OCR boxes. Final chord assembly receives normal semantic regions
from those local boxes:

```text
root
root_accidental
suffix_lower_right
```

This changes the multi-chord model from:

```text
full measure OCR -> assembled chord
```

to:

```text
full measure root probe -> root anchors -> local semantic OCR -> assembled chord
```

The important accuracy rule is that `root_wide`, `root_accidental_wide`, and
`suffix_wide` are no longer final semantic assembly sources. They remain useful
for debug experiments, but the production and local semantic runner paths use
anchor-local normal regions for multi-chord recovery.

Reviewed Autumn Leaves run:

```text
storage/jobs/chart-debug-autumn-leaves-root-anchor-suffix-20260607
```

This run selected measures 19 and 20 for multi-chord probing, produced four
root anchors, ran twelve anchor-local semantic OCR boxes, and recovered:

```text
measure 19: Gm7, Gb7
measure 20: Fm7, E7
```

An earlier root-anchor run without plan-derived hints over-detected six anchors
from the same two measures. The false anchors came from root-only OCR text such
as `GF` and `CA`. The revised implementation uses page/row multi-chord evidence
as anchor hints and lets root-anchor OCR refine only nearby matching root
letters. That prevents unrelated full-measure root-only letters from becoming
final chord starts.

### Low-resolution chart upscaling trial

Body and Soul originally produced almost no chords because grid detection found
only one measure cell near the bottom-right of the page. Diagnostic component
checks showed that the native `599x720` image had 1-2 pixel barlines that were
lost by the existing vertical-line morphology. The chart path now upscales
small chord-chart images in memory before grid detection and OCR. For Body and
Soul, the image becomes `1198x1440`, which restores the visible barline
components without changing the barline threshold or crop ratios.

Reviewed Body and Soul run:

```text
storage/jobs/chart-debug-body-and-soul-root-anchor-20260607
```

This run detected 25 measures and 34 public chord events after upscaling. It no
longer lets full-measure wide tokens such as `DG` assemble directly into final
chords. The remaining issue is anchor over-selection: 15 measures were selected
for multi-chord probing, producing 37 anchors and 100 anchor-local OCR boxes.
That result is usable as a diagnostic run, but not yet a finished multi-chord
selection strategy for dense charts.

### Position-first anchor trial for dense measures

The Body and Soul chart exposed two separate failures in the root-anchor path:

- Measure 1 contained a second root candidate for `Bb7b13`, but that candidate
  was derived from an OCR text span and did not produce a valid suffix crop.
- Measure 7 had semantic crop evidence for `Bbm7`, but the local debug runner
  skipped semantic assembly because the repeat probe had detected a visual `%`.

The next trial adds image-derived root anchors alongside the OCR root-anchor
scan. For each measure, the pipeline thresholds the chord band, keeps connected
components whose size matches main root glyphs, groups nearby components from
the same chord symbol, and records the largest component in each group as a
chord-start position.

A first Body and Soul regeneration let visual anchors select supplemental OCR
measures by themselves. That selected 24 of 25 measures, produced 81 final
anchors and 232 anchor-local OCR boxes, and increased runtime to about 187
seconds. That behavior was too broad for production use. The visual anchors now
stay in diagnostics and can refine positions for measures that page/row OCR
already selected for multi-chord probing, but they do not by themselves expand
the supplemental OCR measure set.

The visual anchors do not provide the final chord text. They only refine local
OCR box positions. The final chord text still comes from anchor-local `root`,
`root_accidental`, and `suffix_lower_right` OCR crops, followed by semantic
assembly.

The same pass also added a suffix-specific fallback for anchor-local OCR: if a
`suffix_lower_right` crop returns no text at scale `2.0`, that crop is retried at
scale `3.0`. Body and Soul measure 1 showed why this matters: the second-chord
suffix pixels for `Bb7b13` were readable as `3711`/`37613` in direct crop probes,
but the normal pass could produce no suffix token. Semantic assembly now treats
`7613`, `37613`, and `3711` as numeric OCR readings of `7b13`.

The local semantic debug runner also stopped using the repeat probe as a hard
semantic-assembly skip. The parser already adds a visual `%` only when a measure
has no parsed chords, so allowing semantic assembly first lets a real chord like
Body and Soul measure 7 win over a false percent detection.

The scan-boundary overlay now draws accepted semantic anchor-local boxes instead
of every candidate anchor box. This keeps the debug image focused on the crop
regions that actually contributed to accepted semantic chords. Anchor-local
vertical bounds were also aligned with `_cell_ocr_regions()`: root, accidental,
and suffix boxes use the same top/bottom ratios as the regular measure-level
semantic crops. In particular, anchor-local `suffix_lower_right` now ends at the
same `0.76` measure-height ratio as the regular suffix crop instead of extending
to `0.92`.

The padded measure crop is now scaled from detected measure height instead of
using fixed vertical pixel padding. Autumn Leaves is the reference geometry:
detected measure height `180`, top padding `35`, next-row-capped bottom padding
`75`, and padded crop height `290`. The resulting ratios are `35/180` top
padding, `80/180` requested bottom padding, and `8/180` next-row safety gap.
This keeps `_cell_ocr_regions()` boxes at the same height ratio relative to the
detected measure across charts with different source resolutions.

Multi-chord probing now has a second trigger after the page/row spacing rules:
visual root-height anchors. The page/row plan still handles explicit spacing,
wide OCR tokens, and right-half chord-like fragments first. When that evidence
is absent, the visual pass can still mark a measure as multi-chord if it finds
at least two root-height components. The detector uses the first chord root's
component height as the reference and keeps later components with comparable
height, so horizontally squished roots can become anchors without depending on
root width as the main signal.

The visual root-height detector now calibrates root height once per detected
row instead of once per measure. Each measure is still scanned for component
positions, but those components are compared against the row's first usable root
height. Component grouping also stops when another row-calibrated root-height
component appears between nearby components, so a suffix-like component can stay
with its root while a second root starts a new anchor group.

A visual-position crop trial was not kept. In Body and Soul measure 4, replacing
OCR-derived anchor centers with visual component centers aligned the debug boxes
for `Fm7` and `Edim7`, but the same crop-position change made Autumn Leaves
measure 19 regress from `Gbm7` to `Fm7`. The current implementation therefore
uses visual roots to decide anchor counts and supplemental measures, while
anchor-local OCR crop placement still uses the OCR/root-anchor center that won
the final anchor merge.

## 2026-06-06 - Public chart contract and semantic crop OCR

### Public contract split

The chart export now separates the consumer contract from internal diagnostics:

```text
chord_chart.json        # public Spring Boot/frontend payload
chord_chart_debug.json  # MusicVision OCR/parser diagnostics
```

`chord_chart.json` is intentionally slim. It contains the final chart metadata,
final chord events, section/repeat/ending/navigation flow, and warnings. It no
longer exposes the parser's page/system/measure tree, OCR evidence, bounding
boxes, raw/corrected fragments, or parsed chord components.

The public chord event shape is:

```json
{
  "kind": "chord",
  "text": "G7b9",
  "measure_index": 14,
  "beat": 2,
  "section": "A",
  "source": "direct"
}
```

Percent-repeat measures are returned as the written chart symbol:

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

This keeps the frontend display faithful to the chart while preserving the
resolved source measure for backend logic.

### Semantic crop OCR experiment

The Cherokee chord chart exposed that whole-cell or row-level OCR could miss
small suffixes and jazz-glyph details even when the measure grid was correct.
The experimental semantic runner now scans dedicated chord subregions:

- `root`
- `root_accidental`
- `suffix_lower_right`

Region-specific allowlists narrow the OCR search space. Root OCR is restricted
to uppercase `A` through `G`, and semantic assembly uses only the first detected
root letter from the root crop. This repairs cases where the root crop includes
visual spillover and OCR returns text such as `Ba`, `Be`, `BG`, or `Gl`.

Suffix assembly now handles reusable OCR confusions observed in the chart:

- split suffix fragments such as `7` plus `#5` become `7#5`
- `745` repairs to `7#5`
- `719` repairs to `7b9`
- digit-only suffixes outside valid chord extensions are rejected
- `77` may become `m7` when the crop visually contains a minor dash
- triangle-like major-seventh marks read as `07` can become `maj7` when visual
  evidence supports a triangle glyph

The parser also preserves richer semantic chord results, so a detected
alteration such as `G7b9` is not downgraded later by weaker OCR context.

### Cherokee validation snapshot

Latest reviewed run:

```text
storage/jobs/chart-debug-cherokee_chord_chart-semantic-crops-20260606-183151
```

The public output was reviewed against the Cherokee ground truth and marked
correct. Representative recovered cases:

```text
Bb6
G7b9
F7#5
C#m7
F#7
Bmaj7
Gmaj7
%
```

Runtime on local CPU:

```text
total:              123.88s
page OCR:            34.83s
semantic cell OCR:   88.70s
semantic OCR calls: 108
```

Verification:

```text
.venv\Scripts\python.exe -m pytest tests\test_chord_chart_semantic_assembly.py tests\test_chord_chart_parser.py tests\test_chord_chart_ocr_backend.py
25 passed
```

Updated API/contract docs:

- `docs/chord_charts.md`
- `docs/api/spring_boot_backend.md`

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

## Preview root-anchor probe regions

```powershell
python .\scripts\render_chord_chart_crop_regions.py .\resources\chord_charts\autumn_leaves_chord_chart.jpg --regions root_anchor_scan --measure-indices 19,20
```

The multi-chord path uses `root_anchor_scan` only to find likely chord starts.
Final chord names come from anchor-local `root`, `root_accidental`, and
`suffix_lower_right` OCR boxes.

## Chord chart OCR trials and current behavior

### Glyph and semantic-crop trials

- `suffix_lower_right` text is normalized at the OCR-crop boundary before chord grammar parsing. This is where visual fixes for minor dash, diminished, half-diminished, triangle/major, and numeric-flat suffix reads should live.
- Semantic assembly combines separate `root`, `root_accidental`, and `suffix_lower_right` OCR tokens. Root-only chords such as `C` are valid when there is no nearby suffix evidence.
- If OCR sees a nearby suffix crop but the suffix cannot be parsed, semantic assembly rejects that partial chord instead of publishing only the root. This prevents outputs such as `Gb` when the chart likely contains `Gb7`.
- The fixed first-chord root crop retries a narrower left crop when the primary `root` crop returns no OCR result. This is meant for horizontally crowded first chords near a measure line.

### Multi-chord anchor planning

- Multi-chord planning still uses OCR spacing as the first signal.
- A root-only OCR fragment such as `C` now counts as chord-like evidence.
- Visual root-height anchors use connected components whose height matches the row's first root. The component does not have to be OCR-recognized as a root letter; it only needs to look root-sized on the same y band.
- Root-anchor probing now uses planned/visual x-coordinates for anchor-local crop placement. `root_anchor_scan` may provide a nearby root letter, but it no longer creates extra anchors when planned/visual positions already exist.
- If visual anchors already exist, unmatched `chord_like_fragment` hints are skipped. This prevents malformed fragments such as `Ig-` from adding a false middle anchor between two real root-height anchors.

### 2026-06-08 trial outputs

- Autumn Leaves: `chart-debug-autumn-leaves-anchor-planmerge-20260608`
  - m19 now has two root-anchor candidates, not three: x=936.5 and x=1143.5.
  - Current semantic output still drops the second chord because the second suffix OCR is invalid.
  - Current semantic output reads m19 first chord as `Gm7`, so accidental attachment for the first `Gb` is still unstable.
- Body and Soul: `chart-debug-body-and-soul-anchor-planmerge-20260608`
  - m07 has three root-anchor candidates: x=646.0, x=777.5, and x=848.5.
  - Current semantic output still rejects `Ab` in m07 because suffix OCR is invalid.
  - m04 detects the second root anchor `E`, but semantic assembly rejects it because the diminished/seventh suffix OCR is invalid.

## Current limits

The chord-chart parser is still designed for clean grid charts. It is not a
lyrics-over-chords parser, and it does not yet expand a complete playback order
from repeats/endings/navigation. The `flow` block preserves those symbols so a
future form-expansion pass can reason over them explicitly.

Future improvements should be driven by additional reviewed charts. The
preferred pattern is to add reusable OCR/layout repairs and regression tests,
rather than hardcoding song-specific measure fixes.
