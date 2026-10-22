from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers  # noqa: E402
from test_receipts import Base  # noqa: E402

from cvcore import review, run, snapshot  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
out, cwd = a[a.index("-o") + 1], a[a.index("-C") + 1]
prompt = sys.stdin.read()
files = sorted(os.path.relpath(os.path.join(d, f), cwd)
               for d, _, fs in os.walk(cwd) for f in fs)
with open(out, "w") as fh:
    json.dump({"snapshot": "x", "summary": json.dumps(files), "findings": [],
               "prompt_has_request": "add a booking page" in prompt}, fh)
sys.exit(int(os.environ.get("FAKE_CODEX_RC", "0")))
'''


class ReviewTest(Base):
    def setUp(self):
        super().setUp()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "codex").write_text(FAKE)
        os.chmod(bindir / "codex", 0o755)
        self._path = os.environ["PATH"]
        os.environ["PATH"] = f"{bindir}{os.pathsep}{self._path}"
        self.out = self.repo / f"docs/compound-v/runs/{self.rec['id']}-review-1.json"

    def tearDown(self):
        os.environ["PATH"] = self._path
        os.environ.pop("FAKE_CODEX_RC", None)
        super().tearDown()

    def test_codex_failure_is_error(self):
        os.environ["FAKE_CODEX_RC"] = "124"
        with self.assertRaises(review.ReviewError):
            review.codex(self.repo, self.reload(), self.out, timeout_s=60)

    def test_codex_checkout_has_untracked(self):
        helpers.write(self.repo, {"src/new.js": "n\n"})
        path = review.codex(self.repo, self.reload(), self.out, timeout_s=60)
        data = json.loads(Path(path).read_text())
        self.assertIn("src/new.js", json.loads(data["summary"]))
        self.assertNotIn("live.rc", json.loads(data["summary"]))
        self.assertTrue(data["prompt_has_request"])
        self.assertEqual(snapshot.tree(self.repo), data["snapshot"])

    def test_setup_replacing_source_is_error(self):
        helpers.write(self.repo, {"src/a.js": "throw new Error('broken')\n"})
        rec = self.reload()
        rec["setup_cmd"] = "printf 'ok\\n' > src/a.js; mkdir -p node_modules; touch node_modules/x"
        run.save(self.repo, rec)
        with self.assertRaises(review.ReviewError) as cm:
            review.codex(self.repo, self.reload(), self.out, timeout_s=60)
        self.assertIn("setup or reviewer changed source", str(cm.exception))
        rec["setup_cmd"] = "mkdir -p node_modules; touch node_modules/x"
        run.save(self.repo, rec)
        review.codex(self.repo, self.reload(), self.out, timeout_s=60)

    def test_reviewer_editing_source_is_error(self):
        bindir = self.tmp / "bin"
        (bindir / "codex").write_text(FAKE.replace("prompt = sys.stdin.read()",
                                                   "prompt = sys.stdin.read()\n"
                                                   "open(os.path.join(cwd, 'src/a.js'), 'w').write('x')"))
        with self.assertRaises(review.ReviewError):
            review.codex(self.repo, self.reload(), self.out, timeout_s=60)

    def test_submodule_review_clear_error(self):
        sub = helpers.make_repo(self.tmp / "sub", {"lib.py": "pass\n"})
        helpers.sh(self.repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q",
                   str(sub), "vendor")
        with self.assertRaises(review.ReviewError) as cm:
            review.codex(self.repo, self.reload(), self.out, timeout_s=60)
        self.assertIn("submodules are not supported", str(cm.exception))

    def test_codex_unparsable_output_is_error(self):
        bindir = self.tmp / "bin"
        (bindir / "codex").write_text("#!/bin/sh\nwhile [ \"$1\" != -o ]; do shift; done\n"
                                      "echo 'not json' > \"$2\"\n")
        with self.assertRaises(review.ReviewError):
            review.codex(self.repo, self.reload(), self.out, timeout_s=60)

    def test_cli_review_codex_records_round(self):
        r = helpers.cli(self.repo, "review", "codex", "--id", self.rec["id"], "--timeout", "60")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertTrue(self.out.is_file())
        self.assertEqual(1, self.reload()["review_round"])


if __name__ == "__main__":
    unittest.main()
