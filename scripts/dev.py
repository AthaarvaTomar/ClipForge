"""ClipForge AI — Unified Local Development Runner.

Starts Redis (via Docker if not already running), the Celery background worker,
the FastAPI backend, and the React frontend together in a single command.

Usage:
    python scripts/dev.py
    python scripts/dev.py --backend-only
"""

from __future__ import annotations

import argparse
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import NoReturn


def is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a network port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError):
        return False


def ensure_redis() -> None:
    """Ensure Redis is running on port 6379, starting it via docker compose if needed."""
    if is_port_open("localhost", 6379):
        print("[dev] Redis is running on localhost:6379.")
        return

    print(
        "[dev] Redis is not reachable on localhost:6379. "
        "Attempting to start via docker compose..."
    )
    docker_bin = shutil.which("docker")
    if not docker_bin:
        print(
            "[dev] WARNING: Docker not found on PATH. Please ensure Redis is running at "
            "redis://localhost:6379/0 or start it manually."
        )
        return

    try:
        res = subprocess.run(
            [docker_bin, "compose", "up", "-d", "redis"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode == 0:
            print("[dev] Docker started redis service successfully.")
            for _ in range(10):
                time.sleep(1.0)
                if is_port_open("localhost", 6379):
                    print("[dev] Redis container is ready and accepting connections.")
                    return
        else:
            print(f"[dev] Docker compose redis failed: {res.stderr.strip()}")
    except Exception as exc:
        print(f"[dev] Could not auto-start Redis via docker: {exc}")


def main() -> NoReturn:
    parser = argparse.ArgumentParser(description="ClipForge AI unified dev environment runner")
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="Run only Redis, Celery worker, and FastAPI backend (skip Vite frontend)",
    )
    args = parser.parse_args()

    ensure_redis()

    processes: list[subprocess.Popen[bytes]] = []

    def shutdown(signum: int, frame: object | None) -> None:
        print("\n[dev] Shutting down ClipForge development processes...")
        for p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1.0)
        for p in processes:
            try:
                p.kill()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    python_bin = sys.executable

    # 1. Start Celery worker
    worker_cmd = [
        python_bin,
        "-m",
        "celery",
        "-A",
        "app.tasks.celery_app",
        "worker",
        "-Q",
        "default,transcription,indexing,rendering",
        "--loglevel=info",
    ]
    if sys.platform == "win32":
        # Windows requires solo or threads pool for Celery
        worker_cmd.extend(["-P", "solo"])

    print(f"[dev] Starting Celery worker: {' '.join(worker_cmd)}")
    worker_proc = subprocess.Popen(worker_cmd)
    processes.append(worker_proc)

    # 2. Start FastAPI server
    api_cmd = [
        python_bin,
        "-m",
        "uvicorn",
        "app.main:app",
        "--reload",
        "--port",
        "8000",
    ]
    print(f"[dev] Starting FastAPI API server on http://localhost:8000: {' '.join(api_cmd)}")
    api_proc = subprocess.Popen(api_cmd)
    processes.append(api_proc)

    # 3. Start Frontend (if not --backend-only)
    if not args.backend_only:
        npm_bin = shutil.which("npm") or shutil.which("npm.cmd")
        if npm_bin:
            fe_cmd = [npm_bin, "--prefix", "frontend", "run", "dev"]
            print(f"[dev] Starting Vite frontend server: {' '.join(fe_cmd)}")
            fe_proc = subprocess.Popen(fe_cmd)
            processes.append(fe_proc)
        else:
            print(
                "[dev] WARNING: npm not found. "
                "Run `npm --prefix frontend run dev` in a separate terminal."
            )

    print("\n" + "=" * 60)
    print(" ClipForge AI Full Dev Stack Running!")
    print(" - Backend API:  http://localhost:8000 (docs at /docs)")
    print(" - Frontend UI:  http://localhost:5173")
    print(" - Celery Queue: default, transcription, indexing, rendering")
    print(" Press Ctrl+C to terminate all services together.")
    print("=" * 60 + "\n")

    try:
        while True:
            time.sleep(1.0)
            # Check if any process died unexpectedly
            for p in processes:
                code = p.poll()
                if code is not None:
                    print(f"[dev] Process {p.args} exited with code {code}. Shutting down...")
                    shutdown(0, None)
    except KeyboardInterrupt:
        shutdown(0, None)
    sys.exit(0)


if __name__ == "__main__":
    main()
