// Stand-in for /static/js/training.js, which the frame labeler imports by
// absolute URL — a path only a browser can resolve. The smoke test rewrites
// that one import to point here so the module can be loaded under Node.
export function _populateGpuSelect() {}
