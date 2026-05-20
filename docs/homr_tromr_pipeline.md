# HOMR And TrOMR Pipeline Boundary

This note documents the boundary that matters for MusicVision chord assignment:
HOMR exports visual geometry before TrOMR produces the final semantic MusicXML
measure sequence.

## Short Version

HOMR has two related but distinct notions of barlines:

| Stage | Meaning | Used by |
| --- | --- | --- |
| Pre-TrOMR visual barline boxes | Detected vertical shapes in `homr_processed.png` | `geometry.json`, MusicVision chord measure boxes |
| Post-TrOMR semantic barline tokens | Score-sequence symbols emitted by TrOMR | `score.musicxml` measure boundaries |

These usually agree, but they are not guaranteed to be identical. A missed or
merged visual barline can make `geometry.json` imply fewer visual measures than
the final MusicXML contains.

## Before TrOMR

HOMR first preprocesses the page image and runs segmentation/CV logic to detect
visual components:

- staff fragments
- noteheads
- stems and rest-like shapes
- clef/key-signature blobs
- barline-like vertical shapes

Those masks/shapes are converted into bounding boxes in
`homr/homr/main.py` by `predict_symbols()`. HOMR then filters and groups them:

- noteheads and stems become note candidates
- barline-like shapes become `bar_line_boxes`
- staff fragments, clefs, and barlines are used to detect staffs
- staffs are grouped into `MultiStaff` systems

The pre-TrOMR detection result is represented by `DetectionArtifacts`:

```python
DetectionArtifacts(
    multi_staffs=multi_staffs,
    processed_image=predictions.preprocessed,
    debug=debug,
    title_future=title_future,
    bar_line_boxes=bar_line_boxes,
)
```

Although `geometry.json` is written after MusicXML generation in the current
control flow, its contents come from these pre-TrOMR objects.

## What `geometry.json` Contains

`geometry.json` is in the coordinate space of `homr_processed.png`.

It contains:

- processed image width and height
- system boxes derived from HOMR `MultiStaff` groupings
- staff boxes inside each system
- visual barline boxes, centers, and angles

For a single-staff lead sheet, a system box is essentially the detected staff-line
envelope:

```text
x0 = left edge of detected staff span
y0 = top staff line
x1 = right edge of detected staff span
y1 = bottom staff line
```

It is not padded to include chord symbols, ledger notes, or surrounding
whitespace. For multi-staff systems, the system box is the union of the staff-line
boxes in that system.

MusicVision measure boxes are built later from these system boxes and visual
barline centers:

```text
measure.left   = previous boundary x, or system left edge
measure.right  = next visual barline center x
measure.top    = system top y
measure.bottom = system bottom y
```

So MusicVision measure boxes are staff-area boxes, not full page regions around
the measure.

## What TrOMR Sees

TrOMR does not scan individual barline boxes or measure boxes.

For each detected staff, HOMR prepares a whole staff image:

1. Start with the processed page image.
2. Crop around one staff.
3. Include padding around the staff envelope.
4. Dewarp the staff image.
5. Center it on TrOMR's fixed-size input canvas.
6. Run TrOMR on that raster crop.

The crop starts from the detected staff envelope and expands roughly by:

```text
x_min = staff.min_x - 2 * average_unit_size
x_max = staff.max_x + 2 * average_unit_size
y_min = staff.min_y - 4 * average_unit_size
y_max = staff.max_y + 4 * average_unit_size
```

The vertical crop is clipped against neighboring staffs so adjacent systems do
not bleed into each other.

## After TrOMR

TrOMR emits a semantic sequence of `EncodedSymbol` values, such as:

```text
clef_G2
timeSignature/4
note_8 C5
rest_8
barline
newline
```

MusicXML is generated from this semantic token stream. In
`homr/homr/music_xml_generator.py`, a `barline` token closes the current MusicXML
measure and starts the next one.

This means final MusicXML measures come from the TrOMR semantic sequence, not
directly from `geometry.json`.

## Why Counts Can Disagree

Because MusicVision chord assignment uses pre-TrOMR visual geometry while
MusicXML uses post-TrOMR semantic tokens, a score can have:

```text
visual measures from geometry.json: 32
MusicXML measures from TrOMR:       33
```

This happened in the Giant Steps sample. The visual barline geometry missed one
usable interior boundary on system 2, so MusicVision reconstructed one oversized
visual measure. TrOMR still emitted a semantic `barline` token for the final
MusicXML, so the MusicXML sequence had one more measure.

## Time Signature Note

HOMR's TrOMR vocabulary stores time-signature tokens as denominator-like values,
for example:

```text
timeSignature/2
timeSignature/4
timeSignature/8
```

The MusicXML generator then infers the numerator from recognized measure
durations:

```python
denominator = model_time_signature.rhythm.split("/")[1]
beats = int(state.nominator * int(denominator))
```

So an incorrect `timeSignature/2` token can produce `2/2` even when the visible
score is `4/4`. The denominator comes from TrOMR's whole-staff semantic
prediction, not from MusicVision's chord OCR code.

## Implications For MusicVision

Current chord assignment reconstructs visual measures from `geometry.json`.
It does not receive final MusicXML measure coordinates.

Practical consequences:

- A small measure-count mismatch should be treated as localized uncertainty, not
  a reason to discard the whole job.
- System-level alignment can preserve trusted measure mappings for systems whose
  visual and MusicXML measure counts agree.
- Missing-barline repair can use MusicXML system counts as a constraint, but
  MusicXML alone does not provide the missing x-coordinate.
- Future optimizations should keep the distinction explicit: visual geometry,
  semantic MusicXML, and alignment metadata are separate artifacts.

