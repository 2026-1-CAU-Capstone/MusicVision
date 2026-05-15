from pathlib import Path
import json
import torch
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms
from tqdm import tqdm

from time_signature_cnn import TimeSignatureCNN


DATA_DIR = Path("data/crops")
MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)

IMG_SIZE = 64
BATCH_SIZE = 32
EPOCHS = 30
LR = 1e-3


def get_loaders():
    train_tfms = transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.RandomAffine(
            degrees=3,
            translate=(0.05, 0.05),
            scale=(0.9, 1.1),
            shear=2,
        ),
        transforms.ColorJitter(brightness=0.2, contrast=0.2),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5]),
    ])

    eval_tfms = transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.Resize((IMG_SIZE, IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5]),
    ])

    train_ds = datasets.ImageFolder(DATA_DIR / "train", transform=train_tfms)
    val_ds = datasets.ImageFolder(DATA_DIR / "val", transform=eval_tfms)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    return train_ds, val_ds, train_loader, val_loader


def evaluate(model, loader, device):
    model.eval()
    correct = 0
    total = 0
    loss_sum = 0.0
    criterion = nn.CrossEntropyLoss()

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)

            logits = model(images)
            loss = criterion(logits, labels)

            preds = logits.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)
            loss_sum += loss.item() * labels.size(0)

    return loss_sum / total, correct / total


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("device:", device)

    train_ds, val_ds, train_loader, val_loader = get_loaders()

    class_to_idx = train_ds.class_to_idx
    idx_to_class = {v: k for k, v in class_to_idx.items()}

    with open(MODEL_DIR / "time_sig_classes.json", "w", encoding="utf-8") as f:
        json.dump(idx_to_class, f, indent=2)

    model = TimeSignatureCNN(num_classes=len(class_to_idx)).to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)

    best_val_acc = 0.0

    for epoch in range(1, EPOCHS + 1):
        model.train()
        train_loss = 0.0
        correct = 0
        total = 0

        pbar = tqdm(train_loader, desc=f"Epoch {epoch}/{EPOCHS}")

        for images, labels in pbar:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad()
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * labels.size(0)
            preds = logits.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

            pbar.set_postfix({
                "loss": train_loss / total,
                "acc": correct / total,
            })

        val_loss, val_acc = evaluate(model, val_loader, device)

        print(
            f"epoch={epoch} "
            f"train_loss={train_loss / total:.4f} "
            f"train_acc={correct / total:.4f} "
            f"val_loss={val_loss:.4f} "
            f"val_acc={val_acc:.4f}"
        )

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "class_to_idx": class_to_idx,
                    "img_size": IMG_SIZE,
                },
                MODEL_DIR / "time_sig_cnn.pt",
            )
            print("saved best model")

    print("best val acc:", best_val_acc)


if __name__ == "__main__":
    main()