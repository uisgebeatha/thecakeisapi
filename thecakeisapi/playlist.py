from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class QueueTrack:
    path: str
    name: str


@dataclass(frozen=True)
class QueueRemoval:
    removed: bool
    removed_current: bool
    current_track: QueueTrack | None


class PlaybackQueue:
    def __init__(self) -> None:
        self._tracks: list[QueueTrack] = []
        self._current_index: int | None = None
        self._lock = Lock()

    def set_tracks(
        self,
        tracks: list[QueueTrack],
        current_path: str,
    ) -> QueueTrack:
        with self._lock:
            if not tracks:
                tracks = [QueueTrack(path=current_path, name=current_path)]

            current_index = self._find_index(tracks, current_path)
            if current_index is None:
                tracks = [QueueTrack(path=current_path, name=current_path), *tracks]
                current_index = 0

            self._tracks = tracks
            self._current_index = current_index
            return self._tracks[current_index]

    def add_tracks(self, tracks: list[QueueTrack]) -> None:
        with self._lock:
            queue_was_empty = not self._tracks
            self._tracks.extend(tracks)
            if queue_was_empty and self._tracks:
                self._current_index = 0

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

    def remove(self, path: str) -> QueueRemoval:
        with self._lock:
            remove_index = self._find_index(self._tracks, path)
            if remove_index is None:
                return QueueRemoval(
                    removed=False,
                    removed_current=False,
                    current_track=self._current_unlocked(),
                )

            removed_current = remove_index == self._current_index
            self._tracks.pop(remove_index)

            if not self._tracks:
                self._current_index = None
            else:
                self._current_index = self._index_after_removal(
                    self._current_index,
                    remove_index,
                )

            return QueueRemoval(
                removed=True,
                removed_current=removed_current,
                current_track=self._current_unlocked(),
            )

    def move_up(self, path: str) -> bool:
        with self._lock:
            index = self._find_index(self._tracks, path)
            if index is None or index == 0:
                return False

            self._tracks[index - 1], self._tracks[index] = (
                self._tracks[index],
                self._tracks[index - 1],
            )
            self._current_index = self._index_after_swap(
                self._current_index,
                index,
                index - 1,
            )
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
            self._current_index = self._index_after_swap(
                self._current_index,
                index,
                index + 1,
            )
            return True

    def as_dict(self) -> dict[str, object]:
        with self._lock:
            current_path = (
                self._tracks[self._current_index].path
                if self._current_index is not None and self._tracks
                else None
            )
            return {
                "current_path": current_path,
                "tracks": [
                    {
                        "path": track.path,
                        "name": track.name,
                        "is_current": index == self._current_index,
                    }
                    for index, track in enumerate(self._tracks)
                ],
            }

    def _current_unlocked(self) -> QueueTrack | None:
        if self._current_index is None or not self._tracks:
            return None
        return self._tracks[self._current_index]

    def _index_after_removal(
        self,
        current_index: int | None,
        remove_index: int,
    ) -> int | None:
        if current_index is None:
            return None
        if remove_index < current_index:
            return current_index - 1
        if remove_index == current_index:
            return min(remove_index, len(self._tracks) - 1)
        return current_index

    @staticmethod
    def _index_after_swap(
        current_index: int | None,
        first_index: int,
        second_index: int,
    ) -> int | None:
        if current_index == first_index:
            return second_index
        if current_index == second_index:
            return first_index
        return current_index

    @staticmethod
    def _find_index(tracks: list[QueueTrack], current_path: str) -> int | None:
        for index, track in enumerate(tracks):
            if track.path == current_path:
                return index
        return None
