"""Provider-neutral tutor controller for the snapshot HTTP API.

The controller owns one tutor session and turns validated audio or image
bytes into one :class:`SessionResponse`. It composes the existing lesson,
memory, tutor, speech, intent, and vision modules and imports no transport
code. Raw media is only held in memory for the duration of a call.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import perf_counter
from typing import Protocol

from agent.image_ops import ImageError, sheet_crop
from agent.intent_parser import parse_clear_intent
from agent.lesson import Exercise, Lesson
from agent.llm import IntentError, TutorIntent
from agent.memory import SessionState, SessionStore
from agent.responses import placement_prompt, select_response
from agent.sheet_layout import (
    AREA_OK,
    LayoutError,
    SheetLayout,
    load_layout,
)
from agent.stt import STTError, Transcript, decode_pcm16le
from agent.tutor import (
    InvalidTransition,
    TutorSession,
    TutorState,
    is_uncertain_reading,
    worksheet_placement,
)
from agent.vision import (
    PLACEMENT_MISSING,
    PLACEMENT_READY,
    AnswerArea,
    HandwritingRead,
    VisionError,
    WorksheetParse,
)
from server.contract import (
    CAPTURE_CHECK,
    CAPTURE_REVIEW,
    STATUS_ADJUST_SHEET,
    STATUS_CHECKING_SHEET,
    STATUS_LISTENING,
    STATUS_READY,
    STATUS_READING_WORK,
    STATUS_SPEAKING,
    ContractError,
    SessionResponse,
    validate_audio,
    validate_image,
    validate_purpose,
)

_PROVIDER_ERRORS = (
    STTError,
    IntentError,
    VisionError,
    OSError,
    RuntimeError,
    ValueError,
)

# Direct (test or legacy) intents may still use the old names; the parser
# normalizes them too, but the controller must not depend on that.
_ALIASED_INTENTS = {"CHOOSE": "CHOOSE_EXERCISE"}

# A check that mentions the paper must start from a fresh snapshot, even when
# the utterance also contains a candidate number.
_WRITTEN_WORK_WORDS = ("write", "writing", "written", "paper", "sheet", "work")


def _mentions_written_work(transcript: str) -> bool:
    text = transcript.lower()
    return any(word in text for word in _WRITTEN_WORK_WORDS)


def _has_candidate(intent: TutorIntent) -> bool:
    return (
        intent.candidate_answer is not None
        and bool(str(intent.candidate_answer).strip())
    )


def _normalize_intent_name(intent: TutorIntent) -> str:
    name = intent.intent
    if name == "CHECK_ANSWER":
        return "CHECK_SPOKEN_ANSWER" if _has_candidate(intent) else "CHECK_WRITING"
    return _ALIASED_INTENTS.get(name, name)


class TranscriberLike(Protocol):
    def transcribe(self, samples: Sequence[float]) -> Transcript: ...


class IntentLike(Protocol):
    def interpret(
        self, transcript: str, state: dict, exercise: dict
    ) -> TutorIntent: ...


class VisionLike(Protocol):
    def parse_worksheet(self, image_bytes: bytes) -> WorksheetParse: ...

    def locate_answer_area(self, image_bytes: bytes, exercise: dict) -> AnswerArea: ...

    def read_handwriting(
        self, image_bytes: bytes, exercise: dict
    ) -> HandwritingRead: ...


class TutorController:
    """One tutor session behind the HTTP contract."""

    MIN_TRANSCRIPT_CONFIDENCE = 0.5

    def __init__(
        self,
        session_id: str,
        *,
        lesson: Lesson,
        store: SessionStore,
        vision: VisionLike,
        intent: IntentLike,
        transcriber: TranscriberLike,
        min_confidence: float | None = None,
        close: Callable[[], None] | None = None,
        layout: SheetLayout | None = None,
    ) -> None:
        self.session_id = session_id
        self.lesson = lesson
        self.store = store
        self.vision = vision
        self.intent = intent
        self.transcriber = transcriber
        self.layout = layout if layout is not None else load_layout()
        self.min_confidence = (
            self.MIN_TRANSCRIPT_CONFIDENCE
            if min_confidence is None
            else min_confidence
        )
        self._close = close
        self.tutor = TutorSession(lesson, store, session_id)

    def create_response(self) -> SessionResponse:
        state = self.store.get(self.session_id)
        if state is None:
            self.store.create(self.session_id)
            state = self._require_state()
        if state.chosen_exercise is not None:
            return self._response(
                self.tutor.resume(),
                STATUS_SPEAKING,
                exercise_id=state.chosen_exercise,
            )
        if state.placement_confirmed:
            return self._response(self.tutor.list_worksheet(), STATUS_LISTENING)
        return self._response(select_response("review_prompt"), STATUS_READY)

    def handle_audio(
        self, audio: bytes, content_type: str | None
    ) -> SessionResponse:
        data = validate_audio(audio, content_type)
        samples = decode_pcm16le(data)
        started = perf_counter()
        try:
            transcript = self.transcriber.transcribe(samples)
        except _PROVIDER_ERRORS as error:
            self._record_tool("stt.transcribe", started, error)
            return self._service_response(STATUS_LISTENING)
        self._record_tool("stt.transcribe", started)
        return self.handle_transcript(transcript)

    def handle_transcript(self, transcript: Transcript) -> SessionResponse:
        if (
            not transcript.text.strip()
            or transcript.confidence < self.min_confidence
        ):
            return self._response(select_response("unclear"), STATUS_LISTENING)
        state = self._require_state()
        # Unambiguous commands skip the model round trip; every other
        # utterance still reaches Ollama. The gates below are unchanged, so a
        # fast-path hit can neither choose before placement nor grade a spoken
        # number as handwriting.
        started = perf_counter()
        clear = parse_clear_intent(
            transcript.text,
            allow_choice=state.placement_confirmed
            and (
                state.chosen_exercise is None
                or self.tutor.state
                in {TutorState.CHOOSE_EXERCISE, TutorState.NEXT_EXERCISE}
            ),
        )
        if clear is not None:
            self._record_tool("intent.fast_path", started)
            return self._apply_intent(clear, transcript.text)
        exercise = self._exercise_payload_for(state)
        started = perf_counter()
        try:
            intent = self.intent.interpret(
                transcript.text,
                {
                    "state_block": self.store.state_block(self.session_id),
                    "attempts": state.attempts,
                },
                exercise,
            )
        except _PROVIDER_ERRORS as error:
            self._record_tool("ollama.interpret", started, error)
            return self._service_response(STATUS_LISTENING)
        self._record_tool("ollama.interpret", started)
        return self._apply_intent(intent, transcript.text)

    def handle_snapshot(
        self,
        image: bytes,
        content_type: str | None,
        purpose: str | None,
        exercise_id: str | None = None,
    ) -> SessionResponse:
        purpose = validate_purpose(purpose)
        data = validate_image(image, content_type, purpose)
        if purpose == CAPTURE_REVIEW:
            return self._handle_review(data)
        return self._handle_check(data, exercise_id)

    def end(self) -> None:
        try:
            self.store.delete(self.session_id)
        finally:
            self.close()

    def close(self) -> None:
        close = self._close
        self._close = None
        if close is not None:
            close()

    def _apply_intent(
        self, intent: TutorIntent, transcript: str
    ) -> SessionResponse:
        name = _normalize_intent_name(intent)
        state = self._require_state()
        if name == "REVIEW":
            return self._response(
                select_response("review_request"),
                STATUS_CHECKING_SHEET,
                capture_request=CAPTURE_REVIEW,
            )
        if name == "READY":
            if not state.placement_confirmed:
                return self._response(
                    select_response("review_request"),
                    STATUS_CHECKING_SHEET,
                    capture_request=CAPTURE_REVIEW,
                )
            if state.chosen_exercise is None:
                return self._response(self._summary(), STATUS_LISTENING)
            return self._response(
                select_response("ready_with_exercise"),
                STATUS_LISTENING,
                exercise_id=state.chosen_exercise,
            )
        if name == "CHOOSE_EXERCISE":
            if not state.placement_confirmed:
                return self._placement_retry(PLACEMENT_MISSING)
            # Prefer the structured exercise, then section plus number, then
            # the transcript. A bare number stays ambiguous in the tutor.
            spoken = intent.exercise_id
            if not spoken and intent.section is not None and intent.number is not None:
                spoken = f"{intent.section}{intent.number}"
            try:
                text = self.tutor.choose(spoken or transcript)
            except InvalidTransition as error:
                raise self._not_allowed(
                    "The tutor is not ready for an exercise choice"
                ) from error
            chosen = self._require_state().chosen_exercise
            # The tutor is presenting the problem and its first guiding step;
            # no capture is pending, so this is speech, not a work read.
            return self._response(
                text, STATUS_SPEAKING, exercise_id=chosen
            )
        if name == "ASK_STEP":
            if state.chosen_exercise is None:
                if not state.placement_confirmed:
                    return self._placement_retry(PLACEMENT_MISSING)
                return self._response(self._summary(), STATUS_LISTENING)
            try:
                text = self.tutor.ask_step()
            except InvalidTransition as error:
                raise self._not_allowed(
                    "The tutor is not ready for a step question"
                ) from error
            return self._response(
                text, STATUS_SPEAKING, exercise_id=state.chosen_exercise
            )
        if name in {"CHECK_WRITING", "CHECK_SPOKEN_ANSWER"}:
            if state.chosen_exercise is None:
                raise self._not_allowed(
                    "Choose an exercise before checking your answer"
                )
            if name == "CHECK_WRITING" or _mentions_written_work(transcript):
                # Written work always needs a fresh image, even when the
                # student also spoke a number. A spoken number is not paper
                # evidence.
                return self._response(
                    select_response("check_request"),
                    STATUS_READING_WORK,
                    capture_request=CAPTURE_CHECK,
                    exercise_id=state.chosen_exercise,
                )
            if not _has_candidate(intent):
                return self._response(
                    select_response("check_request"),
                    STATUS_READING_WORK,
                    capture_request=CAPTURE_CHECK,
                    exercise_id=state.chosen_exercise,
                )
            try:
                text, _ = self.tutor.check(
                    intent.candidate_answer, intent.guidance_step
                )
            except InvalidTransition as error:
                raise self._not_allowed(
                    "The tutor is not ready to check an answer"
                ) from error
            # A genuine spoken check is never described as a paper read.
            return self._response(
                select_response("spoken_only_fallback") + " " + text,
                STATUS_SPEAKING,
                exercise_id=state.chosen_exercise,
            )
        if name == "NEXT":
            if not state.placement_confirmed:
                # "Next" cannot move the tutor toward exercise choice before
                # the worksheet is confirmed.
                return self._placement_retry(PLACEMENT_MISSING)
            return self._response(self.tutor.offer_next(), STATUS_LISTENING)
        if name == "DONE":
            return self._response(self.tutor.wrap_up(), STATUS_SPEAKING)
        if name == "LIST_WORKSHEET":
            if not state.placement_confirmed:
                return self._placement_retry(PLACEMENT_MISSING)
            try:
                text = self.tutor.list_worksheet()
            except InvalidTransition:
                # A later poor retake can put the tutor back in the gate even
                # though an earlier sheet was confirmed; ask for it again.
                return self._placement_retry(PLACEMENT_MISSING)
            return self._response(text, STATUS_LISTENING)
        if name == "REPEAT":
            return self._response(
                select_response("repeat", text=self._last_tutor_text()),
                STATUS_SPEAKING,
                exercise_id=state.chosen_exercise,
            )
        if name == "OFF_TOPIC":
            return self._response(
                select_response("off_topic"),
                STATUS_LISTENING,
                exercise_id=state.chosen_exercise,
            )
        return self._response(
            select_response("unclear"),
            STATUS_LISTENING,
            exercise_id=state.chosen_exercise,
        )

    def _handle_review(self, image: bytes) -> SessionResponse:
        started = perf_counter()
        try:
            worksheet = self.vision.parse_worksheet(image)
        except _PROVIDER_ERRORS as error:
            self._record_tool("vision.parse_worksheet", started, error)
            return self._service_response(
                STATUS_ADJUST_SHEET, capture_request=CAPTURE_REVIEW
            )
        self._record_tool("vision.parse_worksheet", started)
        placement = worksheet_placement(worksheet, self.lesson)
        if placement != PLACEMENT_READY:
            # A poor photo asks for a specific adjustment and never advances.
            text = self.tutor.request_placement(placement)
            return self._response(
                text,
                STATUS_ADJUST_SHEET,
                capture_request=CAPTURE_REVIEW,
            )
        state = self._require_state()
        if state.chosen_exercise is not None:
            # A re-review during working re-presents the problem and step;
            # reading_work stays reserved for a pending written-work capture.
            self._confirm_placement(state)
            return self._response(
                self.tutor.resume(),
                STATUS_SPEAKING,
                exercise_id=state.chosen_exercise,
            )
        if self.tutor.state in {
            TutorState.GREETING,
            TutorState.WAITING_FOR_PLACEMENT,
        }:
            text = self.tutor.start(worksheet)
            self._confirm_placement(state)
            return self._response(text, STATUS_LISTENING)
        try:
            text = self.tutor.list_worksheet()
        except InvalidTransition as error:
            raise self._not_allowed(
                "The tutor is not ready to present the worksheet"
            ) from error
        self._confirm_placement(state)
        return self._response(text, STATUS_LISTENING)

    def _confirm_placement(self, state: SessionState) -> None:
        if not state.placement_confirmed:
            self.store.update(self.session_id, placement_confirmed=True)

    def _handle_check(
        self, image: bytes, exercise_id: str | None
    ) -> SessionResponse:
        state = self._require_state()
        if state.chosen_exercise is None:
            raise self._not_allowed(
                "Choose an exercise before checking your work"
            )
        if exercise_id is not None and exercise_id.strip():
            if exercise_id.strip().upper() != state.chosen_exercise:
                raise ContractError(
                    "invalid_request",
                    "exercise_id does not match the selected exercise",
                    400,
                )
        try:
            exercise = self.lesson.get(state.chosen_exercise)
        except ValueError as error:
            raise self._not_allowed(
                "The selected exercise is no longer available"
            ) from error
        payload = _handwriting_payload(exercise)
        started = perf_counter()
        try:
            area = self.vision.locate_answer_area(image, payload)
        except _PROVIDER_ERRORS as error:
            self._record_tool("vision.locate_answer_area", started, error)
            # A provider failure stays retryable; nothing is graded.
            return self._service_response(
                STATUS_READING_WORK,
                capture_request=CAPTURE_CHECK,
                exercise_id=state.chosen_exercise,
            )
        self._record_tool("vision.locate_answer_area", started)
        if area is None:
            return self._service_response(
                STATUS_READING_WORK,
                capture_request=CAPTURE_CHECK,
                exercise_id=state.chosen_exercise,
            )
        located_item = str(getattr(area, "item_id", "")).strip().upper()
        if located_item != state.chosen_exercise:
            # The locator answered for another item: ask for the sheet again.
            return self._wrong_area(state.chosen_exercise)
        try:
            verdict = self.layout.validate_area(area.box, state.chosen_exercise)
        except (LayoutError, TypeError, ValueError, AttributeError):
            verdict = ""
        if verdict != AREA_OK:
            return self._wrong_area(state.chosen_exercise)
        # The locator's box only confirms which item the answer belongs to.
        # Crop the fixed item rectangle so a model that returns just the
        # answer blank cannot drop the printed label and expression.
        selected_box = self.layout.expected_box(state.chosen_exercise)
        started = perf_counter()
        try:
            crop = sheet_crop(image, area.corners, selected_box)
        except ImageError as error:
            # A crop that cannot be tied to the item is never sent to OCR.
            self._record_tool("vision.sheet_crop", started, error)
            return self._wrong_area(state.chosen_exercise)
        self._record_tool("vision.sheet_crop", started)
        started = perf_counter()
        try:
            reading = self.vision.read_handwriting(crop, payload)
        except _PROVIDER_ERRORS as error:
            self._record_tool("vision.read_handwriting", started, error)
            # Do not transition the tutor: a provider failure stays retryable.
            return self._service_response(
                STATUS_READING_WORK,
                capture_request=CAPTURE_CHECK,
                exercise_id=state.chosen_exercise,
            )
        self._record_tool("vision.read_handwriting", started)
        if reading is None:
            # No visual evidence: keep the exercise and ask for another photo.
            return self._service_response(
                STATUS_READING_WORK,
                capture_request=CAPTURE_CHECK,
                exercise_id=state.chosen_exercise,
            )
        try:
            text, _ = self.tutor.check_handwriting(reading)
        except InvalidTransition as error:
            raise self._not_allowed(
                "The tutor is not ready to read handwriting"
            ) from error
        if is_uncertain_reading(reading):
            # Uncertain reads ask for a clearer answer and stay retryable.
            return self._response(
                text,
                STATUS_ADJUST_SHEET,
                capture_request=CAPTURE_CHECK,
                exercise_id=state.chosen_exercise,
            )
        return self._response(
            text, STATUS_SPEAKING, exercise_id=state.chosen_exercise
        )

    def _wrong_area(self, exercise_id: str) -> SessionResponse:
        """Ask for the sheet again without reading pixels or counting a try."""
        return self._response(
            select_response("reading_wrong_item"),
            STATUS_ADJUST_SHEET,
            capture_request=CAPTURE_CHECK,
            exercise_id=exercise_id,
        )

    def _summary(self) -> str:
        return (
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice")
        )

    def _placement_retry(self, status: str) -> SessionResponse:
        return self._response(
            placement_prompt(status),
            STATUS_ADJUST_SHEET,
            capture_request=CAPTURE_REVIEW,
        )

    def _service_response(
        self,
        status: str,
        capture_request: str | None = None,
        exercise_id: str | None = None,
    ) -> SessionResponse:
        return self._response(
            select_response("service_error"),
            status,
            capture_request=capture_request,
            exercise_id=exercise_id,
        )

    def _response(
        self,
        text: str,
        status: str,
        capture_request: str | None = None,
        exercise_id: str | None = None,
    ) -> SessionResponse:
        return SessionResponse(
            session_id=self.session_id,
            tutor_text=text,
            status=status,
            capture_request=capture_request,
            exercise_id=exercise_id,
        )

    def _require_state(self) -> SessionState:
        state = self.store.get(self.session_id)
        if state is None:
            raise ContractError("invalid_session", "Session not found", 404)
        return state

    def _exercise_payload_for(self, state: SessionState) -> dict:
        if state.chosen_exercise is None:
            return {}
        try:
            return _intent_exercise_payload(
                self.lesson.get(state.chosen_exercise)
            )
        except ValueError:
            return {}

    def _last_tutor_text(self) -> str:
        state = self.store.get(self.session_id)
        if state is None:
            return ""
        return next(
            (
                turn["text"]
                for turn in reversed(state.turns)
                if turn["role"] == "tutor"
            ),
            "",
        )

    def _record_tool(
        self, name: str, started: float, error: Exception | None = None
    ) -> None:
        self.store.append_tool_call(
            self.session_id,
            name,
            details="" if error is None else type(error).__name__,
            duration_ms=(perf_counter() - started) * 1000,
            success=error is None,
        )

    @staticmethod
    def _not_allowed(message: str) -> ContractError:
        return ContractError("not_allowed_in_state", message, 409)


def _intent_exercise_payload(exercise: Exercise) -> dict:
    """Classification sees the work to guide, never the answer or intermediates."""
    return {
        "id": exercise.id,
        "problem": exercise.problem,
        "steps": [
            {"index": step.index, "prompt": step.prompt}
            for step in exercise.steps
        ],
    }


def _handwriting_payload(exercise: Exercise) -> dict:
    """The selected item's printed work, never its answer or intermediates."""
    return {
        "id": exercise.id,
        "section": exercise.section,
        "item": exercise.item,
        "problem": exercise.problem,
        "expression": exercise.verification_expression,
        "answer_area": (
            f"the answer space for item {exercise.id} "
            f"in section {exercise.section}"
        ),
    }
