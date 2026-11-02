# Research Note Skills

Two complementary Codex skills for turning research sources into structured
Markdown notes and extracting useful figures from papers.

## Included skills

- `tech-paper-notes`: researches arXiv papers, PDFs, repositories, and project
  pages, then creates or updates a structured note in the user's existing note
  system.
- `paper-figure-extractor`: extracts a small set of high-signal figures from a
  paper PDF and writes Obsidian or standard Markdown image links.

They live in one repository because the note-writing workflow can optionally
call the figure extractor. Each skill remains independently installable.

## Design goals

- No hardcoded vault name, taxonomy, home directory, timezone, or proxy.
- Reuse the user's existing folder and naming conventions when they are clear.
- Keep source claims traceable and mark missing or conflicting facts.
- Work with Obsidian links or normal Markdown links.
- Keep figure extraction local and deterministic.

## Install

Clone the repository, then copy either or both skill directories into your
Codex skills directory:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_HOME/skills"
cp -R skills/tech-paper-notes "$CODEX_HOME/skills/"
cp -R skills/paper-figure-extractor "$CODEX_HOME/skills/"
```

Install the figure extractor's Python dependencies when using that skill:

```bash
python3 -m pip install -r requirements.txt
```

Python 3.9 or newer is recommended. `PyMuPDF` is the primary extraction
backend. Pillow improves Poppler fallback trimming. Optional system tools are:

- `pdftotext` and `pdftoppm` from Poppler for fallback extraction
- `pdffigures2` for users who already have a compatible CLI installed

## Usage

Typical requests that activate `tech-paper-notes`:

```text
Create a research note from this arXiv paper and its GitHub repository.
Update my existing note with the model architecture and training data.
Summarize these papers into my Obsidian vault and include key figures.
```

Run the figure extractor directly from this repository:

```bash
python3 skills/paper-figure-extractor/scripts/extract_figures.py paper.pdf \
  --output-dir "notes/attachments/paper-name" \
  --markdown-style markdown \
  --markdown-base "notes" \
  --max-figures 6
```

The output directory contains numbered images, `figures.json`, and
`figures.md`. Re-running the command replaces only those managed outputs and
leaves unrelated files untouched.

## Portability and privacy

The public skills do not contain API keys, credentials, private server
addresses, personal note content, or absolute user paths. Network access is
performed by the agent's available tools. Existing `HTTP_PROXY`,
`HTTPS_PROXY`, or `ALL_PROXY` environment settings may be used by those tools;
the skills do not prescribe a local proxy address.

The note writer chooses its destination in this order:

1. A path explicitly requested by the user.
2. A clearly established note root and nearby convention in the workspace.
3. A conservative `Research Notes/` default under the current workspace.

See [`skills/tech-paper-notes/references/note-schema.md`](skills/tech-paper-notes/references/note-schema.md)
for the default schema and adaptation rules.

## Validation

```bash
python3 -m py_compile skills/paper-figure-extractor/scripts/extract_figures.py
python3 -m unittest discover -s tests -v
```

Codex's bundled skill validator can also be run against each skill directory:

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py skills/tech-paper-notes
python3 /path/to/skill-creator/scripts/quick_validate.py skills/paper-figure-extractor
```

## License

MIT. See [LICENSE](LICENSE).
