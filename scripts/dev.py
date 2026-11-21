from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env", override=False)
HOST = "127.0.0.1"
PORT = 8000


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        try:
            server.bind((host, port))
            return True
        except OSError:
            return False


def start_process(name: str, command: list[str]) -> subprocess.Popen:
    environment = os.environ.copy()
    environment["PYTHONUNBUFFERED"] = "1"

    print(f"\n[DEV] Starting {name}...", flush=True)

    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
    )


def wait_for_api(
    process: subprocess.Popen,
    timeout: float = 60,
) -> None:
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        exit_code = process.poll()

        if exit_code is not None:
            raise RuntimeError(f"FastAPI exited during startup with code {exit_code}.")

        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                print("[DEV] FastAPI is accepting connections.", flush=True)
                return
        except OSError:
            time.sleep(0.25)

    raise RuntimeError("FastAPI did not become ready within 60 seconds.")


def stop_process(name: str, process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    print(f"[DEV] Stopping {name}...", flush=True)

    try:
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGINT)

        process.wait(timeout=15)

    except subprocess.TimeoutExpired:
        print(f"[DEV] {name} did not stop gracefully; terminating.", flush=True)
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    except ProcessLookupError:
        pass


def main() -> int:
    processes: list[tuple[str, subprocess.Popen]] = []

    # Detect a stale API server before creating any child process.
    if not is_port_available(HOST, PORT):
        print(
            f"[DEV] Port {PORT} is already occupied.\n"
            "[DEV] Stop the existing FastAPI process before starting "
            "development mode.",
            flush=True,
        )
        return 1

    python = sys.executable

    try:
        api = start_process(
            "FastAPI",
            [
                python,
                "-m",
                "uvicorn",
                "market_intelligence.api.app:app",
                "--reload",
                "--reload-dir",
                str(PROJECT_ROOT / "src"),
                "--host",
                HOST,
                "--port",
                str(PORT),
            ],
        )
        processes.append(("FastAPI", api))

        print("[DEV] Waiting for FastAPI startup...", flush=True)
        wait_for_api(api)

        # Start the worker only after FastAPI has successfully started.
        worker = start_process(
            "Research worker",
            [
                python,
                "-m",
                "market_intelligence.workers.research_worker",
            ],
        )
        processes.append(("Research worker", worker))

        print("\n" + "=" * 58, flush=True)
        print(" ASYNC MARKET INTELLIGENCE — DEVELOPMENT MODE", flush=True)
        print("=" * 58, flush=True)
        print(" API:       http://127.0.0.1:8000", flush=True)
        print(" API docs:  http://127.0.0.1:8000/docs", flush=True)
        print(" Worker:    Running", flush=True)
        print("=" * 58, flush=True)
        print("Press Ctrl+C to stop both processes.\n", flush=True)

        while True:
            for name, process in processes:
                exit_code = process.poll()

                if exit_code is not None:
                    raise RuntimeError(f"{name} exited unexpectedly with code {exit_code}.")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[DEV] Shutdown requested.", flush=True)
        return 0

    except RuntimeError as exc:
        print(f"\n[DEV] Startup/runtime error: {exc}", flush=True)
        return 1

    finally:
        for name, process in reversed(processes):
            stop_process(name, process)

        if processes:
            print("[DEV] Development processes stopped.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
