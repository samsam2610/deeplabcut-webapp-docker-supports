## Multi-user

The active DLC project is resolved **per request**, from the main webapp's
`webapp:dlc_project:{uid}` Redis key, using the `X-DLC-User` header its proxy
stamps on every forwarded request. There is no server-side "current project" —
several people can use `/dlc-3d/` at once on different projects.

**Do not add a `ports:` mapping to the `dlc-3d` service.** This module trusts
`X-DLC-User`, which is sound only because the main webapp's proxy is the only
route in. Exposing a host port would make user identity spoofable from the LAN.

Gunicorn runs 4 workers. `viewer._VCAP_MAX` is a per-process cache, so the
open-video-handle ceiling is `workers x _VCAP_MAX` — move the two together.
