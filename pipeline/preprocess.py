import shutil
from pathlib import Path


def preprocess_input(*, input_file_path: Path, intermediate_dir: Path) -> Path:
    """
    Create a working copy for the pipeline.

    TODO: Insert real image/PDF preprocessing here before HOMR execution.
    """
    preprocessed_path = intermediate_dir / f"preprocessed{input_file_path.suffix.lower()}"
    shutil.copy2(input_file_path, preprocessed_path)
    return preprocessed_path
