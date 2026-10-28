"""Context builder service for Phase 6 AI Edit Planner (Milestone P2).

Compacts video indexing data (scenes, silences, repeated takes, visual tags, chapters)
and current timeline tracks into a concise, token-budgeted summary for Gemini/LLM prompts.
Guarantees a 3-hour video index comfortably fits within prompt token limits.
"""

from typing import Any

from app.models.video_index import VideoIndex
from app.schemas.timeline import Timeline


class ContextBuilderService:
    """Formats and compacts timeline state and video indexing insights."""

    @classmethod
    def format_timeline_summary(cls, timeline: Timeline) -> str:
        """Create a compact, human- and LLM-readable summary of current timeline tracks."""
        lines: list[str] = [
            (
                f"Timeline ID: {timeline.id} (Version: {timeline.version}, "
                f"Source Duration: {timeline.source_duration_ms or 0}ms)"
            ),
            f"Tracks count: {len(timeline.tracks)}",
        ]
        for trk in timeline.tracks:
            items_summary: list[str] = []
            for item in trk.items:
                effects_info = f" effects={item.effects}" if item.effects else ""
                grade_info = f" grade={item.grade.preset}" if item.grade else ""
                trans_info = (
                    f" transition={item.transition.type}:{item.transition.duration_ms}ms"
                    if item.transition
                    else ""
                )
                text_info = f" text='{item.text}'" if item.text else ""
                items_summary.append(
                    f"[{item.id}: timeline {item.start}-{item.end}ms "
                    f"(src {item.src_in}-{item.src_out}ms)"
                    f"{text_info}{grade_info}{trans_info}{effects_info}]"
                )
            items_str = ", ".join(items_summary) if items_summary else "empty"
            lines.append(f"- Track '{trk.id}' ({trk.type.value}, '{trk.name}'): {items_str}")

        return "\n".join(lines)

    @classmethod
    def format_index_summary(
        cls,
        index: VideoIndex | dict[str, Any] | None,
        max_items_per_category: int = 50,
    ) -> str:
        """Compact multi-hour index into a structured summary respecting token limits."""
        if not index:
            return "No video indexing metadata available."

        if isinstance(index, VideoIndex):
            scenes = index.scenes or []
            silences = index.silences or []
            takes = index.repeated_takes or []
            visuals = index.visuals or []
            chapters = index.chapters or []
            hook = index.hook or {}
            highlights = getattr(index, "highlights", []) or []
        else:
            scenes = index.get("scenes", [])
            silences = index.get("silences", [])
            takes = index.get("repeated_takes", [])
            visuals = index.get("visuals", [])
            chapters = index.get("chapters", [])
            hook = index.get("hook", {})
            highlights = index.get("highlights", [])

        lines: list[str] = ["### Video Index Summary:"]

        # Chapters
        if chapters:
            ch_strs = [
                f"[{ch.get('title', 'Chapter')} @ {ch.get('start', 0)}s - {ch.get('summary', '')}]"
                for ch in chapters[:20]
            ]
            lines.append("Chapters: " + "; ".join(ch_strs))

        # Hook candidate
        if hook:
            lines.append(
                f"Hook candidate: {hook.get('start', 0)}s-{hook.get('end', 0)}s "
                f"(score: {hook.get('virality_score', 0)}/100, text: '{hook.get('text', '')}')"
            )

        # Highlights
        if highlights:
            hl_strs = [
                (
                    f"[{h.get('title', 'Highlight')} {h.get('start', 0)}s-{h.get('end', 0)}s "
                    f"(score {h.get('score', 0)})]"
                )
                for h in highlights[:10]
            ]
            lines.append("Highlights: " + "; ".join(hl_strs))

        # Silences (compact: merged count and top silence spans)
        if silences:
            total_silence_s = sum(
                float(s.get("end", 0)) - float(s.get("start", 0)) for s in silences
            )
            silence_ranges = [
                f"{float(s.get('start', 0)):.1f}s-{float(s.get('end', 0)):.1f}s"
                for s in silences[:max_items_per_category]
            ]
            lines.append(
                f"Silences ({len(silences)} segments, ~{total_silence_s:.1f}s total): "
                + ", ".join(silence_ranges)
            )

        # Repeated Takes
        if takes:
            take_strs = []
            for grp in takes[:max_items_per_category]:
                chosen = grp.get("chosen_take_id", "")
                candidates = grp.get("candidates", [])
                redundant_ids = [c.get("id") for c in candidates if c.get("id") != chosen]
                take_strs.append(f"[Group: best={chosen}, redundant={redundant_ids}]")
            lines.append(f"Repeated Takes ({len(takes)} groups): " + "; ".join(take_strs))

        # Scenes & Visual Tags
        if visuals:
            vis_strs = [
                f"[Scene {v.get('scene_index', 0)} ({v.get('timestamp_s', 0)}s): "
                f"tags={','.join(v.get('tags', [])[:4])}, desc='{v.get('caption', '')[:60]}']"
                for v in visuals[:max_items_per_category]
            ]
            lines.append("Visual Scenes: " + "; ".join(vis_strs))
        elif scenes:
            lines.append(f"Scene cuts detected: {len(scenes)} total scenes.")

        return "\n".join(lines)

    @classmethod
    def build_planner_prompt(
        cls,
        user_prompt: str,
        timeline: Timeline,
        index: VideoIndex | dict[str, Any] | None = None,
    ) -> str:
        """Compose the complete prompt for the Gemini AI edit planner."""
        timeline_summary = cls.format_timeline_summary(timeline)
        index_summary = cls.format_index_summary(index)

        return (
            "You are an expert video editing assistant with direct control over "
            "a multi-track timeline engine.\n"
            "Your task is to analyze the user request and video metadata, "
            "then produce a sequence of timeline operations.\n\n"
            "### Current Timeline State:\n"
            f"{timeline_summary}\n\n"
            f"{index_summary}\n\n"
            "### User Instruction:\n"
            f'"{user_prompt}"\n\n'
            "### Instructions:\n"
            "1. Output a step-by-step editing plan.\n"
            "2. Emit only valid timeline operations using the available tool declarations.\n"
            "3. Ensure all timestamps are non-negative integer milliseconds.\n"
            "4. Ensure item IDs and track IDs correspond to real items in the timeline, "
            "or create new IDs when adding items/tracks.\n"
            "5. Maintain audio/video synchronization and avoid overlapping items "
            "on single tracks.\n"
        )
