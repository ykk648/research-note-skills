from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

try:
    import fitz
except ModuleNotFoundError:  # pragma: no cover - dependency-specific skip
    fitz = None


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "paper-figure-extractor" / "scripts" / "extract_figures.py"


@unittest.skipIf(fitz is None, "PyMuPDF is not installed")
class ExtractFiguresSmokeTest(unittest.TestCase):
    def make_pdf(self, path: Path) -> None:
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(70, 110, 542, 350))
        for x in (180, 306, 432):
            shape.draw_line(fitz.Point(x, 140), fitz.Point(x, 320))
        shape.finish(color=(0.1, 0.2, 0.6), width=2)
        shape.commit()
        page.insert_text(
            fitz.Point(72, 382),
            "Figure 1. Overview architecture and inference pipeline.",
            fontsize=12,
        )
        doc.save(path)
        doc.close()

    def test_pymupdf_extracts_and_replaces_managed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            pdf = temp_path / "paper.pdf"
            output = temp_path / "attachments"
            output.mkdir()
            self.make_pdf(pdf)

            stale = output / "fig-99.png"
            stale.write_bytes(b"stale")
            unrelated = output / "keep.txt"
            unrelated.write_text("keep", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(pdf),
                    "--output-dir",
                    str(output),
                    "--backend",
                    "pymupdf",
                    "--max-figures",
                    "1",
                    "--min-score",
                    "0.1",
                    "--markdown-style",
                    "markdown",
                    "--markdown-base",
                    str(temp_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(stale.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue((output / "fig-01.png").exists())
            self.assertTrue((output / "figures.md").exists())
            metadata = json.loads((output / "figures.json").read_text(encoding="utf-8"))
            self.assertEqual(len(metadata), 1)
            self.assertEqual(metadata[0]["page"], 1)

    @unittest.skipUnless(
        shutil.which("pdftotext") and shutil.which("pdftoppm"),
        "Poppler tools are not installed",
    )
    def test_poppler_fallback_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            pdf = temp_path / "paper.pdf"
            output = temp_path / "attachments"
            self.make_pdf(pdf)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(pdf),
                    "--output-dir",
                    str(output),
                    "--backend",
                    "poppler",
                    "--max-figures",
                    "1",
                    "--min-score",
                    "0.1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((output / "fig-01.png").exists())
            self.assertTrue((output / "figures.json").exists())
            self.assertTrue((output / "figures.md").exists())


class ExplicitBackendTest(unittest.TestCase):
    def load_module(self):
        spec = importlib.util.spec_from_file_location("extract_figures", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.addCleanup(sys.modules.pop, spec.name, None)
        return module

    def test_missing_explicit_pymupdf_backend_fails(self) -> None:
        module = self.load_module()
        original = module.fitz
        module.fitz = None
        args = Namespace(backend="pymupdf")
        try:
            with self.assertRaisesRegex(RuntimeError, "PyMuPDF"):
                module.extract(args)
        finally:
            module.fitz = original

    def test_missing_explicit_pdffigures2_backend_fails(self) -> None:
        module = self.load_module()
        args = Namespace(backend="pdffigures2")
        with mock.patch.object(module.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pdffigures2"):
                module.extract(args)


if __name__ == "__main__":
    unittest.main()
