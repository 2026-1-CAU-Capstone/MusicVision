import shutil
from pathlib import Path

import cv2


WEBP_EXTENSIONS = {".webp"}


def preprocess_input(*, input_file_path: Path, intermediate_dir: Path) -> Path:
    """
    Create a stable raster working copy for the pipeline.

    WebP uploads are normalized to PNG so HOMR, EasyOCR, and chart parsing do
    not depend on downstream WebP decoder support.
    """
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    suffix = input_file_path.suffix.lower()
    if suffix in WEBP_EXTENSIONS:
        return _convert_webp_to_png(
            input_file_path=input_file_path,
            intermediate_dir=intermediate_dir,
        )

    preprocessed_path = intermediate_dir / f"preprocessed{suffix}"
    shutil.copy2(input_file_path, preprocessed_path)
    return preprocessed_path


def _convert_webp_to_png(*, input_file_path: Path, intermediate_dir: Path) -> Path:
    image = cv2.imread(str(input_file_path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise RuntimeError(f"Could not decode WebP upload: {input_file_path}")

    preprocessed_path = intermediate_dir / "preprocessed.png"
    if not cv2.imwrite(str(preprocessed_path), image):
        raise RuntimeError(f"Could not write PNG preprocessed image: {preprocessed_path}")
    return preprocessed_path
