# Task 30: Improve Selected-Work Image Accuracy

## Goal

Make a clear handwriting check depend on visible evidence from the selected
answer area, with fewer unnecessary retries and no false correction.

## Evidence

The browser captures a full camera frame, and `agent/vision.py` sends that
entire JPEG to the model for a selected-work check. The selected item's area
is described in text, but there is no image crop or independently checked
location. `agent/tutor.py` uses the model's self-reported confidence threshold
of 0.75; that threshold has not been calibrated on real handwriting photos.

## Work

- Start with `docs/image.png` and synthetic or adult-written examples for
  image-location tests. Later collect a small, consented rehearsal set from
  the fixed blank worksheet; remove names/signatures and keep it outside the
  repository unless explicitly approved as a test fixture.
- Locate the selected answer area using the fixed sheet layout. Handle camera
  angle and framing variation; keep enough printed context in the crop to
  confirm the item ID. Ask for a clearer image when the crop cannot be tied
  to the selected item.
- Send the selected region at readable resolution for handwriting OCR. Keep
  the full-sheet image for initial placement and worksheet confirmation.
- Measure correct reads, uncertain reads, wrong-item reads, false corrections,
  and request time. Calibrate the uncertainty gate from those results rather
  than treating model confidence as a probability.
- Consider a second OCR pass only for unclear or conflicting reads; never
  turn disagreement into a confident correction.

## Files

Browser capture or backend image preprocessing, `agent/vision.py`,
`agent/controller.py`, OCR tests, and the runbook accuracy results.

## Acceptance

- A2 and B2 handwriting cannot be swapped when both are visible.
- A missing, misaligned, ambiguous, or wrong-item crop asks for clarification
  and does not mark an answer wrong or increment attempts.
- The local test set has no false corrections; report its sample size and
  uncertainty rate. Task 27 later repeats this check on real phone photos
  before demo sign-off.
- The calculator remains the only source of arithmetic truth, and raw student
  images are not retained by the running service.

## Dependencies

Task 26 for the active snapshot runtime. Image-location code and synthetic
tests can start without a phone; real handwriting calibration and device
acceptance require the later Task 27 rehearsal.

## Estimate

1-1.5 days, plus a real worksheet image set.

## Controller Rulings (2026-11-11)

- **Scope and evidence.** Build and test the sheet-location, validation, and
  crop path with `docs/image.png` plus synthetic handwriting drawn by the
  tests. Do **not** calibrate the 0.75 confidence gate from generated data or
  commit any real student photo. Real handwriting calibration and phone
  photos stay in Task 27. Do not change `web/src/turnDetector.ts` or any
  speech threshold.
- **Ruling: file set.** Add `agent/sheet_layout.py`, `agent/image_ops.py`,
  `agent/worksheets/grade3_layout.yaml`, and `tests/test_handwriting_crops.py`.
  Edit `agent/vision.py`, `agent/controller.py`, `agent/responses.py` only if
  a new prompt is truly needed, `requirements.txt`, `docs/DEMO-RUNBOOK.md`,
  and the fake vision classes in `tests/test_session_api.py`,
  `tests/test_conversation.py`, and `tests/test_handwriting.py`. Do not edit
  `web/`, `agent/tutor.py`, `agent/llm.py`, or `server/contract.py`.
- **Ruling: fixed layout.** `grade3_layout.yaml` stores the reference image
  name and the 12 normalized item rectangles (the rounded item boxes on
  `docs/image.png`, not just the answer blanks), in 0-1 image coordinates,
  plus a short note that a camera photo is rectified before these apply.
  `sheet_layout.py` loads it, validates the file (all 12 ids, ordered boxes
  inside 0-1), and exposes `expected_box(item_id)` and
  `validate_area(box, item_id) -> "ok" | "wrong_item" | "ambiguous"`:
  at least 60% of the proposed area must lie inside the selected item box,
  and at most 10% may lie inside any other item box; otherwise
  `wrong_item` or `ambiguous`. Pure math, no image import.
- **Ruling: rectification and crop.** `image_ops.py` (Pillow, imported inside
  the functions) exposes `rectify_sheet(image_bytes, corners, width=1536,
  height=2048) -> bytes` and `crop_sheet(image_bytes, box, margin=0.01) ->
  bytes`, plus a combining `sheet_crop(image_bytes, corners, box,
  margin=0.01) -> bytes`. `corners` is four normalized `[x, y]` points in
  TL, TR, BR, BL order; convert them to pixels and pass them to Pillow's
  `Image.QUAD` in its documented TL, BL, BR, TR order. Reject non-convex,
  degenerate, out-of-range, or empty results with a domain `ImageError`.
  Crop the rectified sheet at the area box expanded by the margin so the
  printed item label and expression stay in the crop; re-encode JPEG quality
  90 and keep the crop transient.
- **Ruling: locator contract.** Add `locate_answer_area(image_bytes, exercise)
  -> AnswerArea` to `agent/vision.py`. `AnswerArea` carries `item_id`, `box`
  `(x0, y0, x1, y1)`, `corners` (four points), `confidence`, and `reason`.
  The instruction asks for JSON `item_id`, `box`, `corners`, `confidence`,
  `reason`; coordinates are normalized to the full photo; `corners` are the
  sheet's outer corners in TL, TR, BR, BL order. Validate every field
  strictly: known item id, four ordered in-range coordinates, four points
  forming a non-degenerate quad; otherwise raise `VisionError`. This is a
  second provider call per written-work check and is accepted for the demo.
- **Ruling: controller check flow.** `TutorController` loads the layout once
  (constructor argument `layout=None` with a default loader) and the check
  path becomes: locate -> require `item_id` equals the selected exercise ->
  `validate_area` -> `sheet_crop` -> `read_handwriting` on the crop -> the
  existing Task 25 uncertainty gate. A locate provider failure keeps the
  current retry response (`reading_work`, capture check, no grading). A
  wrong or ambiguous area, an `ImageError`, or a locator box outside the
  fixed layout returns `status="adjust_sheet"`, `capture_request="check"`,
  the selected `exercise_id`, and `reading_wrong_item`; it must not call the
  handwriting reader and must not increment attempts. A clear A2 crop reads
  A2 even when B2 is visible. The full photo is never retained.
- **Ruling: no second OCR pass yet.** A single cropped read is enough for this
  card. Do not add a retry-pass on disagreement; record it as future work.
  Keep the 0.75 uncertainty gate unchanged.
- **Ruling: dependency and runbook.** Add `Pillow>=10,<13` to
  `requirements.txt`. Add a short runbook accuracy table: the synthetic case
  count, clear/uncertain/wrong-item outcomes, and "false corrections: 0";
  state that real handwriting calibration is Task 27 and no estimate may be
  presented as a measured accuracy.
- **Ruling: tests.** `tests/test_handwriting_crops.py` must build a synthetic
  photo from `docs/image.png` with a perspective warp and drawn answers in
  A2 and B2, then assert rectification restores the sheet (A2 crop matches
  the reference within a small pixel tolerance), an A2 check reads the A2
  digits and not B2, a B2 locator answer for an A2 request is refused
  without a read or attempt, a box spanning both columns is ambiguous, a
  degenerate quad is refused, and the crop keeps the printed item context.
  Update every fake vision to implement the locator. Keep the existing
  placement, spoken-check, and provider-failure tests green.
- **Ruling: no pytest.** Run only `python -m py_compile` on touched Python
  files. Return status, files, compile results, acceptance status, and
  concerns. Do not install packages, run tests, commit, stage, or move files.
  The manager runs the suites and the crop measurements.

## Completion Evidence (2026-11-11)

- Files: `agent/sheet_layout.py`, `agent/image_ops.py`,
  `agent/worksheets/grade3_layout.yaml`, `tests/test_handwriting_crops.py`
  (new); `agent/vision.py` (`AnswerArea`, `locate_answer_area`),
  `agent/controller.py` (locate -> validate -> rectified fixed-box crop ->
  read), `requirements.txt` (`Pillow>=10,<13`), `docs/DEMO-RUNBOOK.md`;
  locator stubs in `tests/test_handwriting.py`, `test_session_api.py`, and
  `test_conversation.py`.
- Verified: `python -m pytest tests -q -p no:cacheprovider` -> **293 passed,
  736 subtests passed**. `python -m py_compile` on every touched Python file
  -> **exit 0**. The synthetic rectification check measures a full-sheet
  mean difference of **28.15/255 at 64x64** (6.35 at 16x16) against the
  reference, and the A2 crop contains the drawn A2 ink with no B2 ink.
- Manager review found and fixed:
  - Two test calibration errors: A2 and B2 are stacked in the same column
    (section A above section B), not side by side; and the text-dense A2 crop
    was too strict for a resampling comparison, so the full rectified sheet
    is compared instead. `getdata` deprecation noise was removed with a
    `_pixels` helper.
  - The crop now uses the fixed layout item box, not the locator's answer
    box, so the printed item number and expression are always retained; the
    locator box is used only for identity/geometry validation. A test covers
    a small locator box and still receives the full item crop.
- Written but not run: none; the suite was run.
- Deferred/manual: real handwriting calibration and the 0.75 gate, locator
  accuracy on real photos, and phone/photograph variation. Task 27 owns these.
- Concerns:
  - A written-work check now makes two provider calls (locate + read), which
    adds latency; Task 28's benchmark will show it.
  - Layout boxes were estimated from `docs/image.png` and validated against
    that clean scan only; a different print/scale needs a new layout file.
  - Rectification trusts the model's four sheet corners; bad corners are
    refused, not corrected.
  - The runbook table's 6 synthetic cases are gating outcomes, not OCR
    accuracy; no estimate is presented as measured handwriting accuracy.
  - A second OCR pass on disagreement is deliberately deferred.
