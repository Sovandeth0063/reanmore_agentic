"""Fixed twelve-item layout for the printed grade-three sheet.

The layout is pure geometry: normalized 0-1 boxes for each rounded item box on
the upright reference sheet. It imports no imaging library, so the locator and
controller can validate a proposed area before any pixels are cropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

ITEM_IDS: tuple[str, ...] = tuple(
    f"{section}{number}" for section in "AB" for number in range(1, 7)
)
DEFAULT_LAYOUT_PATH = Path(__file__).with_name("worksheets") / "grade3_layout.yaml"

AREA_OK = "ok"
AREA_WRONG_ITEM = "wrong_item"
AREA_AMBIGUOUS = "ambiguous"
AREA_STATUSES = (AREA_OK, AREA_WRONG_ITEM, AREA_AMBIGUOUS)

# A proposed area is the selected item only when most of it sits inside that
# item's box and almost none of it reaches another item.
INSIDE_MIN = 0.60
OTHER_MAX = 0.10

_EPSILON = 1e-9


class LayoutError(ValueError):
    """Raised when the fixed layout is missing or malformed."""


@dataclass(frozen=True)
class SheetLayout:
    """The validated reference sheet and its twelve normalized item boxes."""

    reference_image: str
    note: str
    boxes: Mapping[str, tuple[float, float, float, float]]

    def expected_box(self, item_id: str) -> tuple[float, float, float, float]:
        key = str(item_id).strip().upper()
        try:
            return self.boxes[key]
        except KeyError as error:
            raise LayoutError(f"Unknown worksheet item: {item_id}") from error

    def validate_area(self, box, item_id: str) -> str:
        """Classify a proposed area for ``item_id``: ok, wrong item, ambiguous.

        Malformed, unordered, or out-of-range boxes are ``wrong_item`` so the
        caller asks for the sheet again instead of reading pixels.
        """
        target_key = str(item_id).strip().upper()
        if target_key not in self.boxes:
            return AREA_WRONG_ITEM
        candidate = _ordered_box(box)
        if candidate is None:
            return AREA_WRONG_ITEM
        area = _area(candidate)
        if area <= _EPSILON:
            return AREA_WRONG_ITEM
        inside = _overlap(candidate, self.boxes[target_key]) / area
        other = sum(
            _overlap(candidate, other_box) / area
            for key, other_box in self.boxes.items()
            if key != target_key
        )
        if inside >= INSIDE_MIN and other <= OTHER_MAX:
            return AREA_OK
        if inside < INSIDE_MIN:
            best_other = max(
                (
                    _overlap(candidate, other_box) / area
                    for key, other_box in self.boxes.items()
                    if key != target_key
                ),
                default=0.0,
            )
            if best_other >= INSIDE_MIN:
                return AREA_WRONG_ITEM
        return AREA_AMBIGUOUS


def load_layout(path: str | Path | None = None) -> SheetLayout:
    """Load and validate the fixed sheet layout."""
    source = DEFAULT_LAYOUT_PATH if path is None else Path(path)
    with source.open(encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise LayoutError("layout must be a mapping")
    reference = data.get("reference_image")
    if not isinstance(reference, str) or not reference.strip():
        raise LayoutError("layout must name the reference image")
    note = data.get("note")
    if not isinstance(note, str) or not note.strip():
        raise LayoutError("layout must describe the rectification step")
    items = data.get("items")
    if not isinstance(items, dict) or set(items) != set(ITEM_IDS):
        raise LayoutError("layout must define the fixed twelve items")
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for item_id in ITEM_IDS:
        box = _ordered_box(items[item_id])
        if box is None:
            raise LayoutError(f"layout box for {item_id} is not inside the sheet")
        boxes[item_id] = box
    return SheetLayout(reference.strip(), note.strip(), MappingProxyType(boxes))


def _ordered_box(box) -> tuple[float, float, float, float] | None:
    if isinstance(box, (str, bytes)) or not isinstance(box, (list, tuple)):
        return None
    if len(box) != 4:
        return None
    if not all(_number(value) for value in box):
        return None
    x0, y0, x1, y1 = (float(value) for value in box)
    if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
        return None
    return (x0, y0, x1, y1)


def _number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _area(box: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = box
    return (x1 - x0) * (y1 - y0)


def _overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> float:
    width = min(left[2], right[2]) - max(left[0], right[0])
    height = min(left[3], right[3]) - max(left[1], right[1])
    if width <= 0.0 or height <= 0.0:
        return 0.0
    return width * height
