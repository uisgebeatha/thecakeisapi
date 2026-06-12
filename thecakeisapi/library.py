from pathlib import Path


SUPPORTED_AUDIO_EXTENSIONS = {".flac", ".mp3"}


class LibraryError(Exception):
    """Base error for library browsing failures."""


class LibraryPathError(LibraryError):
    """Raised when a requested library path is invalid or unsafe."""


class LibraryNotFoundError(LibraryError):
    """Raised when the configured library path cannot be browsed."""


def get_library_status(music_root: Path) -> dict[str, object]:
    return {
        "music_root": str(music_root),
        "exists": music_root.exists(),
        "is_directory": music_root.is_dir(),
    }


def list_directory(music_root: Path, requested_path: str = "") -> dict[str, object]:
    root_path = music_root.resolve()
    if not root_path.is_dir():
        raise LibraryNotFoundError("Music root does not exist or is not a directory")

    directory_path = resolve_library_path(root_path, requested_path)
    if not directory_path.is_dir():
        raise LibraryNotFoundError("Requested path does not exist or is not a directory")

    directories: list[dict[str, object]] = []
    files: list[dict[str, object]] = []

    for child_path in directory_path.iterdir():
        if child_path.is_dir():
            directories.append(_directory_entry(root_path, child_path))
        elif is_supported_audio_file(child_path):
            files.append(_file_entry(root_path, child_path))

    directories.sort(key=lambda entry: str(entry["name"]).casefold())
    files.sort(key=lambda entry: str(entry["name"]).casefold())

    current_path = _relative_library_path(root_path, directory_path)
    return {
        "music_root": str(root_path),
        "path": current_path,
        "parent_path": _parent_library_path(current_path),
        "directories": directories,
        "files": files,
        "supported_extensions": sorted(SUPPORTED_AUDIO_EXTENSIONS),
    }


def resolve_library_path(music_root: Path, requested_path: str) -> Path:
    if Path(requested_path).is_absolute():
        raise LibraryPathError("Library path must be relative")

    resolved_path = (music_root / requested_path).resolve()
    if not _is_relative_to(resolved_path, music_root):
        raise LibraryPathError("Library path is outside the configured music root")

    return resolved_path


def is_supported_audio_file(path: Path) -> bool:
    return path.is_file() and path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS


def _directory_entry(root_path: Path, directory_path: Path) -> dict[str, object]:
    return {
        "name": directory_path.name,
        "path": _relative_library_path(root_path, directory_path),
        "type": "directory",
    }


def _file_entry(root_path: Path, file_path: Path) -> dict[str, object]:
    return {
        "name": file_path.name,
        "path": _relative_library_path(root_path, file_path),
        "type": "file",
        "size_bytes": file_path.stat().st_size,
    }


def _relative_library_path(root_path: Path, path: Path) -> str:
    relative_path = path.relative_to(root_path)
    if str(relative_path) == ".":
        return ""
    return relative_path.as_posix()


def _parent_library_path(current_path: str) -> str | None:
    if not current_path:
        return None

    parent_path = Path(current_path).parent
    if str(parent_path) == ".":
        return ""
    return parent_path.as_posix()


def _is_relative_to(path: Path, parent_path: Path) -> bool:
    try:
        path.relative_to(parent_path)
    except ValueError:
        return False
    return True
