"""Safe arithmetic evaluation and answer verification."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.lesson import Exercise


@dataclass(frozen=True)
class EvalResult:
    ok: bool
    value: int | None
    expression: str
    error: str | None


@dataclass(frozen=True)
class CheckResult:
    correct: bool
    expected: int | None
    student_answer: int | None
    error_type: str
    focus: str


@dataclass(frozen=True)
class Step:
    index: int
    prompt: str
    expected_intermediate: int | None


def evaluate(expression: str) -> EvalResult:
    try:
        tree = ast.parse(expression, mode="eval")
        value = _evaluate_node(tree.body)
    except ZeroDivisionError:
        return EvalResult(False, None, expression, "division_by_zero")
    except (SyntaxError, TypeError, ValueError):
        return EvalResult(False, None, expression, "malformed_expression")
    return EvalResult(True, value, expression, None)


def _evaluate_node(node: ast.AST) -> int:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in {
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
    }:
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0 or left % right:
            raise ValueError("division_not_integer")
        return left // right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_evaluate_node(node.operand)
    raise ValueError("unsupported_expression")


_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_TENS_WORDS = {
    word: value
    for word, value in _NUMBER_WORDS.items()
    if value >= 20 and value % 10 == 0
}


def parse_number(value: object) -> int | None:
    """Read an integer from digits or an English number word (0-100).

    Accepts ``15``, ``"15"``, ``"nine"``, ``"eighty-seven"``, ``"twenty one"``
    and ``"one hundred"``. Anything else, including ``None`` and ``bool``,
    returns ``None`` so callers can tell "unreadable" from a real answer.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    words = text.replace("-", " ").split()
    if len(words) == 1:
        return _NUMBER_WORDS.get(words[0])
    if len(words) == 2:
        tens, ones = words
        if tens in _TENS_WORDS and _NUMBER_WORDS.get(ones, 0) in range(1, 10):
            return _TENS_WORDS[tens] + _NUMBER_WORDS[ones]
        if tens in {"one", "a"} and ones == "hundred":
            return 100
    return None


def check_answer(expression: str, student_answer: int | str | None) -> CheckResult:
    result = evaluate(expression)
    answer = _coerce_answer(student_answer)
    if not result.ok or answer is None or result.value is None:
        return CheckResult(False, None, None, "unreadable", "Please read the answer again.")
    if answer == result.value:
        return CheckResult(True, result.value, answer, "none", "")
    error_type = _answer_error_type(expression, answer, result.value)
    return CheckResult(False, result.value, answer, error_type, _focus(error_type))


def _coerce_answer(student_answer: int | str | None) -> int | None:
    return parse_number(student_answer)


_OPERATION_LABELS: dict[type, str] = {
    ast.Add: "addition_error",
    ast.Sub: "subtraction_error",
    ast.Mult: "multiplication_table_error",
    ast.Div: "division_error",
}


def _parse(expression: str) -> ast.expr | None:
    try:
        return ast.parse(expression, mode="eval").body
    except (SyntaxError, TypeError, ValueError):
        return None


def _error_type(expression: str) -> str:
    node = _parse(expression)
    if isinstance(node, ast.BinOp):
        label = _OPERATION_LABELS.get(type(node.op))
        if label is not None:
            return label
    return "wrong_operation"


def _answer_error_type(expression: str, answer: int, expected: int) -> str:
    if _is_digit_reversal(answer, expected):
        return "digit_reversal"
    if _has_carry(expression) or _has_borrow(expression):
        return "carry_borrow_error"
    operations = _operations(expression)
    if ast.Div in operations:
        return "division_error"
    if ast.Mult in operations:
        return "multiplication_table_error"
    if abs(answer - expected) == 1:
        return "off_by_one"
    return _error_type(expression)


def _is_digit_reversal(answer: int, expected: int) -> bool:
    digits = str(abs(expected))
    return len(digits) > 1 and str(abs(answer)) == digits[::-1]


def _operations(expression: str) -> set[type]:
    node = _parse(expression)
    if node is None:
        return set()
    return {
        type(item.op)
        for item in ast.walk(node)
        if isinstance(item, ast.BinOp) and type(item.op) in _OPERATION_LABELS
    }


def _flatten_chain(node: ast.expr, operation: type) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, operation):
        return _flatten_chain(node.left, operation) + _flatten_chain(node.right, operation)
    return [node]


def _ones_digit(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return abs(node.value) % 10
    return None


def _has_carry(expression: str) -> bool:
    node = _parse(expression)
    if node is None:
        return False
    operands = _flatten_chain(node, ast.Add)
    if len(operands) < 2:
        return False
    total = 0
    for operand in operands:
        ones = _ones_digit(operand)
        if ones is None:
            return False
        total += ones
    return total >= 10


def _has_borrow(expression: str) -> bool:
    node = _parse(expression)
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Sub):
        return False
    left = _ones_digit(node.left)
    right = _ones_digit(node.right)
    if left is None or right is None:
        return False
    return right > left


def _focus(error_type: str) -> str:
    return {
        "addition_error": "check the ones before the tens",
        "subtraction_error": "check each place from right to left",
        "multiplication_table_error": "think about equal groups",
        "division_error": "check the equal groups",
        "off_by_one": "count the last step carefully",
        "digit_reversal": "check the order of the digits",
        "carry_borrow_error": "check the regrouping in each place",
        "wrong_operation": "look at the operation sign",
    }.get(error_type, "check the next step")


def normalize(expression: str) -> str:
    """Canonical form for comparing a parsed expression with the fixed sheet."""
    text = "".join(expression.lower().split())
    return text.replace("×", "*").replace("÷", "/").replace("x", "*")


def steps_for(exercise: Exercise | dict) -> list[Step]:
    """The authored steps for an exercise.

    Production callers pass the fixed ``agent.lesson.Exercise``; the dict branch
    keeps the YAML shape usable for a standalone calculator test. Both return
    the same step fields, so guidance has one step model, not two.
    """
    if isinstance(exercise, dict):
        authored = exercise.get("steps")
        if authored:
            return [
                Step(
                    int(step["index"]),
                    str(step["prompt"]),
                    step.get("expected_intermediate"),
                )
                for step in authored
            ]
        result = evaluate(exercise["verification_expression"])
        return [
            Step(
                1,
                "Work through the operation carefully",
                result.value if result.ok else None,
            )
        ]
    return list(exercise.steps)


def verified_numbers(
    exercise: Exercise,
    check: CheckResult | None = None,
    *,
    include_answer: bool = True,
) -> set[int]:
    """Answer, printed operands, and verified step intermediates.

    The student's answer is never added, so the tutor cannot repeat a wrong
    number back to the child. ``include_answer=False`` drops the exercise
    answer as well, for an exercise the child has not solved yet, even when a
    step intermediate equals it.
    """
    values = {int(exercise.answer)}
    values.update(int(number) for number in re.findall(r"\d+", exercise.problem))
    for step in steps_for(exercise):
        if step.expected_intermediate is not None:
            values.add(int(step.expected_intermediate))
    if check is not None:
        if check.expected is not None:
            values.add(int(check.expected))
        if check.student_answer is not None:
            # Never hand a wrong number back to the child, even when it also
            # appears in the printed problem or an intermediate.
            values.discard(int(check.student_answer))
    if not include_answer:
        values.discard(int(exercise.answer))
    return values
