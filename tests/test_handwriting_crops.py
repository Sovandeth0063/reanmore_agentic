"""Selected-work crop tests on the reference sheet and synthetic drawings.

These tests build a synthetic camera photo from ``docs/image.png``: the
reference sheet is warped into a perspective quad and answers are drawn in A2
and B2. The handwritten marks are synthetic colour fields, never real student
work, so the suite proves the crop path, not handwriting accuracy.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from agent.config import Settings
from agent.controller import TutorController
from agent.image_ops import ImageError, crop_sheet, rectify_sheet, sheet_crop
from agent.lesson import load_lesson
from agent.llm import TutorIntent
from agent.memory import SessionStore
from agent.responses import select_response
from agent.sheet_layout import (
    AREA_AMBIGUOUS,
    AREA_OK,
    AREA_WRONG_ITEM,
    LayoutError,
    load_layout,
)
from agent.stt import Transcript
from agent.vision import (
    VISIBILITY_BLANK,
    AnswerArea,
    HandwritingRead,
    ParsedItem,
    VisionClient,
    VisionError,
    WorksheetParse,
)
from server.contract import CAPTURE_CHECK, STATUS_ADJUST_SHEET, STATUS_SPEAKING

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs" / "image.png"
LESSON_PATH = ROOT / "agent" / "lessons" / "grade3_demo.yaml"
SESSION_ID = "crop"
SHEET_SIZE = (1536, 2048)
CANVAS = (1400, 1900)
PHOTO_CORNERS = ((0.08, 0.05), (0.93, 0.03), (0.96, 0.97), (0.05, 0.94))
A2_INK = (20, 40, 200)
B2_INK = (200, 30, 20)
A2_ANSWER = "87"
B2_ANSWER = "24"
ANSWER_SLOT = 0.70
OPENCODE_BASE_URL = "https://opencode.ai/inference/openai/v1"


# --- synthetic sheet construction -----------------------------------------


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=44)
    except TypeError:  # Pillow without a sized default font
        return ImageFont.load_default()


def _draw_answer(image: Image.Image, box, text: str, ink) -> None:
    width, height = image.size
    x0, y0, x1, y1 = box
    centre_x = (x0 + (x1 - x0) * ANSWER_SLOT) * width
    centre_y = ((y0 + y1) / 2) * height
    draw = ImageDraw.Draw(image)
    font = _font()
    bounds = draw.textbbox((0, 0), text, font=font)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.text(
        (
            centre_x - text_width / 2 - bounds[0],
            centre_y - text_height / 2 - bounds[1],
        ),
        text,
        font=font,
        fill=ink,
    )


def _reference_sheet() -> Image.Image:
    """The upright reference sheet with synthetic A2 and B2 answers drawn."""
    layout = load_layout()
    image = Image.open(REFERENCE).convert("RGB").resize(
        SHEET_SIZE, Image.Resampling.LANCZOS
    )
    _draw_answer(image, layout.expected_box("A2"), A2_ANSWER, A2_INK)
    _draw_answer(image, layout.expected_box("B2"), B2_ANSWER, B2_INK)
    return image


def _perspective_coefficients(destination, source):
    """Coefficients mapping canvas points to sheet points for Pillow."""
    matrix = []
    for (canvas_x, canvas_y), (source_x, source_y) in zip(destination, source):
        matrix.append(
            [
                canvas_x,
                canvas_y,
                1,
                0,
                0,
                0,
                -canvas_x * source_x,
                -canvas_y * source_x,
                source_x,
            ]
        )
        matrix.append(
            [
                0,
                0,
                0,
                canvas_x,
                canvas_y,
                1,
                -canvas_x * source_y,
                -canvas_y * source_y,
                source_y,
            ]
        )
    for column in range(8):
        pivot = max(
            range(column, 8), key=lambda row: abs(matrix[row][column])
        )
        if abs(matrix[pivot][column]) < 1e-12:
            raise ValueError("degenerate perspective quad")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        divisor = matrix[column][column]
        matrix[column] = [value / divisor for value in matrix[column]]
        for row in range(8):
            if row == column:
                continue
            factor = matrix[row][column]
            if factor:
                matrix[row] = [
                    left - factor * right
                    for left, right in zip(matrix[row], matrix[column])
                ]
    return tuple(matrix[row][8] for row in range(8))


def _synthetic_photo(sheet: Image.Image) -> Image.Image:
    width, height = CANVAS
    destination = [(x * width, y * height) for x, y in PHOTO_CORNERS]
    source = [
        (0.0, 0.0),
        (sheet.width - 1.0, 0.0),
        (sheet.width - 1.0, sheet.height - 1.0),
        (0.0, sheet.height - 1.0),
    ]
    coefficients = _perspective_coefficients(destination, source)
    return sheet.transform(
        CANVAS,
        Image.Transform.PERSPECTIVE,
        coefficients,
        Image.Resampling.BICUBIC,
        fillcolor=(210, 210, 210),
    )


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _decoded(image_bytes: bytes) -> Image.Image:
    return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def _pixels(image: Image.Image):
    """Pixel access without Pillow 12's deprecated getdata() call."""
    flattened = getattr(image, "get_flattened_data", None)
    if flattened is not None:
        return flattened()
    return image.getdata()


def _corner_ink(image_bytes: bytes) -> tuple[int, int]:
    """Count synthetic A2 (blue) and B2 (red) marks in an encoded crop."""
    image = _decoded(image_bytes)
    blue = 0
    red = 0
    for red_value, green_value, blue_value in _pixels(image):
        if (
            blue_value >= 140
            and blue_value - red_value >= 90
            and blue_value - green_value >= 40
        ):
            blue += 1
        elif (
            red_value >= 140
            and red_value - blue_value >= 90
            and red_value - green_value >= 40
        ):
            red += 1
    return blue, red


def valid_sheet(lesson) -> WorksheetParse:
    return WorksheetParse(
        [
            ParsedItem(
                exercise.id,
                exercise.section,
                exercise.problem,
                exercise.verification_expression,
            )
            for exercise in lesson.exercises
        ],
        0.99,
    )


class FakeTranscriber:
    def transcribe(self, samples):
        return Transcript("", 0.95)


class FakeIntent:
    def interpret(self, transcript, state, exercise):
        return TutorIntent("UNCLEAR", None, None, None)


class SheetVision:
    """Locates from the fixed layout and reads the synthetic ink in a crop."""

    def __init__(self, worksheet, layout) -> None:
        self.worksheet = worksheet
        self.layout = layout
        self.area = None
        self.locate_calls = 0
        self.read_calls = 0
        self.read_images: list[bytes] = []

    def parse_worksheet(self, image):
        return self.worksheet

    def locate_answer_area(self, image, exercise):
        self.locate_calls += 1
        if self.area is not None:
            return self.area
        item_id = exercise["id"]
        return AnswerArea(
            item_id,
            self.layout.expected_box(item_id),
            PHOTO_CORNERS,
            0.97,
            "sheet corners visible",
        )

    def read_handwriting(self, image, exercise):
        self.read_calls += 1
        self.read_images.append(image)
        blue, red = _corner_ink(image)
        if blue > red:
            return HandwritingRead(
                A2_ANSWER, A2_ANSWER, 0.96, "63 + 24", visibility="clear"
            )
        if red > blue:
            return HandwritingRead(
                B2_ANSWER, B2_ANSWER, 0.96, "8 x 3", visibility="clear"
            )
        return HandwritingRead("", None, 0.4, "", visibility=VISIBILITY_BLANK)


# --- layout and crop geometry ---------------------------------------------


class SheetLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.layout = load_layout()

    def test_fixed_layout_has_the_twelve_ordered_boxes(self) -> None:
        self.assertEqual(len(self.layout.boxes), 12)
        self.assertEqual(
            set(self.layout.boxes),
            {f"{section}{number}" for section in "AB" for number in (1, 2, 3, 4, 5, 6)},
        )
        self.assertEqual(self.layout.reference_image, "image.png")
        self.assertIn("rectif", self.layout.note.lower())
        for item_id, (x0, y0, x1, y1) in self.layout.boxes.items():
            with self.subTest(item=item_id):
                self.assertLess(x0, x1)
                self.assertLess(y0, y1)
                self.assertGreaterEqual(x0, 0.0)
                self.assertGreaterEqual(y0, 0.0)
                self.assertLessEqual(x1, 1.0)
                self.assertLessEqual(y1, 1.0)

    def test_columns_do_not_overlap(self) -> None:
        a1 = self.layout.expected_box("A1")
        a2 = self.layout.expected_box("A2")
        a3 = self.layout.expected_box("A3")
        b1 = self.layout.expected_box("B1")
        b2 = self.layout.expected_box("B2")
        b3 = self.layout.expected_box("B3")

        # A1 and A2 sit side by side in the first A row.
        self.assertLess(a1[2], a2[0])
        # A2 and A3 are stacked in the right column.
        self.assertLess(a2[3], a3[1])
        # The same adjacencies hold in section B.
        self.assertLess(b1[2], b2[0])
        self.assertLess(b2[3], b3[1])

    def test_known_item_boxes_validate_and_other_items_do_not(self) -> None:
        self.assertEqual(
            self.layout.validate_area(self.layout.expected_box("A2"), "A2"),
            AREA_OK,
        )
        self.assertEqual(
            self.layout.validate_area(self.layout.expected_box("B2"), "A2"),
            AREA_WRONG_ITEM,
        )

    def test_box_spanning_both_columns_is_ambiguous(self) -> None:
        spanning = (0.05, 0.344, 0.965, 0.430)

        self.assertEqual(
            self.layout.validate_area(spanning, "A2"), AREA_AMBIGUOUS
        )

    def test_malformed_area_is_wrong_item(self) -> None:
        for box in (
            (0.5, 0.5, 0.5, 0.6),
            (0.9, 0.3, 0.2, 0.4),
            (0.1, 0.1, 1.4, 0.4),
            "A2",
            None,
        ):
            with self.subTest(box=box):
                self.assertEqual(
                    self.layout.validate_area(box, "A2"), AREA_WRONG_ITEM
                )

    def test_unknown_item_raises_for_expected_box(self) -> None:
        with self.assertRaises(LayoutError):
            self.layout.expected_box("C1")


class ImageOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.layout = load_layout()
        cls.sheet = _reference_sheet()
        cls.photo = _jpeg(_synthetic_photo(cls.sheet))

    def test_rectification_restores_the_reference_sheet(self) -> None:
        rectified = rectify_sheet(self.photo, PHOTO_CORNERS)
        restored = _decoded(rectified)
        self.assertEqual(restored.size, SHEET_SIZE)

        # Compare the whole sheet: a single text-dense item crop is too
        # sensitive to sub-pixel resampling at a coarse scale.
        size = (64, 64)
        left = restored.convert("L").resize(size, Image.Resampling.BOX)
        right = self.sheet.convert("L").resize(size, Image.Resampling.BOX)
        difference = ImageChops.difference(left, right)
        mean = sum(_pixels(difference)) / (size[0] * size[1])
        self.assertLess(mean, 30.0)

        # The A2 crop still targets the drawn A2 answer and not B2.
        box = self.layout.expected_box("A2")
        blue, red = _corner_ink(crop_sheet(rectified, box))
        self.assertGreater(blue, 0)
        self.assertEqual(red, 0)

    def test_crop_keeps_the_printed_item_context(self) -> None:
        box = self.layout.expected_box("A2")
        crop = _decoded(crop_sheet(_jpeg(self.sheet), box))
        width, height = crop.size

        self.assertGreater(width, int((box[2] - box[0]) * SHEET_SIZE[0]))
        self.assertGreater(height, int((box[3] - box[1]) * SHEET_SIZE[1]))
        grey = crop.convert("L")
        left_half = grey.crop((0, 0, width // 2, height))
        dark = sum(1 for value in _pixels(left_half) if value < 128)
        self.assertGreater(dark, 300)

    def test_sheet_crop_returns_a_jpeg_of_the_selected_area(self) -> None:
        crop = sheet_crop(self.photo, PHOTO_CORNERS, self.layout.expected_box("A2"))
        self.assertTrue(crop.startswith(b"\xff\xd8\xff"), "expected JPEG bytes")
        self.assertLess(_decoded(crop).width, CANVAS[0])

    def test_degenerate_and_out_of_range_quads_are_refused(self) -> None:
        cases = (
            ((0.5, 0.5), (0.5, 0.5), (0.5, 0.5), (0.5, 0.5)),
            ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)),
            ((0.0, 0.0), (1.2, 0.0), (1.0, 1.0), (0.0, 1.0)),
            ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
            "corners",
        )
        for corners in cases:
            with self.subTest(corners=corners):
                with self.assertRaises(ImageError):
                    rectify_sheet(self.photo, corners)

    def test_empty_crop_and_bad_margin_are_refused(self) -> None:
        with self.assertRaises(ImageError):
            crop_sheet(self.photo, (0.4, 0.4, 0.4, 0.5))
        with self.assertRaises(ImageError):
            crop_sheet(self.photo, self.layout.expected_box("A2"), margin=0.9)
        with self.assertRaises(ImageError):
            crop_sheet(b"not-an-image", self.layout.expected_box("A2"))


# --- controller crop flow --------------------------------------------------


class ControllerCropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.layout = load_layout()
        cls.sheet = _reference_sheet()
        cls.photo = _jpeg(_synthetic_photo(cls.sheet))
        cls.lesson = load_lesson(LESSON_PATH)

    def setUp(self) -> None:
        self.store = SessionStore("sqlite:///:memory:")
        self.vision = SheetVision(valid_sheet(self.lesson), self.layout)
        self.controller = TutorController(
            SESSION_ID,
            lesson=self.lesson,
            store=self.store,
            vision=self.vision,
            intent=FakeIntent(),
            transcriber=FakeTranscriber(),
            layout=self.layout,
        )
        self.controller.handle_snapshot(self.photo, "image/jpeg", "review")
        self.controller.handle_transcript(Transcript("A2", 0.95))
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A2")

    def tearDown(self) -> None:
        self.store.close()

    def check(self):
        return self.controller.handle_snapshot(
            self.photo, "image/jpeg", "check", "A2"
        )

    def test_clear_a2_crop_reads_a2_and_never_b2(self) -> None:
        response = self.check()

        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertIsNone(response.capture_request)
        self.assertEqual(response.exercise_id, "A2")
        self.assertIn("correct", response.tutor_text.lower())
        self.assertEqual(self.store.get(SESSION_ID).attempts, 1)
        self.assertEqual(self.vision.read_calls, 1)
        crop = self.vision.read_images[0]
        self.assertTrue(crop.startswith(b"\xff\xd8\xff"))
        self.assertLess(_decoded(crop).width, CANVAS[0])
        blue, red = _corner_ink(crop)
        self.assertGreater(blue, 0)
        self.assertEqual(red, 0)

    def test_small_locator_box_still_crops_the_full_item_with_context(self) -> None:
        # The model answers with only the right-hand answer blank; the crop
        # must still come from the fixed A2 item rectangle.
        self.vision.area = AnswerArea(
            "A2",
            (0.70, 0.36, 0.90, 0.40),
            PHOTO_CORNERS,
            0.95,
            "answer blank only",
        )

        response = self.check()

        self.assertEqual(response.status, STATUS_SPEAKING)
        self.assertEqual(self.vision.read_calls, 1)
        crop = _decoded(self.vision.read_images[0])
        fixed = self.layout.expected_box("A2")
        self.assertGreaterEqual(
            crop.width, int((fixed[2] - fixed[0]) * SHEET_SIZE[0])
        )
        self.assertGreaterEqual(
            crop.height, int((fixed[3] - fixed[1]) * SHEET_SIZE[1])
        )
        left_half = crop.convert("L").crop(
            (0, 0, crop.width // 2, crop.height)
        )
        dark = sum(1 for value in _pixels(left_half) if value < 128)
        self.assertGreater(dark, 300)

    def test_b2_locator_for_an_a2_request_is_refused_without_a_read(self) -> None:
        self.vision.area = AnswerArea(
            "B2",
            self.layout.expected_box("B2"),
            PHOTO_CORNERS,
            0.97,
            "wrong item",
        )

        response = self.check()

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, CAPTURE_CHECK)
        self.assertEqual(response.exercise_id, "A2")
        self.assertEqual(
            response.tutor_text, select_response("reading_wrong_item")
        )
        self.assertEqual(self.vision.read_calls, 0)
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)
        self.assertEqual(self.store.get(SESSION_ID).chosen_exercise, "A2")

    def test_a2_id_with_a_b2_box_is_refused_without_a_read(self) -> None:
        self.vision.area = AnswerArea(
            "A2",
            self.layout.expected_box("B2"),
            PHOTO_CORNERS,
            0.97,
            "box on the other item",
        )

        response = self.check()

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(self.vision.read_calls, 0)
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)

    def test_spanning_box_is_refused_as_ambiguous(self) -> None:
        spanning = (0.05, 0.344, 0.965, 0.430)
        self.vision.area = AnswerArea(
            "A2", spanning, PHOTO_CORNERS, 0.97, "both columns"
        )

        response = self.check()

        self.assertEqual(
            self.layout.validate_area(spanning, "A2"), AREA_AMBIGUOUS
        )
        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, CAPTURE_CHECK)
        self.assertEqual(response.exercise_id, "A2")
        self.assertEqual(self.vision.read_calls, 0)
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)

    def test_degenerate_quad_is_refused_before_the_reader(self) -> None:
        self.vision.area = AnswerArea(
            "A2",
            self.layout.expected_box("A2"),
            ((0.2, 0.2), (0.2, 0.2), (0.2, 0.2), (0.2, 0.2)),
            0.9,
            "collapsed corners",
        )

        response = self.check()

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.tutor_text, select_response("reading_wrong_item"))
        self.assertEqual(self.vision.read_calls, 0)
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)

    def test_uncertain_crop_read_keeps_the_task_uncertain(self) -> None:
        # An empty A2 box still crops and reads; the reader reports blank, so
        # the existing Task 25 gate must ask again instead of grading.
        bare_sheet = Image.open(REFERENCE).convert("RGB").resize(
            SHEET_SIZE, Image.Resampling.LANCZOS
        )
        bare_photo = _jpeg(_synthetic_photo(bare_sheet))

        response = self.controller.handle_snapshot(
            bare_photo, "image/jpeg", "check", "A2"
        )

        self.assertEqual(response.status, STATUS_ADJUST_SHEET)
        self.assertEqual(response.capture_request, CAPTURE_CHECK)
        self.assertEqual(self.vision.read_calls, 1)
        self.assertEqual(self.store.get(SESSION_ID).attempts, 0)
        self.assertEqual(
            response.tutor_text, select_response("reading_blank")
        )


# --- locator contract ------------------------------------------------------


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.body


class FakeHttp:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, headers=None, **kwargs):
        self.calls.append(
            {"url": url, "headers": headers, "json": kwargs.get("json")}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def hosted_body(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def make_settings(**overrides) -> Settings:
    values = {
        "ollama_model": "model",
        "vision_provider": "hosted",
        "vision_base_url": OPENCODE_BASE_URL,
        "vision_model": "vision-model",
        "vision_api_key": "vision-key",
    }
    values.update(overrides)
    return Settings(**values)


def locate_body(**overrides) -> dict:
    body = {
        "item_id": "A2",
        "box": [0.522, 0.344, 0.961, 0.428],
        "corners": [
            [0.08, 0.05],
            [0.93, 0.03],
            [0.96, 0.97],
            [0.05, 0.94],
        ],
        "confidence": 0.94,
        "reason": "sheet corners found",
    }
    body.update(overrides)
    return body


class LocatorContractTests(unittest.TestCase):
    def _locate(self, **overrides):
        http = FakeHttp(
            FakeResponse(hosted_body(json.dumps(locate_body(**overrides))))
        )
        client = VisionClient(make_settings(), http)
        return client.locate_answer_area(b"image-bytes", {"id": "A2"}), http

    def test_returns_the_validated_area(self) -> None:
        area, http = self._locate()

        self.assertEqual(area.item_id, "A2")
        self.assertEqual(area.box, (0.522, 0.344, 0.961, 0.428))
        self.assertEqual(len(area.corners), 4)
        self.assertAlmostEqual(area.confidence, 0.94)
        self.assertEqual(area.reason, "sheet corners found")
        self.assertEqual(
            http.calls[0]["url"],
            OPENCODE_BASE_URL + "/chat/completions",
        )

    def test_instruction_requests_the_locator_contract(self) -> None:
        _, http = self._locate()
        instruction = json.loads(
            http.calls[0]["json"]["messages"][0]["content"][0]["text"]
        )["instruction"]

        for field in ("item_id", "box", "corners", "confidence", "reason"):
            with self.subTest(field=field):
                self.assertIn(field, instruction)
        self.assertIn("top-left, top-right, bottom-right, bottom-left", instruction)
        self.assertIn("normalized to the full photo", instruction)

    def test_unknown_item_id_is_refused(self) -> None:
        with self.assertRaises(VisionError):
            self._locate(item_id="C1")

    def test_non_string_item_id_is_refused(self) -> None:
        with self.assertRaises(VisionError):
            self._locate(item_id=2)

    def test_unordered_or_out_of_range_boxes_are_refused(self) -> None:
        for box in (
            [0.9, 0.3, 0.2, 0.4],
            [0.5, 0.5, 0.5, 0.6],
            [0.1, 0.1, 1.4, 0.4],
            [0.1, 0.1, 0.4],
            "box",
        ):
            with self.subTest(box=box):
                with self.assertRaises(VisionError):
                    self._locate(box=box)

    def test_degenerate_or_out_of_range_corners_are_refused(self) -> None:
        for corners in (
            [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5], [0.5, 0.5]],
            [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]],
            [[0.0, 0.0], [1.2, 0.0], [1.0, 1.0], [0.0, 1.0]],
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
        ):
            with self.subTest(corners=corners):
                with self.assertRaises(VisionError):
                    self._locate(corners=corners)

    def test_invalid_confidence_is_refused(self) -> None:
        with self.assertRaises(VisionError):
            self._locate(confidence="high")


if __name__ == "__main__":
    unittest.main()
