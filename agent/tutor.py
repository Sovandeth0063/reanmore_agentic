"""Small explicit state machine for the fixed worksheet flow."""

from dataclasses import dataclass
from enum import Enum
try:
    from enum import StrEnum
except ImportError:  # Python 3.10
    class StrEnum(str, Enum):
        """Minimal enum.StrEnum fallback for Python 3.10."""
        def __str__(self) -> str:
            return str(self.value)
from agent.calculator import (
    CheckResult,
    check_answer,
    evaluate,
    normalize,
    verified_numbers,
)
from agent.lesson import Exercise, Lesson, Step
from agent.memory import SessionStore
from agent.responses import (
    guidance_for,
    guard_numbers,
    placement_prompt,
    select_response,
    uncertain_prompt,
)
from agent.vision import (
    PLACEMENT_DIFFERENT_SHEET,
    PLACEMENT_MISSING,
    PLACEMENT_PARTIAL,
    PLACEMENT_READY,
    PLACEMENT_STATUSES,
    PLACEMENT_UNREADABLE,
    VISIBILITY_CLEAR,
    HandwritingRead,
    WorksheetParse,
)


class InvalidTransition(ValueError):
    """Raised when an event is invalid for the current state."""


class TutorState(StrEnum):
    GREETING = "Greeting"
    WAITING_FOR_PLACEMENT = "WaitingForPlacement"
    PARSE_WORKSHEET = "ParseWorksheet"
    PRESENT_LIST = "PresentList"
    CHOOSE_EXERCISE = "ChooseExercise"
    PRESENT_EXERCISE = "PresentExercise"
    STUDENT_WORKING = "StudentWorking"
    OBSERVE_WORK = "ObserveWork"
    CHECK_ANSWER = "CheckAnswer"
    GUIDE = "Guide"
    PRAISE = "Praise"
    NEXT_EXERCISE = "NextExercise"
    WRAP_UP = "WrapUp"
    RECOVER = "Recover"


# Mirrors docs/architecture/02-Architecture-ai-math-tutor.md §3.9 exactly.
# Guide and Praise return through StudentWorking/NextExercise; there are no
# shortcut edges into CheckAnswer or PresentExercise.
_TRANSITIONS = {
    (TutorState.GREETING, "start"): TutorState.PARSE_WORKSHEET,
    (TutorState.WAITING_FOR_PLACEMENT, "start"): TutorState.PARSE_WORKSHEET,
    (TutorState.PARSE_WORKSHEET, "parsed"): TutorState.PRESENT_LIST,
    (TutorState.PARSE_WORKSHEET, "parse_failed"): TutorState.WAITING_FOR_PLACEMENT,
    (TutorState.PRESENT_LIST, "presented"): TutorState.CHOOSE_EXERCISE,
    (TutorState.CHOOSE_EXERCISE, "choice_valid"): TutorState.PRESENT_EXERCISE,
    (TutorState.CHOOSE_EXERCISE, "choice_unclear"): TutorState.CHOOSE_EXERCISE,
    (TutorState.PRESENT_EXERCISE, "presented"): TutorState.STUDENT_WORKING,
    (TutorState.STUDENT_WORKING, "pause"): TutorState.OBSERVE_WORK,
    (TutorState.STUDENT_WORKING, "check"): TutorState.OBSERVE_WORK,
    (TutorState.OBSERVE_WORK, "read_confident"): TutorState.CHECK_ANSWER,
    (TutorState.OBSERVE_WORK, "read_unclear"): TutorState.GUIDE,
    (TutorState.OBSERVE_WORK, "vision_failed"): TutorState.RECOVER,
    (TutorState.CHECK_ANSWER, "correct"): TutorState.PRAISE,
    (TutorState.CHECK_ANSWER, "incorrect"): TutorState.GUIDE,
    (TutorState.CHECK_ANSWER, "vision_failed"): TutorState.RECOVER,
    (TutorState.GUIDE, "presented"): TutorState.STUDENT_WORKING,
    (TutorState.PRAISE, "more"): TutorState.NEXT_EXERCISE,
    (TutorState.PRAISE, "done"): TutorState.WRAP_UP,
    (TutorState.NEXT_EXERCISE, "choose"): TutorState.CHOOSE_EXERCISE,
    (TutorState.RECOVER, "resumed"): TutorState.STUDENT_WORKING,
}


def next_state(current: TutorState, event: str) -> TutorState:
    try:
        return _TRANSITIONS[(current, event)]
    except KeyError as error:
        raise InvalidTransition(f"{current.value} cannot handle {event}") from error


HANDWRITING_CONFIDENCE_THRESHOLD = 0.75


def is_uncertain_reading(
    reading: HandwritingRead | None,
    confidence_threshold: float = HANDWRITING_CONFIDENCE_THRESHOLD,
) -> bool:
    """True when a handwriting read cannot be graded as a clear answer."""
    if reading is None:
        return True
    if getattr(reading, "visibility", VISIBILITY_CLEAR) != VISIBILITY_CLEAR:
        return True
    value = reading.value
    if value is None or not str(value).strip():
        return True
    return reading.confidence < confidence_threshold


@dataclass(frozen=True)
class CheckOutcome:
    """A graded answer plus the mode and the step the tutor should prompt."""

    text: str
    result: CheckResult | None
    mode: str
    step: Step | None
    completed: bool


def _next_step_after(steps: tuple[Step, ...], answer: int | None) -> Step | None:
    """The authored step after the last one whose intermediate equals ``answer``.

    Matching the highest step follows ``guidance_for``: a child who skips an
    intermediate moves to the step after the one they actually reached.
    """
    if answer is None:
        return None
    matched = [
        step
        for step in steps
        if step.expected_intermediate is not None
        and step.expected_intermediate == answer
    ]
    if not matched:
        return None
    last_index = max(step.index for step in matched)
    later = [step for step in steps if step.index > last_index]
    return min(later, key=lambda step: step.index) if later else None


class TutorSession:
    """Coordinate fixed lesson responses, calculator checks, and session state."""

    def __init__(self, lesson: Lesson, memory: SessionStore, session_id: str) -> None:
        self.lesson = lesson
        self.memory = memory
        self.session_id = session_id
        if self.memory.get(session_id) is None:
            self.memory.create(session_id)
        saved = self.memory.get(session_id)
        if saved is not None and saved.chosen_exercise is not None:
            self.state = TutorState.STUDENT_WORKING
        elif saved is not None and saved.placement_confirmed:
            self.state = TutorState.CHOOSE_EXERCISE
        else:
            self.state = TutorState.WAITING_FOR_PLACEMENT

    def start(self, worksheet: WorksheetParse | None = None) -> str:
        if self.state not in {
            TutorState.GREETING,
            TutorState.WAITING_FOR_PLACEMENT,
        }:
            raise InvalidTransition("Session has already started")
        self.state = next_state(self.state, "start")
        placement = worksheet_placement(worksheet, self.lesson)
        if placement != PLACEMENT_READY:
            # A failed placement stays in the gate: no turn, no choice.
            self.state = next_state(self.state, "parse_failed")
            return placement_prompt(placement)
        self.state = next_state(self.state, "parsed")
        self.state = next_state(self.state, "presented")
        response = (
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice")
        )
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def request_placement(self, status: str) -> str:
        """Ask for a specific adjustment without unsetting an active session."""
        saved = self.memory.get(self.session_id)
        if saved is None or (
            saved.chosen_exercise is None and not saved.placement_confirmed
        ):
            self.state = TutorState.WAITING_FOR_PLACEMENT
        return placement_prompt(status)

    def choose(self, spoken_choice: str) -> str:
        if self.state == TutorState.NEXT_EXERCISE:
            self.state = next_state(self.state, "choose")
        if self.state != TutorState.CHOOSE_EXERCISE:
            raise InvalidTransition("Session is not ready for an exercise choice")
        candidates = self.lesson.choice_candidates(spoken_choice)
        self.memory.append_turn(self.session_id, "student", spoken_choice)
        if len(candidates) != 1:
            # An ambiguous "number two" asks for the section; an unsupported
            # choice asks again. Both stay in the choice state.
            self.state = next_state(self.state, "choice_unclear")
            response = (
                select_response("ask_section")
                if len(candidates) > 1
                else select_response("unclear")
            )
            self.memory.append_turn(self.session_id, "tutor", response)
            return response
        self.state = next_state(self.state, "choice_valid")
        exercise = self.lesson.get(candidates[0])
        # A new exercise starts a fresh step, so hint escalation starts over.
        self.memory.update(
            self.session_id,
            chosen_exercise=exercise.id,
            current_step=1,
            attempts=0,
        )
        self.state = next_state(self.state, "presented")
        response = select_response(
            f"present.{exercise.id}", problem=exercise.problem
        )
        step = exercise.steps[0] if exercise.steps else None
        if step is not None and guard_numbers(
            step.prompt, verified_numbers(exercise)
        ):
            response += " " + step.prompt
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def ask_step(self) -> str:
        """Repeat the current step prompt without changing or capturing state."""
        state = self.memory.get(self.session_id)
        if state is None or state.chosen_exercise is None:
            raise InvalidTransition("No exercise has been chosen")
        exercise = self.lesson.get(state.chosen_exercise)
        step = next(
            (step for step in exercise.steps if step.index == state.current_step),
            None,
        )
        if step is not None and guard_numbers(
            step.prompt, verified_numbers(exercise)
        ):
            response = step.prompt
        else:
            response = select_response("ask_step")
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def check(
        self, student_answer: int | str | None, step_index: int | None = None
    ) -> tuple[str, CheckResult | None]:
        outcome = self.check_with_mode(student_answer, step_index)
        return outcome.text, outcome.result

    def check_with_mode(
        self, student_answer: int | str | None, step_index: int | None = None
    ) -> CheckOutcome:
        """Grade an answer and say which mode the turn should use.

        The final answer wins over an intermediate: an early final answer
        completes the exercise instead of sending the child back to a step.
        A non-final intermediate advances the step and asks the next one. A
        wrong answer stays on the step, hinting first and explaining after the
        second attempt.
        """
        state = self.memory.get(self.session_id)
        if state is None or state.chosen_exercise is None:
            raise InvalidTransition("No exercise has been chosen")
        if self.state in {TutorState.PRAISE, TutorState.NEXT_EXERCISE}:
            # §3.9 gives Praise no check edge: ask for the next choice instead
            # of stalling or raising.
            return CheckOutcome(self._more_practice(), None, "noop", None, False)
        if self.state == TutorState.STUDENT_WORKING:
            # Every check passes through ObserveWork; a spoken answer is a
            # confident read.
            self.state = next_state(self.state, "check")
            self.state = next_state(self.state, "read_confident")
        if self.state != TutorState.CHECK_ANSWER:
            raise InvalidTransition("Session is not ready to check an answer")
        exercise = self.lesson.get(state.chosen_exercise)
        self.memory.append_tool_call(self.session_id, "calculator.check_answer")
        result = check_answer(exercise.verification_expression, student_answer)
        attempts = state.attempts + 1
        self.memory.update(
            self.session_id,
            attempts=attempts,
            last_answer=None if student_answer is None else str(student_answer),
        )
        self.memory.append_turn(
            self.session_id,
            "student",
            "" if student_answer is None else str(student_answer),
        )
        if result.correct:
            self.state = next_state(self.state, "correct")
            self.memory.update(
                self.session_id,
                current_step=(state.current_step or 0) + 1,
            )
            response = select_response(f"correct.{exercise.id}", praise=exercise.praise)
            self.memory.append_turn(self.session_id, "tutor", response)
            return CheckOutcome(response, result, "praise", None, True)
        next_step = _next_step_after(exercise.steps, result.student_answer)
        if next_step is not None:
            self._enter_guide()
            self.memory.update(
                self.session_id,
                current_step=next_step.index,
                attempts=0,
            )
            # The intermediate was correct, so its number may be spoken back
            # as part of the next vetted prompt; it is not a leaked answer.
            text = (
                next_step.prompt
                if guard_numbers(next_step.prompt, verified_numbers(exercise))
                else result.focus
            )
            self.memory.append_turn(self.session_id, "tutor", text)
            return CheckOutcome(text, result, "hint", next_step, False)
        self._enter_guide()
        response = select_response(f"incorrect.{exercise.id}", focus=result.focus)
        # A caller's requested step wins. Otherwise stay on the step the child
        # is actually working on, rather than the first step guidance guesses.
        guidance = guidance_for(
            exercise,
            result,
            step_index if step_index is not None else state.current_step,
        )
        response += " " + guidance
        self.memory.append_turn(self.session_id, "tutor", response)
        mode = "hint" if attempts == 1 else "explain"
        # Report the step that guidance_for actually prompted, not a guess.
        step = next(
            (step for step in exercise.steps if step.prompt == guidance),
            None,
        )
        return CheckOutcome(response, result, mode, step, False)

    def _enter_guide(self) -> None:
        """CheckAnswer --> Guide --> StudentWorking, using existing edges."""
        self.state = next_state(self.state, "incorrect")
        self.state = next_state(self.state, "presented")

    def begin_guided(self, worksheet: WorksheetParse | None = None) -> str:
        """Start the fixed worksheet in lesson order at A1.

        Placement still gates the flow: a failed parse returns its adjustment
        prompt and never presents an exercise. The choice question is not
        spoken in guided mode.
        """
        if self.state in {
            TutorState.GREETING,
            TutorState.WAITING_FOR_PLACEMENT,
        }:
            started = self.start(worksheet)
            if self.state != TutorState.CHOOSE_EXERCISE:
                return started
        if self.state != TutorState.CHOOSE_EXERCISE:
            raise InvalidTransition("Session is not ready to begin guided practice")
        first_id = self.lesson.exercises[0].id
        # choose() performs the existing transitions and records its own turn;
        # guided mode speaks this shorter lead-in instead of "Let's work on".
        self.choose(first_id)
        exercise = self.lesson.get(first_id)
        return (
            select_response("worksheet_summary")
            + f" Let's start with {first_id}: "
            + self._opening_line(exercise)
        )

    def advance_guided(self) -> str:
        """Present the next exercise in lesson order, or wrap up after B6.

        This composes Praise --> NextExercise --> ChooseExercise -->
        PresentExercise; it adds no transition edge.
        """
        state = self.memory.get(self.session_id)
        if state is None or state.chosen_exercise is None:
            raise InvalidTransition("No exercise has been completed")
        if self.state != TutorState.PRAISE:
            raise InvalidTransition("Session has no completed exercise to advance")
        ids = [exercise.id for exercise in self.lesson.exercises]
        try:
            position = ids.index(state.chosen_exercise)
        except ValueError as error:
            raise InvalidTransition(
                "The completed exercise is not in the lesson"
            ) from error
        if position + 1 >= len(ids):
            return self.wrap_up()
        next_id = ids[position + 1]
        # The choice question is discarded: guided mode speaks the next
        # exercise instead of "Let's work on".
        self.offer_next()
        self.choose(next_id)
        exercise = self.lesson.get(next_id)
        return f"Next is {next_id}: {self._opening_line(exercise)}"

    @staticmethod
    def _opening_line(exercise: Exercise) -> str:
        """The printed problem plus the first vetted step prompt.

        Short enough to speak quickly, and every number is authored: the same
        guard the choice path applies before it says a step prompt.
        """
        line = exercise.problem + "."
        step = exercise.steps[0] if exercise.steps else None
        if step is not None and guard_numbers(
            step.prompt, verified_numbers(exercise)
        ):
            line += " " + step.prompt
        return line

    def offer_next(self) -> str:
        if self.state == TutorState.PRAISE:
            self.state = next_state(self.state, "more")
        elif self.state != TutorState.NEXT_EXERCISE:
            # A premature "next" must still leave the session usable: wait in
            # NextExercise so the following choice resolves normally.
            self.state = TutorState.NEXT_EXERCISE
        response = select_response("ask_choice")
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def wrap_up(self) -> str:
        if self.state == TutorState.PRAISE:
            self.state = next_state(self.state, "done")
        else:
            # "I'm done" is terminal from any posture; never leave the student
            # stuck in a working state.
            self.state = TutorState.WRAP_UP
        response = select_response("wrap_up")
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def list_worksheet(self) -> str:
        if self.state == TutorState.NEXT_EXERCISE:
            self.state = next_state(self.state, "choose")
        if self.state != TutorState.CHOOSE_EXERCISE:
            raise InvalidTransition(
                "Session is waiting for a confirmed worksheet"
            )
        response = (
            select_response("worksheet_summary")
            + " "
            + select_response("ask_choice")
        )
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def resume(self) -> str:
        state = self.memory.get(self.session_id)
        if state is None or state.chosen_exercise is None:
            raise InvalidTransition("No exercise to resume")
        exercise = self.lesson.get(state.chosen_exercise)
        self.state = TutorState.STUDENT_WORKING
        response = select_response(f"present.{exercise.id}", problem=exercise.problem)
        step = next(
            (step for step in exercise.steps if step.index == state.current_step),
            None,
        )
        if step is not None and guard_numbers(
            step.prompt, verified_numbers(exercise)
        ):
            response += " " + step.prompt
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def continue_working(self) -> None:
        if self.state == TutorState.GUIDE:
            self.state = next_state(self.state, "presented")
            return
        if self.state == TutorState.PRAISE:
            # Praise has no table edge back to StudentWorking; this explicit
            # "next step" helper keeps the old API usable without a shortcut.
            self.state = TutorState.STUDENT_WORKING
            return
        raise InvalidTransition("Session has no feedback to continue")

    def check_handwriting(
        self,
        reading: HandwritingRead | None,
        confidence_threshold: float = 0.75,
        step_index: int | None = None,
    ) -> tuple[str, CheckResult | None]:
        outcome = self.check_handwriting_with_mode(
            reading, confidence_threshold, step_index
        )
        return outcome.text, outcome.result

    def check_handwriting_with_mode(
        self,
        reading: HandwritingRead | None,
        confidence_threshold: float = 0.75,
        step_index: int | None = None,
    ) -> CheckOutcome:
        """Read one handwritten answer and say which mode the turn uses.

        Mirrors ``check_handwriting``'s state handling, but reports a mode so a
        confident read is graded like the same spoken answer. An uncertain or
        failed read is a ``noop``: it never corrects, counts an attempt, or
        changes the exercise.
        """
        state = self.memory.get(self.session_id)
        if state is None or state.chosen_exercise is None:
            raise InvalidTransition("No exercise has been chosen")
        if self.state in {TutorState.PRAISE, TutorState.NEXT_EXERCISE}:
            return CheckOutcome(self._more_practice(), None, "noop", None, False)
        if self.state == TutorState.STUDENT_WORKING:
            self.state = next_state(self.state, "pause")
        if self.state != TutorState.OBSERVE_WORK:
            raise InvalidTransition("Session is not ready to read handwriting")
        if reading is None:
            # A provider failure is distinct from an uncertain read.
            self.state = next_state(self.state, "vision_failed")
            response = select_response("service_error")
            self.memory.append_turn(self.session_id, "tutor", response)
            return CheckOutcome(response, None, "noop", None, False)
        self.memory.update(
            self.session_id,
            last_confidence=reading.confidence,
        )
        if is_uncertain_reading(reading, confidence_threshold):
            self.state = next_state(self.state, "read_unclear")
            response = uncertain_prompt(
                getattr(reading, "visibility", VISIBILITY_CLEAR)
            )
            # Guide asks for a clearer answer and returns to working
            # immediately: an uncertain read never corrects, never increments
            # attempts, and never blocks a retry.
            self.state = next_state(self.state, "presented")
            self.memory.append_turn(self.session_id, "tutor", response)
            return CheckOutcome(response, None, "noop", None, False)
        self.state = next_state(self.state, "read_confident")
        return self.check_with_mode(reading.value, step_index)

    def recover(self, reason: str = "service") -> str:
        if self.state == TutorState.OBSERVE_WORK:
            self.state = next_state(self.state, "vision_failed")
        elif self.state == TutorState.CHECK_ANSWER:
            self.state = next_state(self.state, "vision_failed")
        state = self.memory.get(self.session_id)
        if state is not None and state.chosen_exercise is not None:
            if self.state == TutorState.RECOVER:
                self.state = next_state(self.state, "resumed")
            else:
                self.state = TutorState.STUDENT_WORKING
        else:
            # No exercise yet: a provider failure cannot bypass placement.
            self.state = TutorState.WAITING_FOR_PLACEMENT
        response = select_response("service_error" if reason == "service" else "unclear")
        self.memory.append_turn(self.session_id, "tutor", response)
        return response

    def _more_practice(self) -> str:
        if self.state == TutorState.PRAISE:
            return self.offer_next()
        response = select_response("ask_choice")
        self.memory.append_turn(self.session_id, "tutor", response)
        return response


def worksheet_placement(worksheet: WorksheetParse | None, lesson: Lesson) -> str:
    """Classify a parsed sheet against the fixed lesson.

    The lesson is the source of truth: a model expression is never adopted.
    """
    if worksheet is None:
        return PLACEMENT_MISSING
    try:
        return _placement_for(worksheet, lesson)
    except (AttributeError, TypeError, ValueError):
        return PLACEMENT_UNREADABLE


def _placement_for(worksheet: WorksheetParse, lesson: Lesson) -> str:
    placement = getattr(worksheet, "placement", PLACEMENT_READY)
    # An explicit, recognized non-ready status wins. A missing or unrecognized
    # placement ("unknown") is not evidence about the sheet, so it falls
    # through to the content checks below instead of failing the gate.
    if (
        isinstance(placement, str)
        and placement in PLACEMENT_STATUSES
        and placement != PLACEMENT_READY
    ):
        return placement
    if worksheet.confidence < 0.75:
        return PLACEMENT_UNREADABLE
    items = list(worksheet.items)
    if not items:
        return PLACEMENT_MISSING
    if len(items) < len(lesson.exercises):
        return PLACEMENT_PARTIAL
    if len(items) > len(lesson.exercises):
        return PLACEMENT_DIFFERENT_SHEET
    expected_ids = {exercise.id for exercise in lesson.exercises}
    seen: list[str] = []
    for item in items:
        item_id = item.item.strip().upper()
        if item_id not in expected_ids or item_id in seen:
            return PLACEMENT_DIFFERENT_SHEET
        seen.append(item_id)
    if set(seen) != expected_ids:
        return PLACEMENT_DIFFERENT_SHEET
    for item in items:
        exercise = lesson.get(item.item.strip().upper())
        if normalize(item.expression) != normalize(exercise.verification_expression):
            return PLACEMENT_DIFFERENT_SHEET
        result = evaluate(normalize(item.expression))
        if not result.ok or result.value != exercise.answer:
            return PLACEMENT_DIFFERENT_SHEET
    return PLACEMENT_READY


def _is_valid_worksheet(worksheet: WorksheetParse, lesson: Lesson) -> bool:
    """A parsed sheet must reproduce the fixed expressions and answers exactly."""
    return worksheet_placement(worksheet, lesson) == PLACEMENT_READY
