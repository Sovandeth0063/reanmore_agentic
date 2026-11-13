/**
 * Fixed layout of the printed grade-three practice sheet (docs/image.png).
 *
 * Keep in sync with agent/worksheets/grade3_layout.yaml. Each box is the
 * rounded item box on the reference sheet in normalized 0-1 image coordinates:
 * [x0, y0, x1, y1] with the origin at the top-left of the upright sheet.
 *
 * These boxes only apply to the upright reference image shown in the Question
 * Paper pane. The backend rectifies a camera photo before using its own copy of
 * the same layout.
 */

export const WORKSHEET_IMAGE_SRC = "/worksheet.png";

export const WORKSHEET_ITEM_IDS = [
  "A1",
  "A2",
  "A3",
  "A4",
  "A5",
  "A6",
  "B1",
  "B2",
  "B3",
  "B4",
  "B5",
  "B6",
] as const;

export type WorksheetItemId = (typeof WORKSHEET_ITEM_IDS)[number];

export interface WorksheetBox {
  readonly x0: number;
  readonly y0: number;
  readonly x1: number;
  readonly y1: number;
}

export const WORKSHEET_ITEMS: Readonly<
  Record<WorksheetItemId, WorksheetBox>
> = {
  A1: { x0: 0.050, y0: 0.344, x1: 0.489, y1: 0.428 },
  A2: { x0: 0.522, y0: 0.344, x1: 0.961, y1: 0.428 },
  A3: { x0: 0.050, y0: 0.452, x1: 0.489, y1: 0.535 },
  A4: { x0: 0.522, y0: 0.452, x1: 0.961, y1: 0.535 },
  A5: { x0: 0.050, y0: 0.560, x1: 0.489, y1: 0.644 },
  A6: { x0: 0.522, y0: 0.560, x1: 0.961, y1: 0.644 },
  B1: { x0: 0.050, y0: 0.689, x1: 0.489, y1: 0.773 },
  B2: { x0: 0.522, y0: 0.689, x1: 0.961, y1: 0.773 },
  B3: { x0: 0.050, y0: 0.796, x1: 0.489, y1: 0.880 },
  B4: { x0: 0.522, y0: 0.796, x1: 0.961, y1: 0.880 },
  B5: { x0: 0.050, y0: 0.903, x1: 0.489, y1: 0.977 },
  B6: { x0: 0.522, y0: 0.903, x1: 0.961, y1: 0.977 },
};

export interface WorksheetItemDescription {
  readonly id: WorksheetItemId;
  readonly section: "A" | "B";
  readonly number: number;
}

export function isWorksheetItemId(value: string): value is WorksheetItemId {
  return (WORKSHEET_ITEM_IDS as readonly string[]).includes(value);
}

/** Accepts the lower-case or padded ids a speech layer may produce. */
export function normalizeWorksheetItem(
  value: string | null | undefined,
): WorksheetItemId | null {
  if (!value) {
    return null;
  }
  const id = value.trim().toUpperCase();
  return isWorksheetItemId(id) ? id : null;
}

export function describeWorksheetItem(
  value: string | null | undefined,
): WorksheetItemDescription | null {
  const id = normalizeWorksheetItem(value);
  if (!id) {
    return null;
  }
  return {
    id,
    section: id.startsWith("A") ? "A" : "B",
    number: Number(id.slice(1)),
  };
}

/** Normalized highlight box for the selected exercise, if it is on the sheet. */
export function worksheetBox(
  value: string | null | undefined,
): WorksheetBox | null {
  const id = normalizeWorksheetItem(value);
  return id ? WORKSHEET_ITEMS[id] : null;
}
