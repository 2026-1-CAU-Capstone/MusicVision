from pathlib import Path
import cv2


RAW_DIR = Path("data/raw_pages")
OUT_DIR = Path("data/auto_crops")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def crop_left_time_sig_region(image):
    """
    Rough crop near the beginning of the first system.
    Tune these values for your sheets.
    """
    h, w = image.shape[:2]

    x1 = int(w * 0.08)
    x2 = int(w * 0.28)

    y1 = int(h * 0.05)
    y2 = int(h * 0.32)

    return image[y1:y2, x1:x2]


def main():
    image_paths = list(RAW_DIR.glob("*.png")) + list(RAW_DIR.glob("*.jpg"))

    for idx, path in enumerate(image_paths):
        image = cv2.imread(str(path))
        if image is None:
            print(f"Could not read {path}")
            continue

        crop = crop_left_time_sig_region(image)
        out_path = OUT_DIR / f"{path.stem}_crop.png"
        cv2.imwrite(str(out_path), crop)
        print("saved", out_path)


if __name__ == "__main__":
    main()