from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402

from cvcore import lanes, run  # noqa: E402


class LanesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = helpers.make_repo(Path(self._tmp.name), {
            "src/a/x.js": "a\n", "src/b/x.js": "b\n"})
        helpers.sh(self.repo, "checkout", "-q", "-b", "feature")
        self.rec = run.start(self.repo, tier="full", request="parallel build")
        self.rec.update({"lanes": {"a": ["src/a/**"]}, "test_cmd": "true"})
        run.save(self.repo, self.rec)
        self.wt = self.repo / ".claude/worktrees/cv-a"
        helpers.sh(self.repo, "worktree", "add", "-q", "-b", "lane-a", str(self.wt), "HEAD")
        self.head = self.rev("HEAD")

    def tearDown(self):
        self._tmp.cleanup()

    def rev(self, ref, repo=None):
        return helpers.sh(repo or self.repo, "rev-parse", ref).decode().strip()

    def lane_commit(self, files):
        helpers.write(self.wt, files)
        helpers.commit_all(self.wt, "lane work")

    def finish(self):
        return lanes.finish(self.repo, run.load(self.repo, self.rec["id"]), "a", "lane-a")

    def test_write_outside_lane_refused(self):
        self.lane_commit({"src/a/x.js": "a2\n", "src/b/x.js": "b2\n"})
        r = self.finish()
        self.assertEqual(("refused", ["src/b/x.js"]), (r["status"], r["violations"]))
        self.assertEqual(self.head, self.rev("HEAD"))

    def test_symlink_escape_in_lane_refused(self):
        os.symlink("../../../../etc/hosts", self.wt / "src/a/l")
        helpers.commit_all(self.wt, "link")
        r = self.finish()
        self.assertEqual(("refused", ["src/a/l"]), (r["status"], r["violations"]))

    def test_interrupted_worker_refused(self):
        self.lane_commit({"src/a/x.js": "a2\n"})
        helpers.write(self.wt, {"src/a/y.js": "half\n"})
        r = self.finish()
        self.assertEqual("refused", r["status"])
        self.assertIn("interrupted", r["reason"])

    def test_no_commits_refused(self):
        r = self.finish()
        self.assertEqual(("refused", "no commits"), (r["status"], r["reason"]))

    def test_tests_fail_aborts_merge(self):
        self.rec["test_cmd"] = "false"
        run.save(self.repo, self.rec)
        self.lane_commit({"src/a/x.js": "a2\n"})
        r = self.finish()
        self.assertEqual(("refused", "tests failed"), (r["status"], r["reason"]))
        self.assertEqual(self.head, self.rev("HEAD"))
        self.assertEqual(b"", helpers.sh(self.repo, "status", "--porcelain", "--", "src"))
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())

    def test_dirty_main_refused(self):
        self.lane_commit({"src/a/x.js": "a2\n"})
        helpers.write(self.repo, {"src/b/x.js": "user edit\n"})
        r = self.finish()
        self.assertEqual(("refused", "main tree dirty"), (r["status"], r["reason"]))
        self.assertEqual("user edit\n", (self.repo / "src/b/x.js").read_text())

    def test_conflict_aborts(self):
        self.lane_commit({"src/a/x.js": "lane\n"})
        helpers.write(self.repo, {"src/a/x.js": "main\n"})
        helpers.commit_all(self.repo, "main moves")
        head = self.rev("HEAD")
        r = self.finish()
        self.assertEqual(("refused", "conflict"), (r["status"], r["reason"]))
        self.assertEqual(head, self.rev("HEAD"))
        self.assertEqual("main\n", (self.repo / "src/a/x.js").read_text())

    def test_clean_lane_merges(self):
        self.lane_commit({"src/a/x.js": "a2\n", "src/a/new.js": "n\n"})
        r = self.finish()
        self.assertEqual(("merged", []), (r["status"], r["violations"]))
        self.assertEqual("a2\n", (self.repo / "src/a/x.js").read_text())
        self.assertEqual("merge lane a", helpers.sh(self.repo, "log", "-1", "--format=%s")
                         .decode().strip())
        self.assertEqual("feature", helpers.sh(self.repo, "branch", "--show-current")
                         .decode().strip())
        self.assertEqual("merged", self.finish()["status"])
        state = run.load(self.repo, self.rec["id"])["lane_state"]["a"]
        self.assertEqual(("lane-a", self.head, "merged"),
                         (state["branch"], state["base"], state["status"]))

    def test_native_worktree_dir_not_in_snapshot_or_scope(self):
        from cvcore import scope, snapshot
        helpers.sh(self.repo, "worktree", "remove", str(self.wt))
        before = snapshot.tree(self.repo)
        helpers.sh(self.repo, "worktree", "add", "-q", str(self.wt), "lane-a")
        self.assertEqual(before, snapshot.tree(self.repo))
        self.assertEqual([], scope.changed(self.repo, "HEAD"))

    def test_lane_never_touches_ignored_user_file(self):
        helpers.write(self.repo, {".gitignore": "src/a/local.txt\n"})
        helpers.commit_all(self.repo, "ignore")
        helpers.sh(self.wt, "merge", "-q", "feature")
        helpers.write(self.wt, {"src/a/local.txt": "worker replacement\n"})
        helpers.sh(self.wt, "add", "-f", "src/a/local.txt")
        helpers.commit_all(self.wt, "worker")
        helpers.write(self.repo, {"src/a/local.txt": "irreplaceable user work\n"})
        for cmd in ("true", "false"):
            self.rec["test_cmd"] = cmd
            run.save(self.repo, self.rec)
            r = self.finish()
            self.assertEqual("refused", r["status"])
            self.assertIn("would overwrite", r["reason"])
            self.assertEqual("irreplaceable user work\n",
                             (self.repo / "src/a/local.txt").read_text())

    def test_lane_refuses_staged_or_merging_main(self):
        self.lane_commit({"src/a/x.js": "a2\n"})
        helpers.write(self.repo, {"docs/compound-v/spec.md": "draft\n"})
        helpers.sh(self.repo, "add", "docs/compound-v/spec.md")
        self.assertEqual("main tree dirty", self.finish()["reason"])
        self.assertIn("docs/compound-v/spec.md",
                      helpers.sh(self.repo, "diff", "--cached", "--name-only").decode())
        helpers.sh(self.repo, "rm", "-q", "--cached", "docs/compound-v/spec.md")
        (self.repo / "docs/compound-v/spec.md").unlink()
        (self.repo / ".git/MERGE_HEAD").write_text(self.head + "\n")
        self.assertEqual("a merge is already in progress", self.finish()["reason"])

    def test_newline_worktree_path(self):
        helpers.sh(self.repo, "worktree", "add", "-q", "-b", "lane-n",
                   str(Path(self._tmp.name) / "worker\nspace"), "HEAD")
        wt = Path(self._tmp.name) / "worker\nspace"
        helpers.write(wt, {"src/a/x.js": "n\n"})
        helpers.commit_all(wt, "n")
        r = lanes.finish(self.repo, run.load(self.repo, self.rec["id"]), "a", "lane-n")
        self.assertEqual("merged", r["status"], r)

    def test_cli_lane_finish(self):
        self.lane_commit({"src/a/x.js": "a2\n"})
        r = helpers.cli(self.repo, "lane", "finish", "--task", "a", "--branch", "lane-a")
        self.assertEqual(0, r.returncode, r.stderr)
        r = helpers.cli(self.repo, "lane", "finish", "--task", "zz", "--branch", "lane-a")
        self.assertEqual(2, r.returncode)


if __name__ == "__main__":
    unittest.main()
