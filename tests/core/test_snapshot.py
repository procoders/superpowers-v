from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import snapshot  # noqa: E402


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = helpers.make_repo(self.tmp, {"a.txt": "one\n", "src/b.js": "b\n"})

    def tearDown(self):
        self._tmp.cleanup()

    def test_untracked_file_changes_tree(self):
        before = snapshot.tree(self.repo)
        helpers.write(self.repo, {"new.txt": "x\n"})
        self.assertNotEqual(before, snapshot.tree(self.repo))

    def test_deletion_and_mode_change_tree(self):
        t0 = snapshot.tree(self.repo)
        (self.repo / "a.txt").unlink()
        t1 = snapshot.tree(self.repo)
        self.assertNotEqual(t0, t1)
        os.chmod(self.repo / "src/b.js", 0o755)
        self.assertNotEqual(t1, snapshot.tree(self.repo))

    def test_user_index_untouched(self):
        helpers.write(self.repo, {"staged.txt": "s\n", "loose.txt": "l\n"})
        helpers.sh(self.repo, "add", "staged.txt")
        before = helpers.sh(self.repo, "diff", "--cached", "--name-only")
        snapshot.tree(self.repo)
        self.assertEqual(before, helpers.sh(self.repo, "diff", "--cached", "--name-only"))

    def test_evidence_dir_excluded(self):
        t0 = snapshot.tree(self.repo)
        helpers.write(self.repo, {"docs/compound-v/runs/x.json": "{}"})
        self.assertEqual(t0, snapshot.tree(self.repo))
        helpers.write(self.repo, {"docs/compound-v/plans/p.md": "plan\n"})
        self.assertNotEqual(t0, snapshot.tree(self.repo))

    def test_crlf_config_independent(self):
        helpers.write(self.repo, {"w.txt": b"line\r\n"})
        plain = snapshot.tree(self.repo)
        helpers.sh(self.repo, "config", "core.autocrlf", "true")
        self.assertEqual(plain, snapshot.tree(self.repo))

    def test_ignored_env_digest(self):
        helpers.write(self.repo, {".gitignore": ".env\n"})
        self.assertEqual("none", snapshot.ignored_env_digest(self.repo))
        helpers.write(self.repo, {".env": "A=1\n"})
        t0, d0 = snapshot.tree(self.repo), snapshot.ignored_env_digest(self.repo)
        helpers.write(self.repo, {".env": "A=2\n"})
        self.assertEqual(t0, snapshot.tree(self.repo))
        self.assertNotEqual(d0, snapshot.ignored_env_digest(self.repo))

    def test_materialize_roundtrip_and_tamper(self):
        helpers.write(self.repo, {"untracked.js": "u\n"})
        tid = snapshot.tree(self.repo)
        self.assertEqual(tid, snapshot.materialize(self.repo, tid, self.tmp / "d1"))
        self.assertEqual("u\n", (self.tmp / "d1/untracked.js").read_text())

        def flip(dest):
            p = Path(dest) / "a.txt"
            data = bytearray(p.read_bytes())
            data[0] ^= 1
            p.write_bytes(bytes(data))

        with self.assertRaises(snapshot.SnapshotMismatch):
            snapshot.materialize(self.repo, tid, self.tmp / "d2", _after_extract=flip)

    def test_snapshot_unicode_and_space_paths(self):
        helpers.write(self.repo, {"a b.txt": "space\n", "বুকিং.txt": "bangla\n"})
        tid = snapshot.tree(self.repo)
        dest = self.tmp / "d"
        self.assertEqual(tid, snapshot.materialize(self.repo, tid, dest))
        self.assertTrue((dest / "a b.txt").is_file())
        self.assertTrue((dest / "বুকিং.txt").is_file())

    def test_snapshot_requires_commit(self):
        bare = helpers.make_repo(self.tmp / "empty", commit=False)
        r = helpers.cli(bare, "snapshot")
        self.assertEqual(2, r.returncode)
        self.assertIn("no commit", r.stderr)
        self.assertEqual(1, len(r.stderr.strip().splitlines()))

    def test_cli_snapshot_and_checkout(self):
        r = helpers.cli(self.repo, "snapshot")
        self.assertEqual(0, r.returncode, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(snapshot.tree(self.repo), out["tree"])
        r = helpers.cli(self.repo, "checkout", "--dest", str(self.tmp / "co"))
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertEqual(out["tree"], json.loads(r.stdout)["tree"])


if __name__ == "__main__":
    unittest.main()
