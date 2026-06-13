from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class QueueTrack:
    path: str
    name: str


class PlaybackQueue:
    def __init__(self) -> None:
        self._tracks: list[QueueTrack] = []
        self._current_index: int | None = None
        self._lock = Lock()

    def set_tracks(self, tracks: list[QueueTrack], current_path: str) -> QueueTrack:
        with self._lock:
            if not tracks:
                tracks = [QueueTrack(path=current_path, name=current_path)]

            current_index = self._find_index(tracks, current_path)
            if current_index is None:
                tracks = [QueueTrack(path=current_path, name=current_path), *tracks]
                current_index = 0

            self._tracks = tracks
            self._current_index = current_index
            return self._tracks[self._current_index]

    def current(self) -> QueueTrack | None:
        with self._lock:
            return self._current_unlocked()

    def next(self) -> QueueTrack | None:
        with self._lock:
            if self._current_index is None or not self._tracks:
                return None

            if self._current_index >= len(self._tracks) - 1:
                return None

            self._current_index += 1
            return self._tracks[self._current_index]

    def previous(self) -> QueueTrack | None:
        with self._lock:
            if self._current_index is None or not self._tracks:
                return None

            if self._current_index <= 0:
                return None

            self._current_index -= 1
            return self._tracks[self._current_index]

    def clear(self) -> None:
        with self._lock:
            self._tracks = []
            self._current_index = None

    def remove(self, path: str) -> tuple[QueueTrack | None, bool]:
        with self._lock:
            remove_index = self._find_index(self._tracks, path)
            if remove_index is None:
                return self._current_unlocked(), False

            removed_current = remove_index == self._current_index
            self._tracks.pop(remove_index)

            if not self._tracks:
                self._current_index = None
                return None, removed_current

            if self._current_index is None:
                return self._current_unlocked(), removed_current

            if remove_index < self._current_index:
                self._current_index -= 1
            elif removed_current:
                self._current_index = min(remove_index, len(self._tracks) - 1)

            return self._current_unlocked(), removed_current

    def move_up(self, path: str) -> bool:
        with self._lock:
            index = self._find_index(self._tracks, path)
            if index is None or index == 0:
                return False

            self._tracks[index - 1], self._tracks[index] = (
                self._tracks[index],
                self._tracks[index - 1],
            )

            if self._current_index == index:
                self._current_index = index - 1
            elif self._current_index == index - 1:
                self._current_index = index

            return True

    def move_down(self, path: str) -> bool:
        with self._lock:
            index = self._find_index(self._tracks, path)
            if index is None or index >= len(self._tracks) - 1:
                return False

            self._tracks[index + 1], self._tracks[index] = (
                self._tracks[index],
                self._tracks[index + 1],
            )

            if self._current_index == index:
                self._current_index = index + 1
            elif self._current_index == index + 1:
                self._current_index = index

            return True

    def as_dict(self) -> dict[str, object]:
        with self._lock:
            current_path = None
            if self._current_index is not None and self._tracks:
                current_path = self._tracks[self._current_index].path

            return {
                "current_path": current_path,
                "tracks": [
                    {
                        "path": track.path,
                        "name": track.name,
                        "is_current": track.path == current_path,
                    }
                    for track in self._tracks
                ],
            }

    def _current_unlocked(self) -> QueueTrack | None:
        if self._current_index is None or not self._tracks:
            return None
        return self._tracks[self._current_index]

    @staticmethod
    def _find_index(tracks: list[QueueTrack], current_path: str) -> int | None:
        for index, track in enumerate(tracks):
            if track.path == current_path:
                return index
        return None
