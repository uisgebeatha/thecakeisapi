import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from thecakeisapi.minidlna import (
    MINIDLNA_AUDIO_FILE_CLASS,
    MINIDLNA_DIRECTORY_CLASS,
    MiniDlnaBrowseObjectError,
    MiniDlnaDatabaseError,
    MiniDlnaObjectClassError,
    MiniDlnaObjectIdResolver,
    MiniDlnaPathError,
)


class MiniDlnaObjectIdResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "files.db"
        self.file_path = str(Path(self.temp_dir.name) / "Albums" / "Air - Moon Safari.flac")
        self.directory_path = str(Path(self.temp_dir.name) / "Music" / "Christmas")
        self._create_database()
        self.resolver = MiniDlnaObjectIdResolver(self.database_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_audio_file_resolves_browse_directory_id_despite_virtual_ids(self) -> None:
        self._insert_detail_with_objects(
            1,
            self.file_path,
            (
                ("1$14$0$0", MINIDLNA_AUDIO_FILE_CLASS, "Air - Moon Safari.flac"),
                ("1$4$0", MINIDLNA_AUDIO_FILE_CLASS, "Air - Moon Safari.flac"),
                ("64$0$0", MINIDLNA_AUDIO_FILE_CLASS, "Air - Moon Safari.flac"),
            ),
        )

        self.assertEqual(self.resolver.resolve_audio_file(self.file_path), "64$0$0")

    def test_directory_resolves_browse_directory_id_despite_virtual_id(self) -> None:
        self._insert_detail_with_objects(
            2,
            self.directory_path,
            (
                ("1$14$1$3", MINIDLNA_DIRECTORY_CLASS, "Christmas"),
                ("64$1$3", MINIDLNA_DIRECTORY_CLASS, "Christmas"),
            ),
        )

        self.assertEqual(self.resolver.resolve_directory(self.directory_path), "64$1$3")

    def test_missing_path_is_reported(self) -> None:
        missing_path = str(Path(self.temp_dir.name) / "missing.mp3")

        with self.assertRaisesRegex(MiniDlnaPathError, "not present"):
            self.resolver.resolve_audio_file(missing_path)

    def test_missing_browse_directory_object_is_reported(self) -> None:
        self._insert_detail_with_objects(
            3,
            self.file_path,
            (("1$4$0", MINIDLNA_AUDIO_FILE_CLASS, "Air - Moon Safari.flac"),),
        )

        with self.assertRaisesRegex(MiniDlnaBrowseObjectError, "No Browse Directory"):
            self.resolver.resolve_audio_file(self.file_path)

    def test_multiple_browse_directory_objects_are_ambiguous(self) -> None:
        self._insert_detail_with_objects(
            4,
            self.file_path,
            (
                ("64$0$0", MINIDLNA_AUDIO_FILE_CLASS, "Air - Moon Safari.flac"),
                ("64$9$9", MINIDLNA_AUDIO_FILE_CLASS, "Air - Moon Safari.flac"),
            ),
        )

        with self.assertRaisesRegex(MiniDlnaBrowseObjectError, "Multiple Browse Directory"):
            self.resolver.resolve_audio_file(self.file_path)

    def test_audio_file_rejects_directory_class(self) -> None:
        self._insert_detail_with_objects(
            5,
            self.file_path,
            (("64$0$0", MINIDLNA_DIRECTORY_CLASS, "Air - Moon Safari.flac"),),
        )

        with self.assertRaisesRegex(MiniDlnaObjectClassError, "musicTrack"):
            self.resolver.resolve_audio_file(self.file_path)

    def test_directory_rejects_audio_file_class(self) -> None:
        self._insert_detail_with_objects(
            6,
            self.directory_path,
            (("64$1$3", MINIDLNA_AUDIO_FILE_CLASS, "Christmas"),),
        )

        with self.assertRaisesRegex(MiniDlnaObjectClassError, "storageFolder"):
            self.resolver.resolve_directory(self.directory_path)

    def test_missing_database_is_reported_without_creating_it(self) -> None:
        missing_database = Path(self.temp_dir.name) / "missing.db"
        resolver = MiniDlnaObjectIdResolver(missing_database)

        with self.assertRaisesRegex(MiniDlnaDatabaseError, "Could not read"):
            resolver.resolve_audio_file(self.file_path)

        self.assertFalse(missing_database.exists())

    def test_unreadable_database_error_is_wrapped(self) -> None:
        with patch(
            "thecakeisapi.minidlna.sqlite3.connect",
            side_effect=sqlite3.OperationalError("permission denied"),
        ):
            with self.assertRaisesRegex(MiniDlnaDatabaseError, "permission denied"):
                self.resolver.resolve_audio_file(self.file_path)

    def _create_database(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.executescript(
                """
                CREATE TABLE DETAILS (
                    ID INTEGER PRIMARY KEY,
                    PATH TEXT NOT NULL
                );
                CREATE TABLE OBJECTS (
                    OBJECT_ID TEXT NOT NULL,
                    PARENT_ID TEXT,
                    CLASS TEXT NOT NULL,
                    DETAIL_ID INTEGER NOT NULL,
                    NAME TEXT
                );
                """,
            )

    def _insert_detail_with_objects(
        self,
        detail_id: int,
        path: str,
        objects: tuple[tuple[str, str, str], ...],
    ) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "INSERT INTO DETAILS (ID, PATH) VALUES (?, ?)",
                (detail_id, path),
            )
            connection.executemany(
                """
                INSERT INTO OBJECTS (OBJECT_ID, PARENT_ID, CLASS, DETAIL_ID, NAME)
                VALUES (?, NULL, ?, ?, ?)
                """,
                (
                    (object_id, object_class, detail_id, name)
                    for object_id, object_class, name in objects
                ),
            )
            connection.commit()


if __name__ == "__main__":
    unittest.main()
