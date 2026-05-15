from pathlib import Path


FAKE_MUSICXML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1">
      <part-name>Piano</part-name>
    </score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key>
          <fifths>0</fifths>
        </key>
        <time>
          <beats>4</beats>
          <beat-type>4</beat-type>
        </time>
        <clef>
          <sign>G</sign>
          <line>2</line>
        </clef>
      </attributes>
      <note>
        <rest/>
        <duration>4</duration>
        <type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>
"""


def run_homr(
    *,
    preprocessed_input_path: Path,
    output_dir: Path,
    logs_dir: Path,
) -> Path:
    """
    Produce a placeholder MusicXML file so the API flow can be tested end-to-end.

    TODO: Replace this stub with the real HOMR invocation and capture its logs/output.
    """
    _ = preprocessed_input_path
    logs_dir.mkdir(parents=True, exist_ok=True)

    musicxml_path = output_dir / "score.musicxml"
    musicxml_path.write_text(FAKE_MUSICXML, encoding="utf-8")

    log_path = logs_dir / "homr.log"
    log_path.write_text(
        "Placeholder HOMR execution completed. Replace with real integration later.\n",
        encoding="utf-8",
    )

    return musicxml_path
