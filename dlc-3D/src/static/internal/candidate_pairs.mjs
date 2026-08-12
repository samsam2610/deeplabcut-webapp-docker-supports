// Pairing the top candidates across the two cameras for the thumbnail strip.
//
// Pure so the column alignment can be tested. The layout's whole meaning is
// that column i is ONE frame seen from two sides; if the groups fall out of
// step the strip still looks correct — five thumbnails beside five — while
// inviting a comparison between a paw in cam0 and a different moment in cam1.

export const PAIR_LIMIT = 5;

/**
 * Split the ranked candidates into two aligned groups.
 *
 * Both groups are built from the SAME filtered list in the SAME order, so they
 * cannot desynchronise: a candidate dropped for having no frame is dropped from
 * both, rather than shortening one column and shifting the other.
 */
export function pairCandidates(top, limit = PAIR_LIMIT) {
  const usable = (top || [])
    .filter((c) => c && Number.isFinite(Number(c.frame)))
    .slice(0, limit);
  const forCam = (cam) => usable.map((c, i) => ({
    frame: Number(c.frame),
    score: Number(c.score),
    cam,
    best: i === 0,
  }));
  return { cam0: forCam("cam0"), cam1: forCam("cam1") };
}
