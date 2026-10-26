"""Timeline-to-FFmpeg Compiler Service (Task R2).

Compiles a multi-track Timeline schema into an FFmpeg filtergraph and CLI command.
Supports:
- Multi-track video: cuts, reframing (crop/blur-bg), grading, and transitions (xfade/acrossfade).
- Overlay tracks: compositing secondary video/B-roll over main video using time-based overlay.
- Audio mixing: multi-stream audio mix (video track + overlay + audio tracks) with volume/mute.
- Caption tracks: burned-in subtitles using ASS builder.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.schemas.edit_spec import CaptionSpec, GradeSpec
from app.schemas.timeline import Item, Timeline, Track, TrackType
from app.services.ass_builder import ASSBuilder, RemappedWord
from app.services.ffmpeg_builder import (
    FFmpegBuilderError,
    build_grade_filter,
    build_reframe_filter,
    check_has_audio,
    get_target_resolution,
)

# Transition name map for xfade
XFADE_MAP: dict[str, str] = {
    "fade": "fade",
    "crossfade": "fade",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "circlecrop": "circlecrop",
    "dissolve": "dissolve",
}


class TimelineCompiler:
    """Compiles a Timeline schema into executable FFmpeg commands."""

    def __init__(
        self,
        timeline: Timeline,
        source_resolver: Callable[[str], Path] | dict[str, Path | str],
        output_path: Path | str,
        target_resolution: tuple[int, int] | None = None,
        lut_path: Path | str | None = None,
    ) -> None:
        self.timeline = timeline
        self.source_resolver = source_resolver
        self.output_path = Path(output_path)
        self.lut_path = Path(lut_path) if lut_path else None

        # Determine aspect ratio and target resolution
        meta = timeline.metadata or {}
        self.aspect_ratio = str(meta.get("aspect_ratio", "9:16"))
        raw_reframe = meta.get("reframe")
        reframe_cfg: dict[str, Any] = raw_reframe if isinstance(raw_reframe, dict) else {}
        self.reframe_strategy = str(reframe_cfg.get("strategy", "crop"))
        self.reframe_crop_x = float(reframe_cfg.get("crop_x_offset", 0.0))

        if target_resolution:
            self.target_width, self.target_height = target_resolution
        else:
            self.target_width, self.target_height = get_target_resolution(
                self.aspect_ratio, 1920, 1080
            )

        # Map each unique source to an input index: source_key -> (input_index, resolved_path)
        self._source_inputs: dict[str, tuple[int, Path]] = {}
        self._audio_status: dict[int, bool] = {}
        self._meta_status: dict[int, tuple[int, int]] = {}

    def resolve_source_path(self, source_ref: str) -> Path:
        """Resolve a media reference identifier to an absolute Path on disk."""
        if callable(self.source_resolver):
            resolved = self.source_resolver(source_ref)
        elif isinstance(self.source_resolver, dict):
            if source_ref in self.source_resolver:
                resolved = Path(self.source_resolver[source_ref])
            elif "source" in self.source_resolver:
                resolved = Path(self.source_resolver["source"])
            elif self.timeline.video_id in self.source_resolver:
                resolved = Path(self.source_resolver[self.timeline.video_id])
            else:
                raise FFmpegBuilderError(f"Cannot resolve source reference: '{source_ref}'")
        else:
            raise FFmpegBuilderError("Invalid source_resolver provided")

        path = Path(resolved)
        if not path.is_file():
            raise FFmpegBuilderError(f"Resolved media file does not exist: {path}")
        return path

    def _register_input(self, source_ref: str) -> int:
        """Register a source media file and return its FFmpeg input index."""
        if source_ref in self._source_inputs:
            return self._source_inputs[source_ref][0]

        path = self.resolve_source_path(source_ref)
        idx = len(self._source_inputs)
        self._source_inputs[source_ref] = (idx, path)

        # Check audio presence and resolution
        self._audio_status[idx] = check_has_audio(path)
        from app.services.video_probe import probe_video

        try:
            p = probe_video(path)
            self._meta_status[idx] = (p.width, p.height)
        except Exception:
            self._meta_status[idx] = (1920, 1080)

        return idx

    @property
    def total_duration_seconds(self) -> float:
        """Total duration of the timeline in seconds."""
        ms = self.timeline.duration
        return max(0.1, ms / 1000.0)

    def _compile_video_track(
        self, track: Track, filters: list[str], include_audio: bool = True
    ) -> tuple[str, str, float]:
        """Compile main video track items into a continuous (v_label, a_label, duration)."""
        items = sorted(track.items, key=lambda it: it.start)
        if not items:
            dur = self.total_duration_seconds
            filters.append(
                f"color=c=black:s={self.target_width}x{self.target_height}:d={dur:.3f}[v_empty]"
            )
            if include_audio:
                filters.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                    f"atrim=start=0:end={dur:.3f},asetpts=PTS-STARTPTS[a_empty]"
                )
                return "v_empty", "a_empty", dur
            return "v_empty", "", dur

        n = len(items)
        cut_v_labels: list[str] = []
        cut_a_labels: list[str] = []
        durations: list[float] = []

        for i, item in enumerate(items):
            in_idx = self._register_input(item.source)
            has_a = self._audio_status[in_idx] and not track.muted
            src_w, src_h = self._meta_status[in_idx]

            in_s = item.src_in / 1000.0
            out_s = item.src_out / 1000.0
            dur_s = max(0.05, out_s - in_s)
            durations.append(dur_s)

            # 1. Trim video
            v_trim = f"v_t_{track.id}_{i}"
            filters.append(
                f"[{in_idx}:v]trim=start={in_s:.3f}:end={out_s:.3f},setpts=PTS-STARTPTS[{v_trim}]"
            )

            # 2. Reframe to target resolution
            v_rf = f"v_rf_{track.id}_{i}"
            rf_lines = build_reframe_filter(
                in_label=v_trim,
                out_label=v_rf,
                source_width=src_w,
                source_height=src_h,
                target_width=self.target_width,
                target_height=self.target_height,
                strategy=self.reframe_strategy,
                crop_x_offset=self.reframe_crop_x,
            )
            filters.extend(rf_lines)

            # 3. Apply item grade
            v_graded = f"v_gr_{track.id}_{i}"
            grade_spec = item.grade or GradeSpec()
            gr_lines = build_grade_filter(
                in_label=v_rf,
                out_label=v_graded,
                grade=grade_spec,
                lut_path=self.lut_path,
            )
            filters.extend(gr_lines)
            cut_v_labels.append(v_graded)

            # 4. Trim audio with item volume (if requested)
            if include_audio:
                a_out = f"a_t_{track.id}_{i}"
                vol = item.volume if not track.muted else 0.0
                if has_a:
                    filters.append(
                        f"[{in_idx}:a]atrim=start={in_s:.3f}:end={out_s:.3f},"
                        f"asetpts=PTS-STARTPTS,volume={vol:.3f}[{a_out}]"
                    )
                else:
                    filters.append(
                        f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                        f"atrim=start=0:end={dur_s:.3f},asetpts=PTS-STARTPTS[{a_out}]"
                    )
                cut_a_labels.append(a_out)

        has_transitions = any(
            it.transition and it.transition.type != "none" and it.transition.duration_ms > 0
            for it in items[1:]
        )

        if not include_audio:
            if n == 1:
                return cut_v_labels[0], "", durations[0]

            if has_transitions:
                curr_v = cut_v_labels[0]
                accum_dur = durations[0]
                for i in range(1, n):
                    item = items[i]
                    trans = item.transition
                    trans_type = trans.type if trans else "fade"
                    trans_name = XFADE_MAP.get(trans_type, "fade")
                    trans_dur = (trans.duration_ms / 1000.0) if trans else 0.5
                    d = min(trans_dur, min(durations[i - 1], durations[i]) * 0.45)
                    d = max(0.05, d)
                    offset = max(0.0, accum_dur - d)
                    out_v = f"v_xf_{i}"
                    filters.append(
                        f"[{curr_v}][{cut_v_labels[i]}]xfade=transition={trans_name}:"
                        f"duration={d:.3f}:offset={offset:.3f}[{out_v}]"
                    )
                    curr_v = out_v
                    accum_dur = accum_dur + durations[i] - d
                return curr_v, "", accum_dur

            concat_inputs = "".join(f"[{cut_v_labels[i]}]" for i in range(n))
            v_cat = f"v_cat_{track.id}"
            filters.append(f"{concat_inputs}concat=n={n}:v=1:a=0[{v_cat}]")
            return v_cat, "", sum(durations)

        if n == 1:
            return cut_v_labels[0], cut_a_labels[0], durations[0]

        if has_transitions:
            curr_v = cut_v_labels[0]
            curr_a = cut_a_labels[0]
            accum_dur = durations[0]

            for i in range(1, n):
                item = items[i]
                trans = item.transition
                trans_type = trans.type if trans else "fade"
                trans_name = XFADE_MAP.get(trans_type, "fade")
                trans_dur = (trans.duration_ms / 1000.0) if trans else 0.5
                d = min(trans_dur, min(durations[i - 1], durations[i]) * 0.45)
                d = max(0.05, d)

                offset = max(0.0, accum_dur - d)
                out_v = f"v_xf_{i}"
                out_a = f"a_xf_{i}"

                filters.append(
                    f"[{curr_v}][{cut_v_labels[i]}]xfade=transition={trans_name}:"
                    f"duration={d:.3f}:offset={offset:.3f}[{out_v}]"
                )
                filters.append(
                    f"[{curr_a}][{cut_a_labels[i]}]acrossfade=d={d:.3f}[{out_a}]"
                )

                curr_v = out_v
                curr_a = out_a
                accum_dur = accum_dur + durations[i] - d

            return curr_v, curr_a, accum_dur

        # Normal concatenation
        concat_inputs = "".join(f"[{cut_v_labels[i]}][{cut_a_labels[i]}]" for i in range(n))
        v_cat = f"v_cat_{track.id}"
        a_cat = f"a_cat_{track.id}"
        filters.append(f"{concat_inputs}concat=n={n}:v=1:a=1[{v_cat}][a_cat]")
        return v_cat, a_cat, sum(durations)

    def _compile_overlay_track(
        self,
        track: Track,
        base_v: str,
        filters: list[str],
        include_audio: bool = True,
    ) -> tuple[str, list[str]]:
        """Composite overlay items onto base_v. Returns (new_base_v, list_of_audio_labels)."""
        curr_base = base_v
        overlay_audios: list[str] = []

        for idx, item in enumerate(track.items):
            in_idx = self._register_input(item.source)
            has_a = self._audio_status[in_idx] and not track.muted
            src_w, src_h = self._meta_status[in_idx]

            in_s = item.src_in / 1000.0
            out_s = item.src_out / 1000.0
            tl_start = item.start / 1000.0
            tl_end = item.end / 1000.0

            # Trim overlay video
            v_ov_trim = f"v_ov_t_{track.id}_{idx}"
            filters.append(
                f"[{in_idx}:v]trim=start={in_s:.3f}:end={out_s:.3f},"
                f"setpts=PTS-STARTPTS+{tl_start:.3f}/TB[{v_ov_trim}]"
            )

            # Scale / grade overlay item if specified
            v_ov_ready = f"v_ov_r_{track.id}_{idx}"
            effects = item.effects or {}
            scale_w = int(effects.get("width", self.target_width))
            scale_h = int(effects.get("height", -2))
            ov_grade = item.grade or GradeSpec()

            ov_v_chain: list[str] = [f"scale={scale_w}:{scale_h}"]
            if ov_grade.preset != "none" or ov_grade.brightness != 0 or ov_grade.contrast != 1:
                ov_gr_lines = build_grade_filter("dummy_in", "dummy_out", ov_grade)
                # extract filter inside dummy labels
                core = ov_gr_lines[0].split("]")[1].split("[")[0]
                if core != "null":
                    ov_v_chain.append(core)

            filters.append(f"[{v_ov_trim}]{','.join(ov_v_chain)}[{v_ov_ready}]")

            # Composite onto curr_base with time enable
            v_ov_out = f"v_comp_{track.id}_{idx}"
            filters.append(
                f"[{curr_base}][{v_ov_ready}]overlay=x=(W-w)/2:y=(H-h)/2:"
                f"enable='between(t,{tl_start:.3f},{tl_end:.3f})':eof_action=pass[{v_ov_out}]"
            )
            curr_base = v_ov_out

            # Audio for overlay item
            if include_audio and has_a and item.volume > 0:
                a_ov_out = f"a_ov_{track.id}_{idx}"
                delay_ms = int(item.start)
                filters.append(
                    f"[{in_idx}:a]atrim=start={in_s:.3f}:end={out_s:.3f},asetpts=PTS-STARTPTS,"
                    f"adelay={delay_ms}|{delay_ms},volume={item.volume:.3f}[{a_ov_out}]"
                )
                overlay_audios.append(a_ov_out)

        return curr_base, overlay_audios

    def _compile_audio_track(
        self,
        track: Track,
        filters: list[str],
    ) -> list[str]:
        """Compile a dedicated audio track items into delayed, volume-adjusted audio labels."""
        if track.muted:
            return []

        audio_labels: list[str] = []
        for idx, item in enumerate(track.items):
            in_idx = self._register_input(item.source)
            if not self._audio_status[in_idx]:
                continue

            in_s = item.src_in / 1000.0
            out_s = item.src_out / 1000.0
            delay_ms = int(item.start)
            a_lbl = f"a_trk_{track.id}_{idx}"

            filters.append(
                f"[{in_idx}:a]atrim=start={in_s:.3f}:end={out_s:.3f},asetpts=PTS-STARTPTS,"
                f"adelay={delay_ms}|{delay_ms},volume={item.volume:.3f}[{a_lbl}]"
            )
            audio_labels.append(a_lbl)

        return audio_labels

    def _compile_captions(
        self,
        caption_tracks: list[Track],
        filters: list[str],
        base_v: str,
        tmp_dir: Path,
    ) -> tuple[str, Path | None]:
        """Compile caption items into an ASS subtitle file and add ass filter."""
        all_caption_items: list[Item] = []
        for trk in caption_tracks:
            if not trk.muted:
                all_caption_items.extend(trk.items)

        if not all_caption_items:
            return base_v, None

        all_caption_items.sort(key=lambda it: it.start)

        # Build RemappedWord items from caption items
        remapped_words: list[RemappedWord] = []
        for it in all_caption_items:
            text = it.text or ""
            if not text:
                continue
            start_s = it.start / 1000.0
            dur_s = max(0.1, (it.src_out - it.src_in) / 1000.0)
            end_s = start_s + dur_s
            remapped_words.append(RemappedWord(word=text, start=start_s, end=end_s))

        if not remapped_words:
            return base_v, None

        caption_spec = all_caption_items[0].caption_style or CaptionSpec()
        ass_builder = ASSBuilder(
            caption_spec=caption_spec,
            target_width=self.target_width,
            target_height=self.target_height,
        )

        tmp_dir.mkdir(parents=True, exist_ok=True)
        ass_path = tmp_dir / f"{self.timeline.id}_timeline_subs.ass"
        meta_title = None
        if isinstance(self.timeline.metadata, dict):
            meta_title = self.timeline.metadata.get("title")
        ass_builder.write_ass_file(
            output_file=ass_path,
            words=remapped_words,
            title=meta_title,
        )

        escaped_sub = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
        subbed_v = "v_subbed"
        filters.append(f"[{base_v}]ass='{escaped_sub}'[{subbed_v}]")
        return subbed_v, ass_path

    def build_filter_graph(
        self,
        tmp_dir: Path | None = None,
        include_audio: bool = True,
    ) -> tuple[str, str, str, Path | None]:
        """Construct the complete FFmpeg -filter_complex graph."""
        filters: list[str] = []
        tracks_by_type: dict[TrackType, list[Track]] = {
            TrackType.VIDEO: [],
            TrackType.OVERLAY: [],
            TrackType.AUDIO: [],
            TrackType.CAPTION: [],
        }

        for trk in self.timeline.tracks:
            tracks_by_type[trk.type].append(trk)

        # 1. Main Video Track
        main_video_tracks = tracks_by_type[TrackType.VIDEO]
        if main_video_tracks:
            base_v, base_a, _ = self._compile_video_track(
                main_video_tracks[0], filters, include_audio=include_audio
            )
        else:
            # Fallback black canvas
            dur = self.total_duration_seconds
            filters.append(
                f"color=c=black:s={self.target_width}x{self.target_height}:d={dur:.3f}[v_empty]"
            )
            if include_audio:
                filters.append(
                    f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                    f"atrim=start=0:end={dur:.3f},asetpts=PTS-STARTPTS[a_empty]"
                )
                base_a = "a_empty"
            else:
                base_a = ""
            base_v = "v_empty"

        # 2. Overlay Tracks
        curr_v = base_v
        overlay_audio_labels: list[str] = []
        for ov_track in tracks_by_type[TrackType.OVERLAY]:
            curr_v, ov_audios = self._compile_overlay_track(
                ov_track, curr_v, filters, include_audio=include_audio
            )
            overlay_audio_labels.extend(ov_audios)

        # 3. Dedicated Audio Tracks
        extra_audio_labels: list[str] = []
        if include_audio:
            for aud_track in tracks_by_type[TrackType.AUDIO]:
                extra_audios = self._compile_audio_track(aud_track, filters)
                extra_audio_labels.extend(extra_audios)

        # 4. Audio Mixdown
        final_a = ""
        if include_audio:
            all_audio_labels = (
                ([base_a] if base_a else [])
                + overlay_audio_labels
                + extra_audio_labels
            )
            if not all_audio_labels:
                final_a = ""
            elif len(all_audio_labels) == 1:
                final_a = all_audio_labels[0]
            else:
                final_a = "a_mixed"
                audio_inputs = "".join(f"[{lbl}]" for lbl in all_audio_labels)
                filters.append(
                    f"{audio_inputs}amix=inputs={len(all_audio_labels)}:duration=first:dropout_transition=0[{final_a}]"
                )

        # 5. Captions
        sub_tmp_dir = tmp_dir or self.output_path.parent
        caption_tracks = tracks_by_type[TrackType.CAPTION]
        final_v, sub_file = self._compile_captions(caption_tracks, filters, curr_v, sub_tmp_dir)

        filter_complex = ";".join(filters)
        return filter_complex, final_v, final_a, sub_file

    def build_command(
        self,
        with_progress: bool = False,
        tmp_dir: Path | None = None,
    ) -> tuple[list[str], Path | None]:
        """Generate the complete FFmpeg CLI execution command."""
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise FFmpegBuilderError("ffmpeg executable not found in PATH")

        # 1. Build filter graph (this also populates _source_inputs)
        filter_complex, final_v, final_a, sub_file = self.build_filter_graph(tmp_dir)

        # 2. Build inputs list ordered by input index
        sorted_inputs = sorted(self._source_inputs.values(), key=lambda t: t[0])
        input_args: list[str] = []
        for _, path in sorted_inputs:
            input_args.extend(["-i", str(path.resolve())])

        cmd = [ffmpeg_bin, "-y"]
        if with_progress:
            cmd.extend(["-progress", "pipe:1", "-nostats"])

        cmd.extend(input_args)
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", f"[{final_v}]",
            "-map", f"[{final_a}]",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            str(self.output_path.resolve()),
        ])

        return cmd, sub_file

    def run(
        self,
        timeout: float = 300.0,
        on_progress: Callable[[float], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """Execute the compiled FFmpeg command to render the timeline video."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        sub_file: Path | None = None

        try:
            cmd, sub_file = self.build_command(
                with_progress=(on_progress is not None),
                tmp_dir=self.output_path.parent,
            )
            total_dur = self.total_duration_seconds

            if on_progress is None:
                try:
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=timeout,
                    )
                except subprocess.CalledProcessError as e:
                    self.output_path.unlink(missing_ok=True)
                    raise FFmpegBuilderError(
                        f"FFmpeg timeline render failed ({e.returncode}): {e.stderr}"
                    ) from e
            else:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                stderr_lines: list[str] = []

                def drain_err() -> None:
                    if proc.stderr:
                        for err_line in iter(proc.stderr.readline, ""):
                            stderr_lines.append(err_line)

                t = threading.Thread(target=drain_err, daemon=True)
                t.start()

                if proc.stdout:
                    for line in iter(proc.stdout.readline, ""):
                        if cancel_check and cancel_check():
                            proc.kill()
                            self.output_path.unlink(missing_ok=True)
                            raise FFmpegBuilderError("Render cancelled by user")

                        line = line.strip()
                        if line.startswith("out_time_us="):
                            try:
                                us = int(line.split("=")[1])
                                curr_sec = us / 1_000_000.0
                                pct = min(99.0, max(0.0, (curr_sec / total_dur) * 100.0))
                                on_progress(round(pct, 1))
                            except (ValueError, IndexError):
                                pass
                        elif line.startswith("progress=end"):
                            on_progress(100.0)

                t.join(timeout=5.0)
                retcode = proc.wait(timeout=timeout)
                if retcode != 0:
                    err_msg = "".join(stderr_lines)[-800:]
                    self.output_path.unlink(missing_ok=True)
                    raise FFmpegBuilderError(
                        f"FFmpeg timeline render failed ({retcode}): {err_msg}"
                    )

                on_progress(100.0)

            if not self.output_path.is_file() or self.output_path.stat().st_size == 0:
                self.output_path.unlink(missing_ok=True)
                raise FFmpegBuilderError(f"Rendered file was not created: {self.output_path}")

            return self.output_path

        except Exception:
            self.output_path.unlink(missing_ok=True)
            raise
        finally:
            if sub_file and sub_file.exists():
                sub_file.unlink(missing_ok=True)

    def extract_frame(
        self,
        timestamp: float = 0.0,
        output_file: Path | str | None = None,
        timeout: float = 30.0,
    ) -> bytes:
        """Extract a single JPEG frame at a timeline timestamp (seconds)."""
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise FFmpegBuilderError("ffmpeg executable not found in PATH")

        sub_tmp_dir = Path(output_file).parent if output_file else self.output_path.parent
        filter_complex, final_v, _, sub_file = self.build_filter_graph(
            sub_tmp_dir, include_audio=False
        )

        sorted_inputs = sorted(self._source_inputs.values(), key=lambda t: t[0])
        input_args: list[str] = []
        for _, path in sorted_inputs:
            input_args.extend(["-i", str(path.resolve())])

        safe_t = max(0.0, timestamp)
        target = "pipe:1" if output_file is None else str(Path(output_file).resolve())
        cmd = [
            ffmpeg_bin,
            "-y",
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{final_v}]",
            "-an",
            "-ss",
            f"{safe_t:.3f}",
            "-vframes",
            "1",
            "-q:v",
            "2",
            "-f",
            "image2",
            target,
        ]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=timeout,
            )
            if output_file is not None:
                return Path(output_file).read_bytes()
            return res.stdout
        except subprocess.CalledProcessError as e:
            raise FFmpegBuilderError(f"Failed to extract timeline frame: {e.stderr}") from e
        finally:
            if sub_file and sub_file.exists():
                sub_file.unlink(missing_ok=True)
