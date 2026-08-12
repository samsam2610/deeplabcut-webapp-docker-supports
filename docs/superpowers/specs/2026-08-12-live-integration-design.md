# Live integration — storing results and writing tags

**Date:** 2026-08-12
**Card:** `3D Inline Analysis - SAM Model`
**Status:** approved in brainstorming; tests first

Until now the tool has been read-only with respect to the experimental record.
This is the change that lets it write back, plus the batch and persistence
machinery that makes that useful.

## What is being added

| | |
|---|---|
| per-trial results stored | `<video>_trials.csv` |
| **Batch 2D** / **Batch 3D** | score every trial, store, resumable |
| **Add tag** | current trial → `start-success` / `start-failure` |
| **Add all as candidates** | every stored trial → `start-*-candidate` |
| **Undo last write** | revert the last batch exactly |
| dropdown state | shows whether a trial is already tagged |

## 1. Per-trial results — `<video>_trials.csv`

```
marker,window_start,outcome,mode,pick,score,n_candidates,n_kept,prompt,judge_sig,scored_at
24454,22923,f,3d,24045,0.8626,121,32,right paw,a91c4f,2026-08-12T15:40:11
```

**Keyed on `marker`, not on the window bounds.** The marker is the human `s`/`f`
frame and is fixed; a window's `start` moves whenever `lookback` or
`past prev marker` changes, so keying on the span would orphan every stored
result the moment a judging parameter was touched.

`judge_sig` is a short hash of the judging parameters in force. It does not
invalidate anything — it makes a stale result *visible*, so a row scored under a
different gate can be spotted rather than silently trusted.

Merged on `marker`, same tidy idiom as `motion3d`: re-scoring a trial replaces
its row and leaves the rest alone.

**Tag state is deliberately NOT stored here.** It is derived by reading the
companion CSV, so there is one source of truth and the dropdown cannot go stale
after a hand-edit in the main webapp.

## 2. Writing to the companion CSV

The companion CSV is the experimental record and every frame already exists in
it as a row — 250 158 rows for the reference video. So a write **sets the `note`
on an existing row**; it never inserts one.

Three properties, each guarding something already observed:

* **`timestamp` and `frame_line_status` are preserved verbatim.** Timestamps
  carry full precision (`63.718505415`); the main webapp's `/annotate/save-row`
  recomputes them as `frame / fps` to 3 dp, so routing through it would quietly
  degrade the row being tagged. That is why this writes its own.
* **Atomic replace, CRLF preserved.** The file is CRLF; Python's csv writer
  defaults to `\r\n`, so this holds as long as nobody "helpfully" sets
  `lineterminator`.
* **A batch is ONE read-modify-write**, not one per trial. 129 rewrites of a
  6 MB file is both slow and 129 chances to be interrupted halfway.

### ±5 placement

Try the proposed frame; if its note is non-empty, step outward `−1, +1, −2, +2 …`
to the nearest row with an empty note. Earlier before later on a tie —
arbitrary, but deterministic and reported.

**Nothing free within ±5 → refuse, and say which frames were in the way.** The
±5 rule exists precisely so a tag never displaces an existing note; widening the
search to "somewhere it fits" would defeat it.

## 3. Journal and undo — `<video>_tagwrites.csv`

```
written_at,batch_id,frame,note,previous_note,window_start,marker
```

`previous_note` is what was in the cell before, so **Undo restores the exact
prior state** rather than blanking the cell. Undo reverts the most recent
`batch_id` — a single add is a batch of one.

A timestamped `<video>.csv.bak-<iso>` is taken before the first write of a
session as a backstop. The journal is the precise instrument; the copy is for
the case where the journal itself is wrong.

This survives a crash mid-batch, which unpicking 129 tags by hand would not.

## 4. Buttons and their scopes

| button | writes | scope |
|---|---|---|
| **Batch 2D**, **Batch 3D** | nothing | every trial → `_trials.csv`; skips trials already stored unless *recompute* is ticked |
| **Add tag** | `start-success` / `start-failure` | current trial only |
| **Add all as candidates** | `start-*-candidate` | every stored trial; skips human-tagged unless *include tagged* is ticked |
| **Undo last write** | reverts | the last `batch_id` |

Two batch buttons rather than one following the last-used mode: which scorer ran
is then a property of the click, not of hidden state.

Cost at 129 trials: **~32 min for 2D, ~75 min for 3D.** Both run through the
existing job/poll plumbing and the existing run lock, so nothing can start twice.
Resumable, because a stored trial is skipped by default.

Single add gets a success/failure select pre-set from the trial's marker outcome
and flippable — the human is looking at the frame and may disagree with nothing
but the label.

### Already-tagged trials

The batch skips them by default: the human's tag is ground truth and a competing
candidate beside it is noise. An *include tagged* checkbox turns them on, which
is how ±5 accuracy gets measured — the candidate lands beside the human tag and
the two can be compared directly.

## 5. Dropdown state

```
#8  f  [22923–24454]  121 cand  ✓ start-failure @24041
#9  s  [24455–25847]  116 cand  ~ candidate @25531
#10 f  [25848–27536]   98 cand
```

Derived from the companion CSV on load, so it reflects hand-edits made
elsewhere.

## 6. Machine-written tags as future exemplars

The single-trial button writes a **real** `start-success` tag, indistinguishable
from a hand-placed one. Exemplars are built from `start-*` tags on `Tag=Done`
videos, so those tags will train the model.

**That is intended and safe**: the human reviews the frame on screen before
clicking, so the tag records a human decision that a machine helped find. Its
epistemic status is the same as one placed by hand.

The unreviewed batch output is a different matter, and is already excluded by a
decision made at the start of the project: it is written as
`start-success-candidate`, and `notes.onsets()` matches **exactly**, so the
`-candidate` suffix keeps it out of the exemplar bank without any new rule. The
journal also records every frame this tool wrote, so the choice can be revisited
with data rather than re-derived.

## Tests, first

Pure and unit-tested:

1. placement finds the proposed frame when free
2. placement steps outward and reports where it landed
3. placement refuses when ±5 is full, naming the blockers
4. a write preserves `timestamp` and `frame_line_status` byte-for-byte
5. a write never touches any other row
6. the journal round-trips, and undo restores `previous_note` exactly
7. undo reverts only the last `batch_id`
8. undo after a hand-edit does not clobber the newer value — it reverts only
   cells still holding what this tool wrote
9. trial rows merge on `marker`, and survive a change to `lookback`
10. `judge_sig` changes with the judging parameters
11. batch skips stored trials, and re-scores them under *recompute*
12. batch skips human-tagged trials, and includes them under *include tagged*
13. `start-*-candidate` is not matched by `notes.onsets()` — the exemplar
    safeguard, pinned

Panel-side `.mjs`: dropdown state rendering for all three cases, and the
success/failure select defaulting to the marker outcome and staying flippable.

## Out of scope

End-to-end acceptance measurement. It is still unmeasured and still the most
important gap, but batch-writing candidates is not the same thing as measuring
them — see `METHODOLOGY.md` §9.
