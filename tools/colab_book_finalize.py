"""Merge finished Colab book parts into one audiobook and translated book."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

TEXT_EXTS = {".md", ".markdown", ".txt"}
TRANSLATED_EXTS = {".epub", *TEXT_EXTS}
AUDIO_EXTS = {".m4b", ".m4a", ".mp4", ".mp3", ".flac", ".wav",
              ".ogg", ".oga", ".opus", ".aac", ".wma"}

REENCODE_ARGS = {
    "m4b": ["-c:a", "aac", "-b:a", "128k"],
    "m4a": ["-c:a", "aac", "-b:a", "128k"],
    "mp4": ["-c:a", "aac", "-b:a", "128k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"],
    "flac": ["-c:a", "flac"],
    "wav": ["-c:a", "pcm_s16le"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
    "oga": ["-c:a", "libvorbis", "-q:a", "5"],
    "opus": ["-c:a", "libopus", "-b:a", "96k"],
}


class FinalizeError(RuntimeError):
    pass


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _files(folder):
    result = []
    for dirpath, _, names in os.walk(folder):
        for name in names:
            result.append(os.path.join(dirpath, name))
    return result


def _safe_name(value):
    value = re.sub(r'[\x00-\x1f<>:"/\\|?*]', " ", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:150].rstrip(" .") or "Book"


def _tool(name):
    path = shutil.which(name)
    if not path:
        raise FinalizeError(f"{name} was not found on PATH.")
    return path


def _run(cmd):
    result = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode, result.stdout or ""


def _probe(path):
    ffprobe = _tool("ffprobe")
    rc, output = _run([
        ffprobe, "-v", "error", "-print_format", "json",
        "-show_format", "-show_chapters", path,
    ])
    if rc != 0:
        raise FinalizeError(f"ffprobe could not read {path}:\n{output[-2000:]}")
    try:
        data = json.loads(output)
    except Exception as exc:
        raise FinalizeError(f"ffprobe returned invalid JSON for {path}: {exc}") from exc

    duration = 0.0
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0

    chapters = []
    for chapter in data.get("chapters") or []:
        try:
            start = max(0.0, float(chapter.get("start_time") or 0))
            end = float(chapter.get("end_time") or 0)
        except (TypeError, ValueError):
            continue
        tags = chapter.get("tags") or {}
        title = str(tags.get("title") or "").strip()
        chapters.append({"start": start, "end": end, "title": title})
    if duration <= 0 and chapters:
        duration = max(chapter["end"] for chapter in chapters)
    if duration <= 0:
        raise FinalizeError(f"Could not determine the duration of {path}.")
    for chapter in chapters:
        if chapter["end"] <= chapter["start"] or chapter["end"] > duration + 1:
            chapter["end"] = duration
    tags = (data.get("format") or {}).get("tags") or {}
    return {"duration": duration, "chapters": chapters, "tags": tags}


def _meta_value(value):
    return (str(value or "").replace("\\", "\\\\")
            .replace("\n", " ").replace("\r", " ")
            .replace("=", "\\=").replace(";", "\\;").replace("#", "\\#"))


def _chapter_metadata(parts, title, path):
    lines = [";FFMETADATA1", f"title={_meta_value(title)}"]
    artist = ""
    offset = 0.0
    total = 0.0
    chapter_number = 0
    for part in parts:
        for number, audio_path in enumerate(part["audio"], start=1):
            info = _probe(audio_path)
            if not artist:
                artist = str(info["tags"].get("artist") or info["tags"].get("album_artist") or "")
            chapters = info["chapters"]
            if not chapters:
                fallback = part["title"] or f"Part {part['index']:02d}"
                if len(part["audio"]) > 1:
                    fallback = f"{fallback} ({number})"
                chapters = [{"start": 0.0, "end": info["duration"], "title": fallback}]
            for chapter in chapters:
                start = offset + chapter["start"]
                end = offset + chapter["end"]
                if end <= start:
                    continue
                chapter_number += 1
                start_ms = max(0, int(round(start * 1000)))
                end_ms = max(start_ms + 1, int(round(end * 1000)))
                chapter_title = chapter["title"] or f"Chapter {chapter_number}"
                lines += [
                    "[CHAPTER]",
                    "TIMEBASE=1/1000",
                    f"START={start_ms}",
                    f"END={end_ms}",
                    f"title={_meta_value(chapter_title)}",
                ]
            offset += info["duration"]
            total = offset
    if not any(line == "[CHAPTER]" for line in lines):
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            "START=0",
            f"END={max(1, int(round(total * 1000)))}",
            f"title={_meta_value(title)}",
        ]
    if artist:
        lines.insert(2, f"artist={_meta_value(artist)}")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return total


def _link_for_concat(source, directory, index):
    suffix = os.path.splitext(source)[1].lower() or ".audio"
    target = os.path.join(directory, f"part{index:04d}{suffix}")
    try:
        os.link(source, target)
        return target
    except OSError:
        pass
    try:
        os.symlink(os.path.abspath(source), target)
        return target
    except OSError:
        pass
    shutil.copy2(source, target)
    return target


def _merge_audio(parts, output_path, title, audio_format):
    ffmpeg = _tool("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="colab-audio-") as temp_dir:
        links = []
        for part in parts:
            for audio_path in part["audio"]:
                links.append(_link_for_concat(audio_path, temp_dir, len(links)))
        concat_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_path, "w", encoding="utf-8") as handle:
            for link in links:
                safe = os.path.abspath(link).replace("\\", "/")
                handle.write(f"file '{safe}'\n")
        metadata_path = os.path.join(temp_dir, "chapters.txt")
        expected = _chapter_metadata(parts, title, metadata_path)
        temporary = os.path.join(temp_dir, f"final.{audio_format}")
        common = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_path,
            "-i", metadata_path, "-map", "0:a:0",
            "-map_metadata", "1", "-map_chapters", "1", "-vn",
        ]
        tail = []
        if audio_format in ("m4b", "m4a", "mp4"):
            tail += ["-movflags", "+faststart"]
        elif audio_format == "mp3":
            tail += ["-id3v2_version", "3"]
        rc, output = _run(common + ["-c:a", "copy"] + tail + [temporary])
        if rc != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
            codec = REENCODE_ARGS.get(audio_format)
            if not codec:
                raise FinalizeError(
                    "The part audio streams cannot be joined without re-encoding,\n"
                    f"and no fallback encoder is known for .{audio_format}:\n{output[-2000:]}"
                )
            if os.path.exists(temporary):
                os.remove(temporary)
            rc, output = _run(common + codec + tail + [temporary])
        if rc != 0 or not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
            raise FinalizeError(f"ffmpeg could not merge the audio:\n{output[-3000:]}")
        try:
            merged = _probe(temporary)
        except FinalizeError:
            merged = None
        if merged and merged["duration"] < expected * 0.98:
            raise FinalizeError(
                f"Merged audio is shorter than expected ({merged['duration']:.1f}s "
                f"instead of {expected:.1f}s)."
            )
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_output = output_path + ".part"
        shutil.copy2(temporary, temp_output)
        os.replace(temp_output, output_path)
    return expected


def _doc_content(raw, fallback_title):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    title = ""
    if soup.title:
        title = soup.title.get_text(" ", strip=True)
    if not title:
        heading = soup.find(["h1", "h2", "h3", "h4", "h5", "h6"])
        if heading:
            title = heading.get_text(" ", strip=True)
    title = title or fallback_title
    body = soup.body
    content = body.decode_contents() if body else raw
    return content, title


def _merge_translated_epubs(paths, output_path, title, language):
    try:
        import ebooklib
        from ebooklib import epub
    except Exception as exc:
        raise FinalizeError(f"ebooklib is required to merge translated EPUBs: {exc}") from exc

    merged = epub.EpubBook()
    identifier = hashlib.sha1(f"{title}|{'|'.join(paths)}".encode("utf-8")).hexdigest()
    merged.set_identifier(f"urn:uuid:{identifier}")
    merged.set_title(title)
    merged.set_language(language or "en")
    cover_added = False
    chapters = []

    for part_number, path in enumerate(paths, start=1):
        try:
            book = epub.read_epub(path)
        except Exception as exc:
            raise FinalizeError(f"Cannot read translated EPUB {path}: {exc}") from exc
        if part_number == 1:
            creators = book.get_metadata("DC", "creator")
            if creators and creators[0] and creators[0][0]:
                merged.add_author(str(creators[0][0]))
        if not cover_added:
            covers = list(book.get_items_of_type(ebooklib.ITEM_COVER))
            if not covers:
                covers = [item for item in book.get_items_of_type(ebooklib.ITEM_IMAGE)
                          if "cover" in item.get_name().lower()]
            if covers:
                item = covers[0]
                try:
                    merged.set_cover(os.path.basename(item.get_name()) or "cover.jpg",
                                     item.get_content(), create_page=False)
                    cover_added = True
                except Exception:
                    pass

        spine_ids = []
        for entry in book.spine:
            idref = entry[0] if isinstance(entry, (tuple, list)) else entry
            if idref and idref not in spine_ids:
                spine_ids.append(idref)
        documents = []
        for idref in spine_ids:
            item = book.get_item_with_id(idref)
            if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
                documents.append(item)
        if not documents:
            documents = [item for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
                         if "nav" not in item.get_name().lower()]

        for sequence, item in enumerate(documents, start=1):
            raw = item.get_content().decode("utf-8", "replace")
            content, chapter_title = _doc_content(
                raw, f"Part {part_number:02d} - Chapter {sequence:02d}"
            )
            if not content.strip():
                continue
            chapter = epub.EpubHtml(
                uid=f"p{part_number:03d}_{sequence:03d}",
                file_name=f"p{part_number:03d}_{sequence:03d}.xhtml",
                title=chapter_title,
            )
            chapter.content = content
            merged.add_item(chapter)
            chapters.append(chapter)

    if not chapters:
        raise FinalizeError("The translated EPUBs contain no readable chapters.")
    merged.toc = tuple(chapters)
    merged.add_item(epub.EpubNcx())
    merged.add_item(epub.EpubNav())
    merged.spine = chapters
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temporary = output_path + ".part.epub"
    try:
        epub.write_epub(temporary, merged)
        if not os.path.isfile(temporary) or os.path.getsize(temporary) == 0:
            raise FinalizeError("The merged translated EPUB is empty.")
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
    return len(chapters)


def _merge_translated_text(paths, output_path, title):
    chunks = []
    for path in paths:
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as handle:
                text = handle.read().strip()
        except OSError as exc:
            raise FinalizeError(f"Cannot read translated text {path}: {exc}") from exc
        if text:
            chunks.append(text)
    if not chunks:
        raise FinalizeError("The translated text parts are empty.")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temporary = output_path + ".part"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(f"# {title}\n\n")
        handle.write("\n\n".join(chunks))
        handle.write("\n")
    os.replace(temporary, output_path)
    return len(chunks)


def _translated_file(part_dir):
    candidates = []
    for path in _files(part_dir):
        name = os.path.basename(path).lower()
        if not name.startswith("translated_"):
            continue
        if os.path.splitext(name)[1] not in TRANSLATED_EXTS:
            continue
        try:
            if os.path.getsize(path) > 0:
                candidates.append(path)
        except OSError:
            pass
    candidates.sort(key=lambda path: (
        os.path.splitext(path)[1].lower() != ".epub", path))
    return candidates[0] if candidates else None


def _parts_signature(parts):
    raw = "|".join(
        f"{part['index']}:{part.get('sha1', '')}:{part.get('completed_at', '')}"
        for part in parts
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _book_title(plan_dir, state, override):
    if override:
        return str(override).strip()
    manifest = _read_json(os.path.join(plan_dir, "parts", "manifest.json"))
    if isinstance(manifest, dict) and manifest.get("title"):
        return str(manifest["title"]).strip()
    if state.get("title"):
        return str(state["title"]).strip()
    for entry in state.get("parts", {}).values():
        title = str(entry.get("title") or "")
        match = re.match(r"^(.*?)\s+-\s+Part\s+\d+", title)
        if match:
            return match.group(1).strip()
    source = os.path.splitext(str(state.get("source_name") or ""))[0]
    return source or "Book"


def finalize(plan_dir, audio_format=None, title_override=None, language=None):
    plan_dir = os.path.abspath(plan_dir)
    state = _read_json(os.path.join(plan_dir, "state.json"))
    if not isinstance(state, dict):
        raise FinalizeError(f"state.json is missing or invalid in {plan_dir}.")
    settings = state.get("settings") or {}
    audio_format = str(audio_format or settings.get("output_format") or "m4b").lower().lstrip(".")
    if f".{audio_format}" not in AUDIO_EXTS:
        raise FinalizeError(f"Unsupported audio format: .{audio_format}")

    state_parts = state.get("parts") or {}
    if not state_parts:
        raise FinalizeError("The plan has no parts.")
    ordered = sorted(state_parts.items(), key=lambda item: int(
        item[1].get("index", item[0]) if isinstance(item[1], dict) else item[0]))
    parts = []
    missing_translation = []
    for key, entry in ordered:
        if not isinstance(entry, dict) or entry.get("status") != "done":
            raise FinalizeError("Not all parts are finished yet.")
        index = int(entry.get("index") or key)
        part_dir = os.path.join(plan_dir, "output", f"{index:03d}")
        audio = [path for path in _files(part_dir)
                 if path.lower().endswith("." + audio_format)
                 and os.path.getsize(path) > 0]
        audio.sort()
        if not audio:
            raise FinalizeError(f"Part {index:03d} has no .{audio_format} audio in {part_dir}.")
        translated = _translated_file(part_dir)
        if translated:
            parts.append({
                "index": index, "title": entry.get("title") or "",
                "sha1": entry.get("sha1", ""),
                "completed_at": entry.get("completed_at", ""),
                "audio": audio, "translated": translated,
            })
        else:
            missing_translation.append(index)
            parts.append({
                "index": index, "title": entry.get("title") or "",
                "sha1": entry.get("sha1", ""),
                "completed_at": entry.get("completed_at", ""),
                "audio": audio, "translated": None,
            })

    title = _book_title(plan_dir, state, title_override)
    safe_title = _safe_name(title)
    final_dir = os.path.join(plan_dir, "output", "final")
    os.makedirs(final_dir, exist_ok=True)
    audio_name = f"{safe_title}.{audio_format}"
    audio_path = os.path.join(final_dir, audio_name)
    signature = _parts_signature(parts)
    previous = _read_json(os.path.join(final_dir, "final.json"))
    reuse_audio = (
        isinstance(previous, dict)
        and previous.get("plan_id") == state.get("plan_id")
        and previous.get("audio") == audio_name
        and previous.get("parts_signature") == signature
        and os.path.isfile(audio_path)
        and os.path.getsize(audio_path) > 0
    )
    if reuse_audio:
        duration = float(previous.get("duration_seconds") or 0)
        if duration <= 0:
            try:
                duration = _probe(audio_path)["duration"]
            except FinalizeError:
                duration = 0.0
        print(f"Reusing existing merged audiobook: {audio_path}", flush=True)
    else:
        print(f"Merging {len(parts)} part(s) into {audio_name} ...", flush=True)
        duration = _merge_audio(parts, audio_path, title, audio_format)
        print(f"Final audiobook: {audio_path} ({duration / 60.0:.1f} min)", flush=True)

    translated_path = None
    translated_count = 0
    translated_error = None
    if missing_translation:
        if len(missing_translation) == len(parts):
            print("No translated part files were found; skipping the translated book.",
                  flush=True)
        else:
            print("Translated files are missing for part(s) "
                  f"{', '.join(f'{index:03d}' for index in missing_translation)}; "
                  "skipping the translated book.", flush=True)
    else:
        suffixes = {os.path.splitext(part["translated"])[1].lower() for part in parts}
        try:
            if suffixes == {".epub"}:
                translated_name = f"translated_{safe_title}.epub"
                translated_path = os.path.join(final_dir, translated_name)
                translated_count = _merge_translated_epubs(
                    [part["translated"] for part in parts],
                    translated_path, title, language or settings.get("target_lang"),
                )
            elif suffixes <= TEXT_EXTS:
                translated_name = f"translated_{safe_title}.md"
                translated_path = os.path.join(final_dir, translated_name)
                translated_count = _merge_translated_text(
                    [part["translated"] for part in parts], translated_path, title)
            else:
                translated_error = ("The translated parts use mixed formats "
                                    f"({', '.join(sorted(suffixes))}); not merged.")
        except FinalizeError as exc:
            translated_error = str(exc)
        if translated_path and translated_error is None:
            print(f"Translated book: {translated_path} ({translated_count} chapters)",
                  flush=True)

    info = {
        "version": 1,
        "plan_id": state.get("plan_id"),
        "title": title,
        "audio": audio_name,
        "audio_format": audio_format,
        "duration_seconds": round(duration, 3),
        "translated": os.path.basename(translated_path) if translated_path and not translated_error else None,
        "translated_format": (os.path.splitext(translated_path)[1].lstrip(".")
                              if translated_path and not translated_error else None),
        "translated_chapters": translated_count,
        "translated_error": translated_error,
        "merged_parts": len(parts),
        "parts_signature": signature,
        "completed_at": _now(),
    }
    _write_json(os.path.join(final_dir, "final.json"), info)
    if translated_error:
        raise FinalizeError(translated_error)
    return info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-dir", required=True)
    parser.add_argument("--audio-format", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--language", default=None)
    args = parser.parse_args(argv)
    try:
        info = finalize(args.plan_dir, args.audio_format, args.title, args.language)
    except FinalizeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
