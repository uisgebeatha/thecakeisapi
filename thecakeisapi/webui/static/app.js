const healthBadge = document.querySelector("#health");
const libraryStatus = document.querySelector("#library-status");
const libraryPath = document.querySelector("#library-path");
const libraryList = document.querySelector("#library-list");
const upButton = document.querySelector("#up-button");

async function loadApp() {
  try {
    const [healthResponse, browseResponse] = await Promise.all([
      fetch("/api/health"),
      fetchBrowse(currentPath()),
    ]);

    if (!healthResponse.ok) {
      throw new Error("Status request failed");
    }

    const health = await healthResponse.json();

    healthBadge.textContent = health.status;
    healthBadge.dataset.state = "ok";
    await renderBrowseResponse(browseResponse);
  } catch (error) {
    healthBadge.textContent = "Offline";
    healthBadge.dataset.state = "error";
    libraryStatus.textContent = "The application API is not responding.";
    clearLibraryList();
  }
}

async function loadDirectory(path) {
  libraryStatus.textContent = "Loading...";
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

  const button = document.createElement("button");
  button.className = "entry-button";
  button.type = "button";
  button.disabled = entry.type !== "directory";

  if (entry.type === "directory") {
    button.addEventListener("click", () => navigateTo(entry.path));
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
  button.append(icon, details);
  item.appendChild(button);
  return item;
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

upButton.addEventListener("click", () => {
  navigateTo(upButton.dataset.path || "");
});

window.addEventListener("hashchange", () => {
  loadDirectory(currentPath());
});

loadApp();
