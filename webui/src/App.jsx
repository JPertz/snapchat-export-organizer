import { useEffect, useRef, useState } from "react";

const initialSummary = {
  zip_count: 0,
  folder_count: 0,
  source_item_count: 0,
  metadata_records: 0,
  total_media: 0,
  image_count: 0,
  video_count: 0,
  scan_complete: false,
  scan_ready: false,
  found_media_files: 0,
  matched_media_files: 0,
  missing_media_files: 0,
  orphan_media_files: 0,
  errors: [],
  warnings: [],
};

const initialStats = {
  discovered_metadata: 0,
  discovered_media: 0,
  merged_files: 0,
  tagged_files: 0,
  skipped_files: 0,
  error_count: 0,
  errors: [],
};

const initialProgress = {
  phase: "idle",
  total_files: 0,
  completed_files: 0,
  files_left: 0,
  merged_files: 0,
  tagged_files: 0,
  skipped_files: 0,
  error_count: 0,
  progress_percent: 0,
  current_mid: null,
  current_output_name: null,
  started_at: null,
  elapsed_seconds: 0,
  estimated_remaining_seconds: null,
};

const DIALOG_REQUEST_TIMEOUT_MS = 15000;

function dedupePaths(currentPaths, incomingPaths) {
  const known = new Set(currentPaths);
  const merged = [...currentPaths];
  for (const value of incomingPaths) {
    if (!known.has(value)) {
      known.add(value);
      merged.push(value);
    }
  }
  return merged;
}

async function readJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail ?? detail;
    } catch {
      detail = response.statusText;
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return null;
  }

  return response.json();
}

async function readDialogJson(url, options, timeoutMessage) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), DIALOG_REQUEST_TIMEOUT_MS);

  try {
    return await readJson(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(timeoutMessage);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function formatPhaseLabel(phase) {
  switch (phase) {
    case "preparing":
      return "Preparing inputs";
    case "loading_metadata":
      return "Loading metadata";
    case "scanning_media":
      return "Scanning media";
    case "processing":
      return "Processing files";
    case "completed":
      return "All files processed";
    case "failed":
      return "Processing failed";
    default:
      return "Waiting to start";
  }
}

function formatDuration(totalSeconds) {
  const rounded = Math.max(0, Math.round(totalSeconds ?? 0));
  const minutes = Math.floor(rounded / 60);
  const seconds = rounded % 60;
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

function App() {
  const [appState, setAppState] = useState(null);
  const [sources, setSources] = useState([]);
  const [outputDir, setOutputDir] = useState("");
  const [summaryData, setSummaryData] = useState(initialSummary);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [job, setJob] = useState(null);
  const [jobStatus, setJobStatus] = useState("ready");
  const [logLines, setLogLines] = useState([]);
  const [stats, setStats] = useState(initialStats);
  const [progress, setProgress] = useState(initialProgress);
  const [errorMessage, setErrorMessage] = useState("");
  const [inputPickerBusy, setInputPickerBusy] = useState("");
  const [outputPickerBusy, setOutputPickerBusy] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showInputPicker, setShowInputPicker] = useState(false);
  const eventSourceRef = useRef(null);
  const logSectionRef = useRef(null);

  const loadAppState = async () => {
    const payload = await readJson("/api/app-state");
    setAppState(payload);
  };

  const loadJob = async (jobId) => {
    const payload = await readJson(`/api/jobs/${jobId}`);
    setJob(payload);
    setJobStatus(payload.status);
    setStats(payload.stats ?? initialStats);
    setProgress(payload.progress ?? initialProgress);
    setLogLines(payload.logs ?? []);
  };

  useEffect(() => {
    loadAppState().catch((error) => {
      setErrorMessage(error.message);
    });
  }, []);

  useEffect(() => {
    if (sources.length === 0) {
      setSummaryData(initialSummary);
      setIsAnalyzing(false);
      return undefined;
    }

    let cancelled = false;
    setIsAnalyzing(true);

    readJson("/api/analysis/summary", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ sources }),
    })
      .then((payload) => {
        if (cancelled) {
          return;
        }
        setSummaryData(payload);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setErrorMessage(error.message);
      })
      .finally(() => {
        if (!cancelled) {
          setIsAnalyzing(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [sources]);

  useEffect(() => {
    const heartbeat = window.setInterval(() => {
      fetch("/api/heartbeat", {
        method: "POST",
        keepalive: true,
      }).catch(() => {
        // The launcher may already be shutting down.
      });
    }, 15000);

    return () => {
      window.clearInterval(heartbeat);
    };
  }, []);

  useEffect(() => {
    if (!job?.job_id) {
      return undefined;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const stream = new EventSource(`/api/jobs/${job.job_id}/events`);
    eventSourceRef.current = stream;

    const appendLog = (event) => {
      const payload = JSON.parse(event.data);
      setLogLines((current) => [...current, payload.message]);
    };

    const updateProgress = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.progress) {
        setProgress(payload.progress);
      }
    };

    const refreshJob = () => {
      loadJob(job.job_id).catch((error) => {
        setErrorMessage(error.message);
      });
    };

    stream.addEventListener("log", appendLog);
    stream.addEventListener("progress", updateProgress);
    stream.addEventListener("status", refreshJob);
    stream.addEventListener("completed", () => {
      refreshJob();
      stream.close();
    });
    stream.addEventListener("failed", () => {
      refreshJob();
      stream.close();
    });
    stream.addEventListener("close", () => {
      stream.close();
    });
    stream.onerror = () => {
      stream.close();
    };

    return () => {
      stream.close();
    };
  }, [job?.job_id]);

  const handleSelectZips = async () => {
    setShowInputPicker(false);
    setInputPickerBusy("zips");
    setErrorMessage("");
    try {
      const payload = await readDialogJson(
        "/api/dialog/select-zips",
        { method: "POST" },
        "The ZIP file picker did not respond. Please try again."
      );
      setSources((current) => dedupePaths(current, payload.paths));
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setInputPickerBusy("");
    }
  };

  const handleSelectFolder = async () => {
    setShowInputPicker(false);
    setInputPickerBusy("folder");
    setErrorMessage("");
    try {
      const payload = await readDialogJson(
        "/api/dialog/select-folder",
        { method: "POST" },
        "The folder picker did not respond. Please try again."
      );
      if (payload.path) {
        setSources((current) => dedupePaths(current, [payload.path]));
      }
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setInputPickerBusy("");
    }
  };

  const handleSelectOutput = async () => {
    setOutputPickerBusy(true);
    setErrorMessage("");
    try {
      const payload = await readDialogJson(
        "/api/dialog/select-output",
        { method: "POST" },
        "The output folder picker did not respond. Please try again."
      );
      if (payload.path) {
        setOutputDir(payload.path);
      }
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setOutputPickerBusy(false);
    }
  };

  const handleStart = async () => {
    setIsSubmitting(true);
    setErrorMessage("");
    setLogLines([]);
    setStats(initialStats);
    setProgress(initialProgress);
    try {
      const payload = await readJson("/api/jobs", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          sources,
          output_dir: outputDir,
        }),
      });
      await loadJob(payload.job_id);
      window.requestAnimationFrame(() => {
        logSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (error) {
      setErrorMessage(error.message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleShutdown = async () => {
    try {
      await readJson("/api/shutdown", { method: "POST" });
      window.close();
    } catch (error) {
      setErrorMessage(error.message);
    }
  };

  const removeSource = (value) => {
    setSources((current) => current.filter((item) => item !== value));
  };

  const clearSources = () => {
    setSources([]);
    setShowInputPicker(false);
  };

  const running = jobStatus === "running";
  const inputPickerActive = inputPickerBusy.length > 0;
  const summaryErrors = summaryData.errors ?? [];
  const summaryWarnings = summaryData.warnings ?? [];
  const readyToStart =
    sources.length > 0 &&
    outputDir.trim().length > 0 &&
    !running &&
    !isSubmitting &&
    !isAnalyzing &&
    summaryData.scan_ready;
  const scanStatusLabel =
    isAnalyzing
      ? "Scanning..."
      : summaryData.scan_ready
        ? "Ready to process"
        : sources.length === 0
          ? "Add inputs to scan"
          : "Blocked: scan issues found";
  const startBlockedReason =
    sources.length === 0
      ? "Add at least one ZIP file or folder."
      : isAnalyzing
        ? "Waiting for scan to finish."
        : outputDir.trim().length === 0
          ? "Choose an output folder."
          : summaryErrors[0]
            ? summaryErrors[0]
            : summaryData.missing_media_files > 0
              ? `${summaryData.missing_media_files} media files from JSON were not found.`
              : summaryData.orphan_media_files > 0
                ? `${summaryData.orphan_media_files} files were found without matching JSON records.`
                : !summaryData.scan_ready
                  ? "Summary scan has not passed yet."
                  : "";
  const statusLabel =
    jobStatus === "running"
      ? "Processing"
      : jobStatus === "completed"
        ? "Completed"
        : jobStatus === "failed"
          ? "Failed"
          : "Ready";
  const etaLabel =
    progress.estimated_remaining_seconds == null
      ? progress.completed_files >= 3 || jobStatus === "completed"
        ? "Done"
        : "Calculating..."
      : formatDuration(progress.estimated_remaining_seconds);

  return (
    <div className="page-shell">
      <header className="topbar">
        <div className="brand">
          <div>
            <h1>Snapchat Export Organizer</h1>
            <p className="subtitle">
              Merge Snapchat export overlays, rebuild photos and videos, and write capture metadata locally on this PC without storing media in the app folder.
            </p>
          </div>
        </div>
        <div className="topbar-actions">
          <div className={`status-badge status-${jobStatus}`}>
            <span className="status-dot" />
            {statusLabel}
          </div>
          <button className="ghost-button" type="button" onClick={handleShutdown}>
            Close app
          </button>
        </div>
      </header>

      {errorMessage ? <div className="alert-banner">{errorMessage}</div> : null}

      <main className="dashboard">
        <aside className="sidebar-card">
          <h2>Summary</h2>
          <div className="metric-tile">
            <strong>{summaryData.total_media}</strong>
            <span>Processable Snapchat media</span>
          </div>
          <div className="metric-list">
            <div>
              <span>Input items</span>
              <strong>{summaryData.source_item_count}</strong>
            </div>
            <div>
              <span>ZIP files</span>
              <strong>{summaryData.zip_count}</strong>
            </div>
            <div>
              <span>Folders</span>
              <strong>{summaryData.folder_count}</strong>
            </div>
            <div>
              <span>Images</span>
              <strong>{summaryData.image_count}</strong>
            </div>
            <div>
              <span>Videos</span>
              <strong>{summaryData.video_count}</strong>
            </div>
            <div>
              <span>Metadata records</span>
              <strong>{summaryData.metadata_records}</strong>
            </div>
          </div>
          <div className="info-card">
            <h3>Last processing result</h3>
            <p>Merged: {stats.merged_files}</p>
            <p>Tagged: {stats.tagged_files}</p>
            <p>Errors: {stats.error_count}</p>
          </div>
          <div className="info-card">
            <h3>Scan checks</h3>
            <p>Matched media: {summaryData.matched_media_files}</p>
            <p>Missing media: {summaryData.missing_media_files}</p>
            <p>Orphan files: {summaryData.orphan_media_files}</p>
          </div>
          <div className="footnote">
            <p>{scanStatusLabel}</p>
            <p>Media counts exclude JSON files, folders, and other non-media export items.</p>
            <p>Temporary work files are cleaned up automatically.</p>
            <p>Only one app instance can process media at a time.</p>
          </div>
          {summaryErrors.length > 0 ? (
            <div className="alert-inline">
              Summary error: {summaryErrors[0]}
            </div>
          ) : null}
          {!summaryErrors.length && summaryWarnings.length > 0 ? (
            <div className="alert-inline">
              Summary warning: {summaryWarnings[0]}
            </div>
          ) : null}
          <div className="footnote">
            <p>Version {appState?.version ?? "..."}</p>
            <p>{appState?.platform ?? "Windows"} local mode</p>
          </div>
        </aside>

        <section className="content-card">
          <div className="card-header">
            <div>
              <p className="eyebrow">Export Settings</p>
              <h2>Prepare your local Snapchat export</h2>
              <p className="subtitle">
                Add ZIP archives or extracted folders, choose one target folder, and keep temporary work files out of the project folder.
              </p>
            </div>
            <button
              className="primary-button"
              type="button"
              onClick={handleStart}
              disabled={!readyToStart}
            >
              {running || isSubmitting ? "Processing..." : "Start processing"}
            </button>
          </div>
          {!readyToStart && sources.length > 0 ? (
            <div className="alert-inline">
              {startBlockedReason}
            </div>
          ) : null}

          <div className="action-row">
            <div className="input-picker">
              <button
                className="secondary-button"
                type="button"
                onClick={() => setShowInputPicker((current) => !current)}
                disabled={inputPickerActive || running}
              >
                {inputPickerActive ? "Opening..." : "Add inputs"}
              </button>
              {showInputPicker ? (
                <div className="input-picker-menu">
                  <button className="ghost-button" type="button" onClick={handleSelectZips} disabled={inputPickerActive || running}>
                    {inputPickerBusy === "zips" ? "Opening ZIP picker..." : "ZIP files"}
                  </button>
                  <button className="ghost-button" type="button" onClick={handleSelectFolder} disabled={inputPickerActive || running}>
                    {inputPickerBusy === "folder" ? "Opening folder picker..." : "Folder"}
                  </button>
                </div>
              ) : null}
            </div>
            <button className="ghost-button" type="button" onClick={clearSources} disabled={sources.length === 0 || running}>
              Clear list
            </button>
          </div>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h3>Selected inputs</h3>
                <p>These paths are passed directly to the local Python pipeline.</p>
              </div>
            </div>
            <div className="source-list">
              {sources.length === 0 ? (
                <div className="empty-state">No ZIP files or folders selected yet.</div>
              ) : (
                sources.map((source) => (
                  <div className="source-item" key={source}>
                    <div>
                      <span className="source-kind">{source.toLowerCase().endsWith(".zip") ? "ZIP" : "Folder"}</span>
                      <p>{source}</p>
                    </div>
                    <button className="ghost-button" type="button" onClick={() => removeSource(source)} disabled={running}>
                      Remove
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="panel">
            <div className="panel-header">
              <div>
                <h3>Output folder</h3>
                <p>Finished files stay here. ZIP contents are unpacked only in temporary system storage and cleaned up afterwards.</p>
              </div>
              <button
                className="secondary-button"
                type="button"
                onClick={handleSelectOutput}
                disabled={outputPickerBusy || running}
              >
                {outputPickerBusy ? "Opening..." : "Browse"}
              </button>
            </div>
            <input
              className="path-input"
              type="text"
              value={outputDir}
              onChange={(event) => setOutputDir(event.target.value)}
              placeholder="Choose or paste an output path"
              disabled={running}
            />
          </section>

          <section className="stats-grid">
            <article className="stat-card">
              <span>Total media</span>
              <strong>{summaryData.total_media}</strong>
            </article>
            <article className="stat-card">
              <span>Images</span>
              <strong>{summaryData.image_count}</strong>
            </article>
            <article className="stat-card">
              <span>Videos</span>
              <strong>{summaryData.video_count}</strong>
            </article>
            <article className="stat-card">
              <span>Metadata records</span>
              <strong>{summaryData.metadata_records}</strong>
            </article>
          </section>
        </section>
      </main>

      <section className="log-card" ref={logSectionRef}>
        <div className="panel-header">
          <div>
            <p className="eyebrow">Processing Log</p>
            <h2>Live status updates</h2>
          </div>
          <div className={`status-badge status-${jobStatus}`}>{statusLabel}</div>
        </div>

        <section className="progress-grid">
          <article className="progress-card">
            <span>Files left</span>
            <strong>{progress.files_left}</strong>
          </article>
          <article className="progress-card">
            <span>Done</span>
            <strong>{progress.completed_files}</strong>
          </article>
          <article className="progress-card">
            <span>Tagged</span>
            <strong>{progress.tagged_files}</strong>
          </article>
          <article className="progress-card">
            <span>Skipped</span>
            <strong>{progress.skipped_files}</strong>
          </article>
          <article className="progress-card">
            <span>Errors</span>
            <strong>{progress.error_count}</strong>
          </article>
          <article className="progress-card">
            <span>Estimated time left</span>
            <strong>{etaLabel}</strong>
          </article>
        </section>

        <div className="progress-panel">
          <div className="progress-meta">
            <div>
              <span>Current step</span>
              <strong>{formatPhaseLabel(progress.phase)}</strong>
            </div>
            <div>
              <span>Current file</span>
              <strong>{progress.current_output_name ?? "Waiting..."}</strong>
            </div>
            <div>
              <span>Elapsed time</span>
              <strong>{formatDuration(progress.elapsed_seconds)}</strong>
            </div>
          </div>
          <div className="progress-bar-track" aria-label="Processing progress">
            <div className="progress-bar-fill" style={{ width: `${progress.progress_percent}%` }} />
          </div>
          <div className="progress-caption">
            <span>{progress.total_files > 0 ? `${progress.completed_files} / ${progress.total_files} files` : "Waiting for file count..."}</span>
            <strong>{Math.round(progress.progress_percent)}%</strong>
          </div>
        </div>

        <div className="log-surface">
          {logLines.length === 0 ? (
            <div className="empty-state">The live log will appear here once processing starts.</div>
          ) : (
            logLines.map((line, index) => (
              <div className="log-line" key={`${index}-${line}`}>
                {line}
              </div>
            ))
          )}
        </div>

        {job?.error ? <div className="alert-inline">Job failed: {job.error}</div> : null}
      </section>
    </div>
  );
}

export default App;
