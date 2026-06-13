const healthBadge = document.querySelector("#health");
const libraryStatus = document.querySelector("#library-status");
const playbackStatus = document.querySelector("#playback-status");
const libraryPath = document.querySelector("#library-path");
const libraryList = document.querySelector("#library-list");
const queueStatus = document.querySelector("#queue-status");
const queueList = document.querySelector("#queue-list");
const nowPlayingTitle = document.querySelector("#now-playing-title");
const elapsedTime = document.querySelector("#elapsed-time");
const durationTime = document.querySelector("#duration-time");
const trackProgress = document.querySelector("#track-progress");
const upButton = document.querySelector("#up-button");
const previousButton = document.querySelector("#previous-button");
const playButton = document.querySelector("#play-button");
const pauseButton = document.querySelector("#pause-button");
const stopButton = document.querySelector("#stop-button");
const nextButton = document.querySelector("#next-button");
const repeatButton = document.querySelector("#repeat-button");

let currentDirectoryFiles = [];
let lastPlaybackState = null;

async function loadApp() {
  try {
    const [healthResponse, browseResponse, playbackResponse] = await Promise.all([
      fetch("/api/health"),
      fetchBrowse(currentPath()),
      fetch("/api/player/local/status"),
    ]);

    if (!healthResponse.ok) {
      throw new Error("Status request failed");
    }

    const health = await healthResponse.json();

    healthBadge.textContent = health.status;
    healthBadge.dataset.state = "ok";
    await renderBrowseResponse(browseResponse);
    await renderPlaybackResponse(playbackResponse);
  } catch (error) {
    healthBadge.textContent = "Offline";
    healthBadge.dataset.state = "error";
    libraryStatus.textContent = "The application API is not responding.";
    clearLibraryList();
  }
}

async function loadDirectory(path) {
  libraryStatus.textContent = "Loading...";
  playbackStatus.textContent = "";
  clearLibraryList();

  try {
    const response = await fetchBrowse(path);
    await renderBrowseResponse(response);
  } catch (error) {
    libraryStatus.textContent = "The library folder could not be loaded.";
  }
}

function fetchBrowse(path) {
  const params = new URLSearchParams();
  if (path) {
    params.set("path", path);
  }

  const query = params.toString();
  return fetch(`/api/library/browse${query ? `?${query}` : ""}`);
}

async function renderBrowseResponse(response) {
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Browse request failed");
  }

  const directory = await response.json();
  renderDirectory(directory);
}

function renderDirectory(directory) {
  libraryPath.textContent = `/${directory.path}`;
  upButton.disabled = directory.parent_path === null;
  upButton.dataset.path = directory.parent_path || "";
  currentDirectoryFiles = directory.files.map((entry) => entry.path);

  clearLibraryList();

  const entries = [
    ...directory.directories.map((entry) => ({ ...entry, icon: "folder" })),
    ...directory.files.map((entry) => ({ ...entry, icon: "audio" })),
  ];

  if (entries.length === 0) {
    libraryStatus.textContent = "No supported audio files or folders found.";
    return;
  }

  libraryStatus.textContent = `${directory.directories.length} folders, ${directory.files.length} files`;

  for (const entry of entries) {
    libraryList.appendChild(createEntry(entry));
  }
}

function createEntry(entry) {
  const item = document.createElement("li");
  item.className = "library-item";

  const row = document.createElement("div");
  row.className = "entry-row";

  const detailsElement =
    entry.type === "directory" ? document.createElement("button") : document.createElement("div");
  detailsElement.className = "entry-details-button";

  if (entry.type === "directory") {
    detailsElement.type = "button";
    detailsElement.addEventListener("click", () => navigateTo(entry.path));
  }

  const icon = document.createElement("span");
  icon.className = "entry-icon";
  icon.textContent = entry.icon === "folder" ? "DIR" : "AUD";

  const details = document.createElement("span");
  details.className = "entry-details";

  const name = document.createElement("span");
  name.className = "entry-name";
  name.textContent = entry.name;

  const meta = document.createElement("span");
  meta.className = "entry-meta";
  meta.textContent = entry.type === "directory" ? "Folder" : formatSize(entry.size_bytes);

  details.append(name, meta);
  detailsElement.append(icon, details);
  row.appendChild(detailsElement);

  if (entry.type === "file") {
    const playButton = document.createElement("button");
    playButton.className = "play-button";
    playButton.type = "button";
    playButton.textContent = "Play on Pi";
    playButton.addEventListener("click", () => playOnPi(entry, playButton));
    row.appendChild(playButton);
  }

  item.appendChild(row);
  return item;
}

async function playOnPi(entry, playButton) {
  const originalText = playButton.textContent;
  playButton.disabled = true;
  playButton.textContent = "Starting";
  playbackStatus.textContent = `Starting ${entry.name} on Pi...`;
  playbackStatus.dataset.state = "";

  try {
    const params = new URLSearchParams({ path: entry.path });
    const response = await fetch(`/api/player/local/play?${params.toString()}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        queue_paths: currentDirectoryFiles,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Playback request failed");
    }

    playbackStatus.textContent = `Playing on Pi: ${entry.name}`;
    playbackStatus.dataset.state = "ok";
    await refreshPlaybackStatus();
  } catch (error) {
    playbackStatus.textContent = `Could not start playback: ${error.message}`;
    playbackStatus.dataset.state = "error";
  } finally {
    playButton.disabled = false;
    playButton.textContent = originalText;
  }
}

async function sendTransportCommand(endpoint) {
  playbackStatus.textContent = "Updating playback...";
  playbackStatus.dataset.state = "";

  try {
    const response = await fetch(endpoint, { method: "POST" });
    await renderPlaybackResponse(response);
  } catch (error) {
    playbackStatus.textContent = `Playback command failed: ${error.message}`;
    playbackStatus.dataset.state = "error";
  }
}

async function refreshPlaybackStatus() {
  try {
    const response = await fetch("/api/player/local/status");
    await renderPlaybackResponse(response);
  } catch (error) {
    playbackStatus.textContent = "Playback status is unavailable.";
    playbackStatus.dataset.state = "error";
  }
}

async function renderPlaybackResponse(response) {
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Playback request failed");
  }

  const playbackState = await response.json();
  lastPlaybackState = playbackState;
  renderPlaybackState(playbackState);
}

function renderPlaybackState(playbackState) {
  const nowPlaying = playbackState.now_playing;
  nowPlayingTitle.textContent = nowPlaying ? nowPlaying.name : "Nothing playing";
  playbackStatus.textContent = playbackMessage(playbackState);
  playbackStatus.dataset.state = playbackState.state === "stopped" ? "" : "ok";

  renderTimer(playbackState);
  renderQueue(playbackState.queue || []);
  updateTransportButtons(playbackState);
}

function playbackMessage(playbackState) {
  if (playbackState.message) {
    return playbackState.message;
  }

  if (playbackState.state === "playing") {
    return "Playing on Pi";
  }

  if (playbackState.state === "paused") {
    return "Paused";
  }

  return "Stopped";
}

function renderTimer(playbackState) {
  const elapsed = playbackState.elapsed_seconds;
  const duration = playbackState.duration_seconds;

  elapsedTime.textContent = formatTime(elapsed);
  durationTime.textContent = duration === null ? "--:--" : formatTime(duration);

  if (duration && elapsed !== null) {
    trackProgress.value = Math.min(100, Math.max(0, (elapsed / duration) * 100));
  } else {
    trackProgress.value = 0;
  }
}

function renderQueue(queue) {
  queueList.replaceChildren();
  queueStatus.textContent = queue.length ? `${queue.length} tracks queued` : "No tracks queued.";

  for (const track of queue) {
    const item = document.createElement("li");
    item.className = track.is_current ? "queue-item current" : "queue-item";
    item.textContent = track.name;
    queueList.appendChild(item);
  }
}

function updateTransportButtons(playbackState) {
  const hasTrack = Boolean(playbackState.now_playing);
  const isPlaying = playbackState.state === "playing";
  const isPaused = playbackState.state === "paused";

  playButton.disabled = !hasTrack || isPlaying;
  pauseButton.disabled = !isPlaying;
  stopButton.disabled = !hasTrack || playbackState.state === "stopped";
  previousButton.disabled = !hasTrack;
  nextButton.disabled = !hasTrack;
  repeatButton.dataset.active = playbackState.repeat_track ? "true" : "false";
  repeatButton.setAttribute("aria-pressed", playbackState.repeat_track ? "true" : "false");

  playButton.textContent = isPaused ? "Play" : "Play";
}

function navigateTo(path) {
  const encodedPath = encodeURIComponent(path);
  location.hash = encodedPath ? `#${encodedPath}` : "";
}

function currentPath() {
  return decodeURIComponent(location.hash.slice(1));
}

function clearLibraryList() {
  libraryList.replaceChildren();
}

function formatSize(sizeBytes) {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }

  if (sizeBytes < 1024 * 1024) {
    return `${(sizeBytes / 1024).toFixed(1)} KB`;
  }

  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return "0:00";
  }

  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainingSeconds = safeSeconds % 60;
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

upButton.addEventListener("click", () => {
  navigateTo(upButton.dataset.path || "");
});

previousButton.addEventListener("click", () => {
  sendTransportCommand("/api/player/local/previous");
});

playButton.addEventListener("click", () => {
  sendTransportCommand("/api/player/local/resume");
});

pauseButton.addEventListener("click", () => {
  sendTransportCommand("/api/player/local/pause");
});

stopButton.addEventListener("click", () => {
  sendTransportCommand("/api/player/local/stop");
});

nextButton.addEventListener("click", () => {
  sendTransportCommand("/api/player/local/next");
});

repeatButton.addEventListener("click", () => {
  const enabled = repeatButton.dataset.active !== "true";
  sendTransportCommand(`/api/player/local/repeat?enabled=${enabled}`);
});

window.addEventListener("hashchange", () => {
  loadDirectory(currentPath());
});

loadApp();
setInterval(() => {
  if (lastPlaybackState !== null) {
    refreshPlaybackStatus();
  }
}, 1000);
