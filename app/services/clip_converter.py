"""Service to convert draft clips and EditSpec into valid multi-track Timelines (Task T7)."""

import uuid
from typing import Any

from app.models.clip import Clip
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.edit_spec import CaptionSpec, CutSegment, EditSpec, GradeSpec
from app.schemas.timeline import Item, ItemTransition, Timeline, Track, TrackType


class ClipConverter:
    """Converts draft clips and EditSpecs into multi-track Timelines."""

    @classmethod
    def edit_spec_to_timeline(
        cls,
        clip_id: str,
        video_id: str,
        edit_spec: EditSpec | dict[str, Any],
        title: str = "Clip",
        video: Video | None = None,
        transcript: Transcript | None = None,
        timeline_id: str | None = None,
    ) -> Timeline:
        """Convert an EditSpec and clip metadata into a validated Timeline schema."""
        # 1. Rehydrate EditSpec
        if isinstance(edit_spec, dict):
            # Fallback for minimal/empty edit_spec dictionaries
            cuts_raw = edit_spec.get("cuts")
            if not cuts_raw:
                clip_start = float(edit_spec.get("start", 0.0))
                clip_end = float(edit_spec.get("end", 0.0))
                if clip_end <= clip_start and video and video.duration:
                    clip_end = video.duration
                cuts_raw = [{"start": clip_start, "end": max(clip_start + 1.0, clip_end)}]
                edit_spec = {**edit_spec, "cuts": cuts_raw}
            spec = EditSpec.model_validate(edit_spec)
        else:
            spec = edit_spec

        # 2. Determine source video duration boundary
        source_dur_ms: int | None = None
        if video and video.duration is not None:
            source_dur_ms = int(round(video.duration * 1000))

        # Check cuts within source_dur_ms
        cuts: list[CutSegment] = list(spec.cuts)
        if not cuts:
            def_end = video.duration if video and video.duration else 10.0
            cuts = [CutSegment(start=0.0, end=def_end)]

        max_cut_end_ms = int(round(max(c.end for c in cuts) * 1000))
        if source_dur_ms is None or max_cut_end_ms > source_dur_ms:
            source_dur_ms = max_cut_end_ms

        # 3. Build Video Track
        video_items: list[Item] = []
        current_playhead_ms = 0
        cut_offsets: list[tuple[CutSegment, int, int]] = []

        grade_model: GradeSpec | None = None
        if spec.grade and spec.grade.preset != "none":
            grade_model = spec.grade

        transition_model: ItemTransition | None = None
        if spec.transition and spec.transition.type != "none":
            transition_model = ItemTransition(
                type=spec.transition.type,
                duration_ms=int(round(spec.transition.duration * 1000)),
            )

        for i, cut in enumerate(cuts):
            src_in = int(round(cut.start * 1000))
            src_out = int(round(cut.end * 1000))
            if src_out <= src_in:
                src_out = src_in + 100  # min 100ms cut

            # Clamp against source_duration_ms
            if source_dur_ms is not None and src_out > source_dur_ms:
                src_out = source_dur_ms
                if src_in >= src_out:
                    src_in = max(0, src_out - 100)

            duration = src_out - src_in
            cut_offsets.append((cut, current_playhead_ms, duration))

            # Apply transition between cuts (on second and subsequent cuts)
            item_transition = transition_model if i > 0 else None

            video_item = Item(
                id=f"itm_v_{i}_{uuid.uuid4().hex[:6]}",
                source=video_id,
                src_in=src_in,
                src_out=src_out,
                start=current_playhead_ms,
                volume=1.0,
                grade=grade_model,
                transition=item_transition,
            )
            video_items.append(video_item)
            current_playhead_ms += duration

        video_track = Track(
            id=f"trk_video_{uuid.uuid4().hex[:6]}",
            type=TrackType.VIDEO,
            name="Main Video",
            items=video_items,
        )
        tracks: list[Track] = [video_track]

        # 4. Build Caption Track if enabled
        caption_spec: CaptionSpec = spec.captions
        if caption_spec.enabled:
            caption_items: list[Item] = []
            last_caption_end = 0

            # Remap word timestamps from transcript if available
            if transcript and transcript.words:
                words: list[dict[str, Any]] = transcript.words
                for cut, cut_playhead, _ in cut_offsets:
                    # Filter words falling within this cut segment
                    for w in words:
                        w_start = float(w.get("start", 0.0))
                        w_end = float(w.get("end", 0.0))
                        text = str(w.get("word") or w.get("text", "")).strip()

                        if not text or w_end <= w_start:
                            continue

                        # Word is within this cut
                        if cut.start <= w_start < cut.end:
                            rel_start = w_start - cut.start
                            rel_end = min(w_end, cut.end) - cut.start
                            tl_start = cut_playhead + int(round(rel_start * 1000))
                            tl_end = cut_playhead + int(round(rel_end * 1000))

                            # Ensure non-overlapping on caption track
                            if tl_start < last_caption_end:
                                tl_start = last_caption_end
                            if tl_end <= tl_start:
                                tl_end = tl_start + 250  # 250ms default word display

                            item_dur = tl_end - tl_start
                            caption_item = Item(
                                id=f"cap_{uuid.uuid4().hex[:6]}",
                                source="text",
                                src_in=0,
                                src_out=item_dur,
                                start=tl_start,
                                text=text,
                                caption_style=caption_spec,
                            )
                            caption_items.append(caption_item)
                            last_caption_end = tl_end

            # If no transcript words were mapped, add hook or title as an introductory caption
            if not caption_items and (spec.hook or title):
                hook_text = spec.hook or title
                hook_dur = min(current_playhead_ms, 3000)
                if hook_dur > 0:
                    caption_items.append(
                        Item(
                            id=f"cap_hook_{uuid.uuid4().hex[:6]}",
                            source="text",
                            src_in=0,
                            src_out=hook_dur,
                            start=0,
                            text=hook_text,
                            caption_style=caption_spec,
                        )
                    )

            caption_track = Track(
                id=f"trk_cap_{uuid.uuid4().hex[:6]}",
                type=TrackType.CAPTION,
                name="Captions",
                items=caption_items,
            )
            tracks.append(caption_track)

        # 5. Assemble Timeline metadata
        metadata = {
            "clip_id": clip_id,
            "title": title,
            "aspect_ratio": spec.aspect_ratio,
            "reframe": spec.reframe.model_dump(mode="json"),
            "hook": spec.hook,
            "reason": spec.reason,
            "score": spec.score,
        }

        # 6. Instantiate and validate Timeline
        t_id = timeline_id or str(uuid.uuid4())
        timeline = Timeline(
            id=t_id,
            video_id=video_id,
            version=1,
            tracks=tracks,
            source_duration_ms=source_dur_ms,
            metadata=metadata,
        )
        return timeline

    @classmethod
    def clip_to_timeline(
        cls,
        clip: Clip,
        video: Video | None = None,
        transcript: Transcript | None = None,
        timeline_id: str | None = None,
    ) -> Timeline:
        """Convert a Clip model instance into a Timeline schema."""
        edit_spec_raw = clip.edit_spec or {}
        # Ensure cuts are populated from clip start/end if empty
        if not edit_spec_raw.get("cuts"):
            c_start = clip.start_time
            c_end = clip.end_time
            if c_end <= c_start and video and video.duration:
                c_end = video.duration
            edit_spec_raw = {
                **edit_spec_raw,
                "cuts": [{"start": c_start, "end": max(c_start + 1.0, c_end)}],
            }

        return cls.edit_spec_to_timeline(
            clip_id=clip.id,
            video_id=clip.video_id,
            edit_spec=edit_spec_raw,
            title=clip.title,
            video=video,
            transcript=transcript,
            timeline_id=timeline_id,
        )
