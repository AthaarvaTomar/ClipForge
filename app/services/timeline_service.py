import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.timeline import TimelineModel, TimelineOpModel, TimelineVersionModel
from app.schemas.timeline import Timeline, Track
from app.services.timeline_engine import TimelineOperationError, apply


class TimelineNotFoundError(Exception):
    """Raised when a timeline cannot be found by ID."""

    def __init__(self, timeline_id: str):
        super().__init__(f"Timeline '{timeline_id}' not found")
        self.timeline_id = timeline_id


class TimelineVersionConflictError(Exception):
    """Raised when an operation has a version conflict (HTTP 409)."""

    def __init__(self, current_version: int, expected_version: int):
        super().__init__(
            f"Timeline version conflict: client provided version {expected_version}, "
            f"but current timeline version is {current_version}"
        )
        self.current_version = current_version
        self.expected_version = expected_version


class TimelineService:
    """Service orchestrating persistent timeline operations, op logs, and undo/redo stacks."""

    @staticmethod
    def create_timeline(
        db: Session,
        video_id: str,
        tracks: list[Track] | None = None,
        source_duration_ms: int | None = None,
        timeline_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Timeline:
        """Create a new timeline record in the database."""
        t_id = timeline_id or str(uuid.uuid4())
        initial_schema = Timeline(
            id=t_id,
            video_id=video_id,
            version=1,
            source_duration_ms=source_duration_ms,
            tracks=tracks or [],
            metadata=metadata or {},
        )

        model = TimelineModel(
            id=t_id,
            video_id=video_id,
            version=1,
            current_seq=0,
            source_duration_ms=source_duration_ms,
            data=initial_schema.model_dump(mode="json"),
        )
        db.add(model)

        # Initial version snapshot (version 1)
        initial_version = TimelineVersionModel(
            timeline_id=t_id,
            version=1,
            snapshot=model.data,
        )
        db.add(initial_version)

        db.commit()
        db.refresh(model)
        return initial_schema

    @staticmethod
    def get_timeline_model(db: Session, timeline_id: str) -> TimelineModel:
        """Fetch a TimelineModel or raise TimelineNotFoundError."""
        model = db.execute(
            select(TimelineModel).where(TimelineModel.id == timeline_id)
        ).scalar_one_or_none()
        if not model:
            raise TimelineNotFoundError(timeline_id)
        return model

    @classmethod
    def get_timeline(cls, db: Session, timeline_id: str) -> Timeline:
        """Fetch the rehydrated Timeline schema."""
        model = cls.get_timeline_model(db, timeline_id)
        return model.to_schema()

    @classmethod
    def apply_ops(
        cls,
        db: Session,
        timeline_id: str,
        ops: list[dict[str, Any]],
        expected_version: int,
        actor: str = "user",
        group_id: str | None = None,
    ) -> Timeline:
        """Apply a batch of operations sharing a single group_id.

        - Enforces optimistic concurrency (version match).
        - Clears the redo stack (deletes ops with seq > current_seq).
        - Saves every op + inverse to timeline_ops.
        - Automatically creates snapshots every N ops.
        """
        model = cls.get_timeline_model(db, timeline_id)
        if model.version != expected_version:
            raise TimelineVersionConflictError(
                current_version=model.version,
                expected_version=expected_version,
            )

        if not ops:
            return model.to_schema()

        # 1. Clear redo stack if we were in an undone state
        if model.current_seq >= 0:
            db.execute(
                delete(TimelineOpModel).where(
                    TimelineOpModel.timeline_id == timeline_id,
                    TimelineOpModel.seq > model.current_seq,
                )
            )

        # 2. Rehydrate timeline and apply operations sequentially
        current_schema = model.to_schema()
        op_group_id = group_id or str(uuid.uuid4())
        initial_seq = model.current_seq
        created_ops: list[TimelineOpModel] = []

        for op in ops:
            next_schema, inverse_op = apply(current_schema, op)
            model.current_seq += 1

            op_record = TimelineOpModel(
                timeline_id=timeline_id,
                seq=model.current_seq,
                group_id=op_group_id,
                op=op,
                inverse_op=inverse_op,
                actor=actor,
            )
            created_ops.append(op_record)
            current_schema = next_schema

        db.add_all(created_ops)

        # 3. Bump timeline version
        model.version += 1
        current_schema = current_schema.model_copy(update={"version": model.version})
        model.data = current_schema.model_dump(mode="json")

        # 4. Check snapshot interval (every N ops)
        snapshot_interval = settings.TIMELINE_SNAPSHOT_INTERVAL
        if snapshot_interval > 0:
            # Check if any multiple of snapshot_interval falls in (initial_seq, model.current_seq]
            start_bucket = initial_seq // snapshot_interval
            end_bucket = model.current_seq // snapshot_interval
            if end_bucket > start_bucket:
                version_record = TimelineVersionModel(
                    timeline_id=timeline_id,
                    version=model.version,
                    snapshot=model.data,
                )
                db.add(version_record)

        db.commit()
        db.refresh(model)
        return current_schema

    @classmethod
    def undo(
        cls,
        db: Session,
        timeline_id: str,
        expected_version: int,
    ) -> Timeline:
        """Undo the latest applied group of operations.

        Applies the stored inverses in reverse sequence order.
        """
        model = cls.get_timeline_model(db, timeline_id)
        if model.version != expected_version:
            raise TimelineVersionConflictError(
                current_version=model.version,
                expected_version=expected_version,
            )

        if model.current_seq <= 0:
            # Nothing to undo
            return model.to_schema()

        # Find the op at the current pointer
        last_op = db.execute(
            select(TimelineOpModel).where(
                TimelineOpModel.timeline_id == timeline_id,
                TimelineOpModel.seq == model.current_seq,
            )
        ).scalar_one_or_none()

        if not last_op:
            return model.to_schema()

        # Find all ops sharing the same group_id up to current_seq, in reverse order
        group_ops = db.execute(
            select(TimelineOpModel)
            .where(
                TimelineOpModel.timeline_id == timeline_id,
                TimelineOpModel.group_id == last_op.group_id,
                TimelineOpModel.seq <= model.current_seq,
            )
            .order_by(TimelineOpModel.seq.desc())
        ).scalars().all()

        current_schema = model.to_schema()
        for op_rec in group_ops:
            current_schema, _ = apply(current_schema, op_rec.inverse_op)

        # Move current_seq back to before this group
        min_seq = min(op_rec.seq for op_rec in group_ops)
        model.current_seq = min_seq - 1

        # Increment version for optimistic concurrency tracking
        model.version += 1
        current_schema = current_schema.model_copy(update={"version": model.version})
        model.data = current_schema.model_dump(mode="json")

        db.commit()
        db.refresh(model)
        return current_schema

    @classmethod
    def redo(
        cls,
        db: Session,
        timeline_id: str,
        expected_version: int,
    ) -> Timeline:
        """Redo the next undone group of operations."""
        model = cls.get_timeline_model(db, timeline_id)
        if model.version != expected_version:
            raise TimelineVersionConflictError(
                current_version=model.version,
                expected_version=expected_version,
            )

        # Find the next op after current_seq
        next_op = db.execute(
            select(TimelineOpModel)
            .where(
                TimelineOpModel.timeline_id == timeline_id,
                TimelineOpModel.seq > model.current_seq,
            )
            .order_by(TimelineOpModel.seq.asc())
        ).scalars().first()

        if not next_op:
            # Nothing to redo
            return model.to_schema()

        # Find all ops sharing this next group_id in forward sequence order
        group_ops = db.execute(
            select(TimelineOpModel)
            .where(
                TimelineOpModel.timeline_id == timeline_id,
                TimelineOpModel.group_id == next_op.group_id,
                TimelineOpModel.seq > model.current_seq,
            )
            .order_by(TimelineOpModel.seq.asc())
        ).scalars().all()

        current_schema = model.to_schema()
        for op_rec in group_ops:
            current_schema, _ = apply(current_schema, op_rec.op)

        # Advance current_seq to the end of this group
        max_seq = max(op_rec.seq for op_rec in group_ops)
        model.current_seq = max_seq

        # Increment version for optimistic concurrency tracking
        model.version += 1
        current_schema = current_schema.model_copy(update={"version": model.version})
        model.data = current_schema.model_dump(mode="json")

        db.commit()
        db.refresh(model)
        return current_schema

    @classmethod
    def restore_version(
        cls,
        db: Session,
        timeline_id: str,
        target_version: int,
        expected_version: int,
    ) -> Timeline:
        """Restore a pinned timeline snapshot from timeline_versions."""
        model = cls.get_timeline_model(db, timeline_id)
        if model.version != expected_version:
            raise TimelineVersionConflictError(
                current_version=model.version,
                expected_version=expected_version,
            )

        version_record = db.execute(
            select(TimelineVersionModel).where(
                TimelineVersionModel.timeline_id == timeline_id,
                TimelineVersionModel.version == target_version,
            )
        ).scalar_one_or_none()

        if not version_record:
            raise TimelineOperationError(
                f"Version {target_version} snapshot not found for timeline '{timeline_id}'"
            )

        restored_schema = Timeline.model_validate(version_record.snapshot)
        model.version += 1
        restored_schema = restored_schema.model_copy(update={"version": model.version})
        model.data = restored_schema.model_dump(mode="json")

        db.commit()
        db.refresh(model)
        return restored_schema

    @classmethod
    def get_history(cls, db: Session, timeline_id: str) -> dict[str, Any]:
        """Fetch operation history and snapshot versions for a timeline."""
        model = cls.get_timeline_model(db, timeline_id)
        ops = db.execute(
            select(TimelineOpModel)
            .where(TimelineOpModel.timeline_id == timeline_id)
            .order_by(TimelineOpModel.seq.asc())
        ).scalars().all()
        versions = db.execute(
            select(TimelineVersionModel)
            .where(TimelineVersionModel.timeline_id == timeline_id)
            .order_by(TimelineVersionModel.version.asc())
        ).scalars().all()

        return {
            "timeline_id": model.id,
            "current_version": model.version,
            "current_seq": model.current_seq,
            "ops": ops,
            "versions": versions,
        }

    @classmethod
    def open_clip_timeline(
        cls,
        db: Session,
        clip_id: str,
        force_recreate: bool = False,
    ) -> Timeline:
        """Open or convert a draft clip and its EditSpec into a persistent Timeline (Task T7).

        - If clip already has a linked timeline_id and not force_recreate, loads existing timeline.
        - Otherwise, converts EditSpec (cuts, grade, transition, captions) into a Timeline,
          persists it to the database, links clip.timeline_id, and returns the Timeline.
        """
        from app.models.clip import Clip
        from app.models.transcript import Transcript
        from app.models.video import Video
        from app.services.clip_converter import ClipConverter

        clip = db.scalar(select(Clip).where(Clip.id == clip_id))
        if not clip:
            raise TimelineNotFoundError(f"Clip '{clip_id}' not found")

        # Return existing linked timeline if available
        if clip.timeline_id and not force_recreate:
            existing_model = db.scalar(
                select(TimelineModel).where(TimelineModel.id == clip.timeline_id)
            )
            if existing_model:
                return existing_model.to_schema()

        # Fetch video and optional transcript
        video = db.scalar(select(Video).where(Video.id == clip.video_id))
        transcript = db.scalar(select(Transcript).where(Transcript.video_id == clip.video_id))

        # Convert to Timeline schema
        timeline_schema = ClipConverter.clip_to_timeline(
            clip=clip,
            video=video,
            transcript=transcript,
        )

        # Persist new timeline with initial snapshot
        created = cls.create_timeline(
            db=db,
            video_id=clip.video_id,
            tracks=timeline_schema.tracks,
            source_duration_ms=timeline_schema.source_duration_ms,
            timeline_id=timeline_schema.id,
            metadata=timeline_schema.metadata,
        )

        # Link clip to the timeline
        clip.timeline_id = created.id
        db.commit()
        db.refresh(clip)

        return created

    @classmethod
    def convert_all_draft_clips(
        cls,
        db: Session,
        video_id: str | None = None,
    ) -> list[Timeline]:
        """Batch convert all draft clips without linked timelines into valid timelines."""
        from app.models.clip import Clip

        stmt = select(Clip).where(Clip.timeline_id.is_(None))
        if video_id:
            stmt = stmt.where(Clip.video_id == video_id)

        unlinked_clips = list(db.scalars(stmt).all())
        results: list[Timeline] = []
        for c in unlinked_clips:
            tl = cls.open_clip_timeline(db, c.id)
            results.append(tl)
        return results
