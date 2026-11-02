# Default note schema

Use this schema only when the workspace has no stronger local convention.
Remove sections that do not apply instead of filling them with generic prose.

```markdown
# Paper or Project Title

**Domain**: task or field
**Authors / organization**: names
**Published**: YYYY-MM-DD; revised YYYY-MM-DD when relevant
**Paper**: https://...
**Project**: https://...
**Repository**: https://...
**Models / demo**: https://...

## One-sentence summary

What the work changes, how it does so, and the most useful verified result.

## Problem and contributions

- What problem or bottleneck is addressed.
- The concrete technical contributions.
- What is genuinely different from the closest prior work.

## Architecture and method

- Overall pipeline and inputs/outputs.
- Important modules, losses, routing, conditioning, or system components.
- Parameter counts and active parameter counts where applicable.

## Data and training

- Dataset sources, scale, duration/sample count, filtering, and labels.
- Training stages, teacher/student relationships, objectives, and schedules.
- Hardware, GPU count, precision, batch size, optimizer, and training time.

## Inference and deployment

- Sampling steps, resolution, duration, FPS/latency/throughput, and memory.
- Quantization, sparsity, caching, parallelism, or other optimizations.
- Hardware and software constraints behind reported numbers.

## Evaluation

- Benchmarks, metrics, human evaluation, baselines, and ablations.
- Exact improvements and the conditions under which they were measured.

## Release status and limitations

- Code, weights, training code, data, demo, and their licenses.
- Known limitations, missing disclosures, and contradictions between sources.

## Related work

- Only the nearest methods needed to understand this work.
```

## Adaptation rules

- Match the title level and metadata syntax of neighboring notes.
- If the vault uses date-prefixed filenames, use the paper's initial public
  release date unless the local convention clearly uses another date.
- If attachments live beside each note, follow that layout. Otherwise use an
  `attachments/<note-stem>/` directory under the note's folder.
- Use Obsidian wikilinks only in a vault that already uses them.
- For multiple papers, create separate notes unless the user asked for a
  survey, comparison, or combined project note.
