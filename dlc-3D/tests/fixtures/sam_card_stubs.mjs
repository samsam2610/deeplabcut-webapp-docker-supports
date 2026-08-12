// Stubs for the two absolute-URL imports in inline_analysis_3d_sam.js.
// Only a browser can resolve /static/... ; the load test rewrites both to here.
export function makeTrackedFiles() {
  return { refresh() {}, mount() {}, destroy() {} };
}
export const state = {
  project: null, projectPath: null, videos: [], subscribe() {}, set() {},
};
