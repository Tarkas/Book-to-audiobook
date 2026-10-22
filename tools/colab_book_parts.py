"""Split an ebook into chapter-aware parts sized for one cloud session.

The Colab notebook runs one part per ``app.py --headless`` invocation, so a
free Colab runtime that dies after a couple of hours never loses more than the
part it was working on.  Each part is a normal ebook file, which keeps the
conversion/resume logic of the main application untouched.

Usage:
    python tools/colab_book_parts.py plan \
        --ebook book.epub --out-dir parts \
        --part-minutes 120 --chars-per-minute 900

The command writes ``manifest.json`` plus ``part-001.epub`` (or ``.md`` for
PDF/TXT/Markdown sources).  Re-running with the same arguments reuses an
existing manifest, so the notebook can call it on every start.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

DEFAULT_CHARS_PER_MINUTE = 900
MANIFEST_VERSION = 1

EPUB_EXT = ".epub"
TEXT_EXT = (".md", ".markdown", ".txt")
PDF_EXT = ".pdf"

BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre",
    "table", "figure", "figcaption", "dl", "dt", "dd", "address", "hr",
}
CONTAINER_TAGS = {"div", "section", "article", "main", "aside", "header",
                  "footer", "body", "html", "ul", "ol", "tbody", "thead",
                  "tr", "td", "th"}
DROP_TAGS = ["script", "style", "nav", "noscript", "svg", "img", "picture",
             "source", "audio", "video", "iframe", "object", "canvas", "map",
             "button", "form", "input", "select", "textarea"]


class SplitError(RuntimeError):
    pass


def sha1_file(path):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def visible_len(text):
    return len(re.sub(r"\s+", " ", text or "").strip())


def _sentence_split(text, target):
    """Split oversized plain text on sentence boundaries."""
    sentences = re.split(r"(?<=[.!?…。！？])\s+", text)
    chunks = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > target:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
        while len(current) > target * 1.5:
            cut = current.rfind(" ", 0, target)
            cut = cut if cut > target * 0.5 else target
            chunks.append(current[:cut].strip())
            current = current[cut:].strip()
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ---------------------------------------------------------------------------
# Markdown / plain text
# ---------------------------------------------------------------------------

def _markdown_sections(text):
    """Split markdown into sections that start at a heading."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = []
    current = []
    for line in lines:
        if re.match(r"^#{1,6}\s+\S", line) and any(l.strip() for l in current):
            section = "\n".join(current).strip()
            if section:
                sections.append(section)
            current = [line]
        else:
            current.append(line)
    section = "\n".join(current).strip()
    if section:
        sections.append(section)
    return sections


def _split_markdown_body(text, target):
    """Split a section into <=target chunks, keeping paragraphs intact."""
    paragraphs = re.split(r"\n\s*\n", text)
    units = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        units.extend(_sentence_split(paragraph, target) if len(paragraph) > target
                     else [paragraph])

    chunks = []
    current = []
    current_len = 0
    for unit in units:
        addition = len(unit) + (2 if current else 0)
        if current and current_len + addition > target:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(unit)
        current_len += addition
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _finalize_markdown_groups(groups, target):
    """Drop page-number noise and fold tiny leftovers into a neighbour."""
    cleaned = []
    for group in groups:
        text = group.strip()
        if not text:
            continue
        if not re.search(r"[^\W\d_]", text, re.UNICODE) and visible_len(text) < 200:
            continue
        cleaned.append(text)
    if not cleaned:
        raise SplitError("The document contains no readable text.")

    merged = []
    for group in cleaned:
        if merged and visible_len(group) < max(40, int(target * 0.15)):
            merged[-1] = f"{merged[-1].rstrip()}\n\n{group.strip()}"
        else:
            merged.append(group)
    return merged


def _finalize_unit_groups(groups, target):
    cleaned = []
    for group in groups:
        blocks = [block for unit in group for block in unit]
        size = sum(visible_len(text) for text, _ in blocks)
        if not size:
            continue
        has_letters = any(re.search(r"[^\W\d_]", text, re.UNICODE)
                          for text, _ in blocks)
        if not has_letters and size < 200:
            continue
        cleaned.append(group)
    if not cleaned:
        raise SplitError("The document contains no readable text.")

    merged = []
    for group in cleaned:
        size = sum(visible_len(text) for unit in group for text, _ in unit)
        if merged and size < max(40, int(target * 0.15)):
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def plan_markdown(text, title, target_chars):
    sections = _markdown_sections(text)
    if not sections:
        raise SplitError("The document contains no readable text.")

    groups = []
    current = []
    current_len = 0
    for section in sections:
        if len(section) > target_chars:
            if current:
                groups.append("\n\n".join(current))
                current = []
                current_len = 0
            groups.extend(_split_markdown_body(section, target_chars))
            continue
        addition = len(section) + (2 if current else 0)
        if current and current_len + addition > target_chars:
            groups.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(section)
        current_len += addition
    if current:
        groups.append("\n\n".join(current))

    groups = _finalize_markdown_groups(groups, target_chars)
    total = len(groups)
    parts = []
    for index, body in enumerate(groups, start=1):
        part_title = f"{title} - Part {index:02d} of {total:02d}"
        content = f"# {part_title}\n\n{body.strip()}\n"
        parts.append((part_title, content, visible_len(body)))
    return parts


def plan_text_file(path, title, target_chars):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read()
    return title, plan_markdown(text, title, target_chars)


def plan_pdf(path, title, target_chars):
    try:
        import fitz
        import pymupdf4llm
    except Exception as exc:  # pragma: no cover - dependency message
        raise SplitError(f"PDF support needs PyMuPDF and pymupdf4llm: {exc}") from exc

    if not title:
        try:
            title = (fitz.open(path).metadata or {}).get("title") or ""
        except Exception:
            title = ""
    title = title or re.sub(r"^translated_", "", os.path.splitext(os.path.basename(path))[0]).replace("_", " ").strip() or "Book"

    markdown_text = pymupdf4llm.to_markdown(path)
    markdown_text = re.sub(r"<!--\s*Start of picture text\s*-->\s*", "", markdown_text)
    markdown_text = re.sub(r"<!--\s*End of picture text\s*-->\s*", "", markdown_text)
    markdown_text = re.sub(r"^\s*--+\s*Start of picture text\s*--*\s*$", "", markdown_text, flags=re.M)
    markdown_text = re.sub(r"^\s*--+\s*End of picture text\s*--*\s*$", "", markdown_text, flags=re.M)
    markdown_text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"\1", markdown_text)
    markdown_text = re.sub(r"(?<!_)_(?!_)(.*?)_(?!_)", r"\1", markdown_text)
    return title, plan_markdown(markdown_text, title, target_chars)


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------

def _clean_body(raw):
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(DROP_TAGS):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for anchor in soup.find_all("a"):
        anchor.unwrap()

    body = soup.body or soup
    blocks = []

    def add_text(text):
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            blocks.append((text, f"<p>{html.escape(text)}</p>"))

    def walk(node):
        for child in node.children:
            if isinstance(child, NavigableString):
                add_text(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = (child.name or "").lower()
            if name in DROP_TAGS:
                continue
            nested_block = any(
                isinstance(desc, Tag) and (desc.name or "").lower() in BLOCK_TAGS
                for desc in child.find_all(recursive=True)
            )
            if name in CONTAINER_TAGS and nested_block:
                walk(child)
            else:
                text = child.get_text(" ", strip=True)
                if text or name in ("hr",):
                    blocks.append((text, str(child)))

    walk(body)
    return blocks


def _split_blocks(blocks, target):
    """Split blocks into chunks near ``target`` characters."""
    chunks = []
    current = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if current:
            chunks.append(current)
            current = []
            current_len = 0

    for text, markup in blocks:
        size = visible_len(text)
        if size > target:
            flush()
            plain = text
            for piece in _sentence_split(plain, target):
                chunks.append([(piece, f"<p>{html.escape(piece)}</p>")])
            continue
        if current and current_len + size > target:
            flush()
        current.append((text, markup))
        current_len += size + 1
    flush()
    return chunks


def _epub_metadata(book, fallback_title):
    def first(namespace, name):
        data = book.get_metadata(namespace, name)
        if data and data[0] and data[0][0]:
            return str(data[0][0]).strip()
        return ""

    title = first("DC", "title")
    if not title or title.lower() in ("index", "untitled", "colab"):
        title = fallback_title
    language = first("DC", "language") or "en"
    creator = first("DC", "creator") or first("DC", "author")
    return title, language, creator


def plan_epub(path, title_override, target_chars):
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    try:
        book = epub.read_epub(path, {"ignore_ncx": True})
    except Exception as exc:
        raise SplitError(f"Cannot read EPUB {path}: {exc}") from exc

    source_title, language, creator = _epub_metadata(
        book,
        title_override or re.sub(r"^translated_", "", os.path.splitext(os.path.basename(path))[0]).replace("_", " ").strip() or "Book",
    )
    title = title_override or source_title
    spine_ids = [entry[0] for entry in book.spine]
    docs = [item for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
            if item.id in spine_ids]
    if not docs:
        docs = [item for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)]
    if not docs:
        raise SplitError("The EPUB has no document items.")

    cover = None
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        cover = (os.path.basename(item.get_name()) or "cover.jpg", item.get_content())
        break
    if cover is None:
        for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
            if "cover" in item.get_name().lower():
                cover = (os.path.basename(item.get_name()) or "cover.jpg", item.get_content())
                break

    sections = []
    for doc in docs:
        try:
            raw = doc.get_body_content().decode("utf-8", "replace")
        except Exception:
            raw = doc.get_content().decode("utf-8", "replace")
        soup = BeautifulSoup(raw, "html.parser")
        body = soup.body or soup
        if not body.get_text(" ", strip=True):
            continue
        blocks = _clean_body(raw)
        if blocks:
            sections.append(blocks)
    if not sections:
        raise SplitError("The EPUB contains no readable text.")

    units = []
    for section in sections:
        section_len = sum(visible_len(text) for text, _ in section)
        if section_len > target_chars:
            units.extend(_split_blocks(section, target_chars))
        else:
            units.append(section)

    part_groups = []
    current = []
    current_len = 0
    for unit in units:
        unit_len = sum(visible_len(text) for text, _ in unit)
        if current and current_len + unit_len > target_chars:
            part_groups.append(current)
            current = []
            current_len = 0
        current.append(unit)
        current_len += unit_len
    if current:
        part_groups.append(current)

    part_groups = _finalize_unit_groups(part_groups, target_chars)
    total = len(part_groups)
    parts = []
    for index, unit_group in enumerate(part_groups, start=1):
        part_title = f"{title} - Part {index:02d} of {total:02d}"
        part_book = epub.EpubBook()
        identifier = hashlib.sha1(f"{title}|{index}|{total}".encode("utf-8")).hexdigest()
        part_book.set_identifier(f"urn:uuid:{identifier}")
        part_book.set_title(part_title)
        part_book.set_language(language or "en")
        if creator:
            part_book.add_author(creator)
        if cover:
            cover_name, cover_data = cover
            try:
                part_book.set_cover(cover_name, cover_data, create_page=False)
            except Exception:
                pass

        chapters = []
        for sequence, blocks in enumerate(unit_group, start=1):
            first_text = next((text for text, _ in blocks if text), "")
            chapter = epub.EpubHtml(
                uid=f"part{index:03d}_{sequence:03d}",
                file_name=f"part{index:03d}_{sequence:03d}.xhtml",
                media_type="application/xhtml+xml",
                title=(first_text[:80] if first_text else part_title),
            )
            chapter.content = "<div>" + "".join(markup for _, markup in blocks) + "</div>"
            part_book.add_item(chapter)
            chapters.append(chapter)

        part_book.toc = tuple(chapters)
        part_book.add_item(epub.EpubNcx())
        part_book.add_item(epub.EpubNav())
        part_book.spine = chapters
        chars = sum(visible_len(text) for unit in unit_group for text, _ in unit)
        parts.append((part_title, part_book, chars))
    return title, language, parts


# ---------------------------------------------------------------------------
# Planning entry point
# ---------------------------------------------------------------------------

def _calibre_epub(path, tmpdir):
    converter = shutil.which("ebook-convert")
    if not converter:
        raise SplitError("ebook-convert was not found; install Calibre or "
                         "convert the book to EPUB/PDF/Markdown first.")
    out = os.path.join(tmpdir, os.path.splitext(os.path.basename(path))[0] + ".epub")
    result = subprocess.run(
        [converter, path, out, "--input-encoding=utf-8",
         "--output-profile=generic_eink", "--epub-version=3",
         "--chapter-mark=pagebreak", "--disable-font-rescaling"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "QT_OPENGL": "software", "QT_QPA_PLATFORM": "offscreen"},
    )
    if result.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) == 0:
        raise SplitError(f"Calibre could not convert {path}:\n{result.stderr[-2000:]}")
    return out


def build_plan(ebook, out_dir, part_minutes, chars_per_minute, title=None,
               language=None, force=False):
    if not os.path.isfile(ebook):
        raise SplitError(f"Ebook not found: {ebook}")
    if part_minutes <= 0 or chars_per_minute <= 0:
        raise SplitError("part-minutes and chars-per-minute must be positive.")

    target_chars = int(part_minutes * chars_per_minute)
    ext = os.path.splitext(ebook)[1].lower()
    stem = os.path.splitext(os.path.basename(ebook))[0]
    fallback_title = title or re.sub(r"^translated_", "", stem).replace("_", " ").strip() or "Book"

    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.json")
    source_hash = sha1_file(ebook)

    if os.path.isfile(manifest_path) and not force:
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            split = existing.get("split", {})
            if (existing.get("source_sha1") == source_hash
                    and (title is None or existing.get("title") == title)
                    and int(split.get("target_chars", -1)) == target_chars
                    and all(os.path.isfile(os.path.join(out_dir, p["file"]))
                            for p in existing.get("parts", []))):
                print(f"Reusing existing plan: {manifest_path}")
                return existing
        except Exception:
            pass

    for name in os.listdir(out_dir):
        if name.startswith("part-") and os.path.isfile(os.path.join(out_dir, name)):
            os.remove(os.path.join(out_dir, name))

    with tempfile.TemporaryDirectory() as tmpdir:
        if ext == EPUB_EXT:
            resolved_title, detected_lang, raw_parts = plan_epub(ebook, title, target_chars)
            out_ext = EPUB_EXT
        elif ext == PDF_EXT:
            resolved_title, raw_parts = plan_pdf(ebook, title, target_chars)
            detected_lang = language or "en"
            out_ext = ".md"
        elif ext in TEXT_EXT:
            resolved_title, raw_parts = plan_text_file(ebook, fallback_title, target_chars)
            detected_lang = language or "en"
            out_ext = ".md"
        else:
            converted = _calibre_epub(ebook, tmpdir)
            resolved_title, detected_lang, raw_parts = plan_epub(converted, title, target_chars)
            out_ext = EPUB_EXT

        if not raw_parts:
            raise SplitError("Splitting produced no parts.")

        parts = []
        for index, item in enumerate(raw_parts, start=1):
            part_title = item[0]
            file_name = f"part-{index:03d}{out_ext}"
            file_path = os.path.join(out_dir, file_name)
            if out_ext == EPUB_EXT:
                from ebooklib import epub as epub_mod
                part_book = item[1]
                epub_mod.write_epub(file_path, part_book)
                chars = item[2]
            else:
                _, content, chars = item
                with open(file_path, "w", encoding="utf-8") as handle:
                    handle.write(content)
            parts.append({
                "index": index,
                "file": file_name,
                "title": part_title,
                "chars": chars,
                "estimated_minutes": round(chars / chars_per_minute, 1),
                "sha1": sha1_file(file_path),
                "size": os.path.getsize(file_path),
            })

    manifest = {
        "version": MANIFEST_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": os.path.abspath(ebook),
        "source_name": os.path.basename(ebook),
        "source_sha1": source_hash,
        "title": resolved_title,
        "language": language or detected_lang,
        "split": {
            "part_minutes": part_minutes,
            "chars_per_minute": chars_per_minute,
            "target_chars": target_chars,
            "format": out_ext.lstrip("."),
        },
        "total_chars": sum(p["chars"] for p in parts),
        "estimated_total_minutes": round(sum(p["chars"] for p in parts) / chars_per_minute, 1),
        "parts": parts,
    }
    temporary = manifest_path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, manifest_path)

    print(f"Plan written: {manifest_path}")
    print(f"  {manifest['title']}: {len(parts)} part(s), "
          f"~{manifest['estimated_total_minutes']} min of audio")
    for part in parts:
        print(f"  {part['file']}: {part['chars']} chars, "
              f"~{part['estimated_minutes']} min")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="split an ebook into parts")
    plan.add_argument("--ebook", required=True)
    plan.add_argument("--out-dir", required=True)
    plan.add_argument("--part-minutes", type=float, default=120.0)
    plan.add_argument("--chars-per-minute", type=float,
                      default=DEFAULT_CHARS_PER_MINUTE)
    plan.add_argument("--title", default=None)
    plan.add_argument("--language", default=None)
    plan.add_argument("--force", action="store_true",
                      help="rebuild the parts even if a matching manifest exists")
    args = parser.parse_args(argv)

    try:
        build_plan(os.path.abspath(args.ebook), os.path.abspath(args.out_dir),
                   args.part_minutes, args.chars_per_minute,
                   args.title, args.language, args.force)
    except SplitError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
