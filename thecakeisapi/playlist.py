from dataclasses import dataclass
from threading import Lock
from typing import Literal


PlaybackOutput = Literal["local", "bose"]


@dataclass(frozen=True)
class QueueTrack:
    path: str
    name: str


@dataclass(frozen=True)
class QueueOutputRemoval:
    current_track: QueueTrack | None
    removed_current: bool


@dataclass(frozen=True)
class QueueRemoval:
    removed: bool
    local: QueueOutputRemoval
    bose: QueueOutputRemoval


class PlaybackQueue:
    def __init__(self) -> None:
        self._tracks: list[QueueTrack] = []
        self._local_index: int | None = None
        self._bose_index: int | None = None
        self._lock = Lock()

    def set_tracks(
        self,
        tracks: list[QueueTrack],
        current_path: str,
        output: PlaybackOutput,
    ) -> QueueTrack:
        self._validate_output(output)
        with self._lock:
            other_output: PlaybackOutput = "bose" if output == "local" else "local"
            other_current = self._current_unlocked(other_output)

            if not tracks:
                tracks = [QueueTrack(path=current_path, name=current_path)]

            current_index = self._find_index(tracks, current_path)
            if current_index is None:
                tracks = [QueueTrack(path=current_path, name=current_path), *tracks]
                current_index = 0

            self._tracks = tracks
            self._set_index_unlocked(output, current_index)
            self._set_index_unlocked(
                other_output,
                self._find_index(tracks, other_current.path)
                if other_current is not None
                else None,
            )
            return self._tracks[current_index]

    def add_tracks(self, tracks: list[QueueTrack]) -> None:
        with self._lock:
            queue_was_empty = not self._tracks
            self._tracks.extend(tracks)
            if queue_was_empty and self._tracks:
                self._local_index = 0
                self._bose_index = 0

    def current(self, output: PlaybackOutput) -> QueueTrack | None:
        self._validate_output(output)
        with self._lock:
            return self._current_unlocked(output)

    def next(self, output: PlaybackOutput) -> QueueTrack | None:
        self._validate_output(output)
        with self._lock:
            current_index = self._index_unlocked(output)
            if current_index is None or not self._tracks:
                return None

            if current_index >= len(self._tracks) - 1:
                return None

            current_index += 1
            self._set_index_unlocked(output, current_index)
            return self._tracks[current_index]

    def previous(self, output: PlaybackOutput) -> QueueTrack | None:
        self._validate_output(output)
        with self._lock:
            current_index = self._index_unlocked(output)
            if current_index is None or not self._tracks:
                return None

            if current_index <= 0:
                return None

            current_index -= 1
            self._set_index_unlocked(output, current_index)
            return self._tracks[current_index]

    def clear_cursor(self, output: PlaybackOutput) -> None:
        self._validate_output(output)
        with self._lock:
            self._set_index_unlocked(output, None)

    def clear(self) -> None:
        with self._lock:
            self._tracks = []
            self._local_index = None
            self._bose_index = None

    def remove(self, path: str) -> QueueRemoval:
        with self._lock:
            remove_index = self._find_index(self._tracks, path)
            if remove_index is None:
                return self._removal_result_unlocked(False, False, False)

            removed_local_current = remove_index == self._local_index
            removed_bose_current = remove_index == self._bose_index
            self._tracks.pop(remove_index)

            if not self._tracks:
                self._local_index = None
                self._bose_index = None
            else:
                self._local_index = self._index_after_removal(
                    self._local_index,
                    remove_index,
                )
                self._bose_index = self._index_after_removal(
                    self._bose_index,
                    remove_index,
                )

            return self._removal_result_unlocked(
                True,
                removed_local_current,
                removed_bose_current,
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

            self._local_index = self._index_after_swap(
                self._local_index,
                index,
                index - 1,
            )
            self._bose_index = self._index_after_swap(
                self._bose_index,
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

            self._local_index = self._index_after_swap(
                self._local_index,
                index,
                index + 1,
            )
            self._bose_index = self._index_after_swap(
                self._bose_index,
                index,
                index + 1,
            )

            return True

    def as_dict(self, active_output: PlaybackOutput) -> dict[str, object]:
        self._validate_output(active_output)
        with self._lock:
            active_index = self._index_unlocked(active_output)
            current_path = self._path_at_index_unlocked(active_index)

            return {
                "current_path": current_path,
                "tracks": [
                    {
                        "path": track.path,
                        "name": track.name,
                        "is_current": index == active_index,
                        "is_current_local": index == self._local_index,
                        "is_current_bose": index == self._bose_index,
                    }
                    for index, track in enumerate(self._tracks)
                ],
            }

    def _current_unlocked(self, output: PlaybackOutput) -> QueueTrack | None:
        current_index = self._index_unlocked(output)
        if current_index is None or not self._tracks:
            return None
        return self._tracks[current_index]

    def _removal_result_unlocked(
        self,
        removed: bool,
        removed_local_current: bool,
        removed_bose_current: bool,
    ) -> QueueRemoval:
        return QueueRemoval(
            removed=removed,
            local=QueueOutputRemoval(
                current_track=self._current_unlocked("local"),
                removed_current=removed_local_current,
            ),
            bose=QueueOutputRemoval(
                current_track=self._current_unlocked("bose"),
                removed_current=removed_bose_current,
            ),
        )

    def _index_unlocked(self, output: PlaybackOutput) -> int | None:
        return self._local_index if output == "local" else self._bose_index

    def _set_index_unlocked(
        self,
        output: PlaybackOutput,
        index: int | None,
    ) -> None:
        if output == "local":
            self._local_index = index
        else:
            self._bose_index = index

    def _path_at_index_unlocked(self, index: int | None) -> str | None:
        if index is None or not self._tracks:
            return None
        return self._tracks[index].path

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
    def _validate_output(output: str) -> None:
        if output not in {"local", "bose"}:
            raise ValueError(f"Unsupported playback output: {output}")

    @staticmethod
    def _find_index(tracks: list[QueueTrack], current_path: str) -> int | None:
        for index, track in enumerate(tracks):
            if track.path == current_path:
                return index
        return None
