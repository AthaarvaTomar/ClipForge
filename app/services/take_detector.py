"""Service for detecting and grouping repeated takes using RapidFuzz (Milestone I3)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def _split_into_sentences(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segment word timestamp stream into sentence units."""
    if not words:
        return []

    sentences: list[dict[str, Any]] = []
    current_words: list[str] = []
    sent_start: float | None = None
    sent_end: float = 0.0

    for idx, w in enumerate(words):
        raw_word = str(w.get("word", "")).strip()
        if not raw_word:
            continue
        w_start = float(w.get("start", 0.0))
        w_end = float(w.get("end", w_start))

        if sent_start is None:
            sent_start = w_start

        current_words.append(raw_word)
        sent_end = w_end

        # Check pause to next word (> 1.2s gap implies boundary)
        has_pause = False
        if idx < len(words) - 1:
            next_start = float(words[idx + 1].get("start", w_end))
            if next_start - w_end > 1.2:
                has_pause = True

        is_terminal = bool(re.search(r"[.!?]$", raw_word))
        if is_terminal or has_pause or len(current_words) >= 20:
            text = " ".join(current_words).strip()
            if text:
                sentences.append(
                    {
                        "text": text,
                        "start_time": round(sent_start, 3),
                        "end_time": round(sent_end, 3),
                        "duration": round(max(0.1, sent_end - sent_start), 3),
                    }
                )
            current_words = []
            sent_start = None

    if current_words and sent_start is not None:
        text = " ".join(current_words).strip()
        if text:
            sentences.append(
                {
                    "text": text,
                    "start_time": round(sent_start, 3),
                    "end_time": round(sent_end, 3),
                    "duration": round(max(0.1, sent_end - sent_start), 3),
                }
            )

    return sentences


class RepeatedTakeService:
    """Detects repeated near-duplicate takes and selects the best take candidate."""

    @staticmethod
    def detect_repeated_takes(
        words: list[dict[str, Any]] | None = None,
        sentences: list[dict[str, Any]] | None = None,
        similarity_threshold: float = 65.0,
    ) -> list[dict[str, Any]]:
        """Group repeated adjacent sentences and identify the best take.

        Returns list of take groups:
        [{'group_id': 'grp_1', 'takes': [...], 'chosen_take_index': 1}]
        """
        try:
            from rapidfuzz import fuzz  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("rapidfuzz not installed; skipping repeated take detection")
            return []

        units = sentences if sentences is not None else _split_into_sentences(words or [])
        if len(units) < 2:
            return []

        take_groups: list[dict[str, Any]] = []
        visited = set()

        for i in range(len(units)):
            if i in visited:
                continue

            current_cluster: list[tuple[int, dict[str, Any]]] = [(i, units[i])]
            curr_text = re.sub(r"[^\w\s]", "", units[i]["text"]).lower().strip()

            # Check forward adjacent sentences (up to 4 sentences ahead)
            for j in range(i + 1, min(len(units), i + 6)):
                if j in visited:
                    continue

                candidate_text = re.sub(r"[^\w\s]", "", units[j]["text"]).lower().strip()
                score = fuzz.token_sort_ratio(curr_text, candidate_text)

                if score >= similarity_threshold:
                    current_cluster.append((j, units[j]))
                    visited.add(j)

            if len(current_cluster) >= 2:
                visited.add(i)
                group_id = f"take_grp_{uuid.uuid4().hex[:6]}"
                takes: list[dict[str, Any]] = []

                # Rank takes within group:
                # Criteria: Later take preference (production standard), length/completeness
                max_score = -1.0
                best_idx = 0

                for t_idx, (_, s_item) in enumerate(current_cluster):
                    word_count = len(s_item["text"].split())
                    # Base score from word count + position recency bonus
                    pos_bonus = (t_idx / len(current_cluster)) * 25.0
                    completeness_score = min(75.0, word_count * 5.0)
                    take_score = round(completeness_score + pos_bonus, 1)

                    is_best = False
                    if take_score > max_score:
                        max_score = take_score
                        best_idx = t_idx

                    takes.append(
                        {
                            "take_index": t_idx,
                            "text": s_item["text"],
                            "start_time": s_item["start_time"],
                            "end_time": s_item["end_time"],
                            "score": take_score,
                            "is_best": is_best,
                        }
                    )

                # Set is_best flag for chosen take
                for t in takes:
                    if t["take_index"] == best_idx:
                        t["is_best"] = True

                take_groups.append(
                    {
                        "group_id": group_id,
                        "takes": takes,
                        "chosen_take_index": best_idx,
                    }
                )

        return take_groups
