---
name: tech-paper-notes
description: Create or update structured Markdown research notes from arXiv papers, PDFs, repositories, and project pages. Use when the user asks to research a technical paper, add it to a note system or Obsidian vault, compare related work, or enrich an existing paper note with verified model, data, training, inference, and evaluation details.
---

# Technical Paper Notes

Create a concise, evidence-grounded technical note that fits the user's
existing workspace. Preserve nearby conventions when updating a note; do not
impose a private taxonomy, fixed vault name, timezone, language, or local path.

## Workflow

1. Record every supplied source and search the intended note root for an
   existing note by title, paper ID, repository name, and distinctive keywords.
2. Prefer primary sources: paper/PDF, official repository, project page, model
   card, and official release notes. Use secondary sources only to locate or
   contextualize primary material.
3. Capture title, authors, affiliations, initial publication date and latest
   revision when relevant, task, contributions, architecture, model sizes,
   datasets, training compute, inference settings, evaluation, limitations,
   released artifacts, and license. Write "not disclosed" rather than infer a
   number that the sources do not provide.
4. Resolve conflicts explicitly. Prefer the paper for method claims and the
   latest official repository or model card for release and deployment facts.
5. Create or update the note using the local structure and style. Read
   [references/note-schema.md](references/note-schema.md) when a schema is
   needed or the workspace has no clear convention.
6. When figures improve the note and the companion `paper-figure-extractor`
   skill is installed, extract a small curated set and place each image near
   the section it explains. If the companion is unavailable, continue with a
   complete text note unless the user explicitly requires figures.
7. Verify links, numbers, file paths, image references, and the final diff.

## Destination and naming

Choose the destination in this order:

1. The exact path or directory requested by the user.
2. A clearly established paper-note root and neighboring convention in the
   current workspace.
3. `Research Notes/` under the current workspace.

Reuse an existing note instead of creating a duplicate. Match neighboring
title level, filename date format, language, attachment layout, and metadata
style. If none exists, use `YYYY-MM Short Title.md`, the user's language, a
level-one title, and standard Markdown links.

Use the paper's publication date for filenames when the workspace encodes a
date. Use the current system timezone only when a current date is actually
needed.

## Source acquisition

Use the available browser, search, repository, PDF, and CLI tools. Do not rely
on a tool name that may not exist in another environment. For command-line
downloads, honor existing `HTTPS_PROXY`, `HTTP_PROXY`, and `ALL_PROXY`
variables. Do not hardcode a proxy or silently change the user's network
configuration.

For a local PDF, use an available structured PDF reader or `pdftotext`. A
portable `pypdf` fallback looks like this:

```bash
python3 - /path/to/paper.pdf <<'PY'
import sys
from pathlib import Path
from pypdf import PdfReader

pdf = Path(sys.argv[1])
for page in PdfReader(str(pdf)).pages:
    text = (page.extract_text() or "").strip()
    if text:
        print(text)
PY
```

Do not install packages or mutate external services without the authorization
required by the active environment.

## Writing rules

- Match the user's language unless they request another one. Preserve standard
  English names for methods, models, datasets, and metrics.
- Prefer dense, factual paragraphs and bullets over a paper-length translation.
- Keep exact values with their conditions: resolution, duration, batch size,
  GPU type/count, precision, sampling steps, latency definition, and baseline.
- Distinguish total parameters, active parameters, checkpoint size, and runtime
  memory. Distinguish training compute from inference hardware.
- Separate released facts from paper claims. State whether code, weights,
  training code, data, and licenses are actually available.
- Avoid unsupported causal claims, invented implementation details, and hidden
  citation markup. Keep source URLs visible in the note.
- Add personal opinions or TODOs only when requested.

## Figures

Normally keep 3-6 high-signal figures for a single paper: overview,
architecture, training/inference pipeline, or one decisive qualitative/result
grid. Skip logos, author portraits, repeated examples, and appendix noise.

Choose Obsidian embeds only when the destination uses them; otherwise use
standard Markdown images. Do not add a redundant caption below every image
when the surrounding prose already explains it.

## Final checks

- No duplicate note was created.
- Metadata and URLs resolve to the intended paper/project.
- Important model, data, training, inference, hardware, and evaluation facts
  are present or explicitly marked unavailable.
- Comparisons use the same metric and evaluation conditions.
- Every image exists and its link is relative to the note as expected.
- Only the requested note and its deliberate attachments changed.
