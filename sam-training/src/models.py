"""Stage 2 (SAM 3) and stage 3 (DINOv3), loaded lazily and shared.

Both models are several GB and take ~30 s to load, so they are process-level
singletons behind a lock rather than per-request.

Two hard-won constraints are encoded here:

* **DINOv3 must not run in float16.** It returns all-NaN embeddings, and because
  NaN propagates silently through cosine similarity into ``argmax`` (which
  happily returns 0), the symptom is a plausible-looking 0 % accuracy with every
  prediction pinned to the first frame — it reads as "the method does not work".
  bfloat16 is fine and just as fast.

* **SAM 3 finds the pellet via text prompting not at all** ("white pellet"
  returns zero instances), and returns SEVERAL paw instances per frame. The
  pellet is OpenCV's job; picking the reaching paw is ``choose_reaching_paw``.
"""
from __future__ import annotations

import os
import threading

import numpy as np

SAM_MODEL = os.environ.get("SAM_TRAINING_SAM_MODEL", "facebook/sam3")
DINO_MODEL = os.environ.get("SAM_TRAINING_DINO_MODEL",
                            "facebook/dinov3-vitl16-pretrain-lvd1689m")
SAM_DEVICE = os.environ.get("SAM_TRAINING_SAM_DEVICE", "cuda:0")
DINO_DEVICE = os.environ.get("SAM_TRAINING_DINO_DEVICE", "cuda:1")

_sam = _sam_proc = None
_dino = _dino_proc = None
_sam_lock = threading.Lock()
_dino_lock = threading.Lock()


def _dtype():
    import torch
    return torch.bfloat16          # never float16 — see module docstring


def sam():
    """(processor, model) for SAM 3, loaded once."""
    global _sam, _sam_proc
    if _sam is None:
        with _sam_lock:
            if _sam is None:
                import torch
                from transformers import Sam3Processor, Sam3Model
                dev = SAM_DEVICE if torch.cuda.is_available() else "cpu"
                _sam_proc = Sam3Processor.from_pretrained(SAM_MODEL)
                _sam = Sam3Model.from_pretrained(
                    SAM_MODEL, dtype=_dtype()).to(dev).eval()
    return _sam_proc, _sam


def dino():
    """(processor, model) for DINOv3, loaded once."""
    global _dino, _dino_proc
    if _dino is None:
        with _dino_lock:
            if _dino is None:
                import torch
                from transformers import AutoImageProcessor, AutoModel
                dev = DINO_DEVICE if torch.cuda.is_available() else "cpu"
                _dino_proc = AutoImageProcessor.from_pretrained(DINO_MODEL)
                _dino = AutoModel.from_pretrained(
                    DINO_MODEL, dtype=_dtype()).to(dev).eval()
    return _dino_proc, _dino


def segment(rgb, prompt: str = "paw", threshold: float = 0.4):
    """SAM 3 instances for one RGB frame.

    Returns ``[{score, mask (bool HxW), bbox (x, y, w, h)}]``, best first.
    """
    import torch
    proc, model = sam()
    dev = next(model.parameters()).device
    inputs = proc(images=rgb, text=prompt, return_tensors="pt").to(dev)
    with torch.no_grad():
        out = model(**inputs)
    res = proc.post_process_instance_segmentation(
        out, threshold=threshold, mask_threshold=0.5,
        target_sizes=inputs.get("original_sizes").tolist())[0]
    items = []
    scores = res["scores"].float().cpu().numpy()
    for i in np.argsort(-scores):
        mask = res["masks"][i].cpu().numpy().astype(bool)
        ys, xs = np.nonzero(mask)
        if not len(xs):
            continue
        items.append({
            "score": float(scores[i]),
            "mask": mask,
            "bbox": (int(xs.min()), int(ys.min()),
                     int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)),
        })
    return items


MAX_PAW_PELLET_PX = 180.0


def choose_reaching_paw(items, pellet_xy, aperture_box=None,
                        max_distance: float = MAX_PAW_PELLET_PX):
    """Pick the instance that is the REACHING paw, not a resting one.

    SAM returns every paw it can see — typically the reaching one plus one or
    two on the floor. Confidence does not distinguish them (a resting paw often
    scores higher, being unblurred), so geometry does: nearest to the pellet,
    within ``max_distance``.

    ``aperture_box`` is accepted but deliberately NOT used as a filter. It was,
    and it rejected every correct paw: the config default is an unvalidated
    guess (y 150-320) while the reaching paw at the pellet actually spans
    y 341-449, entirely below it — so `/score` returned zero masks on every
    frame. Stage 0 does not measure the aperture yet, and until it does, a box
    nobody has checked must not be allowed to veto a detection. Distance to the
    pellet is measured from the calibration, so it is grounded.

    Returns None when nothing qualifies, which is a real answer — on most frames
    of a window no paw is anywhere near the pellet.
    """
    if not items:
        return None
    px, py = pellet_xy
    best, best_d = None, None
    for it in items:
        x, y, w, h = it["bbox"]
        cx, cy = x + w / 2.0, y + h / 2.0
        d = float(np.hypot(cx - px, cy - py))
        if d > max_distance:
            continue
        if best_d is None or d < best_d:
            best, best_d = it, d
    return best


def embed(images, batch: int = 32):
    """L2-normalised DINOv3 embeddings for a list of RGB arrays."""
    import torch
    from PIL import Image
    if not len(images):
        return np.zeros((0, 1024), dtype=np.float32)
    proc, model = dino()
    dev = next(model.parameters()).device
    out = []
    for i in range(0, len(images), batch):
        chunk = [Image.fromarray(x) for x in images[i:i + batch]]
        with torch.no_grad():
            b = proc(images=chunk, return_tensors="pt").to(dev)
            b = {k: (v.to(_dtype()) if v.dtype == torch.float32 else v)
                 for k, v in b.items()}
            f = model(**b).pooler_output.float().cpu().numpy()
        if np.isnan(f).any():
            # Loud, because the silent version of this cost a whole experiment.
            raise RuntimeError(
                "DINOv3 produced NaN embeddings — check the dtype is not float16")
        out.append(f / np.clip(np.linalg.norm(f, axis=1, keepdims=True), 1e-8, None))
    return np.concatenate(out)


def similarity(query, exemplars, topk: int = 5):
    """Mean cosine to the top-k nearest exemplars, per query row.

    Top-k rather than a single prototype: reach posture varies enough between
    animals that one mean vector blurs it, and top-k lets a query match the
    handful of exemplars that actually resemble it.
    """
    if not len(query) or not len(exemplars):
        return np.zeros(len(query), dtype=np.float32)
    sim = query @ exemplars.T
    k = int(min(max(1, topk), sim.shape[1]))
    return np.sort(sim, axis=1)[:, -k:].mean(axis=1).astype(np.float32)
