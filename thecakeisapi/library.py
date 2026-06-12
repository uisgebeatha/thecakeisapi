from pathlib import Path


def get_library_status(music_root: Path) -> dict[str, object]:
    return {
        "music_root": str(music_root),
        "exists": music_root.exists(),
        "is_directory": music_root.is_dir(),
    }

