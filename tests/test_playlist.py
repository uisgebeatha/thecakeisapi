import unittest

from thecakeisapi.playlist import PlaybackQueue, QueueTrack


def tracks(*paths: str) -> list[QueueTrack]:
    return [QueueTrack(path=path, name=path) for path in paths]


class PlaybackQueueTests(unittest.TestCase):
    def test_current_next_and_previous_use_one_cursor(self) -> None:
        queue = PlaybackQueue()
        queue.set_tracks(tracks("one.mp3", "two.mp3", "three.mp3"), "one.mp3")

        self.assertEqual(queue.current().path, "one.mp3")
        self.assertEqual(queue.next().path, "two.mp3")
        self.assertEqual(queue.previous().path, "one.mp3")
        self.assertIsNone(queue.previous())

    def test_set_tracks_adds_a_missing_current_track(self) -> None:
        queue = PlaybackQueue()

        selected = queue.set_tracks(tracks("two.mp3"), "one.mp3")

        self.assertEqual(selected.path, "one.mp3")
        self.assertEqual(
            [track["path"] for track in queue.as_dict()["tracks"]],
            ["one.mp3", "two.mp3"],
        )

    def test_add_to_empty_selects_first_track_and_later_add_preserves_cursor(self) -> None:
        queue = PlaybackQueue()
        queue.add_tracks(tracks("one.mp3"))
        queue.add_tracks(tracks("two.mp3"))

        self.assertEqual(queue.current().path, "one.mp3")
        self.assertEqual(queue.next().path, "two.mp3")

    def test_remove_preserves_or_replaces_current_track(self) -> None:
        queue = PlaybackQueue()
        queue.set_tracks(tracks("one.mp3", "two.mp3", "three.mp3"), "two.mp3")

        before_current = queue.remove("one.mp3")
        self.assertTrue(before_current.removed)
        self.assertFalse(before_current.removed_current)
        self.assertEqual(before_current.current_track.path, "two.mp3")

        current = queue.remove("two.mp3")
        self.assertTrue(current.removed_current)
        self.assertEqual(current.current_track.path, "three.mp3")

        last = queue.remove("three.mp3")
        self.assertTrue(last.removed_current)
        self.assertIsNone(last.current_track)

    def test_move_keeps_cursor_on_logical_track(self) -> None:
        queue = PlaybackQueue()
        queue.set_tracks(tracks("one.mp3", "two.mp3", "three.mp3"), "two.mp3")

        self.assertTrue(queue.move_down("two.mp3"))
        self.assertEqual(queue.current().path, "two.mp3")
        self.assertTrue(queue.move_up("two.mp3"))
        self.assertEqual(queue.current().path, "two.mp3")

    def test_clear_resets_tracks_and_cursor(self) -> None:
        queue = PlaybackQueue()
        queue.add_tracks(tracks("one.mp3"))

        queue.clear()

        self.assertIsNone(queue.current())
        self.assertEqual(queue.as_dict(), {"current_path": None, "tracks": []})

    def test_serialization_exposes_only_one_current_track(self) -> None:
        queue = PlaybackQueue()
        queue.set_tracks(tracks("one.mp3", "two.mp3"), "two.mp3")

        status = queue.as_dict()

        self.assertEqual(status["current_path"], "two.mp3")
        self.assertEqual(
            status["tracks"],
            [
                {"path": "one.mp3", "name": "one.mp3", "is_current": False},
                {"path": "two.mp3", "name": "two.mp3", "is_current": True},
            ],
        )

    def test_two_instances_are_completely_independent(self) -> None:
        local_queue = PlaybackQueue()
        bose_queue = PlaybackQueue()
        local_queue.set_tracks(tracks("local-one.mp3", "local-two.mp3"), "local-one.mp3")
        bose_queue.set_tracks(tracks("bose-only.mp3"), "bose-only.mp3")

        local_queue.next()
        local_queue.add_tracks(tracks("local-three.mp3"))
        local_queue.remove("local-one.mp3")
        local_queue.move_up("local-three.mp3")
        local_queue.clear()

        self.assertEqual(bose_queue.current().path, "bose-only.mp3")
        self.assertEqual(
            [track["path"] for track in bose_queue.as_dict()["tracks"]],
            ["bose-only.mp3"],
        )


if __name__ == "__main__":
    unittest.main()
