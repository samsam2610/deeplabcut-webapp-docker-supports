# sam-training

Proposes reach-onset tags on the RatBox reaching task so a human confirms them
instead of hunting through a 252 000-frame video.

During an experiment the outcome of each reach is keyed live as an `s` or `f`
note. Afterwards someone has to go back and hand-place the *onset* frame for
each one — ~85 per video, ~0.03 % of frames. **That retrospective hunt is the
only thing this module automates.**

Success/failure is never predicted. It is already in the CSV: a candidate's
label is read off the human `s`/`f` marker that closes its window. No marker,
no candidate.

Method, with the numbers behind each decision: **[`METHODOLOGY.md`](METHODOLOGY.md)**.
Design history: `docs/superpowers/specs/2026-08-1*-*.md`.

## Pipeline

| stage | what it does | status |
|---|---|---|
| 0 | derive the pellet template once per session (NCC) | **built** |
| 1 | NCC sweep → pellet-stationary intervals → search windows | **built** |
| 2 | SAM: paw/wrist masks across each window | not started |
| 3 | DINO: embed masked crops, match against human-tagged exemplars | not started |
| 4 | write `start-*-candidate` into the companion CSV | not started |

Stages 0–1 are model-independent, which is why they came first.

**Known gap:** stage 0 does not locate the aperture — it passes the `config`
default through. Nothing needs it yet, but stage 2 gates on the paw clearing the
aperture, so it has to become a real measurement before that lands.

## Debug panel

`src/app.py` serves a panel at `/sam-training/` showing what each stage did to a
given frame: the pellet-search and aperture boxes, the NCC match location and
score, and a timeline of the whole video with armed intervals, search windows,
human onset tags and `s`/`f` markers. Click the timeline to scrub; arrow keys
step frames.

Layers are drawn client-side from whatever `/api/layers` returns, keyed on
`kind` (`box` | `mask` | `scalar`). **Stage 2 and 3 appear automatically once
they emit layers** — no front-end change needed. Masks travel run-length encoded
(a paw-sized blob is a few hundred integers, not 480 000).

It exists because every bug found in this pipeline so far was invisible in the
numbers and obvious in a picture — a brightness detector firing on the white
reload vane, and search windows opening after the onset they were meant to
contain.

## Layout

```
src/
  config.py      rig geometry + sweep defaults (800x600, 200fps)
  tracked.py     dataset selection from tracked_files.sqlite (Tag = Done)
  notes.py       companion-CSV reading, trial pairing, orphan detection
  ncc.py         normalised cross-correlation + strided video sweep
  intervals.py   debounce, pellet-present intervals, search windows
  rig.py         stage 0 calibration, cached per session
tests/           synthetic fixtures only — no video, no GPU
```

## Two things to know before changing anything

**The working set comes from `tracked_files.sqlite`, not from listing
`videos/`.** Only tracked files whose `Tag` segment is `Done` are training data.
The `video` table alone is a registry of files ever seen — in DREADD-Ali it
holds 13 rows against 12 tracked, and the extra is a near-duplicate that would
double-count trials inside a cross-validation fold.

**Pellet detection must stay illumination-invariant.** A white vane sweeps in to
reload the pellet and swings the frame mean from ~40 to ~142. Three separate
brightness-based guards were tried against real footage and all three failed to
tell the vane from a white paw. `TM_CCOEFF_NORMED` is invariant to it;
`test_ncc.py` asserts this so it cannot silently regress.

## Tests

```
python3 -m pytest
```

No video files, no GPU, no network. Fixtures are synthetic by design — an
earlier incident in this repo leaked 614 GB into `/tmp` from tests that touched
real footage.

## Dev

Nothing runs in a container yet; stages 0–1 are a library. When the panel lands
it will follow the repo convention: self-contained module, internal port,
reverse-proxied at `/sam-training/` by the main Flask app.
