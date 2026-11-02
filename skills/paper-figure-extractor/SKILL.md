---
name: paper-figure-extractor
description: Extract useful diagrams, architecture figures, result grids, tables, and nearby captions from research-paper PDFs, then write Obsidian or standard Markdown image links. Use when the user asks to add paper figures to a note, inspect a PDF visually, or prepare a curated set of research figures.
---

# Paper Figure Extractor

Extract a small, curated set of useful figures from a local research PDF. The
bundled script writes numbered image files, machine-readable metadata, and
ready-to-insert image links without sending the paper to an external service.

## Run

From an installed Codex skill:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/paper-figure-extractor/scripts/extract_figures.py" \
  /path/to/paper.pdf \
  --output-dir "/path/to/note/attachments/paper-name" \
  --markdown-style obsidian \
  --markdown-base "/path/to/note" \
  --max-figures 6
```

From the repository checkout, run
`python3 skills/paper-figure-extractor/scripts/extract_figures.py ...`.

The output directory contains:

- `fig-01.png`, `fig-02.png`, and other selected images
- `figures.json` with page, bounding box, score, and nearby caption metadata
- `figures.md` with Obsidian or standard Markdown image links

Re-running the script replaces only these managed outputs. Unrelated files in
the output directory are preserved.

## Dependencies and backends

Python 3.9+ is recommended.

- `PyMuPDF` is the primary backend and provides cropped figure regions.
- Pillow is optional and improves white-margin trimming in Poppler fallback.
- `pdftotext` and `pdftoppm` provide a lower-precision page-render fallback.
- `pdffigures2` is optional for users with a compatible CLI already installed.

Install the repository dependencies with `python3 -m pip install -r
requirements.txt` from the repository root. Follow the active environment's
authorization policy before installing packages.

Backend behavior:

- `--backend auto`: try `pdffigures2` when installed, then PyMuPDF, then
  Poppler.
- `--backend pymupdf`: require PyMuPDF and fail clearly if unavailable.
- `--backend pdffigures2`: require its CLI and fail clearly if unavailable.
- `--backend poppler`: require both `pdftotext` and `pdftoppm`.

## Selection

Prefer overview architecture, framework, pipeline, training/inference flow,
meaningful qualitative comparisons, and decisive result tables. Skip logos,
QR codes, author portraits, isolated icons, equation-only crops, references,
repeated grids, and appendix material unless explicitly requested.

For a normal single-paper note, retain 3-6 figures. Inspect the generated PNGs
before inserting them. Put each figure near the relevant discussion rather
than grouping every image at the top.

Captions help locate and score regions but are not written below image links by
default. Use `--write-captions` to add blockquotes to `figures.md`, and
`--include-source-caption` to keep the paper's caption inside the crop.

## Link style

Use `--markdown-style obsidian` for wikilink embeds:

```markdown
![[attachments/paper-name/fig-01.png]]
```

Use `--markdown-style markdown` for portable Markdown:

```markdown
![Architecture overview](attachments/paper-name/fig-01.png)
```

Set `--markdown-base` to the note directory so generated paths are relative to
that directory. If the output lies outside the base, the script keeps the
caller-provided path rather than inventing a broken relative link.

## Validate

- Open the selected images and remove weak or incorrectly cropped candidates.
- Confirm every link in `figures.md` resolves from the note.
- Confirm captions and page numbers in `figures.json` match the source PDF.
- Do not paste `figures.json` directly into the research note.
