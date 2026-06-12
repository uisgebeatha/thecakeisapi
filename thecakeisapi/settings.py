import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    music_root: Path = Path("/mnt/music")

    @classmethod
    def from_environment(cls) -> "Settings":
        music_root = os.getenv("THECAKEISAPI_MUSIC_ROOT", "/mnt/music")
        return cls(music_root=Path(music_root))

