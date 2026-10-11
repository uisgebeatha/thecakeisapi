import os
import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath, PureWindowsPath


BROWSE_DIRECTORY_OBJECT_ID_PREFIX = "64$"
MINIDLNA_AUDIO_FILE_CLASS = "item.audioItem.musicTrack"
MINIDLNA_DIRECTORY_CLASS = "container.storageFolder"


class MiniDlnaResolverError(Exception):
    """Base error for MiniDLNA Browse Directory object-ID resolution."""


class MiniDlnaDatabaseError(MiniDlnaResolverError):
    """Raised when the MiniDLNA database cannot be read."""


class MiniDlnaPathError(MiniDlnaResolverError):
    """Raised when a path is invalid or absent from the MiniDLNA database."""


class MiniDlnaBrowseObjectError(MiniDlnaResolverError):
    """Raised when a unique Browse Directory object cannot be selected."""


class MiniDlnaObjectClassError(MiniDlnaResolverError):
    """Raised when an object has the wrong MiniDLNA class for the requested type."""


class MiniDlnaObjectIdResolver:
    """Resolve exact filesystem paths to raw MiniDLNA Browse Directory IDs.

    MiniDLNA can expose one item through several virtual hierarchies. The ``64$``
    hierarchy is its filesystem-oriented Browse Directory view. Returned IDs are
    deliberately unchanged; any Bose-specific suffix such as `` TRACK`` belongs
    to the playback layer.
    """

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)

    def resolve_audio_file(self, file_path: Path | str) -> str:
        return self._resolve(
            file_path,
            expected_class=MINIDLNA_AUDIO_FILE_CLASS,
            expected_type="audio file",
        )

    def resolve_directory(self, directory_path: Path | str) -> str:
        return self._resolve(
            directory_path,
            expected_class=MINIDLNA_DIRECTORY_CLASS,
            expected_type="directory",
        )

    def _resolve(
        self,
        filesystem_path: Path | str,
        expected_class: str,
        expected_type: str,
    ) -> str:
        path_text = os.fspath(filesystem_path)
        if not _is_absolute_path(path_text):
            raise MiniDlnaPathError(
                f"MiniDLNA lookup path must be absolute: {path_text}",
            )

        try:
            with closing(
                sqlite3.connect(self._read_only_database_uri(), uri=True),
            ) as connection:
                path_exists = connection.execute(
                    "SELECT 1 FROM DETAILS WHERE PATH = ? LIMIT 1",
                    (path_text,),
                ).fetchone()
                if path_exists is None:
                    raise MiniDlnaPathError(
                        f"Path is not present in the MiniDLNA database: {path_text}",
                    )

                browse_objects = connection.execute(
                    """
                    SELECT OBJECTS.OBJECT_ID, OBJECTS.CLASS
                    FROM DETAILS
                    JOIN OBJECTS ON OBJECTS.DETAIL_ID = DETAILS.ID
                    WHERE DETAILS.PATH = ?
                      AND OBJECTS.OBJECT_ID LIKE ?
                    """,
                    (path_text, f"{BROWSE_DIRECTORY_OBJECT_ID_PREFIX}%"),
                ).fetchall()
        except MiniDlnaResolverError:
            raise
        except (OSError, sqlite3.Error) as error:
            raise MiniDlnaDatabaseError(
                f"Could not read MiniDLNA database {self.database_path}: {error}",
            ) from error

        if not browse_objects:
            raise MiniDlnaBrowseObjectError(
                f"No Browse Directory object exists for MiniDLNA path: {path_text}",
            )
        if len(browse_objects) > 1:
            object_ids = ", ".join(str(row[0]) for row in browse_objects)
            raise MiniDlnaBrowseObjectError(
                "Multiple Browse Directory objects exist for MiniDLNA path "
                f"{path_text}: {object_ids}",
            )

        object_id, object_class = browse_objects[0]
        if object_class != expected_class:
            raise MiniDlnaObjectClassError(
                f"MiniDLNA object {object_id} for {path_text} has class "
                f"{object_class!r}; expected {expected_class!r} for an {expected_type}",
            )

        return str(object_id)

    def _read_only_database_uri(self) -> str:
        return f"{self.database_path.resolve().as_uri()}?mode=ro"


def _is_absolute_path(path: str) -> bool:
    return (
        Path(path).is_absolute()
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
    )
