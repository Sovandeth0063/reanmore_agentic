"""Measure backend turn stage latency with local audio and one worksheet image.

The script drives the real controller with the configured providers, so it
fails with the normal configuration error when ``.env`` is incomplete. It
prints durations only: never audio, images, transcripts, tutor text, or
credentials.

Usage (repository root)::

    python scripts/benchmark_turn.py --label before \
        --audio path/to/utterance.pcm --image docs/image.jpg --turns 3

``--audio`` is raw PCM16LE, mono, 16 kHz. ``--image`` is a JPEG.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

# Allow `python scripts/benchmark_turn.py` from the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import ConfigurationError, Settings  # noqa: E402
from server.contract import (  # noqa: E402
    ContractError,
    validate_audio,
    validate_image,
)

AUDIO_CONTENT_TYPE = "audio/l16"
IMAGE_CONTENT_TYPE = "image/jpeg"
CHOICE = "A1"


@dataclass
class Row:
    step: str
    stage: str
    milliseconds: float | None
    status: str = "ok"


def _read_file(path: str, kind: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        print(f"{kind}: FAIL (cannot read the given file)")
        return None


def _tool_rows(store, session_id: str, after_id: int):
    """Return (new highest tool id, rows) for one controller operation."""
    rows = store.connection.execute(
        "SELECT id, name, duration_ms, success FROM tool_calls "
        "WHERE session_id = ? AND id > ? ORDER BY id",
        (session_id, after_id),
    ).fetchall()
    if rows:
        after_id = rows[-1]["id"]
    return after_id, rows


def _run_step(store, session_id: str, step: str, after_id: int, operation):
    """Time one controller operation and collect its recorded stage rows."""
    started = time.perf_counter()
    status = "ok"
    try:
        operation()
    except ContractError as error:
        status = f"failed:{error.code}"
    except Exception as error:  # noqa: BLE001 - redact unexpected failures
        status = f"failed:{type(error).__name__}"
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after_id, tools = _tool_rows(store, session_id, after_id)
    rows = [
        Row(
            step,
            tool["name"],
            tool["duration_ms"],
            "ok" if tool["success"] else "failed",
        )
        for tool in tools
    ]
    rows.append(Row(step, "total", elapsed_ms, status))
    return after_id, elapsed_ms, status, rows


def _print_table(rows: list[Row]) -> None:
    step_width = max(18, *(len(row.step) for row in rows))
    stage_width = max(14, *(len(row.stage) for row in rows))
    print(
        f"{'Step':<{step_width}}  {'Stage':<{stage_width}}"
        f"  {'ms':>10}  Result"
    )
    print(
        f"{'-' * step_width}  {'-' * stage_width}  {'-' * 10}  {'-' * 10}"
    )
    for row in rows:
        duration = "-" if row.milliseconds is None else f"{row.milliseconds:.1f}"
        print(
            f"{row.step:<{step_width}}  {row.stage:<{stage_width}}"
            f"  {duration:>10}  {row.status}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure controller stage latency for one demo session."
    )
    parser.add_argument(
        "--audio", required=True, help="raw PCM16LE mono 16 kHz file"
    )
    parser.add_argument("--image", required=True, help="worksheet JPEG")
    parser.add_argument(
        "--turns", type=int, default=3, help="warm speech turns (default 3)"
    )
    parser.add_argument(
        "--label",
        choices=("before", "after"),
        default="after",
        help="which side of a change this run records",
    )
    args = parser.parse_args(argv)
    if args.turns < 1:
        parser.error("--turns must be at least 1")

    try:
        settings = Settings.from_environment()
    except ConfigurationError as error:
        print(f"Configuration: FAIL ({error})")
        return 1

    audio = _read_file(args.audio, "Audio")
    if audio is None:
        return 1
    image = _read_file(args.image, "Image")
    if image is None:
        return 1
    try:
        validate_audio(audio, AUDIO_CONTENT_TYPE)
        validate_image(image, IMAGE_CONTENT_TYPE, "review")
    except ContractError as error:
        print(f"Input: FAIL ({error.code})")
        return 1

    import httpx

    from agent.controller import TutorController
    from agent.lesson import load_lesson
    from agent.llm import OllamaClient
    from agent.memory import SessionStore
    from agent.stt import Transcriber
    from agent.vision import VisionClient
    from server.session_api import DEFAULT_LESSON_PATH

    rows: list[Row] = []
    store = SessionStore(settings.db_url)
    http = httpx.Client(timeout=10.0)
    session_id = "benchmark-" + uuid4().hex
    try:
        store.create(session_id)
        lesson = load_lesson(DEFAULT_LESSON_PATH)
        controller = TutorController(
            session_id,
            lesson=lesson,
            store=store,
            vision=VisionClient(settings, http=http),
            intent=OllamaClient(settings, http=http),
            transcriber=Transcriber(settings.whisper_model),
        )

        after_id = 0
        after_id, create_ms, _, create_rows = _run_step(
            store, session_id, "create", after_id, controller.create_response
        )
        rows.extend(create_rows)

        turn_totals: list[float] = []
        for index in range(1, args.turns + 1):
            step = f"turn {index}" + (" (cold)" if index == 1 else "")
            after_id, turn_ms, _, turn_rows = _run_step(
                store,
                session_id,
                step,
                after_id,
                lambda: controller.handle_audio(audio, AUDIO_CONTENT_TYPE),
            )
            rows.extend(turn_rows)
            turn_totals.append(turn_ms)

        after_id, _, review_status, review_rows = _run_step(
            store,
            session_id,
            "review",
            after_id,
            lambda: controller.handle_snapshot(
                image, IMAGE_CONTENT_TYPE, "review"
            ),
        )
        rows.extend(review_rows)

        state = store.get(session_id)
        if (
            review_status != "ok"
            or state is None
            or not state.placement_confirmed
        ):
            _print_report(args, rows, audio, image, create_ms, turn_totals, None)
            print(
                "Review did not confirm placement; the check stage was not timed."
            )
            return 1

        # The choice bypasses the intent model on purpose: the benchmark times
        # the check snapshot, not a fixed utterance's classification.
        after_id, _, choice_status, choice_rows = _run_step(
            store,
            session_id,
            "choice",
            after_id,
            lambda: controller.tutor.choose(CHOICE),
        )
        rows.extend(choice_rows)
        if choice_status != "ok":
            _print_report(args, rows, audio, image, create_ms, turn_totals, None)
            print("Exercise choice failed; the check stage was not timed.")
            return 1

        after_id, check_ms, _, check_rows = _run_step(
            store,
            session_id,
            "check",
            after_id,
            lambda: controller.handle_snapshot(
                image, IMAGE_CONTENT_TYPE, "check", CHOICE
            ),
        )
        rows.extend(check_rows)

        _print_report(args, rows, audio, image, create_ms, turn_totals, check_ms)
        return 0
    finally:
        try:
            store.delete(session_id)
        except OSError:
            pass
        http.close()
        store.close()


def _print_report(
    args,
    rows: list[Row],
    audio: bytes,
    image: bytes,
    create_ms: float,
    turn_totals: list[float],
    check_ms: float | None,
) -> None:
    print(f"Turn latency benchmark ({args.label})")
    print(
        f"{len(turn_totals)} turns, audio={len(audio)} bytes, "
        f"image={len(image)} bytes"
    )
    print()
    _print_table(rows)
    print()
    print(f"Cold turn total: {turn_totals[0]:.1f} ms")
    if len(turn_totals) > 1:
        warm = turn_totals[1:]
        print(f"Warm turn average: {sum(warm) / len(warm):.1f} ms")
    print(f"Create total: {create_ms:.1f} ms")
    if check_ms is not None:
        print(f"Check total: {check_ms:.1f} ms")
    print("Stage rows come from tool_calls.duration_ms; '-' means not recorded.")


if __name__ == "__main__":
    sys.exit(main())
