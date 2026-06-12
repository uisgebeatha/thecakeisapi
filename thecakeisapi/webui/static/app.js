async function loadStatus() {
  const healthBadge = document.querySelector("#health");
  const libraryStatus = document.querySelector("#library-status");

  try {
    const [healthResponse, libraryResponse] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/library/status"),
    ]);

    if (!healthResponse.ok || !libraryResponse.ok) {
      throw new Error("Status request failed");
    }

    const health = await healthResponse.json();
    const library = await libraryResponse.json();

    healthBadge.textContent = health.status;
    healthBadge.dataset.state = "ok";
    libraryStatus.textContent = library.is_directory
      ? `Ready to browse ${library.music_root}`
      : `Music folder not found: ${library.music_root}`;
  } catch (error) {
    healthBadge.textContent = "Offline";
    healthBadge.dataset.state = "error";
    libraryStatus.textContent = "The application API is not responding.";
  }
}

loadStatus();

