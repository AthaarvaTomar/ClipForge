import copy
import uuid
from typing import Any

from pydantic import BaseModel

from app.schemas.edit_spec import CaptionSpec, GradeSpec
from app.schemas.timeline import Item, ItemTransition, Timeline, Track, TrackType


class TimelineOperationError(ValueError):
    """Raised when an operation cannot be applied to a timeline."""


def _find_track(timeline: Timeline, track_id: str) -> tuple[int, Track]:
    """Helper to locate a track by ID, returning its index and track reference."""
    for idx, track in enumerate(timeline.tracks):
        if track.id == track_id:
            return idx, track
    raise TimelineOperationError(f"Track '{track_id}' not found in timeline '{timeline.id}'")


def _find_item(track: Track, item_id: str) -> tuple[int, Item]:
    """Helper to locate an item within a track by ID, returning its index and item reference."""
    for idx, item in enumerate(track.items):
        if item.id == item_id:
            return idx, item
    raise TimelineOperationError(f"Item '{item_id}' not found in track '{track.id}'")


def _validate_track_items(track: Track) -> None:
    """Ensure no items on the track overlap after modifications."""
    if len(track.items) <= 1:
        return

    sorted_items = sorted(track.items, key=lambda itm: itm.start)
    for i in range(len(sorted_items) - 1):
        curr = sorted_items[i]
        nxt = sorted_items[i + 1]
        curr_end = curr.start + (curr.src_out - curr.src_in)
        if nxt.start < curr_end:
            raise TimelineOperationError(
                f"Track '{track.id}' ({track.type.value}) contains overlapping items: "
                f"item '{curr.id}' [{curr.start}ms - {curr_end}ms] overlaps with "
                f"item '{nxt.id}' starting at {nxt.start}ms"
            )


def apply(
    timeline: Timeline,
    op: dict[str, Any] | BaseModel,
    *,
    increment_version: bool = False,
) -> tuple[Timeline, dict[str, Any]]:
    """Pure function applying an operation to a timeline, returning (new_timeline, inverse_op).

    (new_timeline, inverse_op) = apply(timeline, op)
    Applying inverse_op to new_timeline restores timeline exactly.
    The input timeline is never mutated in-place.
    All time values are integer milliseconds.
    """
    op_dict: dict[str, Any] = (
        op.model_dump(mode="json") if isinstance(op, BaseModel) else copy.deepcopy(op)
    )
    op_type = op_dict.get("type") or op_dict.get("op")
    if not op_type:
        raise TimelineOperationError("Operation missing required 'type' or 'op' field")

    # Create an immutable copy with structural sharing:
    # Each track is copied with a fresh items list, ensuring original timeline is untouched.
    new_tl = Timeline(
        id=timeline.id,
        video_id=timeline.video_id,
        version=timeline.version,
        source_duration_ms=timeline.source_duration_ms,
        tracks=[
            Track(
                id=t.id,
                type=t.type,
                name=t.name,
                items=list(t.items),
            )
            for t in timeline.tracks
        ],
    )

    inverse_op: dict[str, Any]

    if op_type == "add_track":
        raw_track = op_dict.get("track")
        if not raw_track:
            # Construct track from top-level fields if provided
            track_id = op_dict.get("track_id") or f"trk_{uuid.uuid4().hex[:8]}"
            track_type = op_dict.get("track_type", "video")
            track_name = op_dict.get("name")
            new_track = Track(id=track_id, type=TrackType(track_type), name=track_name)
        elif isinstance(raw_track, dict):
            new_track = Track.model_validate(raw_track)
        else:
            new_track = raw_track

        if isinstance(op, dict):
            op["track_id"] = new_track.id

        # Check for duplicate track ID
        for existing in new_tl.tracks:
            if existing.id == new_track.id:
                raise TimelineOperationError(f"Track with ID '{new_track.id}' already exists")

        index = op_dict.get("index")
        if index is not None and 0 <= index <= len(new_tl.tracks):
            new_tl.tracks.insert(index, new_track)
        else:
            new_tl.tracks.append(new_track)

        inverse_op = {
            "type": "remove_track",
            "track_id": new_track.id,
        }

    elif op_type == "remove_track":
        track_id = op_dict.get("track_id")
        if not track_id:
            raise TimelineOperationError("remove_track requires 'track_id'")
        idx, removed_track = _find_track(new_tl, track_id)
        new_tl.tracks.pop(idx)

        inverse_op = {
            "type": "add_track",
            "track": removed_track.model_dump(mode="json"),
            "index": idx,
        }

    elif op_type == "add_item":
        track_id = op_dict.get("track_id")
        if track_id is None:
            track_index = op_dict.get("track_index")
            if track_index is not None and 0 <= track_index < len(new_tl.tracks):
                track_id = new_tl.tracks[track_index].id
                if isinstance(op, dict):
                    op["track_id"] = track_id
        if not track_id:
            raise TimelineOperationError("add_item requires 'track_id' or valid 'track_index'")
        raw_item = op_dict.get("item")
        if not raw_item:
            raise TimelineOperationError("add_item requires 'item'")

        new_item = (
            Item.model_validate(raw_item)
            if isinstance(raw_item, dict)
            else new_item_copy(raw_item)
        )

        _, track = _find_track(new_tl, track_id)
        # Check source duration if timeline defines it
        if new_tl.source_duration_ms is not None and new_item.src_out > new_tl.source_duration_ms:
            raise TimelineOperationError(
                f"Item '{new_item.id}' src_out ({new_item.src_out}ms) exceeds "
                f"timeline source_duration_ms ({new_tl.source_duration_ms}ms)"
            )

        # Check duplicate item ID on this track
        for itm in track.items:
            if itm.id == new_item.id:
                raise TimelineOperationError(
                    f"Item with ID '{new_item.id}' already exists in track '{track_id}'"
                )

        track.items.append(new_item)
        track.items.sort(key=lambda itm: itm.start)
        _validate_track_items(track)

        inverse_op = {
            "type": "remove_item",
            "track_id": track_id,
            "item_id": new_item.id,
        }

    elif op_type == "remove_item":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        if not track_id or not item_id:
            raise TimelineOperationError("remove_item requires 'track_id' and 'item_id'")

        _, track = _find_track(new_tl, track_id)
        item_idx, removed_item = _find_item(track, item_id)
        track.items.pop(item_idx)

        inverse_op = {
            "type": "add_item",
            "track_id": track_id,
            "item": removed_item.model_dump(mode="json"),
        }

    elif op_type == "split":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        split_time = op_dict.get("split_time")
        if not track_id or not item_id or split_time is None:
            raise TimelineOperationError("split requires 'track_id', 'item_id', and 'split_time'")

        _, track = _find_track(new_tl, track_id)
        item_idx, orig_item = _find_item(track, item_id)

        if not (orig_item.start < split_time < orig_item.end):
            raise TimelineOperationError(
                f"split_time ({split_time}ms) must be strictly between item '{item_id}' "
                f"start ({orig_item.start}ms) and end ({orig_item.end}ms)"
            )

        offset = split_time - orig_item.start
        new_item_id = op_dict.get("new_item_id") or str(uuid.uuid4())
        if isinstance(op, dict):
            op["new_item_id"] = new_item_id

        # Left split item keeps original ID, shortened src_out
        left_item = orig_item.model_copy(
            update={
                "src_out": orig_item.src_in + offset,
            }
        )
        # Right split item gets new ID, starts at split_time
        right_item = orig_item.model_copy(
            update={
                "id": new_item_id,
                "start": split_time,
                "src_in": orig_item.src_in + offset,
            }
        )

        track.items[item_idx] = left_item
        track.items.insert(item_idx + 1, right_item)

        inverse_op = {
            "type": "merge",
            "track_id": track_id,
            "first_item_id": left_item.id,
            "second_item_id": right_item.id,
        }

    elif op_type == "merge":
        track_id = op_dict.get("track_id")
        first_id = op_dict.get("first_item_id")
        second_id = op_dict.get("second_item_id")
        if not track_id or not first_id or not second_id:
            raise TimelineOperationError(
                "merge requires 'track_id', 'first_item_id', and 'second_item_id'"
            )

        _, track = _find_track(new_tl, track_id)
        idx1, item1 = _find_item(track, first_id)
        idx2, item2 = _find_item(track, second_id)

        is_contiguous = (
            idx2 == idx1 + 1
            and item1.end == item2.start
            and item1.src_out == item2.src_in
            and item1.source == item2.source
        )
        if not is_contiguous:
            raise TimelineOperationError(
                f"Cannot merge items '{first_id}' and '{second_id}': "
                "items must be contiguous segments from the same source"
            )

        # Extend first item to cover second item
        merged_item = item1.model_copy(update={"src_out": item2.src_out})
        track.items[idx1] = merged_item
        track.items.pop(idx2)

        inverse_op = {
            "type": "split",
            "track_id": track_id,
            "item_id": merged_item.id,
            "split_time": item1.end,
            "new_item_id": item2.id,
        }

    elif op_type == "trim":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        if not track_id or not item_id:
            raise TimelineOperationError("trim requires 'track_id' and 'item_id'")

        _, track = _find_track(new_tl, track_id)
        item_idx, item = _find_item(track, item_id)

        old_src_in = item.src_in
        old_src_out = item.src_out
        old_start = item.start

        new_src_in = op_dict.get("new_src_in", op_dict.get("src_in", old_src_in))
        new_src_out = op_dict.get("new_src_out", op_dict.get("src_out", old_src_out))
        new_start = op_dict.get("new_start", op_dict.get("start", old_start))

        if new_src_in < 0 or new_src_out < 0 or new_start < 0:
            raise TimelineOperationError(
                "Timeline trim timestamps must be non-negative integer milliseconds"
            )
        if new_src_in >= new_src_out:
            raise TimelineOperationError(
                f"new_src_in ({new_src_in}ms) must be strictly less than "
                f"new_src_out ({new_src_out}ms)"
            )
        if new_tl.source_duration_ms is not None and new_src_out > new_tl.source_duration_ms:
            raise TimelineOperationError(
                f"Trimmed src_out ({new_src_out}ms) exceeds timeline "
                f"source_duration_ms ({new_tl.source_duration_ms}ms)"
            )

        trimmed_item = item.model_copy(
            update={
                "src_in": new_src_in,
                "src_out": new_src_out,
                "start": new_start,
            }
        )
        track.items[item_idx] = trimmed_item
        track.items.sort(key=lambda itm: itm.start)
        _validate_track_items(track)

        inverse_op = {
            "type": "trim",
            "track_id": track_id,
            "item_id": item_id,
            "new_src_in": old_src_in,
            "new_src_out": old_src_out,
            "new_start": old_start,
        }

    elif op_type == "move":
        item_id = op_dict.get("item_id")
        from_track_id = op_dict.get("from_track_id")
        to_track_id = op_dict.get("to_track_id") or from_track_id
        new_start = op_dict.get("new_start")

        if not item_id or not from_track_id or not to_track_id or new_start is None:
            raise TimelineOperationError(
                "move requires 'item_id', 'from_track_id', 'to_track_id', and 'new_start'"
            )
        if new_start < 0:
            raise TimelineOperationError(
                "new_start must be a non-negative integer millisecond timestamp"
            )

        _, from_track = _find_track(new_tl, from_track_id)
        _, to_track = _find_track(new_tl, to_track_id)
        from_idx, moving_item = _find_item(from_track, item_id)

        old_start = moving_item.start
        from_track.items.pop(from_idx)

        moved_item = moving_item.model_copy(update={"start": new_start})
        to_track.items.append(moved_item)
        to_track.items.sort(key=lambda itm: itm.start)

        try:
            _validate_track_items(to_track)
        except TimelineOperationError as err:
            # Revert move before raising to maintain error message clarity
            raise err

        inverse_op = {
            "type": "move",
            "item_id": item_id,
            "from_track_id": to_track_id,
            "to_track_id": from_track_id,
            "new_start": old_start,
        }

    elif op_type == "ripple_delete":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        if not track_id or not item_id:
            raise TimelineOperationError("ripple_delete requires 'track_id' and 'item_id'")

        _, track = _find_track(new_tl, track_id)
        item_idx, deleted_item = _find_item(track, item_id)

        del_duration = deleted_item.duration
        del_start = deleted_item.start
        track.items.pop(item_idx)

        # Shift subsequent items to the left by deleted item's duration
        track.items = [
            itm.model_copy(update={"start": itm.start - del_duration})
            if itm.start >= del_start + del_duration
            else itm
            for itm in track.items
        ]

        inverse_op = {
            "type": "ripple_insert",
            "track_id": track_id,
            "item": deleted_item.model_dump(mode="json"),
            "insert_start": del_start,
        }

    elif op_type == "ripple_insert":
        track_id = op_dict.get("track_id")
        raw_item = op_dict.get("item")
        insert_start = op_dict.get("insert_start")
        if not track_id or not raw_item or insert_start is None:
            raise TimelineOperationError(
                "ripple_insert requires 'track_id', 'item', and 'insert_start'"
            )

        item_to_insert = (
            Item.model_validate(raw_item)
            if isinstance(raw_item, dict)
            else raw_item
        )
        item_to_insert = item_to_insert.model_copy(update={"start": insert_start})
        ins_duration = item_to_insert.duration

        _, track = _find_track(new_tl, track_id)
        # Shift existing items at or after insert_start to the right
        track.items = [
            itm.model_copy(update={"start": itm.start + ins_duration})
            if itm.start >= insert_start
            else itm
            for itm in track.items
        ]

        track.items.append(item_to_insert)
        track.items.sort(key=lambda itm: itm.start)
        _validate_track_items(track)

        inverse_op = {
            "type": "ripple_delete",
            "track_id": track_id,
            "item_id": item_to_insert.id,
        }

    elif op_type == "set_volume":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        volume = op_dict.get("volume")
        if not track_id or not item_id or volume is None:
            raise TimelineOperationError("set_volume requires 'track_id', 'item_id', and 'volume'")
        if volume < 0.0:
            raise TimelineOperationError("volume must be non-negative")

        _, track = _find_track(new_tl, track_id)
        item_idx, item = _find_item(track, item_id)
        old_volume = item.volume

        track.items[item_idx] = item.model_copy(update={"volume": float(volume)})

        inverse_op = {
            "type": "set_volume",
            "track_id": track_id,
            "item_id": item_id,
            "volume": old_volume,
        }

    elif op_type == "set_grade":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        if not track_id or not item_id:
            raise TimelineOperationError("set_grade requires 'track_id' and 'item_id'")

        _, track = _find_track(new_tl, track_id)
        item_idx, item = _find_item(track, item_id)
        old_grade = item.grade.model_dump(mode="json") if item.grade else None

        raw_grade = op_dict.get("grade")
        new_grade = GradeSpec.model_validate(raw_grade) if raw_grade else None

        track.items[item_idx] = item.model_copy(update={"grade": new_grade})

        inverse_op = {
            "type": "set_grade",
            "track_id": track_id,
            "item_id": item_id,
            "grade": old_grade,
        }

    elif op_type == "set_transition":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        if not track_id or not item_id:
            raise TimelineOperationError("set_transition requires 'track_id' and 'item_id'")

        _, track = _find_track(new_tl, track_id)
        item_idx, item = _find_item(track, item_id)
        old_transition = item.transition.model_dump(mode="json") if item.transition else None

        raw_trans = op_dict.get("transition")
        new_transition = ItemTransition.model_validate(raw_trans) if raw_trans else None

        track.items[item_idx] = item.model_copy(update={"transition": new_transition})

        inverse_op = {
            "type": "set_transition",
            "track_id": track_id,
            "item_id": item_id,
            "transition": old_transition,
        }

    elif op_type == "add_caption":
        raw_item = op_dict.get("item")
        caption_text = op_dict.get("text")
        start = op_dict.get("start", 0)
        duration_ms = op_dict.get("duration_ms", 3000)
        track_id = op_dict.get("track_id")

        if raw_item:
            caption_item = Item.model_validate(raw_item) if isinstance(raw_item, dict) else raw_item
        else:
            if not caption_text:
                raise TimelineOperationError("add_caption requires either 'item' or 'text'")
            caption_id = op_dict.get("item_id") or f"cap_{uuid.uuid4().hex[:8]}"
            caption_item = Item(
                id=caption_id,
                source="caption",
                src_in=0,
                src_out=duration_ms,
                start=start,
                text=caption_text,
            )

        # Locate target caption track or auto-create one
        caption_track: Track | None = None
        if track_id:
            for trk in new_tl.tracks:
                if trk.id == track_id:
                    caption_track = trk
                    break
        else:
            for trk in new_tl.tracks:
                if trk.type == TrackType.CAPTION:
                    caption_track = trk
                    track_id = trk.id
                    break

        created_track_for_caption = False
        if caption_track is None:
            track_id = track_id or f"trk_caption_{uuid.uuid4().hex[:8]}"
            caption_track = Track(id=track_id, type=TrackType.CAPTION, name="Captions")
            new_tl.tracks.append(caption_track)
            created_track_for_caption = True


        caption_track.items.append(caption_item)
        caption_track.items.sort(key=lambda itm: itm.start)
        _validate_track_items(caption_track)

        if isinstance(op, dict):
            if "item_id" not in op:
                op["item_id"] = caption_item.id
            if "track_id" not in op:
                op["track_id"] = caption_track.id

        if created_track_for_caption:
            inverse_op = {
                "type": "remove_track",
                "track_id": caption_track.id,
            }
        else:
            inverse_op = {
                "type": "remove_item",
                "track_id": caption_track.id,
                "item_id": caption_item.id,
            }

    elif op_type == "update_caption":
        track_id = op_dict.get("track_id")
        item_id = op_dict.get("item_id")
        if not track_id or not item_id:
            raise TimelineOperationError("update_caption requires 'track_id' and 'item_id'")

        _, track = _find_track(new_tl, track_id)
        item_idx, item = _find_item(track, item_id)

        old_text = item.text
        old_caption_style = (
            item.caption_style.model_dump(mode="json") if item.caption_style else None
        )
        old_start = item.start
        old_src_in = item.src_in
        old_src_out = item.src_out

        update_fields: dict[str, Any] = {}
        if "text" in op_dict:
            update_fields["text"] = op_dict["text"]
        if "caption_style" in op_dict or "caption_spec" in op_dict:
            raw_spec = op_dict.get("caption_style") or op_dict.get("caption_spec")
            update_fields["caption_style"] = (
                CaptionSpec.model_validate(raw_spec) if raw_spec else None
            )
        if "start" in op_dict:
            update_fields["start"] = op_dict["start"]
        if "src_in" in op_dict:
            update_fields["src_in"] = op_dict["src_in"]
        if "src_out" in op_dict:
            update_fields["src_out"] = op_dict["src_out"]
        elif "duration_ms" in op_dict:
            update_fields["src_out"] = item.src_in + op_dict["duration_ms"]

        updated_caption = item.model_copy(update=update_fields)
        track.items[item_idx] = updated_caption
        track.items.sort(key=lambda itm: itm.start)
        _validate_track_items(track)

        inverse_op = {
            "type": "update_caption",
            "track_id": track_id,
            "item_id": item_id,
            "text": old_text,
            "caption_style": old_caption_style,
            "start": old_start,
            "src_in": old_src_in,
            "src_out": old_src_out,
        }

    else:
        raise TimelineOperationError(f"Unknown operation type: '{op_type}'")

    if increment_version:
        new_tl.version += 1

    return new_tl, inverse_op


def new_item_copy(item: Item) -> Item:
    """Helper to return an exact copy of an Item."""
    return item.model_copy(deep=True)
