from pathlib import Path
import json
import torch
from torchvision import transforms
from PIL import Image

from time_signature_cnn import TimeSignatureCNN


MODEL_PATH = Path("models/time_sig_cnn.pt")
CLASS_PATH = Path("models/time_sig_classes.json")


def load_model():
    checkpoint = torch.load(MODEL_PATH, map_location="cpu")

    with open(CLASS_PATH, "r", encoding="utf-8") as f:
        idx_to_class = json.load(f)

    idx_to_class = {int(k): v for k, v in idx_to_class.items()}

    model = TimeSignatureCNN(num_classes=len(idx_to_class))
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    return model, idx_to_class


def predict(image_path: str):
    model, idx_to_class = load_model()

    tfm = transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.Resize((64, 64)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5]),
    ])

    image = Image.open(image_path).convert("RGB")
    x = tfm(image).unsqueeze(0)

    with torch.no_grad():
        logits = model(x)
        probs = torch.softmax(logits, dim=1)[0]

    conf, idx = torch.max(probs, dim=0)
    label = idx_to_class[int(idx)]

    return label, float(conf)


if __name__ == "__main__":
    import sys

    label, confidence = predict(sys.argv[1])
    print(label, confidence)