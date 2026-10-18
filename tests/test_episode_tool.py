"""Synthetic fixtures only; these are not recorded AI battles."""
import importlib.util
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "episode_tool.py"
SPEC = importlib.util.spec_from_file_location("episode_tool", MODULE_PATH)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def chunk(kind, data):
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff))


def png():
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
            + chunk(b"IEND", b""))


class EpisodeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "episode"
        tool.initialize(self.root, "synthetic-test", 1, 30)
        (self.root / "frames").mkdir()
        (self.root / "frames" / "frame.png").write_bytes(png())
        (self.root / "state.json").write_text('{"synthetic":true}', encoding="utf-8")
        (self.root / "decision.json").write_text(
            '{"synthetic":true,"actor_id":"blue-van","accepted":true,'
            '"command":"hold","public_brief":"Observe first."}', encoding="utf-8")
        self.image = tool.file_ref(self.root, "frames/frame.png")
        self.receipt = tool.file_ref(self.root, "decision.json")
        state_sha = tool.sha256(self.root / "state.json")
        self.data = json.loads((self.root / "episode.json").read_text(encoding="utf-8"))
        self.data.update(
            actors=[{"id": "blue-van", "side": "blue",
                     "model": "example-model", "unit_ids": ["blue-1"]}],
            supervision_views=["director", "blue-van"],
            selected_game_id="game-1",
            shots=[
                {"id": "intro", "start_frame": 0, "duration_frames": 30,
                 "view": "director", "evidence_kind": "actual",
                 "source_refs": [self.image]},
                {"id": "question", "start_frame": 30, "duration_frames": 120,
                 "view": "blue-van", "evidence_kind": "actual",
                 "source_refs": [self.image]},
                {"id": "reveal", "start_frame": 150, "duration_frames": 60,
                 "view": "blue-van", "evidence_kind": "actual",
                 "source_refs": [self.image, self.receipt]}],
            interactions=[{"actor_id": "blue-van", "prompt_shot_id": "question",
                           "reveal_shot_id": "reveal", "prompt_audio_end_frame": 60,
                           "countdown_start_frame": 60, "countdown_frames": 90,
                           "receipt": self.receipt}])
        self.data["games"][0].update(
            status="complete", completed_turns=[0, 1],
            snapshots=[{"turn": t, "view": view, "image": self.image,
                        "state_sha256": state_sha}
                       for t in (0, 1) for view in ("director", "blue-van")])
        self.save()

    def save(self):
        (self.root / "episode.json").write_text(
            json.dumps(self.data, ensure_ascii=False), encoding="utf-8")

    def test_valid_edit_and_html(self):
        _, report = tool.validate(self.root, "edit")
        self.assertEqual(report["snapshots"], 4)
        page = tool.supervision(self.root)
        content = page.read_text(encoding="utf-8")
        self.assertIn("Director / 全知监督", content)
        self.assertIn("blue-van", content)
        self.assertIn("frames/frame.png", content)

    def test_missing_actor_snapshot(self):
        self.data["games"][0]["snapshots"].pop()
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "Missing supervision"):
            tool.validate(self.root, "capture")

    def test_capture_turn_gap(self):
        game = self.data["games"][0]
        game["completed_turns"] = [0, 2]
        for snap in game["snapshots"]:
            if snap["turn"] == 1:
                snap["turn"] = 2
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "sequence has a gap"):
            tool.validate(self.root, "capture")

    def test_incomplete_batch_cannot_be_selected_for_edit(self):
        self.data["selected_game_id"] = None
        self.data["games"][0]["status"] = "running"
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "batch is incomplete"):
            tool.validate(self.root, "edit")

    def test_tampered_source(self):
        (self.root / "decision.json").write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(tool.AuditError, "SHA256 mismatch"):
            tool.validate(self.root, "edit")

    def test_lfs_pointer_is_not_a_snapshot(self):
        (self.root / "frames" / "frame.png").write_text(
            "version https://git-lfs.github.com/spec/v1\n", encoding="utf-8")
        ref = tool.file_ref(self.root, "frames/frame.png")
        for snap in self.data["games"][0]["snapshots"]:
            snap["image"] = ref
        for shot in self.data["shots"]:
            shot["source_refs"] = [ref, self.receipt]
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "Not a PNG header"):
            tool.validate(self.root, "capture")

    def test_rejects_path_escape_and_windows_drive(self):
        for relative in ("../outside.txt", "Z:/outside.txt", "\\\\server\\share\\file"):
            with self.subTest(path=relative):
                with self.assertRaises(tool.AuditError):
                    tool.local_path(self.root, relative, must_exist=False)

    def test_rejects_symlink_escape(self):
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "link.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("OS does not allow symlink creation")
        with self.assertRaisesRegex(tool.AuditError, "escapes episode"):
            tool.file_ref(self.root, "link.txt")

    def test_rejects_timeline_gap(self):
        self.data["shots"][1]["start_frame"] = 31
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "gap/overlap"):
            tool.validate(self.root, "edit")

    def test_countdown_after_question_audio(self):
        self.data["interactions"][0]["prompt_audio_end_frame"] = 61
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "before complete question"):
            tool.validate(self.root, "edit")

    def test_three_seconds_at_other_fps(self):
        self.data["fps"] = 24
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "exactly three seconds"):
            tool.validate(self.root, "edit")
        self.data["interactions"][0].update(
            countdown_start_frame=78, countdown_frames=72)
        self.save()
        tool.validate(self.root, "edit")

    def test_reveal_requires_actual_receipt_reference(self):
        self.data["shots"][2]["source_refs"] = [self.image]
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "not bound"):
            tool.validate(self.root, "edit")

    def test_prompt_cannot_use_director_omniscience(self):
        self.data["shots"][1]["view"] = "director"
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "actor view"):
            tool.validate(self.root, "edit")

    def test_duplicate_unit_control(self):
        self.data["actors"].append(
            {"id": "blue-rear", "side": "blue", "model": "example-model",
             "unit_ids": ["blue-1"]})
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "multiple actor slots"):
            tool.validate(self.root, "draft")

    def test_delivery_requires_nonempty_artifacts(self):
        for key, name in (("video", "movie.mp4"), ("subtitles", "captions.srt"),
                          ("source_package", "source.zip")):
            (self.root / name).write_bytes(b"synthetic fixture, not actual media")
            self.data["delivery"][key] = tool.file_ref(self.root, name)
        self.save()
        tool.validate(self.root, "delivery")
        (self.root / "movie.mp4").write_bytes(b"")
        self.data["delivery"]["video"] = tool.file_ref(self.root, "movie.mp4")
        self.save()
        with self.assertRaisesRegex(tool.AuditError, "Empty delivery artifact"):
            tool.validate(self.root, "delivery")

    def test_html_escapes_user_metadata(self):
        self.data["episode_id"] = '<script>alert("x")</script>'
        self.save()
        text = tool.supervision(self.root).read_text(encoding="utf-8")
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)

    def test_no_silent_output_overwrite(self):
        page = tool.supervision(self.root)
        before = page.read_bytes()
        with self.assertRaisesRegex(tool.AuditError, "index.html exists"):
            tool.supervision(self.root)
        self.assertEqual(before, page.read_bytes())
        tool.supervision(self.root, overwrite=True)
        with self.assertRaises(FileExistsError):
            tool.initialize(self.root, "new", 5, 30)
        self.assertEqual(json.loads((self.root / "episode.json").read_text(
            encoding="utf-8"))["episode_id"], "synthetic-test")


if __name__ == "__main__":
    unittest.main()
