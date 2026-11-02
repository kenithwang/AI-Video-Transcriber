"""Select original-language captions and turn timed cues into plain text."""

from dataclasses import dataclass
import html
import json
import math
import re
from urllib.parse import parse_qs, urlparse


SUBTITLE_FORMATS = ("json3", "vtt", "srt", "json")


@dataclass(frozen=True)
class SubtitleTranscript:
    text: str
    title: str
    language: str
    kind: str  # manual or automatic


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def _language(code: str) -> str:
    return code.removeprefix("ai-").removesuffix("-orig").lower()


def subtitle_candidates(info: dict):
    """Prefer native manual captions, then native ASR; never request translations."""
    manual = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    originals = {
        _language(fmt["language"])
        for fmt in info.get("formats") or []
        if fmt.get("language") and "original" in (fmt.get("format_note") or "").lower()
    }
    if not originals:
        originals = {_language(code) for code in automatic if code.endswith("-orig")}
    if not originals and info.get("language"):
        originals.add(_language(info["language"]))

    candidates = []
    seen = set()
    for tracks, automatic_source in ((manual, False), (automatic, True)):
        for code, formats in tracks.items():
            if code in {"live_chat", "danmaku"}:
                continue
            language = _language(code)
            if originals and not any(
                language.split("-")[0] == original.split("-")[0]
                for original in originals
            ):
                continue
            is_auto = automatic_source or code.startswith("ai-")
            for track in formats:
                ext = track.get("ext", "").lower()
                if ext not in SUBTITLE_FORMATS:
                    continue
                query = parse_qs(urlparse(track.get("url") or "").query)
                if query.get("tlang"):  # YouTube machine-translated track
                    continue
                key = (track.get("url"), track.get("data"), ext)
                if key in seen:
                    continue
                seen.add(key)
                # Manual first, explicit original before compatible duplicates.
                rank = (is_auto, not code.endswith("-orig"), SUBTITLE_FORMATS.index(ext))
                candidates.append((rank, language, "automatic" if is_auto else "manual", track))
    candidates.sort(key=lambda item: item[0])
    return [(language, kind, track) for _, language, kind, track in candidates]


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]*>", "", text)
    text = html.unescape(text).replace("\u200b", "")
    return " ".join(text.split())


def _seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))


def _cue(start, end, text) -> Cue:
    start, end = float(start), float(end)
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
        raise ValueError("invalid subtitle timing")
    return Cue(start, end, _clean(text))


def parse_subtitles(data: str, ext: str) -> list[Cue]:
    """Parse YouTube JSON3, WebVTT/SRT, or Bilibili JSON without an LLM."""
    if ext == "json3":
        payload = json.loads(data)
        cues = []
        for event in payload.get("events", []):
            text = "".join(seg.get("utf8", "") for seg in event.get("segs", []))
            if not text.strip():
                continue
            start = float(event["tStartMs"]) / 1000
            end = start + float(event.get("dDurationMs", 0)) / 1000
            cues.append(_cue(start, end, text))
        return cues
    if ext == "json":
        return [_cue(row["from"], row["to"], row["content"])
                for row in json.loads(data).get("body", [])]
    if ext not in {"vtt", "srt"}:
        raise ValueError("unsupported subtitle format")

    cues = []
    timestamp = r"(?:\d+:)?\d{2}:\d{2}[.,]\d{3}"
    for block in re.split(r"\n\s*\n", data.lstrip("\ufeff").replace("\r\n", "\n")):
        lines = block.splitlines()
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        for index, line in enumerate(lines):
            match = re.match(rf"\s*({timestamp})\s+-->\s+({timestamp})(?:\s|$)", line)
            if match:
                cues.append(_cue(_seconds(match[1]), _seconds(match[2]),
                                 " ".join(lines[index + 1:])))
                break
    return cues


def subtitles_to_text(data: str, ext: str, duration: float = 0) -> str:
    cues = sorted((cue for cue in parse_subtitles(data, ext) if cue.text),
                  key=lambda cue: cue.start)
    if not cues:
        raise ValueError("empty subtitles")
    # Reject an excerpt or a visibly truncated response for a long video.
    if duration and duration > 60:
        if cues[0].start > max(30, duration * 0.1) or max(c.end for c in cues) < duration * 0.8:
            raise ValueError("incomplete subtitle coverage")

    lines = []
    previous = None
    for cue in cues:
        text = cue.text
        if previous and cue.start < previous.end - 0.01:
            # Rolling captions often repeat the preceding cue. Only remove
            # overlap in simultaneous cues, preserving later repeated speech.
            before, current = previous.text.split(), text.split()
            for count in range(min(len(before), len(current)), 0, -1):
                if before[-count:] == current[:count]:
                    text = " ".join(current[count:])
                    break
        if text:
            lines.append(text)
        previous = cue
    text = "\n".join(lines)
    speech = re.sub(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)", "", text)
    if not any(char.isalnum() for char in speech):
        raise ValueError("subtitles contain no speech")
    if duration and duration > 60 and sum(char.isalnum() for char in speech) < 20:
        raise ValueError("subtitles contain too little speech")
    return text
