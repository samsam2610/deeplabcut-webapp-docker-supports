## Multi-user

The active DLC project is resolved **per request**, from the main webapp's
`webapp:dlc_project:{uid}` Redis key, using the `X-DLC-User` header its proxy
stamps on every forwarded request. There is no server-side "current project" —
several people can use `/dlc-3d/` at once on different projects.

This is a **correctness fix, not a security isolation boundary.** Before this
change, dlc-3D kept one global "current project" in module state, so two
concurrent users silently overwrote each other's selection and, via
`_save_single_frame`, each other's labeled-data. Per-user resolution fixes
that. It does not add any new authentication or network isolation: verified
from the Docker host, `http://<container-ip>:5050/dlc-3d/` already answers
200 with no `ports:` mapping at all, because bridge networks are routable
from the host by default — and the dlc-3d image bakes in the main webapp's
`base_app` with `AUTH_DISABLED=true`, so that same address also serves other
main-webapp blueprints, unauthenticated. Redis itself publishes on
`0.0.0.0:6379`. None of this is new or introduced by this change; it is the
pre-existing trust model of the Docker network these services run on. **Do
not add a `ports:` mapping to the `dlc-3d` service** — that rule still holds,
since it's the one thing standing between this module and being reachable
from the LAN rather than just the Docker host — but do not read the absence
of a `ports:` mapping as meaning `X-DLC-User` is cryptographically trusted or
that the module is otherwise hardened against a host on the internal network.

Gunicorn runs 4 workers. `viewer._VCAP_MAX` is a per-process cache, so the
open-video-handle ceiling is `workers x _VCAP_MAX` — move the two together.

## Deploy order (load-bearing)

`X-DLC-User` is stamped by the main webapp's `proxy_dlc_3d` route in
`app.py`. That file is bind-mounted as a **single file**, which goes stale
on a plain `restart` (the container keeps the old inode) — it needs a
force-recreate to pick up changes. dlc-3D's `routes.py`, by contrast, is
mounted as part of a **directory**, so `docker compose restart dlc-3d` does
pick up new code immediately.

That asymmetry means deploy order matters:

```sh
# 1. Deploy the main webapp FIRST — force-recreate, not restart, because
#    app.py is a single-file mount:
docker compose up -d --force-recreate flask

# 2. THEN deploy dlc-3d:
docker compose restart dlc-3d
# or, if dlc-3d's own image changed:
docker compose up -d --force-recreate dlc-3d
```

If dlc-3d is redeployed while flask is still running stale code that
predates the `X-DLC-User` stamp (or is otherwise not forwarding it),
`_user_id()` in `routes.py` returns `""` for every request, every route
resolves "no project", and `/dlc-3d/` is functionally dead for all users —
while the project card in the main UI still shows a project name, because
that comes from the main webapp's own session state, not from dlc-3D. This
looks like a data problem, not a deploy problem. If `/dlc-3d/` routes
suddenly report "no project" for everyone right after a deploy, check
deploy order before anything else — the two warning log lines in
`_active_project_for_user()` (empty uid, and the Redis-lookup exception
handler) exist specifically to make this diagnosable.

A bare `docker compose restart dlc-3d` on its own does not fully deploy this
change — it only completes the deploy if flask was already force-recreated
first.
