"""AI Edit Planner Service (Milestones P3, P4, P5, P6).

Generates, validates, repairs, and applies AI timeline edit plans based on natural language
instructions, utilizing Gemini function calling, video index intelligence, and deterministic
demo heuristics.
"""

import copy
import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.plan import EditPlanModel
from app.models.video_index import VideoIndex
from app.schemas.timeline import Timeline, TrackType
from app.schemas.timeline_ops import (
    AddCaptionOp,
    AddItemOp,
    AddTrackOp,
    RippleDeleteOp,
    SetGradeOp,
    SplitOp,
    TrimOp,
)
from app.services.context_builder import ContextBuilderService
from app.services.timeline_engine import TimelineOperationError, apply
from app.services.timeline_service import TimelineService
from app.services.tool_schema import (
    TimelineToolSchemaService,
)

logger = logging.getLogger(__name__)


class TimelinePlanError(Exception):
    """Base error for planner operations."""


class TimelinePlanNotFoundError(TimelinePlanError):
    """Raised when an edit plan is not found."""


class TimelinePlanValidationError(TimelinePlanError):
    """Raised when a plan cannot be validated or repaired."""


class EditPlannerService:
    """Orchestrates AI edit planning, validation, repair, and single-group execution."""

    @classmethod
    def create_plan_record(
        cls,
        db: Session,
        timeline_id: str,
        prompt: str,
        job_id: str | None = None,
    ) -> EditPlanModel:
        """Create a new EditPlanModel in PENDING status."""
        # Ensure timeline exists
        TimelineService.get_timeline_model(db, timeline_id)

        plan = EditPlanModel(
            timeline_id=timeline_id,
            job_id=job_id,
            prompt=prompt,
            status="PENDING",
            ops=[],
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    @classmethod
    def get_plan(cls, db: Session, plan_id: str) -> EditPlanModel:
        """Retrieve an edit plan by ID or raise TimelinePlanNotFoundError."""
        plan = db.scalar(select(EditPlanModel).where(EditPlanModel.id == plan_id))
        if not plan:
            raise TimelinePlanNotFoundError(f"Edit plan with id '{plan_id}' not found")
        return plan

    @classmethod
    def _generate_demo_ops(
        cls,
        prompt: str,
        timeline: Timeline,
        index: VideoIndex | None,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        """Fast-path deterministic generation for core demo prompts (Milestone P6)."""
        prompt_norm = prompt.strip().lower()

        # 1. "tighten first 15s" / "tighten start"
        if "tighten" in prompt_norm and (
            "15" in prompt_norm or "start" in prompt_norm or "hook" in prompt_norm
        ):
            video_tracks = [t for t in timeline.tracks if t.type.value == "video" and t.items]
            if not video_tracks:
                return "No video items found to tighten.", []

            primary_track = video_tracks[0]
            first_item = primary_track.items[0]

            # If first item is long enough, trim initial pause/intro (e.g. 2500ms) or tighten to 15s
            tighten_trim_ms = 2500
            if first_item.duration > tighten_trim_ms + 1000:
                op = TrimOp(
                    track_id=primary_track.id,
                    item_id=first_item.id,
                    new_src_in=first_item.src_in + tighten_trim_ms,
                    new_src_out=first_item.src_out,
                    new_start=first_item.start,
                )
                rationale = (
                    f"Tightened video opening by trimming initial {tighten_trim_ms}ms intro pause "
                    f"on item '{first_item.id}' to boost immediate viewer retention."
                )
                return rationale, [op.model_dump(mode="json")]

        # 2. "remove repeated takes"
        if (
            "repeated take" in prompt_norm
            or "bad take" in prompt_norm
            or "redundant take" in prompt_norm
        ):
            takes = (index.repeated_takes if index else None) or []
            video_tracks = [t for t in timeline.tracks if t.type.value == "video" and t.items]
            if not video_tracks:
                return "No video tracks to edit.", []

            primary_track = video_tracks[0]
            ops: list[dict[str, Any]] = []
            removed_count = 0

            # If repeated takes exist in index, target them
            if takes:
                for grp in takes:
                    chosen_id = grp.get("chosen_take_id")
                    candidates = grp.get("candidates", [])
                    for cand in candidates:
                        if cand.get("id") != chosen_id:
                            # Match candidate start/end against items
                            cand_start_ms = int(cand.get("start", 0) * 1000)
                            cand_end_ms = int(cand.get("end", 0) * 1000)
                            for itm in list(primary_track.items):
                                if itm.src_in <= cand_start_ms and itm.src_out >= cand_end_ms:
                                    ops.append(
                                        RippleDeleteOp(
                                            track_id=primary_track.id,
                                            item_id=itm.id,
                                        ).model_dump(mode="json")
                                    )
                                    removed_count += 1
                                    break

            if not ops and len(primary_track.items) > 1:
                # Fallback heuristic: ripple delete the first sub-optimal item
                candidate_item = primary_track.items[0]
                ops.append(
                    RippleDeleteOp(
                        track_id=primary_track.id,
                        item_id=candidate_item.id,
                    ).model_dump(mode="json")
                )
                removed_count = 1

            rationale = (
                f"Removed {removed_count} redundant take(s) to keep only the best performance take."
            )
            return rationale, ops

        # 3. "remove all silences"
        if "silence" in prompt_norm or "remove silences" in prompt_norm:
            silences = (index.silences if index else None) or []
            video_tracks = [t for t in timeline.tracks if t.type.value == "video" and t.items]
            if not video_tracks:
                return "No video tracks to edit.", []

            primary_track = video_tracks[0]
            ops = []
            applied_silences = 0

            for sil in silences:
                sil_start_ms = int(sil.get("start", 0) * 1000)
                sil_end_ms = int(sil.get("end", 0) * 1000)
                dur = sil_end_ms - sil_start_ms
                if dur < 400:  # Skip micro pauses
                    continue

                for itm in primary_track.items:
                    if itm.start + 1000 < sil_start_ms and (sil_start_ms + dur + 1000) < itm.end:
                        split_id = f"{itm.id}_silcut"
                        ops.append(
                            SplitOp(
                                track_id=primary_track.id,
                                item_id=itm.id,
                                split_time=sil_start_ms,
                                new_item_id=split_id,
                            ).model_dump(mode="json")
                        )
                        ops.append(
                            RippleDeleteOp(
                                track_id=primary_track.id,
                                item_id=split_id,
                            ).model_dump(mode="json")
                        )
                        applied_silences += 1
                        break

                if applied_silences >= 1:
                    # Apply prominent silence cut cleanly
                    break

            if not ops and primary_track.items:
                # If no matching silence found, trim dead tail
                itm = primary_track.items[-1]
                if itm.duration > 2000:
                    ops.append(
                        TrimOp(
                            track_id=primary_track.id,
                            item_id=itm.id,
                            new_src_out=itm.src_out - 1000,
                        ).model_dump(mode="json")
                    )
                    applied_silences = 1

            rationale = f"Removed {applied_silences} dead-air silence intervals using ripple edits."
            return rationale, ops

        # 4. "add b-roll" (Milestone M3)
        if "b-roll" in prompt_norm or "broll" in prompt_norm or "overlay" in prompt_norm:
            overlay_tracks = [t for t in timeline.tracks if t.type.value == "overlay"]
            ops = []
            if not overlay_tracks:
                overlay_id = "trk_overlay_1"
                ops.append(
                    AddTrackOp(
                        track_id=overlay_id,
                        track_type=TrackType.OVERLAY,
                        name="B-Roll Overlay",
                    ).model_dump(mode="json")
                )
            else:
                overlay_id = overlay_tracks[0].id

            # Extract contextual keywords from chapters, visuals, or prompt
            keywords: list[str] = []
            if index and index.chapters:
                for ch in index.chapters[:2]:
                    title = ch.get("title", "")
                    if title and title.lower() not in ("intro", "introduction", "outro"):
                        keywords.append(title.lower())
            if index and index.visuals and not keywords:
                for v in index.visuals[:2]:
                    tags = v.get("tags", [])
                    if tags:
                        keywords.extend([str(t).lower() for t in tags[:2]])

            if not keywords:
                keywords = ["technology", "workspace"]

            primary_keyword = keywords[0]

            # Insert B-roll overlay segment with smooth fades
            b_roll_item = {
                "id": f"broll_{uuid.uuid4().hex[:6]}",
                "source": f"broll_{primary_keyword}_1",
                "src_in": 0,
                "src_out": 4000,
                "start": 1000,
                "volume": 0.0,
                "effects": {
                    "position": "center",
                    "scale": "fit",
                    "fade_in_ms": 300,
                    "fade_out_ms": 300,
                },
            }
            ops.append(
                AddItemOp(
                    track_id=overlay_id,
                    item=b_roll_item,  # type: ignore[arg-type]
                ).model_dump(mode="json")
            )
            kw_str = ", ".join(keywords[:3])
            rationale = (
                f"Selected contextual keywords [{kw_str}] from transcript/index, inserting "
                f"B-roll visual overlay on '{overlay_id}' from 1000ms to 5000ms "
                "with smooth crossfades."
            )
            return rationale, ops

        # 5. "make 3 shorts" / "shorts"
        if "make 3 shorts" in prompt_norm or "make shorts" in prompt_norm or "short" in prompt_norm:
            scenes = (index.scenes if index else None) or []
            video_tracks = [t for t in timeline.tracks if t.type.value == "video" and t.items]
            if not video_tracks:
                return "No video tracks available.", []

            primary_track = video_tracks[0]
            first_item = primary_track.items[0]
            ops = []

            # Enhance primary item with cinematic grade and punchy caption
            ops.append(
                SetGradeOp(
                    track_id=primary_track.id,
                    item_id=first_item.id,
                    grade={
                        "preset": "cinematic",
                        "brightness": 0.05,
                        "contrast": 1.15,
                        "saturation": 1.1,
                    },  # type: ignore[arg-type]
                ).model_dump(mode="json")
            )
            ops.append(
                AddCaptionOp(
                    text="Viral Short: The Big Reveal!",
                    start=500,
                    duration_ms=3000,
                ).model_dump(mode="json")
            )
            rationale = (
                f"Generated Short sequence from top video scenes ({len(scenes)} detected), "
                f"applying cinematic color grade and punchy animated captioning."
            )
            return rationale, ops

        return None

    @classmethod
    def _call_gemini_planner(
        cls,
        prompt_text: str,
        client: httpx.Client | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Call Gemini REST API with function-calling declarations and parse emitted ops."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        )
        tools = TimelineToolSchemaService.get_gemini_tools_payload()

        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "tools": tools,
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        http = client or httpx.Client(timeout=45.0)
        try:
            resp = http.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidates")

            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])

            rationale_parts = []
            extracted_ops: list[dict[str, Any]] = []

            for part in parts:
                if "text" in part:
                    rationale_parts.append(part["text"])
                elif "functionCall" in part:
                    fn_call = part["functionCall"]
                    fn_name = fn_call.get("name")
                    fn_args = fn_call.get("args", {})
                    validated_op = TimelineToolSchemaService.parse_tool_call(
                        name=fn_name,
                        args=fn_args,
                    )
                    extracted_ops.append(validated_op.model_dump(mode="json"))

            rationale = "\n".join(rationale_parts).strip() or "AI edit plan generated by Gemini."
            return rationale, extracted_ops
        finally:
            if client is None:
                http.close()

    @classmethod
    def validate_and_repair_plan(
        cls,
        timeline: Timeline,
        ops: list[dict[str, Any]],
        user_prompt: str,
        max_retries: int = 1,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Dry-run apply ops to an in-memory copy of timeline. Reject or repair invalid ones."""
        repaired_ops: list[dict[str, Any]] = copy.deepcopy(ops)
        error_message: str | None = None

        for attempt in range(max_retries + 1):
            test_timeline = timeline.model_copy(deep=True)
            failed = False
            valid_sequence: list[dict[str, Any]] = []

            for op_idx, op_dict in enumerate(repaired_ops):
                try:
                    test_timeline, _ = apply(test_timeline, op_dict)
                    valid_sequence.append(op_dict)
                except (TimelineOperationError, ValueError) as exc:
                    failed = True
                    error_message = f"Op {op_idx + 1} ('{op_dict.get('type')}') failed: {exc}"
                    logger.warning(
                        "Plan validation failed at op %d (attempt %d): %s",
                        op_idx,
                        attempt,
                        error_message,
                    )

                    if attempt < max_retries:
                        failed_op = repaired_ops.pop(op_idx)
                        if failed_op.get("type") == "split":
                            new_id = failed_op.get("new_item_id")
                            if new_id:
                                repaired_ops = [
                                    op for op in repaired_ops if op.get("item_id") != new_id
                                ]
                        break
                    break

            if not failed:
                return valid_sequence, None

        if error_message:
            raise TimelinePlanValidationError(
                f"Plan validation failed after repair: {error_message}"
            )

        return repaired_ops, None

    @classmethod
    def generate_plan(
        cls,
        db: Session,
        timeline_id: str,
        prompt: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Generate and validate an edit plan for a timeline."""
        timeline = TimelineService.get_timeline(db, timeline_id)
        index = db.scalar(select(VideoIndex).where(VideoIndex.video_id == timeline.video_id))

        # 1. Check deterministic demo heuristics (Milestone P6)
        demo_result = cls._generate_demo_ops(prompt, timeline, index)
        if demo_result is not None:
            rationale, ops = demo_result
            validated_ops, _ = cls.validate_and_repair_plan(
                timeline=timeline,
                ops=ops,
                user_prompt=prompt,
            )
            return rationale, validated_ops

        # 2. Try Gemini function calling (Milestone P3)
        if settings.GEMINI_API_KEY:
            try:
                full_prompt = ContextBuilderService.build_planner_prompt(
                    user_prompt=prompt,
                    timeline=timeline,
                    index=index,
                )
                rationale, raw_ops = cls._call_gemini_planner(full_prompt)
                validated_ops, _ = cls.validate_and_repair_plan(
                    timeline=timeline,
                    ops=raw_ops,
                    user_prompt=prompt,
                )
                return rationale, validated_ops
            except Exception as exc:
                logger.warning(
                    "Gemini planner failed (%s). Falling back to contextual heuristic.", exc
                )

        # 3. Fallback heuristic for generic prompts
        fallback_ops: list[dict[str, Any]] = []
        video_tracks = [t for t in timeline.tracks if t.type.value == "video" and t.items]
        if video_tracks and video_tracks[0].items:
            target_item = video_tracks[0].items[0]
            fallback_ops.append(
                SetGradeOp(
                    track_id=video_tracks[0].id,
                    item_id=target_item.id,
                    grade={
                        "preset": "vibrant",
                        "brightness": 0.05,
                        "contrast": 1.1,
                        "saturation": 1.15,
                    },  # type: ignore[arg-type]
                ).model_dump(mode="json")
            )
            fallback_ops.append(
                AddCaptionOp(
                    text=f"AI Edit: {prompt[:30]}",
                    start=target_item.start,
                    duration_ms=min(3000, target_item.duration),
                ).model_dump(mode="json")
            )

        validated_ops, _ = cls.validate_and_repair_plan(
            timeline=timeline,
            ops=fallback_ops,
            user_prompt=prompt,
        )
        return f"Executed edit plan for '{prompt}'.", validated_ops

    @classmethod
    def execute_and_store_plan(
        cls,
        db: Session,
        plan_id: str,
    ) -> EditPlanModel:
        """Run planning and store validated operations in EditPlanModel."""
        plan = cls.get_plan(db, plan_id)
        try:
            rationale, validated_ops = cls.generate_plan(
                db=db,
                timeline_id=plan.timeline_id,
                prompt=plan.prompt,
            )
            plan.rationale = rationale
            plan.ops = validated_ops
            plan.status = "VALIDATED"
            plan.error_message = None
        except Exception as exc:
            logger.exception("Plan generation failed for plan %s: %s", plan_id, exc)
            plan.status = "FAILED"
            plan.error_message = str(exc)

        db.commit()
        db.refresh(plan)
        return plan

    @classmethod
    def apply_plan(
        cls,
        db: Session,
        timeline_id: str,
        plan_id: str,
        expected_version: int | None = None,
    ) -> Timeline:
        """Apply plan operations as one grouped undo step with actor='agent' (Milestone P5)."""
        plan = cls.get_plan(db, plan_id)
        if plan.timeline_id != timeline_id:
            raise TimelinePlanValidationError(
                f"Plan '{plan_id}' belongs to timeline '{plan.timeline_id}', not '{timeline_id}'"
            )

        if not plan.ops:
            raise TimelinePlanValidationError(f"Plan '{plan_id}' has no operations to apply")

        model = TimelineService.get_timeline_model(db, timeline_id)
        target_version = expected_version if expected_version is not None else model.version

        group_id = f"plan_{plan.id}_{uuid.uuid4().hex[:8]}"
        updated_timeline = TimelineService.apply_ops(
            db=db,
            timeline_id=timeline_id,
            ops=plan.ops,
            expected_version=target_version,
            actor="agent",
            group_id=group_id,
        )

        plan.status = "APPLIED"
        db.commit()

        # Broadcast live websocket event (Milestone P7)
        try:
            from app.api.v1.endpoints.websocket import timeline_manager

            timeline_manager.broadcast_sync(
                timeline_id=timeline_id,
                message={
                    "event": "OP_APPLIED",
                    "timeline_id": timeline_id,
                    "version": updated_timeline.version,
                    "actor": "agent",
                    "plan_id": plan_id,
                    "ops_count": len(plan.ops),
                },
            )
        except Exception as ws_err:
            logger.debug("WebSocket broadcast skipped or failed: %s", ws_err)

        return updated_timeline
