import { test } from "node:test";
import assert from "node:assert/strict";
import {
  WORKSHEET_IMAGE_SRC,
  WORKSHEET_ITEMS,
  WORKSHEET_ITEM_IDS,
  describeWorksheetItem,
  isWorksheetItemId,
  normalizeWorksheetItem,
  worksheetBox,
} from "../src/worksheet.ts";

const EXPECTED_BOXES = {
  A1: [0.050, 0.344, 0.489, 0.428],
  A2: [0.522, 0.344, 0.961, 0.428],
  A3: [0.050, 0.452, 0.489, 0.535],
  A4: [0.522, 0.452, 0.961, 0.535],
  A5: [0.050, 0.560, 0.489, 0.644],
  A6: [0.522, 0.560, 0.961, 0.644],
  B1: [0.050, 0.689, 0.489, 0.773],
  B2: [0.522, 0.689, 0.961, 0.773],
  B3: [0.050, 0.796, 0.489, 0.880],
  B4: [0.522, 0.796, 0.961, 0.880],
  B5: [0.050, 0.903, 0.489, 0.977],
  B6: [0.522, 0.903, 0.961, 0.977],
} as const;

test("every fixed item copies the grade3_layout.yaml box", () => {
  assert.deepEqual([...WORKSHEET_ITEM_IDS], Object.keys(EXPECTED_BOXES));
  for (const id of WORKSHEET_ITEM_IDS) {
    const box = WORKSHEET_ITEMS[id];
    assert.deepEqual(
      [box.x0, box.y0, box.x1, box.y1],
      [...EXPECTED_BOXES[id]],
      id,
    );
  }
});

test("all highlight boxes are upright and inside the image", () => {
  for (const id of WORKSHEET_ITEM_IDS) {
    const box = WORKSHEET_ITEMS[id];
    assert.ok(box.x0 >= 0 && box.y0 >= 0, `${id} starts inside`);
    assert.ok(box.x1 <= 1 && box.y1 <= 1, `${id} ends inside`);
    assert.ok(box.x0 < box.x1, `${id} has width`);
    assert.ok(box.y0 < box.y1, `${id} has height`);
  }
});

test("the left and right columns share edges and rows stay aligned", () => {
  for (const id of WORKSHEET_ITEM_IDS) {
    const box = WORKSHEET_ITEMS[id];
    // Items are numbered left-to-right, top-to-bottom: odd numbers occupy the
    // left column and even numbers the right column in both sections.
    if (Number(id.slice(1)) % 2 === 1) {
      assert.equal(box.x0, 0.05, id);
      assert.equal(box.x1, 0.489, id);
    } else {
      assert.equal(box.x0, 0.522, id);
      assert.equal(box.x1, 0.961, id);
    }
  }
  for (const [leftId, rightId] of [
    ["A1", "A2"],
    ["A3", "A4"],
    ["A5", "A6"],
    ["B1", "B2"],
    ["B3", "B4"],
    ["B5", "B6"],
  ] as const) {
    assert.equal(WORKSHEET_ITEMS[leftId].y0, WORKSHEET_ITEMS[rightId].y0);
    assert.equal(WORKSHEET_ITEMS[leftId].y1, WORKSHEET_ITEMS[rightId].y1);
  }
  assert.ok(WORKSHEET_ITEMS.B1.y0 > WORKSHEET_ITEMS.A6.y1);
});

test("item ids normalize from speech-friendly casing and padding", () => {
  assert.equal(normalizeWorksheetItem("a2"), "A2");
  assert.equal(normalizeWorksheetItem(" B6 "), "B6");
  assert.equal(normalizeWorksheetItem("C1"), null);
  assert.equal(normalizeWorksheetItem(""), null);
  assert.equal(normalizeWorksheetItem(null), null);
  assert.equal(isWorksheetItemId("A6"), true);
  assert.equal(isWorksheetItemId("A7"), false);
});

test("descriptions split the fixed sheet into sections and item numbers", () => {
  assert.deepEqual(describeWorksheetItem("A1"), {
    id: "A1",
    section: "A",
    number: 1,
  });
  assert.deepEqual(describeWorksheetItem("b4"), {
    id: "B4",
    section: "B",
    number: 4,
  });
  assert.equal(describeWorksheetItem("Z9"), null);
});

test("the highlight resolves only for items on the fixed sheet", () => {
  assert.deepEqual(worksheetBox("b2"), {
    x0: 0.522,
    y0: 0.689,
    x1: 0.961,
    y1: 0.773,
  });
  assert.equal(worksheetBox("A9"), null);
  assert.equal(worksheetBox(null), null);
  assert.equal(WORKSHEET_IMAGE_SRC, "/worksheet.png");
});
