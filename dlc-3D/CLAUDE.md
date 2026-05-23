# CLAUDE.md (dlc-3D)

## File browsers

All multi-select directory-tree pickers MUST use `src/static/components/file_browser.js`'s `makeFileBrowser`. Do not redefine the factory inline. See `../docs/policies/file-browser-component.md` for the contract and the rationale.

## Video viewers

All frame-by-frame video curation viewers MUST compose `src/static/components/viewer/video_viewer.js`'s `VideoViewer` base + the shared feature modules in `components/viewer/features/` (`statusNoteTimeline`, `frameExtractor`, `clipExtractor`, `markerEditor`). Do not fork the player (no per-card `Tile` class or `Controller` singleton). See `../docs/policies/video-viewer-component.md` for the contract and rationale; `tests/test_video_viewer_policy.py` enforces it.
