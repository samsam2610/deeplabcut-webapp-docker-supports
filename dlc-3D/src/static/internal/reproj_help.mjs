// Contextual help for the reprojection panel's controls.
//
// Condensed from docs/reprojection-parameters.md — update BOTH together. Every
// entry carries a worked example measured on the eggtart-1 reference session,
// because the examples are what make the parameters land.

export const HELP_DEFAULT = {
  title: "Epipolar reprojection",
  body:
    "The trusted camera's marker induces an epipolar line in the other view. " +
    "Markers far off that line are deleted; markers on it that DeepLabCut " +
    "scored low are rescued. Nothing is ever moved. Hover or focus a control " +
    "to see what it does.",
};

export const HELP = {
  trusted_cam: {
    title: "Trusted camera",
    body:
      "Induces the epipolar line. The other camera is the one judged and " +
      "corrected. Per-bodypart overrides flip this for individual bodyparts, " +
      "which also flips which camera's thresholds apply.",
    example:
      "On this session cam1 is the better view: mean likelihood 0.51 against " +
      "cam0's 0.39.",
  },
  k1: {
    title: "Trust band k₁",
    body:
      "A multiplier, not pixels. t_ok = median + k₁ × MAD of each bodypart's " +
      "own residual spread. Inside this band, geometry confirms the marker.",
    example:
      "×3 gives 3.30 px on the Pellet but 21.53 px on the Wrist — the same " +
      "setting, scaled to how tightly each part localises.",
  },
  k2: {
    title: "Reject band k₂",
    body:
      "t_bad = median + k₂ × MAD. Beyond this the marker is geometrically " +
      "impossible: its coordinates are cleared and its likelihood set to 0. " +
      "Keep k₂ above k₁.",
    example: "×8 gives 7.28 px on the Pellet and 45.66 px on the Wrist.",
  },
  gate_ref: {
    title: "gate_ref — on the TRUSTED camera",
    body:
      "Below this likelihood the trusted marker cannot induce a line worth " +
      "believing, so the other camera's marker is left completely untouched. " +
      "This is the coverage dial: raise it for fewer, safer judgements.",
    example:
      "At 0.6, 3,293,909 of 4,026,240 frame × bodypart slots were left " +
      "unjudged — mostly frames where the animal is not reaching.",
  },
  low_tgt: {
    title: "low_tgt — on the JUDGED camera",
    body:
      "The ceiling for what is worth rescuing. Below it, a marker inside the " +
      "trust band becomes a rescue candidate; at or above it, the marker is " +
      "simply confirmed and nothing is written. It does not affect rejection.",
    example:
      "Raise it to admit more rescue candidates. A marker beyond t_bad is " +
      "still deleted whatever its likelihood.",
  },
  high_conf: {
    title: "high_conf — per camera",
    body:
      "Chooses the calibration sample only: frames where each camera clears " +
      "its own bar. Their spread sets t_ok and t_bad. Lowering it admits " +
      "sloppier correspondences, which inflates the thresholds and LOOSENS " +
      "the rule — the opposite of what it sounds like.",
    example:
      "Wrist, cam0 0.9 → 0.7: sample 2,803 → 4,924 frames, t_ok 21.5 → 22.2 px.",
  },
  rescue_floor: {
    title: "rescue_floor — on the JUDGED camera",
    body:
      "The likelihood written onto a successful rescue. It never lowers an " +
      "already-higher value. Set it above whatever threshold your downstream " +
      "filtering uses, or the rescued marker will be discarded anyway.",
    example:
      "Different floors per camera let you tell rescued markers apart by " +
      "which view they came from.",
  },
  line_lik: {
    title: "min likelihood — display only",
    body:
      "A line is drawn only when the trusted camera's marker for that bodypart " +
      "reaches this confidence. It changes nothing about the verdicts: gate_ref " +
      "still decides what the engine judges.",
    example:
      "The default 0.4 sits below gate_ref's 0.6 on purpose, so lines the " +
      "engine ignored are still visible — often the reason a bodypart came " +
      "back UNJUDGED.",
  },
  require_peaks: {
    title: "Require peak evidence",
    body:
      "Refuses a rescue unless exactly one of DeepLabCut's candidate heatmap " +
      "peaks sits on the epipolar line. It can only REFUSE — no marker is ever " +
      "moved. Needs a peaks sidecar, which 'emit peaks' writes during " +
      "Analyze-for-tag; frames without one keep their geometry verdict rather " +
      "than being refused.",
    example:
      "On the validation run, 4,031 of 15,191 judged cells had SEVERAL peaks " +
      "on the line and 1,028 had the wrong one — 33% of refusals that geometry " +
      "alone cannot make at any threshold.",
  },
  peak_floor: {
    title: "Peak score floor",
    body:
      "A peak below this heatmap score does not count as evidence. Too high " +
      "and this degenerates into rescue_floor; too low and a hallucinated peak " +
      "passes. Same 0–1 scale as likelihood.",
    example:
      "The 0.05 default is UNVALIDATED — there is no labelled measurement " +
      "behind it. Under occlusion DeepLabCut typically scores below 0.10, so " +
      "raising it toward 0.10 refuses more and rescues less.",
  },
};
