from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from snapchat_export_organizer.web import LauncherState, create_app


class StubDialogProvider:
    def __init__(
        self,
        *,
        zip_paths: list[str] | None = None,
        folder_paths: dict[str, str | None] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        self.zip_paths = list(zip_paths or [])
        self.folder_paths = dict(folder_paths or {})
        self.errors = dict(errors or {})
        self.calls: list[tuple[str, str | None]] = []

    def select_zip_files(self) -> list[str]:
        self.calls.append(("select_zip_files", None))
        if "select_zip_files" in self.errors:
            raise RuntimeError(self.errors["select_zip_files"])
        return list(self.zip_paths)

    def select_folder(self, title: str) -> str | None:
        self.calls.append(("select_folder", title))
        if title in self.errors:
            raise RuntimeError(self.errors[title])
        return self.folder_paths.get(title)


def _wait_for_completion(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        payload = client.get(f"/api/jobs/{job_id}").json()
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.1)
    raise AssertionError("The job did not complete within the expected time.")


def test_app_state_endpoint() -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    payload = client.get("/api/app-state").json()

    assert payload["app_name"] == "Snapchat Export Organizer"
    assert payload["port"] == 8765
    assert payload["current_job_id"] is None


def test_dialog_endpoints_use_injected_provider(monkeypatch) -> None:
    provider = StubDialogProvider(
        zip_paths=["C:/exports/one.zip", "C:/exports/two.zip"],
        folder_paths={
            "Select a Snapchat export folder": "C:/exports/folder-input",
            "Select output folder": "C:/exports/output",
        },
    )
    monkeypatch.setattr(
        "snapchat_export_organizer.web.default_dialog_provider",
        lambda: (_ for _ in ()).throw(AssertionError("default dialog provider should not be used")),
    )
    client = TestClient(create_app(LauncherState(port=8765), dialog_provider=provider))

    zips_response = client.post("/api/dialog/select-zips")
    folder_response = client.post("/api/dialog/select-folder")
    output_response = client.post("/api/dialog/select-output")

    assert zips_response.status_code == 200
    assert zips_response.json() == {"paths": ["C:/exports/one.zip", "C:/exports/two.zip"]}
    assert folder_response.status_code == 200
    assert folder_response.json() == {"path": "C:/exports/folder-input"}
    assert output_response.status_code == 200
    assert output_response.json() == {"path": "C:/exports/output"}
    assert provider.calls == [
        ("select_zip_files", None),
        ("select_folder", "Select a Snapchat export folder"),
        ("select_folder", "Select output folder"),
    ]


def test_select_folder_endpoint_returns_null_when_dialog_is_cancelled() -> None:
    provider = StubDialogProvider(folder_paths={"Select a Snapchat export folder": None})
    client = TestClient(create_app(LauncherState(port=8765), dialog_provider=provider))

    response = client.post("/api/dialog/select-folder")

    assert response.status_code == 200
    assert response.json() == {"path": None}


def test_select_output_endpoint_returns_provider_errors() -> None:
    provider = StubDialogProvider(errors={"Select output folder": "Could not open the folder picker."})
    client = TestClient(create_app(LauncherState(port=8765), dialog_provider=provider))

    response = client.post("/api/dialog/select-output")

    assert response.status_code == 500
    assert response.json()["detail"] == "Could not open the folder picker."


def test_job_creation_requires_sources() -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    response = client.post("/api/jobs", json={"sources": [], "output_dir": "C:/output"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Please add at least one ZIP file or folder."


def test_summary_requires_sources() -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    response = client.post("/api/analysis/summary", json={"sources": []})

    assert response.status_code == 400
    assert response.json()["detail"] == "Please add at least one ZIP file or folder."


def test_job_creation_requires_output_dir(sample_export_dir: Path) -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    response = client.post("/api/jobs", json={"sources": [str(sample_export_dir)], "output_dir": ""})

    assert response.status_code == 400
    assert response.json()["detail"] == "Please choose an output folder."


def test_summary_endpoint_from_folder(summary_export_dir: Path) -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    response = client.post("/api/analysis/summary", json={"sources": [str(summary_export_dir)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["zip_count"] == 0
    assert payload["folder_count"] == 1
    assert payload["metadata_records"] == 4
    assert payload["total_media"] == 4
    assert payload["image_count"] == 2
    assert payload["video_count"] == 2
    assert payload["scan_complete"] is True
    assert payload["scan_ready"] is False
    assert payload["found_media_files"] == 0
    assert payload["matched_media_files"] == 0
    assert payload["missing_media_files"] == 4
    assert payload["orphan_media_files"] == 0
    assert len(payload["errors"]) == 1
    assert payload["warnings"] == []


def test_summary_endpoint_from_zip(summary_export_zip: Path) -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    response = client.post("/api/analysis/summary", json={"sources": [str(summary_export_zip)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["zip_count"] == 1
    assert payload["folder_count"] == 0
    assert payload["metadata_records"] == 4
    assert payload["total_media"] == 4
    assert payload["image_count"] == 2
    assert payload["video_count"] == 2
    assert payload["scan_complete"] is True
    assert payload["scan_ready"] is False
    assert payload["found_media_files"] == 0
    assert payload["matched_media_files"] == 0
    assert payload["missing_media_files"] == 4
    assert payload["orphan_media_files"] == 0
    assert len(payload["errors"]) == 1
    assert payload["warnings"] == []


def test_summary_endpoint_blocks_start_when_scan_has_missing_and_orphan_files(
    reconciliation_issue_export_dir: Path,
) -> None:
    client = TestClient(create_app(LauncherState(port=8765)))

    response = client.post("/api/analysis/summary", json={"sources": [str(reconciliation_issue_export_dir)]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["scan_complete"] is True
    assert payload["scan_ready"] is False
    assert payload["matched_media_files"] == 1
    assert payload["missing_media_files"] == 1
    assert payload["orphan_media_files"] == 1
    assert payload["errors"] == []


def test_job_lifecycle_and_event_endpoint(sample_export_dir: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(LauncherState(port=8765)))
    output_dir = tmp_path / "output"

    create_response = client.post(
        "/api/jobs",
        json={"sources": [str(sample_export_dir)], "output_dir": str(output_dir)},
    )

    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

    payload = _wait_for_completion(client, job_id)

    assert payload["status"] == "completed"
    assert payload["stats"]["merged_files"] == 1
    assert payload["stats"]["tagged_files"] == 1
    assert payload["progress"]["phase"] == "completed"
    assert payload["progress"]["completed_files"] == 1
    assert payload["progress"]["files_left"] == 0
    assert len(list(output_dir.glob("*.jpg"))) == 1


def test_job_events_include_progress_updates(progress_export_dir: Path, tmp_path: Path) -> None:
    client = TestClient(create_app(LauncherState(port=8765)))
    output_dir = tmp_path / "output-progress-api"

    create_response = client.post(
        "/api/jobs",
        json={"sources": [str(progress_export_dir)], "output_dir": str(output_dir)},
    )

    assert create_response.status_code == 201
    job_id = create_response.json()["job_id"]

    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: progress" in body
    assert '"total_files": 4' in body

    payload = _wait_for_completion(client, job_id)
    assert payload["status"] == "completed"
    assert payload["progress"]["phase"] == "completed"
    assert payload["progress"]["total_files"] == 4
    assert payload["progress"]["completed_files"] == 4
    assert payload["progress"]["files_left"] == 0
