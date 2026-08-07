#!/usr/bin/env python3
"""V264 Phase 2/3 — fine-tune Kronos (tokenizer, then predictor) on the V262 1h corpus.

NOT strategy code. Consumes only the pickles written by ``v264_kronos_prep.py``.

Why this exists instead of ``third_party/kronos/finetune_csv/*``:

  1. Upstream hard-codes ``device = cuda if available else cpu`` — no MPS branch,
     so on this Mac it would silently train on CPU.
  2. Upstream's ``CustomKlineDataset`` reads a single CSV and splits it by row
     ratio. With 13 symbols that lets a sliding window straddle a symbol boundary,
     and it cannot express V264's pre-registered date split.

Everything else is a faithful port of upstream: identical feature layout, identical
per-window z-score + clip normalisation, identical loss functions
(``finetune_tokenizer.py:201-211`` and ``finetune_base_model.py:286-292``),
identical AdamW + OneCycleLR schedule, identical grad-clip norms (2.0 / 3.0).

Usage::

    PYTHONPATH=third_party/kronos HF_HOME=<cache> \
    python3 scripts/v264_kronos_finetune.py --stage tokenizer --epochs 2
    ... --stage predictor --epochs 2
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F  # noqa: N812 (upstream Kronos convention)
from torch.utils.data import DataLoader, Dataset

REPO = Path(__file__).resolve().parents[1]

FEATURE_LIST = ["open", "high", "low", "close", "volume", "amount"]
TIME_FEATURE_LIST = ["minute", "hour", "weekday", "day", "month"]


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def pick_device(requested: str | None) -> torch.device:
    if requested:
        return torch.device(requested)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class MultiSymbolKlineDataset(Dataset):
    """Sliding windows over per-symbol arrays. Windows never cross a symbol boundary.

    A window is ``lookback + predict + 1`` bars, matching upstream. Consecutive
    starts overlap by >99%, so ``stride`` subsamples them: this is a redundancy
    decision made before any result was seen, not a tuning knob.
    """

    def __init__(self, pkl_path: Path, lookback: int, predict: int, stride: int, clip: float):
        with open(pkl_path, "rb") as fh:
            blocks = pickle.load(fh)
        self.window = lookback + predict + 1
        self.clip = clip
        self.symbols: list[str] = []
        self.feats: list[np.ndarray] = []
        self.times: list[np.ndarray] = []
        self.index: list[tuple[int, int]] = []

        for symbol in sorted(blocks):
            f = blocks[symbol]["features"]
            t = blocks[symbol]["time_features"]
            n_starts = len(f) - self.window + 1
            if n_starts <= 0:
                continue
            si = len(self.feats)
            self.symbols.append(symbol)
            self.feats.append(np.ascontiguousarray(f, dtype=np.float32))
            self.times.append(np.ascontiguousarray(t, dtype=np.float32))
            self.index.extend((si, s) for s in range(0, n_starts, stride))

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, i: int):
        si, start = self.index[i]
        x = self.feats[si][start : start + self.window]
        s = self.times[si][start : start + self.window]
        mean = x.mean(axis=0)
        std = x.std(axis=0)
        x = np.clip((x - mean) / (std + 1e-5), -self.clip, self.clip)
        return torch.from_numpy(np.ascontiguousarray(x)), torch.from_numpy(np.ascontiguousarray(s))


def build_loaders(args, data_dir: Path):
    train_ds = MultiSymbolKlineDataset(
        data_dir / "train_data.pkl", args.lookback, args.predict, args.stride, args.clip
    )
    val_ds = MultiSymbolKlineDataset(
        data_dir / "val_data.pkl", args.lookback, args.predict, args.val_stride, args.clip
    )
    print(
        f"[data] train {len(train_ds):,} windows over {len(train_ds.symbols)} symbols | "
        f"val {len(val_ds):,} windows over {len(val_ds.symbols)} symbols"
    )
    g = torch.Generator()
    g.manual_seed(args.seed)
    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        drop_last=True,
        generator=g,
    )
    val_loader = DataLoader(
        val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers
    )
    return train_loader, val_loader


def run_tokenizer(args, device, data_dir: Path, save_dir: Path) -> dict:
    from model import KronosTokenizer

    tokenizer = KronosTokenizer.from_pretrained(args.pretrained_tokenizer).to(device)
    n_params = sum(p.numel() for p in tokenizer.parameters())
    print(f"[model] tokenizer {args.pretrained_tokenizer}  {n_params / 1e6:.2f}M params")

    train_loader, val_loader = build_loaders(args, data_dir)
    optimizer = torch.optim.AdamW(
        tokenizer.parameters(),
        lr=args.tokenizer_lr,
        betas=(args.adam_beta1, args.adam_beta2),
        weight_decay=args.adam_weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=args.tokenizer_lr,
        steps_per_epoch=len(train_loader),
        epochs=args.epochs,
        pct_start=0.03,
        div_factor=10,
    )

    history: list[dict] = []
    best = float("inf")
    for epoch in range(args.epochs):
        t0 = time.time()
        tokenizer.train()
        run_loss, n_batch = 0.0, 0
        for bi, (x, _) in enumerate(train_loader):
            x = x.to(device)
            zs, bsq_loss, _, _ = tokenizer(x)
            z_pre, z = zs
            recon_pre = F.mse_loss(z_pre, x)
            recon_all = F.mse_loss(z, x)
            loss = (recon_pre + recon_all + bsq_loss) / 2
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(tokenizer.parameters(), max_norm=2.0)
            optimizer.step()
            scheduler.step()
            run_loss += loss.item()
            n_batch += 1
            if (bi + 1) % args.log_interval == 0:
                print(
                    f"  [tok e{epoch + 1} {bi + 1}/{len(train_loader)}] "
                    f"lr={optimizer.param_groups[0]['lr']:.2e} loss={loss.item():.4f} "
                    f"(recon_all={recon_all.item():.4f} bsq={bsq_loss.item():.4f}) "
                    f"{(time.time() - t0) / (bi + 1):.2f}s/step",
                    flush=True,
                )

        tokenizer.eval()
        vsum, vn = 0.0, 0
        with torch.no_grad():
            for x, _ in val_loader:
                x = x.to(device)
                zs, _, _, _ = tokenizer(x)
                _, z = zs
                vsum += F.mse_loss(z, x).item() * x.size(0)
                vn += x.size(0)
        val_loss = vsum / max(vn, 1)
        train_loss = run_loss / max(n_batch, 1)
        rec = {
            "epoch": epoch + 1,
            "train_loss": round(train_loss, 6),
            "val_loss": round(val_loss, 6),
            "secs": round(time.time() - t0, 1),
        }
        history.append(rec)
        print(f"[tok] epoch {epoch + 1}: {rec}", flush=True)
        if val_loss < best:
            best = val_loss
            out = save_dir / "best_model"
            out.mkdir(parents=True, exist_ok=True)
            tokenizer.save_pretrained(str(out))
            print(f"[tok] saved best -> {out} (val {best:.6f})", flush=True)

    return {"stage": "tokenizer", "best_val_loss": best, "history": history}


def run_predictor(args, device, data_dir: Path, save_dir: Path) -> dict:
    from model import Kronos, KronosTokenizer

    tok_path = args.finetuned_tokenizer or args.pretrained_tokenizer
    tokenizer = KronosTokenizer.from_pretrained(tok_path).to(device)
    tokenizer.eval()
    for p in tokenizer.parameters():
        p.requires_grad_(False)
    model = Kronos.from_pretrained(args.pretrained_predictor).to(device)
    print(
        f"[model] tokenizer {tok_path} (frozen) + predictor {args.pretrained_predictor} "
        f"{sum(p.numel() for p in model.parameters()) / 1e6:.2f}M params"
    )

    train_loader, val_loader = build_loaders(args, data_dir)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.predictor_lr,
        betas=(args.adam_beta1, args.adam_beta2),
        weight_decay=args.adam_weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer,
        max_lr=args.predictor_lr,
        steps_per_epoch=len(train_loader),
        epochs=args.epochs,
        pct_start=0.03,
        div_factor=10,
    )

    history: list[dict] = []
    best = float("inf")
    for epoch in range(args.epochs):
        t0 = time.time()
        model.train()
        run_loss, n_batch = 0.0, 0
        for bi, (x, s) in enumerate(train_loader):
            x, s = x.to(device), s.to(device)
            with torch.no_grad():
                tok0, tok1 = tokenizer.encode(x, half=True)
            logits = model(tok0[:, :-1], tok1[:, :-1], s[:, :-1, :])
            loss, _, _ = model.head.compute_loss(logits[0], logits[1], tok0[:, 1:], tok1[:, 1:])
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=3.0)
            optimizer.step()
            scheduler.step()
            run_loss += loss.item()
            n_batch += 1
            if (bi + 1) % args.log_interval == 0:
                print(
                    f"  [pred e{epoch + 1} {bi + 1}/{len(train_loader)}] "
                    f"lr={optimizer.param_groups[0]['lr']:.2e} loss={loss.item():.4f} "
                    f"{(time.time() - t0) / (bi + 1):.2f}s/step",
                    flush=True,
                )

        model.eval()
        vsum, vn = 0.0, 0
        with torch.no_grad():
            for x, s in val_loader:
                x, s = x.to(device), s.to(device)
                tok0, tok1 = tokenizer.encode(x, half=True)
                logits = model(tok0[:, :-1], tok1[:, :-1], s[:, :-1, :])
                loss, _, _ = model.head.compute_loss(
                    logits[0], logits[1], tok0[:, 1:], tok1[:, 1:]
                )
                vsum += loss.item()
                vn += 1
        val_loss = vsum / max(vn, 1)
        train_loss = run_loss / max(n_batch, 1)
        rec = {
            "epoch": epoch + 1,
            "train_loss": round(train_loss, 6),
            "val_loss": round(val_loss, 6),
            "secs": round(time.time() - t0, 1),
        }
        history.append(rec)
        print(f"[pred] epoch {epoch + 1}: {rec}", flush=True)
        if val_loss < best:
            best = val_loss
            out = save_dir / "best_model"
            out.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(str(out))
            print(f"[pred] saved best -> {out} (val {best:.6f})", flush=True)

    return {"stage": "predictor", "best_val_loss": best, "history": history}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["tokenizer", "predictor"], required=True)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--save-root", default=None)
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--predict", type=int, default=24)
    ap.add_argument("--clip", type=float, default=5.0)
    ap.add_argument("--stride", type=int, default=8, help="train window subsample stride")
    ap.add_argument("--val-stride", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--num-workers", type=int, default=0)
    ap.add_argument("--log-interval", type=int, default=100)
    ap.add_argument("--tokenizer-lr", type=float, default=2e-4)
    ap.add_argument("--predictor-lr", type=float, default=4e-5)
    ap.add_argument("--adam-beta1", type=float, default=0.9)
    ap.add_argument("--adam-beta2", type=float, default=0.95)
    ap.add_argument("--adam-weight-decay", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default=None)
    ap.add_argument("--pretrained-tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    ap.add_argument("--pretrained-predictor", default="NeoQuasar/Kronos-small")
    ap.add_argument("--finetuned-tokenizer", default=None)
    args = ap.parse_args()

    root = Path(os.environ.get("OMEGA_AUDIT_OUTPUT_DIR", str(REPO / "data"))) / "v264"
    data_dir = Path(args.data_dir) if args.data_dir else root / "kronos_finetune"
    save_root = Path(args.save_root) if args.save_root else root / "checkpoints"
    save_dir = save_root / args.stage
    save_dir.mkdir(parents=True, exist_ok=True)

    set_seed(args.seed)
    device = pick_device(args.device)
    print(f"[v264] stage={args.stage} device={device} data={data_dir} save={save_dir}")

    fn = run_tokenizer if args.stage == "tokenizer" else run_predictor
    result = fn(args, device, data_dir, save_dir)
    result["config"] = vars(args) | {"device": str(device)}
    (save_dir / "training_history.json").write_text(json.dumps(result, indent=2))
    print(f"[v264] history -> {save_dir / 'training_history.json'}")


if __name__ == "__main__":
    main()
