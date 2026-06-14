import tempfile
import unittest
from pathlib import Path

from thecakeisapi.library import list_directory


class LibraryBrowsingTests(unittest.TestCase):
    def test_metadata_directories_are_hidden(self) -> None:
        hidden_directories = [
            "$RECYCLE.BIN",
            "System Volume Information",
            ".Trashes",
            ".Spotlight-V100",
            ".fseventsd",
            "lost+found",
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            music_root = Path(temp_dir)
            (music_root / "Album").mkdir()
            for directory_name in hidden_directories:
                (music_root / directory_name).mkdir()

            result = list_directory(music_root)

        directory_names = {entry["name"] for entry in result["directories"]}
        self.assertEqual(directory_names, {"Album"})


if __name__ == "__main__":
    unittest.main()
