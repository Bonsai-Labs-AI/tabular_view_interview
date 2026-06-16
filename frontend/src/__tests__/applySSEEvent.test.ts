import { describe, it, expect } from "vitest";
import { applySSEEvent } from "../App";
import type { Cell, ResearchTable, SSEEvent } from "../types";

function makeCell(over: Partial<Cell> & Pick<Cell, "id" | "row_id" | "column_id">): Cell {
  return {
    status: "pending",
    ...over,
  };
}

function makeTable(cells: Cell[]): ResearchTable {
  return {
    id: "tbl_1",
    research_goal: "goal",
    status: "running",
    rows: [
      { id: "r1", arbitrator_id: "arb1", name: "Row 1" },
      { id: "r2", arbitrator_id: "arb2", name: "Row 2" },
    ],
    columns: [
      { id: "c1", name: "Col 1", description: "", output_type: "short_text", required_evidence: false },
      { id: "c2", name: "Col 2", description: "", output_type: "short_text", required_evidence: false },
    ],
    cells,
  };
}

describe("applySSEEvent", () => {
  it("marks the matching cell as working on cell_working", () => {
    const table = makeTable([
      makeCell({ id: "cell_r1_c1", row_id: "r1", column_id: "c1" }),
      makeCell({ id: "cell_r1_c2", row_id: "r1", column_id: "c2" }),
    ]);
    const event: SSEEvent = { type: "cell_working", rowId: "r1", columnId: "c1" };

    const next = applySSEEvent(table, event);

    expect(next.cells[0].status).toBe("working");
    // unrelated cell untouched (same reference)
    expect(next.cells[1]).toBe(table.cells[1]);
  });

  it("fills value, confidence, and sources on cell_done", () => {
    const table = makeTable([
      makeCell({ id: "cell_r1_c1", row_id: "r1", column_id: "c1", status: "working" }),
      makeCell({ id: "cell_r2_c1", row_id: "r2", column_id: "c1" }),
    ]);
    const event: SSEEvent = {
      type: "cell_done",
      rowId: "r1",
      columnId: "c1",
      value: "the answer",
      confidence: "high",
      sources: [{ title: "src", url: "https://example.com" }],
    };

    const next = applySSEEvent(table, event);

    expect(next.cells[0]).toMatchObject({
      status: "done",
      value: "the answer",
      confidence: "high",
      sources: [{ title: "src", url: "https://example.com" }],
    });
    expect(next.cells[1]).toBe(table.cells[1]);
  });

  it("marks the matching cell as failed on cell_failed", () => {
    const table = makeTable([
      makeCell({ id: "cell_r1_c1", row_id: "r1", column_id: "c1", status: "working" }),
    ]);
    const event: SSEEvent = {
      type: "cell_failed",
      rowId: "r1",
      columnId: "c1",
      error: "boom",
    };

    const next = applySSEEvent(table, event);

    expect(next.cells[0].status).toBe("failed");
  });

  it("does not mutate cells whose row/column do not match the event", () => {
    const cells = [
      makeCell({ id: "cell_r1_c1", row_id: "r1", column_id: "c1" }),
      makeCell({ id: "cell_r1_c2", row_id: "r1", column_id: "c2" }),
      makeCell({ id: "cell_r2_c1", row_id: "r2", column_id: "c1" }),
    ];
    const table = makeTable(cells);
    const event: SSEEvent = { type: "cell_working", rowId: "r1", columnId: "c1" };

    const next = applySSEEvent(table, event);

    expect(next.cells[0]).not.toBe(cells[0]);
    expect(next.cells[1]).toBe(cells[1]);
    expect(next.cells[2]).toBe(cells[2]);
    // original table not mutated
    expect(table.cells[0].status).toBe("pending");
  });
});
