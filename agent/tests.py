import os
import tempfile
from pathlib import Path

from django.test import TestCase

from agent.tools import code_tools


class CodeToolsTests(TestCase):
    def test_read_file_line_numbers_and_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "hello.txt"
            lines = [f"line {i}" for i in range(5)]
            p.write_text("\n".join(lines), encoding="utf-8")
            out = code_tools.read_file(tmp, "hello.txt")
            self.assertNotIn("error", out or {})
            self.assertEqual(out["total_lines"], 5)
            self.assertIn("1|line 0", out["content"])

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp).resolve()
            outside = tmp.parent / "cra_outside_secret.txt"
            try:
                outside.write_text("nope", encoding="utf-8")
                rel_path = os.path.relpath(str(outside), str(tmp))
                out = code_tools.read_file(str(tmp), rel_path)
                self.assertIn("error", out)
            finally:
                if outside.exists():
                    outside.unlink()
