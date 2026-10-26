"""ASS (Advanced SubStation Alpha) subtitle builder service.

Generates styled .ass subtitle files with word-level animations, title cards,
and cut timestamp remapping for vertical video rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.edit_spec import CaptionSpec, CutSegment, TransitionSpec


@dataclass
class RemappedWord:
    """Transcript word mapped to the continuous playback timeline of a cut clip."""

    word: str
    start: float
    end: float


class ASSBuilderError(Exception):
    """Exception raised for subtitle building errors."""

    pass


def hex_to_ass_color(hex_str: str, alpha: int = 0) -> str:
    """Convert RGB hex (#RRGGBB or #RGB) to ASS color format &HAABBGGRR&.

    In ASS, colors are ordered Alpha, Blue, Green, Red (reverse of RGB).
    Alpha: 0 is completely opaque, 255 is completely transparent.
    """
    clean = hex_str.strip().lstrip("#")
    if len(clean) == 3:
        clean = "".join(c * 2 for c in clean)
    if len(clean) != 6:
        clean = "FFFFFF"

    r = int(clean[0:2], 16)
    g = int(clean[2:4], 16)
    b = int(clean[4:6], 16)
    clamped_alpha = max(0, min(255, alpha))

    return f"&H{clamped_alpha:02X}{b:02X}{g:02X}{r:02X}&"


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp format: H:MM:SS.cc (centiseconds)."""
    total_cs = max(0, int(round(seconds * 100)))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def remap_words_to_cuts(
    words: list[dict[str, Any]],
    cuts: list[CutSegment],
    transition: TransitionSpec | None = None,
) -> list[RemappedWord]:
    """Map transcript word timestamps from the source video into continuous clip playback time.

    Words outside the cut boundaries are dropped.
    Words straddling cut boundaries are clamped to cut boundaries.
    Transition overlaps (xfade duration) are accounted for in cumulative offsets.
    """
    if not cuts or not words:
        return []

    trans_type = transition.type if transition else "none"
    trans_dur = transition.duration if transition else 0.0
    n = len(cuts)

    # Calculate transition overlap d
    d = 0.0
    if trans_type != "none" and trans_dur > 0.0 and n >= 2:
        min_segment_dur = min(cut.end - cut.start for cut in cuts)
        d = min(trans_dur, min_segment_dur * 0.5)
        if d < 0.05:
            d = 0.0

    # Compute start playback offset for each cut
    cut_offsets: list[float] = []
    accumulated = 0.0
    for i, cut in enumerate(cuts):
        if i == 0:
            cut_offsets.append(0.0)
            accumulated = cut.end - cut.start
        else:
            offset = max(0.0, accumulated - d)
            cut_offsets.append(offset)
            accumulated = offset + (cut.end - cut.start)

    remapped: list[RemappedWord] = []

    for item in words:
        w_text = str(item.get("word", "")).strip()
        if not w_text:
            continue

        raw_start = float(item.get("start", 0.0))
        raw_end = float(item.get("end", 0.0))
        if raw_end <= raw_start:
            continue

        # Find which cut contains this word
        for i, cut in enumerate(cuts):
            # Check overlap between word [raw_start, raw_end] and cut [cut.start, cut.end]
            overlap_start = max(raw_start, cut.start)
            overlap_end = min(raw_end, cut.end)

            if overlap_end - overlap_start >= 0.03:
                # Word is within this cut
                offset = cut_offsets[i]
                remap_start = offset + (overlap_start - cut.start)
                remap_end = offset + (overlap_end - cut.start)

                remapped.append(
                    RemappedWord(
                        word=w_text,
                        start=round(remap_start, 3),
                        end=round(remap_end, 3),
                    )
                )
                break

    return remapped


def chunk_words_into_lines(
    words: list[RemappedWord],
    max_words_per_line: int = 3,
    max_pause_seconds: float = 0.45,
) -> list[list[RemappedWord]]:
    """Group words into short, readable caption phrases suitable for vertical video."""
    if not words:
        return []

    chunks: list[list[RemappedWord]] = []
    current_chunk: list[RemappedWord] = []

    for word in words:
        if not current_chunk:
            current_chunk.append(word)
            continue

        prev_word = current_chunk[-1]
        pause = word.start - prev_word.end
        punctuation_break = prev_word.word.endswith((".", "!", "?"))

        should_break = (
            len(current_chunk) >= max_words_per_line
            or pause > max_pause_seconds
            or punctuation_break
        )
        if should_break:
            chunks.append(current_chunk)
            current_chunk = [word]
        else:
            current_chunk.append(word)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class ASSBuilder:
    """Constructs ASS subtitle files with customizable styles, animations, and title cards."""

    def __init__(
        self,
        caption_spec: CaptionSpec | None = None,
        target_width: int = 1080,
        target_height: int = 1920,
    ) -> None:
        self.spec = caption_spec or CaptionSpec()
        self.target_width = target_width
        self.target_height = target_height

    def _generate_header(self) -> str:
        """Generate ASS script info and styles section."""
        primary_color_ass = hex_to_ass_color(self.spec.primary_color)
        highlight_color_ass = hex_to_ass_color(self.spec.highlight_color)
        outline_color_ass = "&H00000000&"  # Solid black outline
        shadow_color_ass = "&H80000000&"   # Semi-transparent black shadow

        # Alignment and vertical margin
        if self.spec.position == "top":
            alignment = 8  # Top-center
            margin_v = int(self.target_height * 0.12)
        elif self.spec.position == "middle":
            alignment = 5  # Middle-center
            margin_v = 0
        else:  # bottom
            alignment = 2  # Bottom-center
            margin_v = int(self.target_height * 0.16)

        margin_lr = int(self.target_width * 0.08)

        # Base subtitle font size scaled if needed
        font_size = self.spec.font_size
        title_font_size = int(font_size * 1.35)
        title_margin_v = int(self.target_height * 0.08)

        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {self.target_width}",
            f"PlayResY: {self.target_height}",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            # Default caption style
            f"Style: Default,{self.spec.font_name},{font_size},"
            f"{primary_color_ass},{highlight_color_ass},{outline_color_ass},{shadow_color_ass},"
            f"-1,0,0,0,100,100,0,0,1,3,2,{alignment},{margin_lr},{margin_lr},{margin_v},1",
            # Title card style
            f"Style: Title,{self.spec.font_name},{title_font_size},"
            f"{highlight_color_ass},{primary_color_ass},{outline_color_ass},{shadow_color_ass},"
            f"-1,0,0,0,100,100,0,0,1,4,3,8,{margin_lr},{margin_lr},{title_margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        return "\n".join(lines)

    def _render_chunk_events(self, chunk: list[RemappedWord]) -> list[str]:
        """Generate ASS Dialogue events for a chunk of words applying the specified animation."""
        if not chunk:
            return []

        anim = self.spec.animation
        primary_c = hex_to_ass_color(self.spec.primary_color)
        highlight_c = hex_to_ass_color(self.spec.highlight_color)

        chunk_start = chunk[0].start
        chunk_end = chunk[-1].end
        events: list[str] = []

        if anim == "none":
            # Plain static text for the whole chunk duration
            start_str = format_ass_timestamp(chunk_start)
            end_str = format_ass_timestamp(chunk_end)
            text = " ".join(w.word for w in chunk)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")

        elif anim == "fade":
            # Smooth fade in and out across the chunk
            start_str = format_ass_timestamp(chunk_start)
            end_str = format_ass_timestamp(chunk_end)
            text = " ".join(w.word for w in chunk)
            events.append(
                f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\fad(150,150)}}{text}"
            )

        elif anim in ("highlight", "pop", "bounce"):
            for i, active_w in enumerate(chunk):
                w_start = format_ass_timestamp(active_w.start)
                w_end = format_ass_timestamp(active_w.end)

                formatted_words: list[str] = []
                for j, w in enumerate(chunk):
                    if j == i:
                        if anim == "highlight":
                            formatted_words.append(
                                f"{{\\c{highlight_c}\\b1}}{w.word}{{\\c{primary_c}\\b0}}"
                            )
                        elif anim == "pop":
                            formatted_words.append(
                                f"{{\\c{highlight_c}\\b1\\t(0,100,\\fscx120\\fscy120)"
                                f"\\t(100,200,\\fscx100\\fscy100)}}{w.word}{{\\c{primary_c}\\b0}}"
                            )
                        else:  # bounce
                            formatted_words.append(
                                f"{{\\c{highlight_c}\\b1\\t(0,80,\\fscy125\\fscx90)"
                                f"\\t(80,160,\\fscy95\\fscx105)\\t(160,220,\\fscx100\\fscy100)}}"
                                f"{w.word}{{\\c{primary_c}\\b0}}"
                            )
                    else:
                        formatted_words.append(f"{{\\c{primary_c}}}{w.word}")

                line_text = " ".join(formatted_words)
                events.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{line_text}")

        return events

    def build_ass(
        self,
        words: list[dict[str, Any]] | list[RemappedWord],
        cuts: list[CutSegment] | None = None,
        transition: TransitionSpec | None = None,
        title: str | None = None,
        title_duration: float = 2.5,
    ) -> str:
        """Build the complete .ass subtitle script string.

        Args:
            words: Either raw transcript words (dicts) or pre-remapped RemappedWord objects.
            cuts: Cuts list used to remap raw transcript words (if words are dicts).
            transition: Optional transition spec affecting cumulative offsets.
            title: Optional title / opening hook to display at the beginning.
            title_duration: Seconds to display title card (default 2.5s).
        """
        header = self._generate_header()
        events: list[str] = []

        # 1. Add title card overlay if specified
        if title and title.strip():
            clean_title = title.strip().replace("\n", "\\N")
            start_str = format_ass_timestamp(0.0)
            end_str = format_ass_timestamp(max(1.0, title_duration))
            events.append(
                f"Dialogue: 1,{start_str},{end_str},Title,,0,0,0,,{{\\fad(200,300)}}{clean_title}"
            )

        # 2. Remap words if not already remapped
        remapped_words: list[RemappedWord] = []
        if words:
            first = words[0]
            if isinstance(first, RemappedWord):
                remapped_words = [w for w in words if isinstance(w, RemappedWord)]
            else:
                raw_list = [w for w in words if isinstance(w, dict)]
                remapped_words = remap_words_to_cuts(raw_list, cuts or [], transition)

        # 3. Generate dialogue events for caption chunks
        if self.spec.enabled and remapped_words:
            chunks = chunk_words_into_lines(remapped_words)
            for chunk in chunks:
                events.extend(self._render_chunk_events(chunk))

        content = header + "\n" + "\n".join(events) + "\n"
        return content

    def write_ass_file(
        self,
        output_file: Path | str,
        words: list[dict[str, Any]] | list[RemappedWord],
        cuts: list[CutSegment] | None = None,
        transition: TransitionSpec | None = None,
        title: str | None = None,
        title_duration: float = 2.5,
    ) -> Path:
        """Generate and save the .ass file to disk."""
        out_p = Path(output_file)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        content = self.build_ass(
            words=words,
            cuts=cuts,
            transition=transition,
            title=title,
            title_duration=title_duration,
        )
        out_p.write_text(content, encoding="utf-8")
        return out_p
