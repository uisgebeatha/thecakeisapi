import unittest

from thecakeisapi.playlist import PlaybackQueue, QueueTrack


def tracks(*paths: str) -> list[QueueTrack]:
    return [QueueTrack(path=path, name=path) for path in paths]


class PlaybackQueueCursorTests(unittest.TestCase):
    def test_local_and_bose_navigation_are_independent(self) -> None:
        queue = PlaybackQueue()
        queue.set_tracks(tracks("one.mp3", "two.mp3", "three.mp3"), "one.mp3", "local")
        queue.set_tracks(tracks("one.mp3", "two.mp3", "three.mp3"), "three.mp3", "bose")

        self.assertEqual(queue.next("local").path, "two.mp3")
        self.assertIsNone(queue.next("bose"))
        self.assertEqual(queue.current("local").path, "two.mp3")
        self.assertEqual(queue.current("bose").path, "three.mp3")

        self.assertEqual(queue.previous("bose").path, "two.mp3")
        self.assertEqual(queue.current("local").path, "two.mp3")

    def test_replacing_queue_remaps_other_cursor_by_exact_path(self) -> None:
        queue = PlaybackQueue()
        original = tracks("one.mp3", "two.mp3", "three.mp3")
        queue.set_tracks(original, "one.mp3", "local")
        queue.set_tracks(original, "two.mp3", "bose")

        queue.set_tracks(
            tracks("four.mp3", "two.mp3", "five.mp3"),
            "four.mp3",
            "local",
        )

        self.assertEqual(queue.current("local").path, "four.mp3")
        self.assertEqual(queue.current("bose").path, "two.mp3")

    def test_replacing_queue_detaches_missing_other_cursor(self) -> None:
        queue = PlaybackQueue()
        original = tracks("one.mp3", "two.mp3")
        queue.set_tracks(original, "one.mp3", "local")
        queue.set_tracks(original, "two.mp3", "bose")

        queue.set_tracks(tracks("three.mp3"), "three.mp3", "local")

        self.assertEqual(queue.current("local").path, "three.mp3")
        self.assertIsNone(queue.current("bose"))

    def test_remove_before_each_cursor_preserves_logical_tracks(self) -> None:
        queue = PlaybackQueue()
        shared_tracks = tracks("one.mp3", "two.mp3", "three.mp3")
        queue.set_tracks(shared_tracks, "three.mp3", "local")
        queue.set_tracks(shared_tracks, "two.mp3", "bose")

        removal = queue.remove("one.mp3")

        self.assertFalse(removal.local.removed_current)
        self.assertFalse(removal.bose.removed_current)
        self.assertEqual(queue.current("local").path, "three.mp3")
        self.assertEqual(queue.current("bose").path, "two.mp3")

    def test_remove_current_selects_successor_or_last_predecessor(self) -> None:
        queue = PlaybackQueue()
        shared_tracks = tracks("one.mp3", "two.mp3", "three.mp3")
        queue.set_tracks(shared_tracks, "two.mp3", "local")
        queue.set_tracks(shared_tracks, "one.mp3", "bose")

        removal = queue.remove("two.mp3")

        self.assertTrue(removal.local.removed_current)
        self.assertFalse(removal.bose.removed_current)
        self.assertEqual(removal.local.current_track.path, "three.mp3")
        self.assertEqual(removal.bose.current_track.path, "one.mp3")

        queue.set_tracks(tracks("one.mp3", "three.mp3"), "three.mp3", "bose")
        removal = queue.remove("three.mp3")
        self.assertTrue(removal.bose.removed_current)
        self.assertEqual(removal.bose.current_track.path, "one.mp3")

    def test_remove_current_adjusts_both_cursors_on_same_item(self) -> None:
        queue = PlaybackQueue()
        shared_tracks = tracks("one.mp3", "two.mp3", "three.mp3")
        queue.set_tracks(shared_tracks, "two.mp3", "local")
        queue.set_tracks(shared_tracks, "two.mp3", "bose")

        removal = queue.remove("two.mp3")

        self.assertTrue(removal.local.removed_current)
        self.assertTrue(removal.bose.removed_current)
        self.assertEqual(queue.current("local").path, "three.mp3")
        self.assertEqual(queue.current("bose").path, "three.mp3")

    def test_adjacent_moves_keep_both_cursors_on_logical_tracks(self) -> None:
        queue = PlaybackQueue()
        shared_tracks = tracks("one.mp3", "two.mp3", "three.mp3")
        queue.set_tracks(shared_tracks, "two.mp3", "local")
        queue.set_tracks(shared_tracks, "three.mp3", "bose")

        self.assertTrue(queue.move_down("two.mp3"))
        self.assertEqual(queue.current("local").path, "two.mp3")
        self.assertEqual(queue.current("bose").path, "three.mp3")

        self.assertTrue(queue.move_up("two.mp3"))
        self.assertEqual(queue.current("local").path, "two.mp3")
        self.assertEqual(queue.current("bose").path, "three.mp3")

    def test_add_to_empty_initializes_both_but_later_add_preserves_none(self) -> None:
        queue = PlaybackQueue()
        queue.add_tracks(tracks("one.mp3"))

        self.assertEqual(queue.current("local").path, "one.mp3")
        self.assertEqual(queue.current("bose").path, "one.mp3")

        queue.clear_cursor("bose")
        queue.add_tracks(tracks("two.mp3"))

        self.assertEqual(queue.current("local").path, "one.mp3")
        self.assertIsNone(queue.current("bose"))

    def test_clear_resets_both_cursors(self) -> None:
        queue = PlaybackQueue()
        queue.add_tracks(tracks("one.mp3"))

        queue.clear()

        self.assertIsNone(queue.current("local"))
        self.assertIsNone(queue.current("bose"))
        self.assertEqual(queue.as_dict("local")["tracks"], [])

    def test_serialization_exposes_both_cursors_and_legacy_active_cursor(self) -> None:
        queue = PlaybackQueue()
        shared_tracks = tracks("one.mp3", "two.mp3")
        queue.set_tracks(shared_tracks, "one.mp3", "local")
        queue.set_tracks(shared_tracks, "two.mp3", "bose")

        local_status = queue.as_dict("local")
        bose_status = queue.as_dict("bose")

        self.assertEqual(
            [track["is_current_local"] for track in local_status["tracks"]],
            [True, False],
        )
        self.assertEqual(
            [track["is_current_bose"] for track in local_status["tracks"]],
            [False, True],
        )
        self.assertEqual(
            [track["is_current"] for track in local_status["tracks"]],
            [True, False],
        )
        self.assertEqual(
            [track["is_current"] for track in bose_status["tracks"]],
            [False, True],
        )

    def test_invalid_output_is_rejected(self) -> None:
        queue = PlaybackQueue()

        with self.assertRaisesRegex(ValueError, "Unsupported playback output"):
            queue.current("invalid")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
