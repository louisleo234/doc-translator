"""Case-sensitive NFC matching, with Latin boundaries and CJK overlaps."""

import unicodedata
import time
from datetime import datetime, timezone
from threading import Event
from typing import Any


def _word_character(character: str) -> bool:
    return (
        character.isdecimal()
        or unicodedata.category(character).startswith("M")
        or "LATIN" in unicodedata.name(character, "")
    )


def _check_deadline(stop: Event | None, deadline: float | None) -> None:
    if (stop is not None and stop.is_set()) or (
        deadline is not None and time.monotonic() >= deadline
    ):
        raise TimeoutError("Terminology matching stopped")


def _first_match(
    text: str, source: str, stop: Event | None = None, deadline: float | None = None
) -> int | None:
    start = 0
    while (position := text.find(source, start)) >= 0:
        _check_deadline(stop, deadline)
        end = position + len(source)
        left_ok = (
            not _word_character(source[0])
            or position == 0
            or not _word_character(text[position - 1])
        )
        right_ok = (
            not _word_character(source[-1])
            or end == len(text)
            or not _word_character(text[end])
        )
        if left_ok and right_ok:
            return position
        start = position + 1
    return None


def _timestamp(value: Any) -> float:
    if not value:
        return float("-inf")
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class TerminologyMatcher:
    """Keep only matching winners while consuming bounded candidate pages."""

    def __init__(
        self, text: str, stop: Event | None = None, deadline: float | None = None
    ) -> None:
        self.text = unicodedata.normalize("NFC", text)
        self.stop = stop
        self.deadline = deadline
        self.matches: dict[str, tuple[tuple[Any, ...], int, dict[str, Any]]] = {}

    def consume(
        self, items: list[dict[str, Any]], catalog_id: str, priority: int
    ) -> None:
        for item in items:
            _check_deadline(self.stop, self.deadline)
            source = unicodedata.normalize("NFC", item["source_term"])
            if not source:
                continue
            position = _first_match(self.text, source, self.stop, self.deadline)
            if position is None:
                continue
            rank = (
                priority,
                -_timestamp(item.get("updated_at")),
                str(item.get("id", "")),
            )
            previous = self.matches.get(source)
            if previous is None or rank < previous[0]:
                result = dict(
                    source_term=item["source_term"],
                    target_term=item["target_term"],
                    catalog_id=catalog_id,
                )
                self.matches[source] = (rank, position, result)

    def result(self, max_results: int) -> dict[str, Any]:
        _check_deadline(self.stop, self.deadline)
        ordered = sorted(
            self.matches,
            key=lambda source: (self.matches[source][1], -len(source), source),
        )
        _check_deadline(self.stop, self.deadline)
        return dict(
            terms=[self.matches[s][2] for s in ordered[:max_results]],
            total_matches=len(ordered),
            truncated=len(ordered) > max_results,
        )
