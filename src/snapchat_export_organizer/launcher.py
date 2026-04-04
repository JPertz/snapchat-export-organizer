from __future__ import annotations

import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from .dialogs import NativeDialogService
from .web import LauncherState, create_app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _wait_for_server(url: str, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise RuntimeError("The local web server did not start in time.")


def run() -> None:
    port = _find_free_port()
    launcher_state = LauncherState(port=port)
    dialog_service = NativeDialogService()
    app = create_app(launcher_state, dialog_provider=dialog_service)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    server_thread = threading.Thread(target=server.run, daemon=True, name="snapchat-export-organizer-server")
    server_thread.start()

    try:
        app_url = f"http://127.0.0.1:{port}"
        _wait_for_server(app_url)
        webbrowser.open(app_url, new=1)

        started_at = time.monotonic()
        while server_thread.is_alive():
            dialog_service.pump_events(timeout_seconds=0.1)
            if launcher_state.shutdown_requested.is_set():
                server.should_exit = True

            idle_seconds = launcher_state.seconds_since_last_heartbeat()
            if launcher_state.heartbeat_seen.is_set():
                if idle_seconds is not None and idle_seconds > launcher_state.heartbeat_timeout_seconds:
                    server.should_exit = True
            elif time.monotonic() - started_at > launcher_state.startup_grace_seconds:
                server.should_exit = True

            if server.should_exit:
                break

            time.sleep(0.1)
    except KeyboardInterrupt:
        server.should_exit = True
    finally:
        server.should_exit = True
        dialog_service.close()
        server_thread.join(timeout=15.0)
