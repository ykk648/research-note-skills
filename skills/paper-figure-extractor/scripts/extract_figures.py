#!/usr/bin/env python3
"""Extract high-signal figures from research PDFs for Obsidian notes.

This is a lightweight local-first extractor. It uses PyMuPDF's drawing/image
blocks plus nearby caption text to crop likely figure regions.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError:
    fitz = None

try:
    from PIL import Image, ImageChops
except ModuleNotFoundError:
    Image = None
    ImageChops = None


CAPTION_RE = re.compile(
    r"(?is)\b(?:fig(?:ure)?\.?|table|图|表)\s*[\dIVXLC]+[a-z]?\s*[:.．、-]?\s+(.{0,450})"
)
CAPTION_START_RE = re.compile(r"(?i)^(?:fig(?:ure)?\.?|table)\s*[\dIVXLC]+[a-z]?\b|^[图表]\s*\d+")
FIGURE_START_RE = re.compile(r"(?i)^(?:fig(?:ure)?\.?)\s*[\dIVXLC]+[a-z]?\b|^图\s*\d+")
TABLE_START_RE = re.compile(r"(?i)^table\s*[\dIVXLC]+[a-z]?\b|^表\s*\d+")
GOOD_WORDS = re.compile(
    r"(?i)\b(architecture|framework|overview|pipeline|model|system|method|training|"
    r"inference|comparison|qualitative|result|ablation|module|network|flow|"
    r"架构|框架|流程|模型|系统|方法|训练|推理|对比|消融|模块)\b"
)
BAD_WORDS = re.compile(r"(?i)\b(references|bibliography|appendix|acknowledg|license)\b")
MANAGED_FIGURE_RE = re.compile(r"^fig-\d+\.(?:png|jpe?g)$", re.IGNORECASE)


@dataclass
class FigureCandidate:
    index: int
    page: int
    bbox: tuple[float, float, float, float]
    score: float
    caption: str
    file: str
    width: int
    height: int


@dataclass
class CaptionAnchor:
    page: int
    rect: object
    text: str
    kind: str


def clamp_rect(rect: fitz.Rect, page_rect: fitz.Rect, margin: float = 6) -> fitz.Rect:
    out = fitz.Rect(
        max(page_rect.x0, rect.x0 - margin),
        max(page_rect.y0, rect.y0 - margin),
        min(page_rect.x1, rect.x1 + margin),
        min(page_rect.y1, rect.y1 + margin),
    )
    return out


def merge_rects(rects: list[fitz.Rect], max_gap: float = 18) -> list[fitz.Rect]:
    merged: list[fitz.Rect] = []
    for rect in sorted(rects, key=lambda r: (r.y0, r.x0)):
        hit = None
        for i, existing in enumerate(merged):
            expanded = fitz.Rect(
                existing.x0 - max_gap,
                existing.y0 - max_gap,
                existing.x1 + max_gap,
                existing.y1 + max_gap,
            )
            if expanded.intersects(rect):
                hit = i
                break
        if hit is None:
            merged.append(fitz.Rect(rect))
        else:
            merged[hit].include_rect(rect)
    return merged


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:700]


def full_text(text: str, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:limit]


def rect_area(rect: object) -> float:
    if hasattr(rect, "get_area"):
        return float(rect.get_area())
    return max(float(rect.width), 0.0) * max(float(rect.height), 0.0)


def find_caption(page: fitz.Page, rect: fitz.Rect) -> str:
    page_rect = page.rect
    zones = [
        fitz.Rect(page_rect.x0, rect.y1, page_rect.x1, min(page_rect.y1, rect.y1 + 120)),
        fitz.Rect(page_rect.x0, max(page_rect.y0, rect.y0 - 100), page_rect.x1, rect.y0),
    ]
    for zone in zones:
        text = normalize_text(page.get_textbox(zone))
        match = CAPTION_RE.search(text)
        if match:
            return normalize_text(match.group(0))
    return ""


def visual_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    page_area = page.rect.width * page.rect.height

    for info in page.get_image_info(xrefs=True):
        bbox = fitz.Rect(info["bbox"])
        area = bbox.width * bbox.height
        if area >= page_area * 0.015 and bbox.width >= 80 and bbox.height >= 60:
            rects.append(bbox)

    drawings = page.get_drawings()
    drawing_rects = []
    for drawing in drawings:
        rect = fitz.Rect(drawing.get("rect", fitz.Rect()))
        if rect.width < 8 and rect.height < 8:
            continue
        # Vector figures are often made from many small boxes and connector
        # lines. Keep small drawing pieces first, then filter after merging.
        if rect.width >= 24 and rect.height <= 2:
            rect = fitz.Rect(rect.x0, rect.y0 - 2, rect.x1, rect.y1 + 2)
        elif rect.height >= 24 and rect.width <= 2:
            rect = fitz.Rect(rect.x0 - 2, rect.y0, rect.x1 + 2, rect.y1)
        drawing_rects.append(rect)

    for rect in merge_rects(drawing_rects, max_gap=26):
        area = rect.width * rect.height
        if area >= page_area * 0.004 and rect.width >= 50 and rect.height >= 28:
            rects.append(rect)

    return merge_rects(rects, max_gap=28)


def text_blocks(page: fitz.Page) -> list[dict]:
    blocks = page.get_text("dict").get("blocks", [])
    out: list[dict] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        text_parts: list[str] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text_parts.append(" ".join(span.get("text", "") for span in spans))
        text = full_text(" ".join(text_parts), limit=1500)
        if text:
            out.append({"bbox": fitz.Rect(block["bbox"]), "text": text})
    return out


def text_lines(page: fitz.Page) -> list[dict]:
    raw_lines: list[dict] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = full_text(" ".join(span.get("text", "") for span in spans), limit=600)
            if not text:
                continue
            sizes = [float(span.get("size", 0)) for span in spans if span.get("size")]
            raw_lines.append(
                {
                    "bbox": fitz.Rect(line["bbox"]),
                    "text": text,
                    "size": max(sizes) if sizes else fitz.Rect(line["bbox"]).height,
                }
            )

    merged: list[dict] = []
    for line in sorted(raw_lines, key=lambda item: (fitz.Rect(item["bbox"]).y0, fitz.Rect(item["bbox"]).x0)):
        rect = fitz.Rect(line["bbox"])
        if not merged:
            merged.append(line)
            continue
        prev = merged[-1]
        prev_rect = fitz.Rect(prev["bbox"])
        same_baseline = abs(rect.y0 - prev_rect.y0) <= max(2.0, float(line.get("size", 10)) * 0.25)
        vertical_overlap = max(0.0, min(rect.y1, prev_rect.y1) - max(rect.y0, prev_rect.y0))
        same_visual_line = same_baseline or vertical_overlap >= min(rect.height, prev_rect.height) * 0.65
        x_gap = rect.x0 - prev_rect.x1
        if same_visual_line and -4 <= x_gap <= 80:
            prev_rect.include_rect(rect)
            prev["bbox"] = prev_rect
            prev["text"] = full_text(f"{prev['text']} {line['text']}", limit=600)
            prev["size"] = max(float(prev.get("size", 0)), float(line.get("size", 0)))
        else:
            merged.append(line)
    return merged


def block_caption_kind(text: str) -> str | None:
    if TABLE_START_RE.search(text):
        return "table"
    if FIGURE_START_RE.search(text):
        return "figure"
    return None


def horizontal_rules(page: fitz.Page, y0: float, y1: float) -> list[fitz.Rect]:
    rules: list[fitz.Rect] = []
    min_width = page.rect.width * 0.22
    for drawing in page.get_drawings():
        rect = fitz.Rect(drawing.get("rect", fitz.Rect()))
        if rect.y0 < y0 or rect.y0 > y1:
            continue
        if rect.width >= min_width and rect.height <= 2:
            rules.append(rect)
    return sorted(rules, key=lambda rect: (rect.y0, rect.x0))


def horizontal_rule_between(page: fitz.Page, y0: float, y1: float) -> bool:
    if y1 < y0:
        return False
    return bool(horizontal_rules(page, y0 - 1, y1 + 1))


def looks_like_section_heading(text: str) -> bool:
    return bool(re.match(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z ]{2,}$", text.strip()))


def same_caption_line(prev: dict, current: dict, base_rect: fitz.Rect) -> bool:
    prev_rect = fitz.Rect(prev["bbox"])
    cur_rect = fitz.Rect(current["bbox"])
    gap = cur_rect.y0 - prev_rect.y1
    if gap < -1 or gap > max(8.0, float(prev.get("size", 10)) * 0.85):
        return False
    if looks_like_section_heading(current["text"]) or CAPTION_START_RE.search(current["text"]):
        return False
    # Captions normally keep a similar line width/indent. Avoid swallowing the
    # next body paragraph, which often starts near the page margin after a gap.
    horizontally_related = (
        abs(cur_rect.x0 - base_rect.x0) < 120
        or cur_rect.intersects(fitz.Rect(base_rect.x0 - 50, base_rect.y0, base_rect.x1 + 50, base_rect.y1 + 120))
    )
    return horizontally_related


def caption_anchors(page: fitz.Page, page_num: int) -> list[CaptionAnchor]:
    anchors: list[CaptionAnchor] = []
    lines = text_lines(page)
    for i, line in enumerate(lines):
        text = line["text"]
        kind = block_caption_kind(text)
        if not kind:
            continue
        rect = fitz.Rect(line["bbox"])
        caption_text = text
        prev = line
        for next_line in lines[i + 1 : i + 8]:
            next_rect = fitz.Rect(next_line["bbox"])
            if kind == "table" and horizontal_rule_between(page, fitz.Rect(prev["bbox"]).y1, next_rect.y0):
                break
            if not same_caption_line(prev, next_line, rect):
                break
            rect.include_rect(next_rect)
            caption_text = f"{caption_text} {next_line['text']}"
            prev = next_line
        anchors.append(CaptionAnchor(page=page_num, rect=rect, text=normalize_text(caption_text), kind=kind))
    return anchors


def neighboring_caption_y(captions: list[CaptionAnchor], anchor: CaptionAnchor, direction: str, page_height: float) -> float:
    ys: list[float] = []
    anchor_rect = fitz.Rect(anchor.rect)
    for other in captions:
        if other is anchor:
            continue
        rect = fitz.Rect(other.rect)
        if direction == "above" and rect.y1 <= anchor_rect.y0:
            ys.append(rect.y1)
        elif direction == "below" and rect.y0 >= anchor_rect.y1:
            ys.append(rect.y0)
    if direction == "above":
        return max(ys) if ys else page_height * 0.04
    return min(ys) if ys else page_height * 0.96


def next_section_y(page: fitz.Page, y: float) -> float | None:
    section_re = re.compile(r"^\d+(?:\.\d+)*\s+[A-Z][A-Za-z][A-Za-z \-/]+$")
    candidates: list[float] = []
    for line in text_lines(page):
        rect = fitz.Rect(line["bbox"])
        if rect.y0 <= y:
            continue
        if section_re.match(line["text"].strip()):
            candidates.append(rect.y0)
    return min(candidates) if candidates else None


def nearby_visual_union(page: fitz.Page, search: fitz.Rect) -> fitz.Rect | None:
    rects = [rect for rect in visual_rects(page) if rect.intersects(search)]
    if not rects:
        return None
    merged = fitz.Rect(rects[0])
    for rect in rects[1:]:
        merged.include_rect(rect)
    return merged


def table_body_rect(page: fitz.Page, cap: fitz.Rect, below_limit: float, include_source_caption: bool) -> fitz.Rect | None:
    page_rect = page.rect
    scan_bottom = min(below_limit - 4, cap.y1 + page_rect.height * 0.42)
    rules = horizontal_rules(page, max(page_rect.y0, cap.y1 - 3), scan_bottom)

    if rules:
        seed = rules[0]
        group = [
            rule
            for rule in rules
            if rule.y0 <= scan_bottom and rule.x1 >= seed.x0 - 24 and rule.x0 <= seed.x1 + 24
        ]
        if not group:
            return None

        raw = fitz.Rect(
            min(rule.x0 for rule in group),
            min(rule.y0 for rule in group),
            max(rule.x1 for rule in group),
            max(rule.y1 for rule in group),
        )
        padded = fitz.Rect(raw.x0 - 14, raw.y0 - 5, raw.x1 + 14, raw.y1 + 7)
        for line in text_lines(page):
            line_rect = fitz.Rect(line["bbox"])
            if line_rect.y1 < padded.y0 or line_rect.y0 > padded.y1:
                continue
            if line_rect.x1 < padded.x0 - 8 or line_rect.x0 > padded.x1 + 8:
                continue
            raw.include_rect(line_rect)
        if include_source_caption:
            raw.include_rect(cap)
        out = clamp_rect(raw, page_rect, margin=6)
        if not include_source_caption:
            out.y0 = max(out.y0, cap.y1 + 2)
        return out

    body_lines: list[dict] = []
    prev_rect: fitz.Rect | None = None
    for line in text_lines(page):
        rect = fitz.Rect(line["bbox"])
        if rect.y0 <= cap.y1 + 1:
            continue
        if rect.y0 >= scan_bottom:
            break
        text = line["text"].strip()
        if CAPTION_START_RE.search(text) or looks_like_section_heading(text):
            break
        gap = rect.y0 - prev_rect.y1 if prev_rect else 0
        looks_like_paragraph = rect.width > page_rect.width * 0.58 and len(text.split()) >= 9
        if body_lines and (gap > max(19, float(line.get("size", 10)) * 1.8) or looks_like_paragraph):
            break
        body_lines.append(line)
        prev_rect = rect

    if len(body_lines) < 2:
        return None

    raw = fitz.Rect(body_lines[0]["bbox"])
    for line in body_lines[1:]:
        raw.include_rect(fitz.Rect(line["bbox"]))
    if include_source_caption:
        raw.include_rect(cap)
    out = clamp_rect(raw, page_rect, margin=8)
    if not include_source_caption:
        out.y0 = max(out.y0, cap.y1 + 2)
    return out


def caption_based_rect(
    page: fitz.Page,
    captions: list[CaptionAnchor],
    anchor: CaptionAnchor,
    include_source_caption: bool,
) -> fitz.Rect | None:
    page_rect = page.rect
    cap = fitz.Rect(anchor.rect)
    left = max(page_rect.x0 + 14, cap.x0 - 40)
    right = min(page_rect.x1 - 14, cap.x1 + 40)

    if anchor.kind == "table":
        # Scientific table titles are usually above the table. Search downward
        # until the next caption or page section boundary.
        below_limit = neighboring_caption_y(captions, anchor, "below", page_rect.height)
        section_y = next_section_y(page, cap.y1)
        if section_y:
            below_limit = min(below_limit, section_y)
        table_rect = table_body_rect(page, cap, below_limit, include_source_caption)
        if table_rect:
            return table_rect
        raw_y0 = cap.y0 - 8 if include_source_caption else cap.y1 + 2
        raw = fitz.Rect(page_rect.x0 + 18, raw_y0, page_rect.x1 - 18, min(below_limit - 8, cap.y1 + page_rect.height * 0.28))
        return clamp_rect(raw, page_rect, margin=6)

    # Figure captions are usually below the visual. Search upward, bounded by
    # previous captions and the top page margin.
    above_limit = neighboring_caption_y(captions, anchor, "above", page_rect.height)
    search = fitz.Rect(page_rect.x0 + 18, max(above_limit + 8, cap.y0 - page_rect.height * 0.46), page_rect.x1 - 18, cap.y0 + 3)
    visuals = nearby_visual_union(page, search)
    if visuals:
        bottom = cap.y1 if include_source_caption else min(visuals.y1, cap.y0 - 2)
        raw = fitz.Rect(min(left, visuals.x0), visuals.y0, max(right, visuals.x1), bottom)
    else:
        bottom = cap.y1 if include_source_caption else cap.y0 - 2
        raw = fitz.Rect(page_rect.x0 + 18, search.y0, page_rect.x1 - 18, bottom)
    out = clamp_rect(raw, page_rect, margin=8)
    if not include_source_caption:
        out.y1 = min(out.y1, cap.y0 - 2)
    return out


def caption_score(anchor: CaptionAnchor, rect: fitz.Rect, page: fitz.Page) -> float:
    page_area = page.rect.width * page.rect.height
    score = 4.0 + min(rect_area(rect) / page_area, 0.5) * 5
    if anchor.kind == "figure":
        score += 1.0
    if GOOD_WORDS.search(anchor.text):
        score += 2.0
    if BAD_WORDS.search(page.get_text("text")[:2500]):
        score -= 2.0
    return score


def caption_based_candidates(
    doc: fitz.Document,
    max_pages: int,
    min_score: float,
    include_source_caption: bool,
) -> list[tuple[int, fitz.Rect, float, str]]:
    candidates: list[tuple[int, fitz.Rect, float, str]] = []
    for page_index in range(max_pages):
        page = doc[page_index]
        anchors = caption_anchors(page, page_index + 1)
        for anchor in anchors:
            rect = caption_based_rect(page, anchors, anchor, include_source_caption)
            if not rect or rect_area(rect) < rect_area(page.rect) * 0.015:
                continue
            score = caption_score(anchor, rect, page)
            if score >= min_score:
                candidates.append((page_index + 1, rect, score, anchor.text))
    return candidates


def score_rect(page: fitz.Page, rect: fitz.Rect, caption: str) -> float:
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    area = rect.width * rect.height
    aspect = rect.width / max(rect.height, 1)
    score = 0.0

    score += min(area / page_area, 0.65) * 8
    if 0.45 <= aspect <= 3.8:
        score += 1.0
    if caption:
        score += 3.0
    if GOOD_WORDS.search(caption):
        score += 2.0

    page_text = normalize_text(page.get_text("text")[:2500])
    if BAD_WORDS.search(page_text):
        score -= 2.5

    if rect.y0 < page_rect.height * 0.08:
        score -= 0.7
    if area < page_area * 0.025:
        score -= 1.2
    return score


def dedupe(candidates: Iterable[tuple[int, fitz.Rect, float, str]]) -> list[tuple[int, fitz.Rect, float, str]]:
    kept: list[tuple[int, fitz.Rect, float, str]] = []
    for page_num, rect, score, caption in sorted(candidates, key=lambda item: item[2], reverse=True):
        duplicate = False
        for kept_page, kept_rect, _kept_score, _kept_caption in kept:
            if kept_page != page_num:
                continue
            inter = rect & kept_rect
            if inter.is_empty:
                continue
            overlap = rect_area(inter) / max(min(rect_area(rect), rect_area(kept_rect)), 1)
            if overlap > 0.55:
                duplicate = True
                break
        if not duplicate:
            kept.append((page_num, rect, score, caption))
    return kept


def relative_for_markdown(path: Path, base_dir: Path | None) -> str:
    if base_dir:
        try:
            return path.resolve().relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def write_markdown(
    candidates: list[FigureCandidate],
    output_dir: Path,
    style: str,
    base_dir: Path | None,
    write_captions: bool,
) -> None:
    lines: list[str] = []
    for cand in candidates:
        img_path = relative_for_markdown(output_dir / cand.file, base_dir)
        caption = cand.caption or f"Figure candidate from page {cand.page}."
        if style == "obsidian":
            lines.append(f"![[{img_path}]]")
        else:
            alt = caption.replace("[", "(").replace("]", ")")[:90]
            lines.append(f"![{alt}]({img_path})")
        if write_captions:
            lines.append("")
            lines.append(f"> {caption}")
        lines.append("")
    (output_dir / "figures.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def reset_managed_outputs(output_dir: Path) -> None:
    """Remove outputs created by a previous run without touching user files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.is_file() and (
            MANAGED_FIGURE_RE.match(path.name) or path.name in {"figures.json", "figures.md"}
        ):
            path.unlink()
    raw_dir = output_dir / "_pdffigures2"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)


def validate_backend_requirements(backend: str) -> None:
    """Fail before replacing previous outputs when no requested backend exists."""

    pdffigures2 = shutil.which("pdffigures2") or shutil.which("pdffigures2.jar")
    pdftotext = shutil.which("pdftotext")
    pdftoppm = shutil.which("pdftoppm")

    if backend == "pymupdf" and fitz is None:
        raise RuntimeError(
            "The PyMuPDF backend was requested, but PyMuPDF is not installed. "
            "Install the repository requirements or choose --backend auto/poppler."
        )
    if backend == "pdffigures2" and not pdffigures2:
        raise RuntimeError(
            "The pdffigures2 backend was requested, but no pdffigures2 CLI was found on PATH."
        )
    if backend == "poppler" and not (pdftotext and pdftoppm):
        raise RuntimeError(
            "The Poppler backend requires both pdftotext and pdftoppm on PATH."
        )
    if backend == "auto" and not (pdffigures2 or fitz is not None or (pdftotext and pdftoppm)):
        raise RuntimeError(
            "No extraction backend is available. Install PyMuPDF, pdffigures2, "
            "or both pdftotext and pdftoppm."
        )


def extract(args: argparse.Namespace) -> list[FigureCandidate]:
    if args.backend in ("auto", "pdffigures2"):
        if args.backend == "pdffigures2" and not (
            shutil.which("pdffigures2") or shutil.which("pdffigures2.jar")
        ):
            raise RuntimeError(
                "The pdffigures2 backend was requested, but no pdffigures2 CLI was found on PATH."
            )
        candidates = extract_with_pdffigures2(args)
        if candidates or args.backend == "pdffigures2":
            return candidates

    if fitz is None:
        if args.backend == "pymupdf":
            raise RuntimeError(
                "The PyMuPDF backend was requested, but PyMuPDF is not installed. "
                "Install the repository requirements or choose --backend auto/poppler."
            )
        return extract_with_poppler(args)

    pdf = Path(args.pdf)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    max_pages = min(len(doc), args.max_pages or len(doc))
    raw_candidates = caption_based_candidates(
        doc,
        max_pages=max_pages,
        min_score=args.min_score,
        include_source_caption=args.include_source_caption,
    )

    if len(raw_candidates) < max(2, min(args.max_figures, 3)):
        for page_index in range(max_pages):
            page = doc[page_index]
            for rect in visual_rects(page):
                rect = clamp_rect(rect, page.rect, margin=args.margin)
                caption = find_caption(page, rect)
                score = score_rect(page, rect, caption)
                if score >= args.min_score:
                    raw_candidates.append((page_index + 1, rect, score, caption))

    selected = dedupe(raw_candidates)[: args.max_figures]
    selected = sorted(selected, key=lambda item: (item[0], item[1].y0))

    figures: list[FigureCandidate] = []
    for idx, (page_num, rect, score, caption) in enumerate(selected, start=1):
        page = doc[page_num - 1]
        zoom = args.dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
        filename = f"fig-{idx:02d}.png"
        pix.save(output_dir / filename)
        figures.append(
            FigureCandidate(
                index=idx,
                page=page_num,
                bbox=tuple(round(v, 2) for v in (rect.x0, rect.y0, rect.x1, rect.y1)),
                score=round(score, 3),
                caption=caption,
                file=filename,
                width=pix.width,
                height=pix.height,
            )
        )

    (output_dir / "figures.json").write_text(
        json.dumps([asdict(fig) for fig in figures], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    base_dir = Path(args.markdown_base) if args.markdown_base else None
    write_markdown(figures, output_dir, args.markdown_style, base_dir, args.write_captions)
    return figures


def extract_with_pdffigures2(args: argparse.Namespace) -> list[FigureCandidate]:
    """Use pdffigures2 JSON output when the command is installed."""

    command = shutil.which("pdffigures2") or shutil.which("pdffigures2.jar")
    if not command:
        return []

    pdf = Path(args.pdf)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "_pdffigures2"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        if command.endswith(".jar"):
            cmd = ["java", "-jar", command, "-m", str(raw_dir), str(pdf)]
        else:
            cmd = [command, "-m", str(raw_dir), str(pdf)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    except Exception:
        if args.backend == "pdffigures2":
            raise
        return []

    images = sorted(raw_dir.glob("*.png")) + sorted(raw_dir.glob("*.jpg"))
    json_files = sorted(raw_dir.glob("*.json"))
    metadata = {}
    for path in json_files:
        try:
            metadata[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    figures: list[FigureCandidate] = []
    for idx, image_path in enumerate(images[: args.max_figures], start=1):
        target = output_dir / f"fig-{idx:02d}{image_path.suffix.lower()}"
        shutil.copyfile(image_path, target)
        caption = ""
        meta = metadata.get(image_path.stem)
        if isinstance(meta, dict):
            caption = normalize_text(str(meta.get("caption", "")))
        figures.append(
            FigureCandidate(
                index=idx,
                page=int(meta.get("page", 0)) + 1 if isinstance(meta, dict) and str(meta.get("page", "")).isdigit() else 0,
                bbox=(0, 0, 0, 0),
                score=10.0,
                caption=caption or f"Figure extracted by pdffigures2: {image_path.name}",
                file=target.name,
                width=0,
                height=0,
            )
        )

    if not figures:
        return []
    (output_dir / "figures.json").write_text(
        json.dumps([asdict(fig) for fig in figures], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    base_dir = Path(args.markdown_base) if args.markdown_base else None
    write_markdown(figures, output_dir, args.markdown_style, base_dir, args.write_captions)
    return figures


def extract_with_poppler(args: argparse.Namespace) -> list[FigureCandidate]:
    """Fallback when PyMuPDF is unavailable.

    Poppler cannot crop semantic figure regions by itself, so this path renders
    high-signal pages selected by captions and method keywords.
    """

    pdf = Path(args.pdf)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pdftotext = shutil.which("pdftotext")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftotext or not pdftoppm:
        raise SystemExit(
            "Neither PyMuPDF nor Poppler tools are available. Install PyMuPDF "
            "or ensure pdftotext/pdftoppm are on PATH."
        )

    text_proc = subprocess.run(
        [pdftotext, "-layout", str(pdf), "-"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pages = text_proc.stdout.split("\f")
    scored: list[tuple[float, int, str]] = []
    for idx, text in enumerate(pages, start=1):
        if args.max_pages and idx > args.max_pages:
            break
        normalized = normalize_text(text)
        if not normalized or BAD_WORDS.search(normalized[:1200]):
            continue
        captions = list(CAPTION_RE.finditer(normalized))
        if not captions:
            continue
        score = float(len(captions)) * 2.5
        if GOOD_WORDS.search(normalized):
            score += 2.0
        scored.append((score, idx, normalized))

    selected = sorted(scored, reverse=True)[: args.max_figures]
    selected = sorted(selected, key=lambda item: item[1])

    figures: list[FigureCandidate] = []
    for out_idx, (score, page_num, text) in enumerate(selected, start=1):
        prefix = output_dir / f"fig-{out_idx:02d}"
        subprocess.run(
            [
                pdftoppm,
                "-f",
                str(page_num),
                "-l",
                str(page_num),
                "-singlefile",
                "-png",
                "-r",
                str(args.dpi),
                str(pdf),
                str(prefix),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        file_path = prefix.with_suffix(".png")
        if Image is not None and ImageChops is not None:
            trim_rendered_page(file_path)
        caption_match = CAPTION_RE.search(text)
        caption = normalize_text(caption_match.group(0)) if caption_match else ""
        figures.append(
            FigureCandidate(
                index=out_idx,
                page=page_num,
                bbox=(0, 0, 0, 0),
                score=round(score, 3),
                caption=caption or f"Rendered high-signal page {page_num} because PyMuPDF was unavailable.",
                file=file_path.name,
                width=0,
                height=0,
            )
        )

    (output_dir / "figures.json").write_text(
        json.dumps([asdict(fig) for fig in figures], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    base_dir = Path(args.markdown_base) if args.markdown_base else None
    write_markdown(figures, output_dir, args.markdown_style, base_dir, args.write_captions)
    return figures


def trim_rendered_page(path: Path) -> None:
    """Trim white margins from a rendered PDF page while preserving captions."""

    image = Image.open(path).convert("RGB")
    width, height = image.size
    # Drop only the outer page chrome. Keep source captions/titles, which may be
    # below figures or above tables.
    top = int(height * 0.045)
    bottom = int(height * 0.985)
    working = image.crop((0, top, width, bottom))
    bg = Image.new("RGB", working.size, (255, 255, 255))
    diff = ImageChops.difference(working, bg).convert("L")
    bbox = diff.point(lambda p: 255 if p > 18 else 0).getbbox()
    if not bbox:
        return
    left, upper, right, lower = bbox
    pad_x = 26
    pad_y = 60
    left = max(0, left - pad_x)
    upper = max(0, upper - pad_y)
    right = min(working.size[0], right + pad_x)
    lower = min(working.size[1], lower + pad_y)
    cropped = working.crop((left, upper, right, lower))
    # Avoid no-op saves, but allow generous crops so captions/table titles survive.
    if cropped.size[0] * cropped.size[1] < width * height * 0.985:
        cropped.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Input research paper PDF.")
    parser.add_argument("--output-dir", required=True, help="Directory for PNGs and metadata.")
    parser.add_argument("--max-figures", type=int, default=6, help="Maximum figures to save.")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit pages scanned; 0 scans all pages.")
    parser.add_argument("--dpi", type=int, default=180, help="Render DPI for cropped figures.")
    parser.add_argument("--margin", type=float, default=8, help="Crop margin in PDF points.")
    parser.add_argument("--min-score", type=float, default=1.8, help="Minimum candidate score.")
    parser.add_argument(
        "--backend",
        choices=["auto", "pymupdf", "pdffigures2", "poppler"],
        default="auto",
        help="Extraction backend. auto tries pdffigures2, then PyMuPDF, then Poppler.",
    )
    parser.add_argument(
        "--markdown-style",
        choices=["obsidian", "markdown"],
        default="obsidian",
        help="Image link style for figures.md.",
    )
    parser.add_argument(
        "--markdown-base",
        default="",
        help="Base directory used to make figure links relative, usually the note directory.",
    )
    parser.add_argument(
        "--write-captions",
        action="store_true",
        help="Write source captions as blockquotes under image links in figures.md. Default is image-only.",
    )
    parser.add_argument(
        "--include-source-caption",
        action="store_true",
        help="Keep the paper's original Figure/Table caption inside the crop. Default crops only the visual/table body.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf = Path(args.pdf)
    if not pdf.is_file():
        raise SystemExit(f"Input PDF does not exist or is not a file: {pdf}")
    if args.max_figures < 1:
        raise SystemExit("--max-figures must be at least 1")
    if args.max_pages < 0:
        raise SystemExit("--max-pages cannot be negative")
    if args.dpi < 36:
        raise SystemExit("--dpi must be at least 36")
    validate_backend_requirements(args.backend)
    reset_managed_outputs(Path(args.output_dir))
    if args.backend == "poppler":
        figures = extract_with_poppler(args)
        print(f"Saved {len(figures)} figure(s) to {Path(args.output_dir).resolve()}")
        print("Used Poppler fallback: rendered selected pages instead of cropped figure regions.")
        return 0
    figures = extract(args)
    print(f"Saved {len(figures)} figure(s) to {Path(args.output_dir).resolve()}")
    if not figures:
        print("No strong figure candidates found. Try lowering --min-score or using a dedicated parser.")
    elif fitz is None:
        print("Used Poppler fallback: rendered selected pages instead of cropped figure regions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
