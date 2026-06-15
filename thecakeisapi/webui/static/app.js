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
const outputSelector = document.querySelector("#output-selector");
const clearQueueButton = document.querySelector("#clear-queue-button");
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
      fetch("/api/player/status"),
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

  if (entry.type === "directory") {
    const playFolderButton = document.createElement("button");
    playFolderButton.className = "play-button";
    playFolderButton.type = "button";
    playFolderButton.textContent = "Play Folder";
    playFolderButton.addEventListener("click", () => playFolder(entry, playFolderButton));
    row.appendChild(playFolderButton);
  }

  if (entry.type === "file") {
    const playButton = document.createElement("button");
    playButton.className = "play-button";
    playButton.type = "button";
    playButton.textContent = "Play Track";
    playButton.addEventListener("click", () => playTrack(entry, playButton));
    row.appendChild(playButton);

    const addButton = document.createElement("button");
    addButton.className = "play-button";
    addButton.type = "button";
    addButton.textContent = "Add To Queue";
    addButton.addEventListener("click", () => addToQueue(entry, addButton));
    row.appendChild(addButton);
  }

  item.appendChild(row);
  return item;
}

async function playTrack(entry, playButton) {
  await playPaths({
    path: entry.path,
    queuePaths: [entry.path],
    label: entry.name,
    playButton,
  });
}

async function playFolder(entry, playButton) {
  const originalText = playButton.textContent;
  playButton.disabled = true;
  playButton.textContent = "Loading";
  playbackStatus.textContent = `Loading ${entry.name}...`;
  playbackStatus.dataset.state = "";

  try {
    const response = await fetchBrowse(entry.path);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Folder request failed");
    }

    const folder = await response.json();
    const queuePaths = folder.files.map((file) => file.path);
    if (queuePaths.length === 0) {
      throw new Error("Folder has no supported audio files");
    }

    await playPaths({
      path: queuePaths[0],
      queuePaths,
      label: entry.name,
      playButton,
    });
  } catch (error) {
    playbackStatus.textContent = `Could not play folder: ${error.message}`;
    playbackStatus.dataset.state = "error";
  } finally {
    playButton.disabled = false;
    playButton.textContent = originalText;
  }
}

async function playPaths({ path, queuePaths, label, playButton }) {
  const originalText = playButton.textContent;
  playButton.disabled = true;
  playButton.textContent = "Starting";
  playbackStatus.textContent = `Starting ${label} on ${outputLabel()}...`;
  playbackStatus.dataset.state = "";

  try {
    const params = new URLSearchParams({ path });
    const response = await fetch(`${playEndpoint()}?${params.toString()}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        queue_paths: queuePaths,
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Playback request failed");
    }

    playbackStatus.textContent = `Playing on ${outputLabel()}: ${label}`;
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

async function addToQueue(entry, addButton) {
  const originalText = addButton.textContent;
  addButton.disabled = true;
  addButton.textContent = "Adding";
  playbackStatus.textContent = `Adding ${entry.name} to queue...`;
  playbackStatus.dataset.state = "";

  try {
    const response = await fetch("/api/player/local/queue/add", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        queue_paths: [entry.path],
      }),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "Queue request failed");
    }

    await renderPlaybackResponse(response);
  } catch (error) {
    playbackStatus.textContent = `Could not add to queue: ${error.message}`;
    playbackStatus.dataset.state = "error";
  } finally {
    addButton.disabled = false;
    addButton.textContent = originalText;
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
    const response = await fetch("/api/player/status");
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
  syncOutputSelector(playbackState);
  renderPlaybackState(playbackState);
}

function syncOutputSelector(playbackState) {
  if (!playbackState.active_output || playbackState.state === "stopped") {
    return;
  }

  outputSelector.value = playbackState.active_output;
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
    trackProgress.max = Math.floor(duration);
    trackProgress.value = Math.min(duration, Math.max(0, elapsed));
    trackProgress.disabled = false;
  } else {
    trackProgress.max = 100;
    trackProgress.value = 0;
    trackProgress.disabled = true;
  }
}

function renderQueue(queue) {
  queueList.replaceChildren();
  queueStatus.textContent = queue.length ? `${queue.length} tracks queued` : "No tracks queued.";
  clearQueueButton.disabled = queue.length === 0;

  for (const track of queue) {
    const item = document.createElement("li");
    item.className = track.is_current ? "queue-item current" : "queue-item";

    const name = document.createElement("span");
    name.className = "queue-name";
    name.textContent = track.name;

    const actions = document.createElement("span");
    actions.className = "queue-actions";
    actions.append(
      createQueueButton("Up", () => moveQueueTrack(track.path, "move-up")),
      createQueueButton("Down", () => moveQueueTrack(track.path, "move-down")),
      createQueueButton("Remove", () => removeQueueTrack(track.path)),
    );

    item.append(name, actions);
    queueList.appendChild(item);
  }
}

function createQueueButton(label, onClick) {
  const button = document.createElement("button");
  button.className = "queue-button";
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function removeQueueTrack(path) {
  const params = new URLSearchParams({ path });
  sendTransportCommand(`/api/player/local/queue/remove?${params.toString()}`);
}

function moveQueueTrack(path, direction) {
  const params = new URLSearchParams({ path });
  sendTransportCommand(`/api/player/local/queue/${direction}?${params.toString()}`);
}

function updateTransportButtons(playbackState) {
  const hasTrack = Boolean(playbackState.now_playing);
  const isPlaying = playbackState.state === "playing";
  const isPaused = isPausedPlayback(playbackState);

  playButton.disabled = !hasTrack || isPlaying || isPaused;
  pauseButton.disabled = !hasTrack || (!isPlaying && !isPaused);
  stopButton.disabled = !hasTrack || playbackState.state === "stopped";
  previousButton.disabled = !hasTrack;
  nextButton.disabled = !hasTrack;
  repeatButton.dataset.active = playbackState.repeat_track ? "true" : "false";
  repeatButton.setAttribute("aria-pressed", playbackState.repeat_track ? "true" : "false");

  playButton.textContent = "Play";
  pauseButton.textContent = isPaused ? "Resume" : "Pause";
}

function isPausedPlayback(playbackState) {
  return playbackState?.state === "paused" || playbackState?.paused === true;
}

function selectedOutput() {
  return outputSelector.value === "bose" ? "bose" : "local";
}

function outputLabel() {
  return selectedOutput() === "bose" ? "Bose SoundTouch" : "Pi";
}

function playEndpoint() {
  return selectedOutput() === "bose" ? "/api/player/bose/play" : "/api/player/local/play";
}

function transportEndpoint(action) {
  const output = selectedOutput();
  if (output === "bose") {
    return `/api/player/bose/${action}`;
  }
  return `/api/player/local/${action}`;
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
  sendTransportCommand(transportEndpoint("previous"));
});

playButton.addEventListener("click", () => {
  sendTransportCommand(transportEndpoint("resume"));
});

pauseButton.addEventListener("click", () => {
  const isPaused = isPausedPlayback(lastPlaybackState);

  if (selectedOutput() === "bose" && isPaused) {
    sendTransportCommand("/api/player/bose/resume");
    return;
  }

  if (selectedOutput() === "bose") {
    sendTransportCommand("/api/player/bose/pause");
    return;
  }

  if (isPaused) {
    sendTransportCommand("/api/player/local/resume");
    return;
  }

  sendTransportCommand("/api/player/local/pause");
});

stopButton.addEventListener("click", () => {
  sendTransportCommand(transportEndpoint("stop"));
});

nextButton.addEventListener("click", () => {
  sendTransportCommand(transportEndpoint("next"));
});

clearQueueButton.addEventListener("click", () => {
  sendTransportCommand("/api/player/local/queue/clear");
});

repeatButton.addEventListener("click", () => {
  const enabled = repeatButton.dataset.active !== "true";
  sendTransportCommand(`/api/player/local/repeat?enabled=${enabled}`);
});

trackProgress.addEventListener("change", () => {
  if (selectedOutput() === "bose") {
    playbackStatus.textContent = "Seeking is not supported for Bose output yet.";
    playbackStatus.dataset.state = "";
    return;
  }

  const seconds = Number(trackProgress.value);
  if (!Number.isNaN(seconds)) {
    sendTransportCommand(`/api/player/local/seek?seconds=${seconds}`);
  }
});

outputSelector.addEventListener("change", () => {
  if (lastPlaybackState !== null) {
    renderPlaybackState(lastPlaybackState);
  }
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
