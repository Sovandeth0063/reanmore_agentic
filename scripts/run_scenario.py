"""Run the IP3 homework scenario and write one JSON report per mode.

This is a harness, not product runtime. Text mode drives the real controller,
lesson, calculator, and tutor state machine in process with a checked-in
worksheet parse fixture. Voice mode drives the live backend and VoxPocket TTS
services over HTTP, resamples each synthesized line to the turn endpoint's
16 kHz PCM16, and reads the stage latencies the backend recorded in its SQLite
tool log.

Neither mode writes audio or images by default, and neither prints transcripts,
prompts, tutor text, or keys. ``--audio-dir`` is the one explicit exception: it
must be outside the repository and is never committed.

Usage (repository root)::

    py -3.10 scripts/run_scenario.py --mode text [--out PATH]
    py -3.10 scripts/run_scenario.py --mode voice [--out PATH] [--audio-dir DIR]
    py -3.10 scripts/run_scenario.py --mode both [--out PATH] [--audio-dir DIR]

Voice and both need the backend on ``http://127.0.0.1:8000`` and the TTS
service on ``http://127.0.0.1:8001``. The runner checks both health endpoints
and refuses to start a run when either is absent; it never starts a service.
When ``--out`` is omitted the report is written under the system temporary
directory, never inside the repository.
"""

from __future__ import annotations

import argparse
import audioop  # stdlib on the demo's Python 3.10; see to_turn_pcm().
import io
import json
import math
import re
import sqlite3
import sys
import tempfile
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

# Allow `python scripts/run_scenario.py` from the repository root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import yaml  # noqa: E402

from agent.calculator import check_answer  # noqa: E402
from agent.config import ConfigurationError, Settings  # noqa: E402
from agent.controller import TutorController  # noqa: E402
from agent.lesson import Lesson, load_lesson  # noqa: E402
from agent.memory import SessionStore  # noqa: E402
from agent.responses import numbers_in  # noqa: E402
from agent.stt import Transcript  # noqa: E402
from agent.vision import (  # noqa: E402
    PLACEMENT_READY,
    ParsedItem,
    WorksheetParse,
)
from server.contract import (  # noqa: E402
    AUDIO_FORM_FIELD,
    CAPTURE_REQUESTS,
    CAPTURE_REVIEW,
    EXERCISE_ID_FORM_FIELD,
    IMAGE_FORM_FIELD,
    MAX_AUDIO_BYTES,
    PURPOSE_FORM_FIELD,
    SESSION_CREATE_PATH,
    SESSION_END_PATH,
    SESSION_SNAPSHOT_PATH,
    SESSION_TURN_PATH,
)
from server.session_api import DEFAULT_LESSON_PATH  # noqa: E402

SCENARIO_PATH = ROOT / "scripts" / "scenarios" / "ip3_homework2.yaml"
FIXTURE_PATH = ROOT / "scripts" / "scenarios" / "ip3_worksheet.json"
TEXT_CONFIDENCE = 0.99
JPEG_CONTENT_TYPE = "image/jpeg"

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_TTS_URL = "http://127.0.0.1:8001"
# The turn endpoint accepts raw PCM16LE at 16 kHz; VoxPocket serves 44.1 kHz.
TURN_SAMPLE_RATE = 16000
TURN_AUDIO_CONTENT_TYPE = "audio/l16"
HEALTH_TIMEOUT_SECONDS = 5.0
# First synthesis loads the model and a full worksheet review is slow; neither
# is a hang, so the harness waits rather than failing a live run.
VOICE_TIMEOUT_SECONDS = 180.0

REQUIRED_MILESTONES: dict[str, bool] = {
    "worksheet_recognized": True,
    "all_12_covered": True,
    "auto_advanced": True,
    "final_answer_leaked": False,
}

_REQUIRED_SCENARIO_KEYS = ("name", "worksheet", "turns")
_EXERCISE_ID_TOKEN = re.compile(r"\b[AB][1-6]\b", re.IGNORECASE)


class ScenarioError(ValueError):
    """Raised when a scenario file cannot be used as written."""


class ServiceUnavailableError(ScenarioError):
    """A required local service is absent or unhealthy; the run did not start."""


class ServiceResponseError(ScenarioError):
    """A service refused or mangled a request; ``code`` is safe to report."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Scenario:
    """One ordered set of student lines for the fixed worksheet."""

    name: str
    worksheet: str
    turns: tuple[str, ...]
    path: Path | None = None


def load_scenario(path: str | Path) -> Scenario:
    """Read and validate one scenario file.

    A missing required key, an empty turn list, or a turn without a student
    line is a clear :class:`ScenarioError` naming the problem, never a KeyError
    deep inside the runner.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:
        raise ScenarioError(f"Cannot read the scenario file: {target}") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ScenarioError(f"The scenario file is not valid YAML: {target}") from error
    if not isinstance(data, dict):
        raise ScenarioError(
            f"The scenario file must contain a mapping: {target}"
        )
    missing = [key for key in _REQUIRED_SCENARIO_KEYS if key not in data]
    if missing:
        raise ScenarioError(
            "The scenario is missing required key(s): " + ", ".join(missing)
        )
    name = str(data["name"]).strip()
    if not name:
        raise ScenarioError("The scenario name must not be empty")
    worksheet = str(data["worksheet"]).strip()
    if not worksheet:
        raise ScenarioError("The scenario worksheet must not be empty")
    raw_turns = data["turns"]
    if not isinstance(raw_turns, (list, tuple)) or not raw_turns:
        raise ScenarioError("The scenario turns must be a non-empty list")
    turns = tuple(
        _student_line(entry, index)
        for index, entry in enumerate(raw_turns, start=1)
    )
    return Scenario(
        name=name,
        worksheet=worksheet,
        turns=turns,
        path=target,
    )


def _student_line(entry: object, index: int) -> str:
    if isinstance(entry, str):
        line = entry.strip()
    elif isinstance(entry, dict):
        value = entry.get("student")
        line = "" if value is None else str(value).strip()
    else:
        line = ""
    if not line:
        raise ScenarioError(f"Scenario turn {index} needs a student line")
    return line


def load_worksheet_fixture(path: str | Path | None = None) -> WorksheetParse:
    """Read the checked-in parse fixture as a :class:`WorksheetParse`."""
    target = Path(path) if path is not None else FIXTURE_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except OSError as error:
        raise ScenarioError(
            f"Cannot read the worksheet fixture: {target}"
        ) from error
    except json.JSONDecodeError as error:
        raise ScenarioError(
            f"The worksheet fixture is not valid JSON: {target}"
        ) from error
    if not isinstance(data, dict):
        raise ScenarioError(
            f"The worksheet fixture must contain an object: {target}"
        )
    items = data.get("items")
    confidence = data.get("confidence")
    if not isinstance(items, list) or not isinstance(confidence, (int, float)):
        raise ScenarioError(
            f"The worksheet fixture needs items and numeric confidence: {target}"
        )
    parsed: list[ParsedItem] = []
    for entry in items:
        if not isinstance(entry, dict) or not {
            "item",
            "section",
            "problem",
            "expression",
        } <= entry.keys():
            raise ScenarioError(
                f"The worksheet fixture has an invalid item: {target}"
            )
        parsed.append(
            ParsedItem(
                item=str(entry["item"]).strip().upper(),
                section=str(entry["section"]).strip().upper(),
                problem=str(entry["problem"]),
                expression=str(entry["expression"]),
            )
        )
    placement = str(data.get("placement") or PLACEMENT_READY)
    return WorksheetParse(
        items=parsed,
        confidence=float(confidence),
        placement=placement,
        reason=str(data.get("reason") or "")[:160],
    )


@dataclass(frozen=True)
class WavClip:
    """One decoded PCM16 WAV: the bytes, its format, and its duration."""

    pcm: bytes
    sample_rate: int
    channels: int
    sample_width: int
    seconds: float


def read_wav(data: bytes) -> WavClip:
    """Decode one TTS WAV without trusting its rate, channels, or length.

    VoxPocket serves mono 44.1 kHz PCM16, but the harness accepts any PCM16
    layout so a future voice can change its rate without breaking the runner.
    The bytes are decoded in memory; nothing is written.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise ScenarioError(
                    "The TTS service returned compressed WAV audio; PCM16 is required"
                )
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError) as error:
        raise ScenarioError(
            "The TTS service returned audio that is not a readable WAV file"
        ) from error
    if width != 2 or channels not in (1, 2) or rate <= 0:
        raise ScenarioError(
            "The TTS service returned a WAV that is not 16-bit mono or stereo PCM"
        )
    if not pcm:
        raise ScenarioError("The TTS service returned an empty WAV file")
    seconds = len(pcm) / (width * channels * rate)
    return WavClip(
        pcm=pcm,
        sample_rate=rate,
        channels=channels,
        sample_width=width,
        seconds=seconds,
    )


def to_turn_pcm(clip: WavClip) -> bytes:
    """Downmix and resample one clip to 16 kHz mono PCM16LE for ``/turn``.

    ``audioop`` is a stdlib module on the demo's Python 3.10; its C loop is
    used only here and only for short tutor lines. Channels are averaged and
    the rate is converted with the module's default filter, which is more than
    enough for speech-to-text input. No file or provider is involved.
    """
    frames = clip.pcm
    if clip.channels > 1:
        frames = audioop.tomono(frames, clip.sample_width, 0.5, 0.5)
    if clip.sample_rate != TURN_SAMPLE_RATE:
        frames, _ = audioop.ratecv(
            frames,
            clip.sample_width,
            1,
            clip.sample_rate,
            TURN_SAMPLE_RATE,
            None,
        )
    if len(frames) % 2:
        frames = frames[:-1]
    return frames


def trim_turn_pcm(pcm: bytes) -> tuple[bytes, bool]:
    """Trim one student clip to the turn contract's maximum audio length.

    A TTS badcase can synthesize an overlong line; posting it untrimmed makes
    the backend answer 413 and the whole voice run stops. The cut is a whole
    number of 16-bit samples, so the payload stays valid PCM16. The boolean is
    the per-turn ``student_audio_truncated`` report field.
    """
    limit = MAX_AUDIO_BYTES - (MAX_AUDIO_BYTES % 2)
    if len(pcm) <= limit:
        return pcm, False
    return pcm[:limit], True


def check_services(backend, tts) -> None:
    """Fail before the first turn when a required voice service is absent.

    The runner never starts a service. Each health method raises
    :class:`ServiceUnavailableError` naming its URL, so ``main`` can print one
    clear line instead of a traceback.
    """
    backend.health()
    tts.health()


class HttpBackend:
    """The live backend client: the HTTP contract plus the tool-timing log.

    The backend owns the session and records one ``tool_calls`` row per stage.
    This class talks to the HTTP API and reads those rows from the backend's
    own SQLite database. Tests substitute a fake with the same surface.
    """

    def __init__(
        self,
        client,
        *,
        base_url: str = DEFAULT_BACKEND_URL,
        db_url: str,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.db_path = _sqlite_path(db_url)

    def health(self) -> None:
        """Probe the FastAPI app; the backend exposes no dedicated /health."""
        try:
            response = self.client.get(
                self.base_url + "/openapi.json",
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as error:
            raise _unreachable("backend session API", self.base_url) from error
        if response.status_code != 200:
            raise ServiceUnavailableError(
                f"The backend session API at {self.base_url} is not ready "
                f"(HTTP {response.status_code}). Start it before running voice mode."
            )

    def create_session(self) -> dict[str, Any]:
        data = self._post(SESSION_CREATE_PATH, operation="create")
        return _response_fields(data, "create")

    def turn(self, session_id: str, pcm: bytes) -> dict[str, Any]:
        data = self._post(
            SESSION_TURN_PATH.format(session_id=session_id),
            operation="turn",
            files={
                AUDIO_FORM_FIELD: (
                    "turn.pcm",
                    pcm,
                    TURN_AUDIO_CONTENT_TYPE,
                )
            },
        )
        return _response_fields(data, "turn")

    def snapshot(
        self,
        session_id: str,
        image: bytes,
        purpose: str,
        exercise_id: str | None = None,
    ) -> dict[str, Any]:
        fields = {PURPOSE_FORM_FIELD: purpose}
        if exercise_id:
            fields[EXERCISE_ID_FORM_FIELD] = exercise_id
        data = self._post(
            SESSION_SNAPSHOT_PATH.format(session_id=session_id),
            operation="snapshot",
            files={
                IMAGE_FORM_FIELD: (
                    "worksheet.jpg",
                    image,
                    JPEG_CONTENT_TYPE,
                )
            },
            data=fields,
        )
        return _response_fields(data, "snapshot")

    def end_session(self, session_id: str) -> None:
        """Best-effort cleanup; the backend also prunes old sessions."""
        try:
            self.client.delete(
                self.base_url + SESSION_END_PATH.format(session_id=session_id),
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError):
            return

    def tool_rows(
        self, session_id: str, after_id: int
    ) -> tuple[int, list[Any]]:
        """Return the highest row id and the tool rows recorded after it.

        The runner and the backend share ``DB_URL``; reading the committed rows
        after each HTTP response is how STT, intent, render, and vision
        durations reach the report. Only the five tool columns are selected:
        no transcript, prompt, or provider text is read.
        """
        rows = self._read(
            "SELECT id, name, duration_ms, success FROM tool_calls "
            "WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id),
        )
        if rows:
            after_id = rows[-1]["id"]
        return after_id, rows

    def session_state(self, session_id: str) -> dict[str, Any]:
        """The three backend session facts the report needs.

        Voice mode cannot call the controller in process, so the suite row is
        the authoritative view of the exercise, the graded answer, and the
        placement gate. No transcript or tutor text is read.
        """
        rows = self._read(
            "SELECT chosen_exercise, last_answer, placement_confirmed "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        if not rows:
            raise ServiceResponseError(
                "session_missing",
                "The backend session row was not found in DB_URL.",
            )
        row = rows[0]
        return {
            "chosen_exercise": row["chosen_exercise"],
            "last_answer": row["last_answer"],
            "placement_confirmed": bool(row["placement_confirmed"]),
        }

    def _read(self, sql: str, parameters: tuple[Any, ...]) -> list[Any]:
        """Read committed rows from the backend's own SQLite database."""
        if not self.db_path.is_file():
            raise ServiceResponseError(
                "db_missing",
                f"The backend database was not found at {self.db_path}. "
                "Start the backend with the same DB_URL the runner reads.",
            )
        try:
            connection = sqlite3.connect(str(self.db_path), timeout=5.0)
            connection.row_factory = sqlite3.Row
            try:
                return connection.execute(sql, parameters).fetchall()
            finally:
                connection.close()
        except sqlite3.Error as error:
            raise ServiceResponseError(
                "db_unreadable",
                "The backend database could not be read from DB_URL.",
            ) from error

    def _post(self, path: str, *, operation: str, **kwargs: Any) -> Any:
        try:
            response = self.client.post(
                self.base_url + path,
                timeout=VOICE_TIMEOUT_SECONDS,
                **kwargs,
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as error:
            raise _unreachable("backend session API", self.base_url) from error
        return _json_payload(response, operation)


class HttpTts:
    """The VoxPocket TTS client; it speaks but stores nothing."""

    def __init__(
        self, client, *, base_url: str = DEFAULT_TTS_URL
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    def health(self) -> None:
        try:
            response = self.client.get(
                self.base_url + "/health",
                timeout=HEALTH_TIMEOUT_SECONDS,
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as error:
            raise _unreachable("TTS service", self.base_url) from error
        if response.status_code != 200:
            raise ServiceUnavailableError(
                f"The TTS service at {self.base_url} is not healthy "
                f"(HTTP {response.status_code}). Start it before running voice mode."
            )

    def synthesize(self, text: str, voice_prompt: bool = True) -> bytes:
        """Return one ``audio/wav`` body; the caller decodes and resamples it.

        Tutor replies keep the designed voice prompt. Student scenario lines
        pass ``voice_prompt=False`` so the style prompt cannot distort a
        one-word utterance before speech-to-text sees it.
        """
        try:
            response = self.client.post(
                self.base_url + "/tts",
                json={"text": text, "voice_prompt": voice_prompt},
                timeout=VOICE_TIMEOUT_SECONDS,
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as error:
            raise _unreachable("TTS service", self.base_url) from error
        if response.status_code >= 400:
            code = _response_error_code(response)
            detail = f", {code}" if code else ""
            raise ServiceResponseError(
                f"tts_http_{response.status_code}",
                "The TTS service refused a speech line "
                f"(HTTP {response.status_code}{detail}).",
            )
        if not response.content:
            raise ServiceResponseError(
                "tts_empty", "The TTS service returned empty audio."
            )
        return response.content


def _unreachable(service: str, url: str) -> ServiceUnavailableError:
    return ServiceUnavailableError(
        f"The {service} is not reachable at {url}. "
        "Start it before running voice mode."
    )


def _json_payload(response, operation: str) -> Any:
    """Decode one backend JSON body, reporting only the status and code."""
    if response.status_code >= 400:
        code = _response_error_code(response)
        detail = f", {code}" if code else ""
        raise ServiceResponseError(
            f"http_{response.status_code}",
            f"The backend refused the {operation} request "
            f"(HTTP {response.status_code}{detail}).",
        )
    try:
        return response.json()
    except ValueError as error:
        raise ServiceResponseError(
            "unreadable_response",
            f"The backend returned an unreadable {operation} response.",
        ) from error


def _response_error_code(response) -> str:
    """The contract error code, never the message or any request content."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return error["code"]
    return ""


def _response_fields(data: Any, operation: str) -> dict[str, Any]:
    """Keep only the contract response fields the report needs."""
    if not isinstance(data, dict):
        raise ServiceResponseError(
            "unreadable_response",
            f"The backend returned an unreadable {operation} response.",
        )
    session_id = data.get("session_id")
    tutor_text = data.get("tutor_text")
    status = data.get("status")
    if (
        not isinstance(session_id, str)
        or not session_id
        or not isinstance(tutor_text, str)
        or not isinstance(status, str)
        or not status
    ):
        raise ServiceResponseError(
            "unreadable_response",
            f"The backend returned an unreadable {operation} response.",
        )
    capture = data.get("capture_request")
    exercise = data.get("exercise_id")
    if capture is not None and capture not in CAPTURE_REQUESTS:
        raise ServiceResponseError(
            "unreadable_response",
            f"The backend returned an unknown capture request in its {operation} response.",
        )
    if exercise is not None and (
        not isinstance(exercise, str) or not exercise
    ):
        raise ServiceResponseError(
            "unreadable_response",
            f"The backend returned an invalid exercise id in its {operation} response.",
        )
    return {
        "session_id": session_id,
        "tutor_text": tutor_text,
        "status": status,
        "capture_request": capture,
        "exercise_id": exercise,
    }


def _sqlite_path(db_url: str) -> Path:
    """Resolve the backend's SQLite path from ``Settings.db_url``."""
    prefix = "sqlite:///"
    if not isinstance(db_url, str) or not db_url.startswith(prefix):
        raise ScenarioError(
            "Voice mode reads tool timings from SQLite; "
            "DB_URL must start with sqlite:///."
        )
    raw = db_url[len(prefix) :]
    if raw in {"", ":memory:"}:
        raise ScenarioError(
            "Voice mode needs the backend's file-backed DB_URL; "
            "an in-memory database has no tool log to read."
        )
    return Path(raw).expanduser().resolve()


class FixtureVision:
    """The text-mode worksheet seam: always returns the checked-in parse."""

    def __init__(self, worksheet: WorksheetParse | None = None) -> None:
        self.worksheet = worksheet or load_worksheet_fixture()
        self.parse_calls = 0

    def parse_worksheet(self, image_bytes: bytes) -> WorksheetParse:
        self.parse_calls += 1
        return self.worksheet

    def locate_answer_area(self, image_bytes: bytes, exercise: dict):
        # Text mode answers by voice; a check snapshot is not part of it.
        raise RuntimeError("text mode does not inspect handwriting")

    def read_handwriting(self, image_bytes: bytes, exercise: dict):
        raise RuntimeError("text mode does not inspect handwriting")


class _NoopTranscriber:
    """Text mode calls ``handle_transcript`` directly; audio is never decoded."""

    def transcribe(self, samples):
        raise RuntimeError("text mode has no audio")


class _RecordingVision:
    """Delegate to the provided vision and keep the last worksheet parse."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.parsed: WorksheetParse | None = None

    def parse_worksheet(self, image_bytes: bytes) -> WorksheetParse:
        parsed = self.inner.parse_worksheet(image_bytes)
        self.parsed = parsed
        return parsed

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


def run_text(
    scenario: Scenario,
    *,
    settings: Settings,
    store: SessionStore,
    vision,
    intent,
    renderer,
) -> dict[str, Any]:
    """Drive the scenario through the guided controller and return the report.

    ``settings`` is accepted for the shared text/voice entry point; text mode
    deliberately uses the injected fixture vision, intent client, and renderer
    instead of provider settings, so the run stays deterministic and offline.
    """
    lesson = load_lesson(DEFAULT_LESSON_PATH)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session_id = f"scenario-{scenario.name}-{uuid4().hex[:8]}"
    jpeg = _worksheet_jpeg(scenario.worksheet)
    recording_vision = _RecordingVision(vision)
    controller = TutorController(
        session_id,
        lesson=lesson,
        store=store,
        vision=recording_vision,
        intent=intent,
        transcriber=_NoopTranscriber(),
        renderer=renderer,
        flow_mode="guided",
    )
    exercise_ids = [exercise.id for exercise in lesson.exercises]

    turns: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    completed: set[str] = set()
    advances: list[bool] = []
    leaked = False
    review_confirmed = False
    worksheet_vision_ms: float | None = None
    after_id = 0

    try:
        for index, line in enumerate(scenario.turns, start=1):
            before = store.get(session_id)
            started = perf_counter()
            try:
                response = controller.handle_transcript(
                    Transcript(line, TEXT_CONFIDENCE)
                )
            except Exception as error:  # noqa: BLE001 - keep the run reportable
                errors.append(
                    {
                        "turn": index,
                        "stage": "transcript",
                        "error": type(error).__name__,
                    }
                )
                turns.append(_failed_turn(index, line))
                after_id, _ = _tool_rows(store, session_id, after_id)
                continue
            transcript_elapsed = (perf_counter() - started) * 1000.0
            after_id, transcript_rows = _tool_rows(store, session_id, after_id)

            snapshot_response = None
            snapshot_rows: list[Any] = []
            if response.capture_request:
                snapshot_started = perf_counter()
                try:
                    snapshot_response = controller.handle_snapshot(
                        jpeg, JPEG_CONTENT_TYPE, response.capture_request
                    )
                except Exception as error:  # noqa: BLE001 - keep the run reportable
                    errors.append(
                        {
                            "turn": index,
                            "stage": "snapshot",
                            "error": type(error).__name__,
                        }
                    )
                transcript_elapsed += (
                    perf_counter() - snapshot_started
                ) * 1000.0
                after_id, snapshot_rows = _tool_rows(
                    store, session_id, after_id
                )
                worksheet_vision_ms = _stage_ms(
                    snapshot_rows, "vision.parse_worksheet"
                )
                if snapshot_response is not None:
                    reviewed = store.get(session_id)
                    review_confirmed = bool(
                        reviewed is not None and reviewed.placement_confirmed
                    )

            after = store.get(session_id)
            turn = _turn_report(
                index,
                line,
                response,
                transcript_elapsed,
                transcript_rows,
                snapshot_response,
                snapshot_rows,
            )
            turns.append(turn)

            checked_id = _checked_exercise(before, transcript_rows)
            if checked_id is not None and after is not None:
                exercise = lesson.get(checked_id)
                result = check_answer(
                    exercise.verification_expression, after.last_answer
                )
                if result.correct:
                    completed.add(checked_id)
                    _track_advance(
                        advances,
                        exercise_ids,
                        checked_id,
                        response.exercise_id,
                    )

            current = after.chosen_exercise if after is not None else None
            if _leaks_answer(response.tutor_text, current, completed, lesson):
                leaked = True
            if snapshot_response is not None and _leaks_answer(
                snapshot_response.tutor_text, current, completed, lesson
            ):
                leaked = True
    finally:
        store.delete(session_id)

    turns.sort(key=lambda turn: turn["index"])
    worksheet = recording_vision.parsed
    worksheet_items = len(worksheet.items) if worksheet is not None else 0
    worksheet_placement = (
        worksheet.placement if worksheet is not None else "unknown"
    )
    worksheet_recognized = bool(
        worksheet is not None
        and worksheet.placement == PLACEMENT_READY
        and worksheet_items == len(lesson.exercises)
        and review_confirmed
    )
    totals = [turn["total_ms"] for turn in turns]
    return {
        "scenario": scenario.name,
        "mode": "text",
        "started_at": started_at,
        "worksheet": {
            "vision_ms": worksheet_vision_ms,
            "placement": worksheet_placement,
            "items": worksheet_items,
        },
        "turns": turns,
        "summary": {
            "turns": len(turns),
            "total_ms": round(sum(totals), 1),
            "turn_p50_ms": _percentile(totals, 0.50),
            "turn_p95_ms": _percentile(totals, 0.95),
            "tutor_audio_seconds": 0.0,
        },
        "milestones": {
            "worksheet_recognized": worksheet_recognized,
            "all_12_covered": set(exercise_ids) <= completed,
            "auto_advanced": (
                len(advances) >= len(exercise_ids) - 1
                and all(advances)
                and set(exercise_ids) <= completed
            ),
            "final_answer_leaked": leaked,
        },
        "errors": errors,
    }


def run_voice(
    scenario: Scenario,
    *,
    http,
    tts,
    audio_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Drive the scenario through the live backend and TTS services.

    ``http`` is the backend client (``HttpBackend`` in production, a fake in
    tests) and owns the HTTP calls plus the session's tool-timing rows. ``tts``
    synthesizes each line; its health is checked before the first turn. Both
    student lines and every tutor reply are synthesized, and the tutor's WAV
    duration is what the report's ``tts_ms`` / ``audio_seconds`` describe.
    ``audio_dir`` is the only way any audio is written, and it must be outside
    the repository.
    """
    directory = _audio_dir(audio_dir) if audio_dir is not None else None
    check_services(http, tts)

    lesson = load_lesson(DEFAULT_LESSON_PATH)
    exercise_ids = [exercise.id for exercise in lesson.exercises]
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jpeg = _worksheet_jpeg(scenario.worksheet)

    session = http.create_session()
    session_id = session["session_id"]
    greeting: dict[str, Any] | None = None

    turns: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    completed: set[str] = set()
    advances: list[bool] = []
    leaked = False
    review_confirmed = False
    worksheet_vision_ms: float | None = None
    exercises_seen: set[str] = set()
    tutor_audio_seconds = 0.0
    after_id = 0

    try:
        # The backend's create response is spoken in the browser too;
        # synthesize and record it so the report covers every tutor reply,
        # not just the scenario turns.
        greeting_tts_ms, greeting_seconds, greeting_wav = _speak(
            tts, session["tutor_text"]
        )
        if directory is not None and greeting_wav:
            _save_audio(directory, "greeting-tutor.wav", greeting_wav)
        greeting = {
            "tutor_text": session["tutor_text"],
            "status": session["status"],
            "capture_request": session["capture_request"],
            "exercise_id": session["exercise_id"],
            "tts_ms": greeting_tts_ms,
            "audio_seconds": greeting_seconds,
        }
        tutor_audio_seconds += greeting_seconds
        if _leaks_answer(greeting["tutor_text"], None, completed, lesson):
            leaked = True

        for index, line in enumerate(scenario.turns, start=1):
            # The student line goes through VoxPocket, then the same 16 kHz PCM
            # the browser uploads. No transcript is synthesized locally.
            stage = "student-tts"
            try:
                # Plain student speech: the tutor voice prompt distorts a
                # one-word answer. Tutor replies below keep it.
                student_wav = tts.synthesize(line, voice_prompt=False)
                if directory is not None:
                    _save_audio(
                        directory,
                        f"turn-{index:02d}-student.wav",
                        student_wav,
                    )
                pcm = to_turn_pcm(read_wav(student_wav))
                # A long TTS student line must not become a 413.
                pcm, student_audio_truncated = trim_turn_pcm(pcm)

                stage = "turn"
                before_state = http.session_state(session_id)
                turn_started = perf_counter()
                response = http.turn(session_id, pcm)
                after_id, rows = http.tool_rows(session_id, after_id)
                stt_ms = _stage_ms(rows, "stt.transcribe")
                if stt_ms is None:
                    raise ServiceResponseError(
                        "timings_missing",
                        "The backend tool log has no STT timing for this turn; "
                        "check that DB_URL matches the backend.",
                    )
                intent_ms = _stage_ms(
                    rows, "intent.interpret", "intent.fast_path"
                )
                render_ms = _stage_ms(rows, "tutor.render")
            except ScenarioError as error:
                errors.append(_error_entry(index, stage, error))
                break

            turn: dict[str, Any] = {
                "index": index,
                "student_text": line,
                "student_audio_truncated": student_audio_truncated,
                "stt_ms": stt_ms,
                "intent_ms": intent_ms,
                "render_ms": render_ms,
                "tutor_text": response["tutor_text"],
                "status": response["status"],
                "capture_request": response["capture_request"],
                "exercise_id": response["exercise_id"],
                "tts_ms": None,
                "audio_seconds": None,
                "total_ms": 0.0,
            }
            turns.append(turn)

            try:
                tts_ms, seconds, tutor_wav = _speak(
                    tts, response["tutor_text"]
                )
            except ScenarioError as error:
                errors.append(_error_entry(index, "tutor-tts", error))
                turn["total_ms"] = round(
                    (perf_counter() - turn_started) * 1000.0, 1
                )
                break
            turn["tts_ms"] = tts_ms
            turn["audio_seconds"] = seconds
            tutor_audio_seconds += seconds
            if directory is not None and tutor_wav:
                _save_audio(
                    directory, f"turn-{index:02d}-tutor.wav", tutor_wav
                )

            snapshot_response = None
            snapshot_rows: list[Any] = []
            reviewed_sheet = response["capture_request"] == CAPTURE_REVIEW
            stage = "snapshot"
            try:
                if response["capture_request"]:
                    snapshot_response = http.snapshot(
                        session_id,
                        jpeg,
                        response["capture_request"],
                        response["exercise_id"],
                    )
                    after_id, snapshot_rows = http.tool_rows(
                        session_id, after_id
                    )
                    vision_ms = _stage_ms(
                        snapshot_rows, "vision.parse_worksheet"
                    )
                    stage = "snapshot-tts"
                    snap_tts_ms, snap_seconds, snap_wav = _speak(
                        tts, snapshot_response["tutor_text"]
                    )
                    tutor_audio_seconds += snap_seconds
                    if directory is not None and snap_wav:
                        suffix = "review" if reviewed_sheet else "check"
                        _save_audio(
                            directory,
                            f"turn-{index:02d}-{suffix}-tutor.wav",
                            snap_wav,
                        )
                    turn["snapshot"] = {
                        "vision_ms": vision_ms,
                        "tutor_text": snapshot_response["tutor_text"],
                        "status": snapshot_response["status"],
                        "capture_request": snapshot_response[
                            "capture_request"
                        ],
                        "exercise_id": snapshot_response["exercise_id"],
                        "tts_ms": snap_tts_ms,
                        "audio_seconds": snap_seconds,
                    }
                stage = "state"
                after_state = http.session_state(session_id)
            except ScenarioError as error:
                errors.append(_error_entry(index, stage, error))
                turn["total_ms"] = round(
                    (perf_counter() - turn_started) * 1000.0, 1
                )
                break

            if reviewed_sheet:
                worksheet_vision_ms = _stage_ms(
                    snapshot_rows, "vision.parse_worksheet"
                )
                # A successful review no longer asks for the sheet.
                review_confirmed = (
                    snapshot_response is not None
                    and snapshot_response["capture_request"]
                    != CAPTURE_REVIEW
                    and bool(after_state["placement_confirmed"])
                )

            # Grade with the backend's own graded answer, not the scripted
            # line: a misheard voice turn must show up as a missing milestone.
            # A capture check records its calculator row under the snapshot.
            checked = _voice_checked(
                before_state["chosen_exercise"], rows + snapshot_rows
            )
            if checked is not None:
                exercise = lesson.get(checked)
                result = check_answer(
                    exercise.verification_expression,
                    after_state["last_answer"],
                )
                if result.correct:
                    completed.add(checked)
                    _track_advance(
                        advances,
                        exercise_ids,
                        checked,
                        after_state["chosen_exercise"],
                    )

            current = _known_exercise(
                after_state["chosen_exercise"], exercise_ids
            )
            if current is not None:
                exercises_seen.add(current)

            if _leaks_answer(
                response["tutor_text"], current, completed, lesson
            ):
                leaked = True
            if snapshot_response is not None and _leaks_answer(
                snapshot_response["tutor_text"],
                current,
                completed,
                lesson,
            ):
                leaked = True
            turn["total_ms"] = round(
                (perf_counter() - turn_started) * 1000.0, 1
            )
    finally:
        try:
            http.end_session(session_id)
        except Exception:  # noqa: BLE001 - cleanup must not mask the report
            pass

    turns.sort(key=lambda turn: turn["index"])
    totals = [turn["total_ms"] for turn in turns]
    worksheet_items = len(exercises_seen)
    return {
        "scenario": scenario.name,
        "mode": "voice",
        "started_at": started_at,
        "worksheet": {
            "vision_ms": worksheet_vision_ms,
            "placement": "ready" if review_confirmed else "unknown",
            # The HTTP response carries no item count. A normal guided run
            # presents all twelve in lesson order, so this is the number of
            # distinct exercises the backend actually presented.
            "items": worksheet_items,
        },
        "greeting": greeting,
        "turns": turns,
        "summary": {
            "turns": len(turns),
            "total_ms": round(sum(totals), 1),
            "turn_p50_ms": _percentile(totals, 0.50),
            "turn_p95_ms": _percentile(totals, 0.95),
            "tutor_audio_seconds": round(tutor_audio_seconds, 2),
        },
        "milestones": {
            "worksheet_recognized": (
                review_confirmed
                and worksheet_items == len(lesson.exercises)
            ),
            "all_12_covered": set(exercise_ids) <= completed,
            "auto_advanced": (
                len(advances) >= len(exercise_ids) - 1
                and all(advances)
                and set(exercise_ids) <= completed
            ),
            "final_answer_leaked": leaked,
        },
        "errors": errors,
    }


def compare_reports(
    text_report: dict[str, Any], voice_report: dict[str, Any]
) -> dict[str, Any]:
    """Compare structure, never exact wording: text and voice can rephrase.

    The LLM renderer is not reproducible and voice transcribes speech, so only
    ``status``, ``capture_request``, ``exercise_id``, and the milestones are
    compared. ``text_diff_count`` is the number of differing structural values
    (plus one for a differing turn count); ``diffs`` names each one without
    copying any tutor text.
    """
    diffs: list[dict[str, Any]] = []
    text_turns = text_report.get("turns", [])
    voice_turns = voice_report.get("turns", [])
    if len(text_turns) != len(voice_turns):
        diffs.append(
            {
                "turn": None,
                "field": "turn_count",
                "text": len(text_turns),
                "voice": len(voice_turns),
            }
        )
    for index in range(min(len(text_turns), len(voice_turns))):
        text_turn = text_turns[index]
        voice_turn = voice_turns[index]
        for field in ("status", "capture_request", "exercise_id"):
            if text_turn.get(field) != voice_turn.get(field):
                diffs.append(
                    {
                        "turn": index + 1,
                        "field": field,
                        "text": text_turn.get(field),
                        "voice": voice_turn.get(field),
                    }
                )
    text_milestones = text_report.get("milestones", {})
    voice_milestones = voice_report.get("milestones", {})
    milestones_match = True
    for name in sorted(set(text_milestones) | set(voice_milestones)):
        if text_milestones.get(name) != voice_milestones.get(name):
            milestones_match = False
            diffs.append(
                {
                    "turn": None,
                    "field": "milestones." + name,
                    "text": text_milestones.get(name),
                    "voice": voice_milestones.get(name),
                }
            )
    return {
        "text_diff_count": len(diffs),
        "diffs": diffs,
        "milestones_match": milestones_match,
        "turn_count": {
            "text": len(text_turns),
            "voice": len(voice_turns),
        },
    }


def build_both_report(
    text_report: dict[str, Any],
    voice_report: dict[str, Any],
    *,
    configured_renderer: str = "template",
) -> dict[str, Any]:
    """Combine the two passes and their structural comparison in one file.

    The text pass is pinned to the template renderer; the voice pass runs in
    the backend, which uses whatever ``TUTOR_RENDERER`` the services were
    started with. ``configured_renderer`` records that assumption from the
    runner's own environment; it does not override the backend.
    """
    errors: list[dict[str, Any]] = []
    for mode, report in (("text", text_report), ("voice", voice_report)):
        for error in report.get("errors", []):
            errors.append({"mode": mode, **error})
    comparison = compare_reports(text_report, voice_report)
    return {
        "scenario": text_report.get("scenario") or voice_report.get("scenario"),
        "mode": "both",
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "renderers": {
            "text": "template",
            "voice": configured_renderer,
        },
        # Repeated at the top level for a one-field check; the full diff list
        # stays under comparison.
        "text_diff_count": comparison["text_diff_count"],
        "text": text_report,
        "voice": voice_report,
        "comparison": comparison,
        "errors": errors,
    }


def write_report(report: dict[str, Any], path: str | Path) -> None:
    """Write one JSON report, creating the parent directory when needed."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _worksheet_jpeg(spec: str) -> bytes:
    """Return JPEG bytes for the scenario worksheet.

    The fixture vision never looks at pixels, but the controller's contract
    still validates the image. A checked-in PNG is converted in memory; a JPEG
    is passed through unchanged. Nothing is written to disk.
    """
    path = Path(spec)
    if not path.is_absolute():
        path = ROOT / path
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ScenarioError(
            f"Cannot read the worksheet image: {path}"
        ) from error
    if data.startswith(b"\xff\xd8\xff"):
        return data
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=90)
            return buffer.getvalue()
    except Exception as error:  # noqa: BLE001 - any decode failure is fatal
        raise ScenarioError(
            f"Cannot convert the worksheet image to JPEG: {path.name}"
        ) from error


def _tool_rows(
    store: SessionStore, session_id: str, after_id: int
) -> tuple[int, list[Any]]:
    """Return the highest row id and the tool rows recorded after it."""
    rows = store.connection.execute(
        "SELECT id, name, duration_ms, success FROM tool_calls "
        "WHERE session_id = ? AND id > ? ORDER BY id",
        (session_id, after_id),
    ).fetchall()
    if rows:
        after_id = rows[-1]["id"]
    return after_id, rows


def _stage_ms(rows: list[Any], *names: str) -> float | None:
    """The last recorded duration for one stage, rounded to 0.1 ms."""
    values = [
        row["duration_ms"]
        for row in rows
        if row["name"] in names and row["duration_ms"] is not None
    ]
    if not values:
        return None
    return round(float(values[-1]), 1)


def _turn_report(
    index: int,
    line: str,
    response,
    elapsed_ms: float,
    transcript_rows: list[Any],
    snapshot_response,
    snapshot_rows: list[Any],
) -> dict[str, Any]:
    turn: dict[str, Any] = {
        "index": index,
        "student_text": line,
        "stt_ms": None,
        "intent_ms": _stage_ms(
            transcript_rows, "intent.interpret", "intent.fast_path"
        ),
        "render_ms": _stage_ms(transcript_rows, "tutor.render"),
        "tutor_text": response.tutor_text,
        "status": response.status,
        "capture_request": response.capture_request,
        "exercise_id": response.exercise_id,
        "tts_ms": None,
        "audio_seconds": None,
        "total_ms": round(elapsed_ms, 1),
    }
    if snapshot_response is not None:
        # The snapshot is a worksheet event, not a student turn: it stays
        # nested so every tutor reply is recorded without inflating the count.
        turn["snapshot"] = {
            "vision_ms": _stage_ms(snapshot_rows, "vision.parse_worksheet"),
            "tutor_text": snapshot_response.tutor_text,
            "status": snapshot_response.status,
            "capture_request": snapshot_response.capture_request,
            "exercise_id": snapshot_response.exercise_id,
        }
    return turn


def _failed_turn(index: int, line: str) -> dict[str, Any]:
    return {
        "index": index,
        "student_text": line,
        "stt_ms": None,
        "intent_ms": None,
        "render_ms": None,
        "tutor_text": "",
        "status": "error",
        "capture_request": None,
        "exercise_id": None,
        "tts_ms": None,
        "audio_seconds": None,
        "total_ms": 0.0,
    }


def _checked_exercise(before, transcript_rows: list[Any]) -> str | None:
    """The exercise graded this turn, or None when no check happened."""
    if before is None or before.chosen_exercise is None:
        return None
    if not any(row["name"] == "calculator.check_answer" for row in transcript_rows):
        return None
    return before.chosen_exercise


def _track_advance(
    advances: list[bool],
    exercise_ids: list[str],
    checked_id: str,
    response_exercise_id: str | None,
) -> None:
    """Record whether completing ``checked_id`` presented the next exercise."""
    position = exercise_ids.index(checked_id)
    if position + 1 >= len(exercise_ids):
        return
    advances.append(response_exercise_id == exercise_ids[position + 1])


def _leaks_answer(
    text: str,
    exercise_id: str | None,
    completed: set[str],
    lesson: Lesson,
) -> bool:
    """True when a tutor line speaks any unsolved exercise's final answer.

    The line is about ``exercise_id``, so that exercise's authored problem and
    step prompts are stripped first: reciting "4 + 5 + 6" is not leaking a
    final answer, even though the text contains B4/B6's answer 5. Exercise id
    tokens are stripped too, so "B4 is five" is judged by "five", not by the
    id's digit. The remaining numbers are checked against every exercise still
    unsolved, which catches B6's printed answer, its own problem's answer, and
    cross-item leaks. A just-earned answer is excluded because its exercise is
    already in ``completed``.
    """
    cleaned = text
    if exercise_id is not None:
        exercise = lesson.get(exercise_id)
        authored = [exercise.problem]
        authored.extend(step.prompt for step in exercise.steps)
        for value in sorted(authored, key=len, reverse=True):
            if value:
                cleaned = re.sub(
                    re.escape(value), " ", cleaned, flags=re.IGNORECASE
                )
        cleaned = _EXERCISE_ID_TOKEN.sub(" ", cleaned)
    forbidden = {
        exercise.answer
        for exercise in lesson.exercises
        if exercise.id not in completed
    }
    return bool(numbers_in(cleaned) & forbidden)


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, so 16 turns report a real turn, not a blend."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return round(float(ordered[rank - 1]), 1)


def _audio_dir(value: str | Path) -> Path:
    """Resolve an explicit audio directory, refusing one inside the repository.

    Audio is never part of a report or a commit. The caller must name a
    directory outside the checkout; this creates it on demand.
    """
    target = Path(value).expanduser().resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        pass
    else:
        raise ScenarioError(
            "--audio-dir must be outside the repository; "
            "audio is never committed"
        )
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ScenarioError(
            f"Cannot create the audio directory: {target}"
        ) from error
    return target


def _save_audio(directory: Path, name: str, data: bytes) -> None:
    """Write one explicit ``--audio-dir`` file; never called by default."""
    try:
        (directory / name).write_bytes(data)
    except OSError as error:
        raise ScenarioError(
            f"Cannot write the requested audio file: {name}"
        ) from error


def _speak(
    tts, text: str, *, voice_prompt: bool = True
) -> tuple[float, float, bytes]:
    """Synthesize one tutor line: (ms, WAV seconds, WAV bytes)."""
    if not text.strip():
        return 0.0, 0.0, b""
    started = perf_counter()
    wav = tts.synthesize(text, voice_prompt=voice_prompt)
    elapsed_ms = (perf_counter() - started) * 1000.0
    clip = read_wav(wav)
    return round(elapsed_ms, 1), round(clip.seconds, 3), wav


def _voice_checked(current: str | None, rows: list[Any]) -> str | None:
    """The exercise graded this turn, or None when no check happened.

    Voice mode has no in-process controller state, so the calculator tool row
    is the evidence a check ran; the exercise is the one presented before the
    turn. ``rows`` includes the turn's snapshot rows when there was one.
    """
    if current is None:
        return None
    if not any(
        row["name"] == "calculator.check_answer" for row in rows
    ):
        return None
    return current


def _known_exercise(value: Any, exercise_ids: list[str]) -> str | None:
    """Return a lesson exercise id or None; never trust an arbitrary string."""
    if isinstance(value, str) and value in exercise_ids:
        return value
    return None


def _error_entry(turn: int, stage: str, error: Exception) -> dict[str, Any]:
    """One safe report error: stage, turn, and code/type, never provider text."""
    return {
        "turn": turn,
        "stage": stage,
        "error": getattr(error, "code", type(error).__name__),
    }


def _default_out(scenario: Scenario, mode: str) -> Path:
    directory = Path(tempfile.gettempdir()) / "ai-math-tutor-scenarios"
    return directory / f"{scenario.name}-{mode}.json"


def _report_ok(report: dict[str, Any]) -> bool:
    """Voice and text reports fail on errors or a required milestone."""
    if report.get("mode") == "both":
        return (
            not report.get("errors")
            and _report_ok(report.get("text", {}))
            and _report_ok(report.get("voice", {}))
        )
    if report.get("errors"):
        return False
    milestones = report.get("milestones", {})
    return all(
        milestones.get(name) is expected
        for name, expected in REQUIRED_MILESTONES.items()
    )


def _summary_line(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    milestones = report.get("milestones", {})
    line = (
        f"{summary.get('turns', 0)} turns | "
        f"worksheet {report.get('worksheet', {}).get('items', 0)} items | "
        f"all 12 covered: {milestones.get('all_12_covered')} | "
        f"auto-advanced: {milestones.get('auto_advanced')} | "
        f"answer leaked: {milestones.get('final_answer_leaked')} | "
        f"errors: {len(report.get('errors', []))}"
    )
    if report.get("mode") == "voice":
        line += (
            f" | tutor audio: {summary.get('tutor_audio_seconds', 0.0)} s"
            f" | p50: {summary.get('turn_p50_ms', 0.0)} ms"
            f" | p95: {summary.get('turn_p95_ms', 0.0)} ms"
        )
    return line


def _run_text_cli(
    scenario: Scenario, settings: Settings, http
) -> dict[str, Any]:
    """Run the text pass exactly as the text-only CLI does."""
    from agent.llm import build_intent_client
    from agent.render import TemplateRenderer

    store = SessionStore("sqlite:///:memory:")
    try:
        return run_text(
            scenario,
            settings=settings,
            store=store,
            vision=FixtureVision(),
            intent=build_intent_client(settings, http=http),
            renderer=TemplateRenderer(),
        )
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the IP3 homework scenario and write its JSON report."
    )
    parser.add_argument(
        "--mode",
        choices=("text", "voice", "both"),
        default="text",
        help=(
            "text uses the checked-in worksheet fixture (default); voice drives "
            "the live backend and TTS; both runs text then voice"
        ),
    )
    parser.add_argument(
        "--scenario",
        default=str(SCENARIO_PATH),
        help="scenario YAML path (default: scripts/scenarios/ip3_homework2.yaml)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="output JSON path (default: a file under the temporary directory)",
    )
    parser.add_argument(
        "--backend-url",
        default=DEFAULT_BACKEND_URL,
        help=f"backend base URL for voice mode (default: {DEFAULT_BACKEND_URL})",
    )
    parser.add_argument(
        "--tts-url",
        default=DEFAULT_TTS_URL,
        help=f"TTS base URL for voice mode (default: {DEFAULT_TTS_URL})",
    )
    parser.add_argument(
        "--audio-dir",
        default=None,
        help=(
            "optional directory outside the repository for the synthesized WAV "
            "files; no audio is written without it"
        ),
    )
    args = parser.parse_args(argv)
    if args.mode == "text" and args.audio_dir is not None:
        parser.error("--audio-dir is only used by voice or both mode")

    try:
        scenario = load_scenario(args.scenario)
    except ScenarioError as error:
        print(f"Scenario: FAIL ({error})")
        return 1
    try:
        settings = Settings.from_environment()
    except ConfigurationError as error:
        print(f"Configuration: FAIL ({error})")
        return 1

    client = httpx.Client(timeout=10.0)
    try:
        try:
            if args.mode == "text":
                report = _run_text_cli(scenario, settings, client)
            else:
                if settings.tutor_flow != "guided":
                    # Voice runs whatever flow the backend was started with.
                    # The scenario expects guided A1 -> B6, so say so plainly.
                    print(
                        "Warning: TUTOR_FLOW is not guided; the voice pass "
                        "follows the backend and may not cover A1-B6."
                    )
                backend = HttpBackend(
                    client,
                    base_url=args.backend_url,
                    db_url=settings.db_url,
                )
                tts = HttpTts(client, base_url=args.tts_url)
                if args.mode == "both":
                    # Fail before the text pass if a voice service is absent.
                    check_services(backend, tts)
                    text_report = _run_text_cli(
                        scenario, settings, client
                    )
                    voice_report = run_voice(
                        scenario,
                        http=backend,
                        tts=tts,
                        audio_dir=args.audio_dir,
                    )
                    report = build_both_report(
                        text_report,
                        voice_report,
                        configured_renderer=settings.tutor_renderer,
                    )
                else:
                    report = run_voice(
                        scenario,
                        http=backend,
                        tts=tts,
                        audio_dir=args.audio_dir,
                    )
        except ScenarioError as error:
            print(f"Scenario: FAIL ({error})")
            return 1
    finally:
        client.close()

    out = (
        Path(args.out)
        if args.out is not None
        else _default_out(scenario, args.mode)
    )
    try:
        write_report(report, out)
    except OSError:
        print("Report: FAIL (cannot write the output file)")
        return 1

    print(f"Report: {out}")
    if args.mode == "both":
        print("text: " + _summary_line(report["text"]))
        print("voice: " + _summary_line(report["voice"]))
        print(
            "structural diffs: "
            f"{report['comparison']['text_diff_count']}"
        )
    else:
        print(_summary_line(report))
    return 0 if _report_ok(report) else 1


if __name__ == "__main__":
    sys.exit(main())
