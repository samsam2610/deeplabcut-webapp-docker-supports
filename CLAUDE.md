# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This directory (`deeplabcut-webapp-docker-supports/`) houses supplementary modules that extend the main DeepLabCut webapp at `/home/sam/docker-images/deeplabcut-webapp-docker`.

The parent directory `/home/sam/docker-images/` contains many other unrelated projects; only subdirectories of `deeplabcut-webapp-docker-supports/` are in scope here.


## Main Project Context

The main webapp (`/home/sam/docker-images/deeplabcut-webapp-docker`) is a Dockerised browser-based orchestrator for DeepLabCut pose-estimation and Anipose 3D triangulation. It runs three services: **flask** (web UI + API), **worker** (PyTorch/Celery), **worker-tf** (TensorFlow/Celery), with Redis as broker and state store.

Key facts relevant to support modules:
- Data root on host: `/home/sam/data-disk/Parra-Data/` → mounted inside containers as `/user-data/Parra-Data/Disk/`
- Ollama LLM endpoint: `http://172.26.0.1:11434` (reachable from Docker containers)
- GPU routing: RTX 5090 = `CUDA_VISIBLE_DEVICES=0` (DLC), RTX PRO 6000 Blackwell = `CUDA_VISIBLE_DEVICES=1` (LLM/orchestration)
- UI runs at `http://localhost:5000`

Refer to `/home/sam/docker-images/deeplabcut-webapp-docker/CLAUDE.md` for detailed architecture of the main project.

## Module Architecture

Each module is **fully self-contained** in its own subdirectory. It owns everything it needs: its own web server, Dockerfile, UI, routes, and dependencies. Modules do not share code with the main webapp and do not live inside its source tree.

Modules are reachable at `http://localhost:5000/<module-name>/`. The main Flask app reverse-proxies that path prefix to the module's container on the internal Docker network — the browser never sees a second port.

### What each module subdirectory contains

```
<module-name>/
  README.md              ← purpose, dev setup, internal port used
  Dockerfile             ← builds the module's own image
  requirements.txt       ← module-specific deps
  src/                   ← all application code (server, templates, static assets)
```

### Rebuilding

Each module has its own Docker image. `docker compose build <module-name>` rebuilds only that module and never touches the main webapp services (`flask`, `worker`, `worker-tf`).

### Main webapp changes (only two things)

When a new module is added, exactly two changes are made to the main project:

1. **`docker-compose.yml`** — add the module as a new service on the internal network (no exposed host port). Example:
   ```yaml
   clip-cutter:
     build: ../deeplabcut-webapp-docker-supports/clip-cutter
     networks:
       - internal
   ```
2. **`base.html`** — add one nav button linking to `/clip-cutter/`.

The main Flask app adds a catch-all proxy route for `/clip-cutter/*` → `http://clip-cutter:<internal-port>/*`. This proxy route is the only Python code added to the main project.

## Current Modules

- `clip-cutter/` — (in progress) video clip extraction tool; standalone site (legacy pattern)
