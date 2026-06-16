import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockEventSourceInstances } from "../test/setup";
import type { Column, ResearchTable } from "../types";

vi.mock("../api", () => ({
  proposeColumns: vi.fn(),
  createTable: vi.fn(),
  startTable: vi.fn(),
  openSSE: vi.fn((tableId: string) => new (globalThis as unknown as {
    EventSource: new (url: string) => EventSource;
  }).EventSource(`http://test/tables/${tableId}/events`)),
  listDocuments: vi.fn().mockResolvedValue([]),
}));

import App from "../App";
import * as api from "../api";

const sampleColumns: Column[] = [
  {
    id: "col_1",
    name: "Background",
    description: "Career background",
    output_type: "short_text",
    required_evidence: false,
  },
];

const sampleTable: ResearchTable = {
  id: "tbl_xyz",
  research_goal: "goal",
  status: "draft",
  rows: [{ id: "r1", arbitrator_id: "arb1", name: "Row 1" }],
  columns: sampleColumns,
  cells: [{ id: "cell_r1_col_1", row_id: "r1", column_id: "col_1", status: "pending" }],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("App", () => {
  it("renders the setup phase initially", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /arbitrator research table/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate columns/i })).toBeInTheDocument();
  });

  it("clicking Generate Columns calls proposeColumns and transitions to editing", async () => {
    const user = userEvent.setup();
    vi.mocked(api.proposeColumns).mockResolvedValue(sampleColumns);

    render(<App />);

    await user.click(screen.getByRole("button", { name: /generate columns/i }));

    await waitFor(() => {
      expect(api.proposeColumns).toHaveBeenCalledTimes(1);
    });
    // editing phase shows column name input + Approve button
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /approve & create table/i })).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("Background")).toBeInTheDocument();
  });

  it("closes the EventSource when the component unmounts while running", async () => {
    const user = userEvent.setup();
    vi.mocked(api.proposeColumns).mockResolvedValue(sampleColumns);
    vi.mocked(api.createTable).mockResolvedValue(sampleTable);
    vi.mocked(api.startTable).mockResolvedValue(undefined);

    const { unmount } = render(<App />);

    // setup -> editing
    await user.click(screen.getByRole("button", { name: /generate columns/i }));
    await screen.findByRole("button", { name: /approve & create table/i });

    // editing -> table (draft)
    await user.click(screen.getByRole("button", { name: /approve & create table/i }));
    const startBtn = await screen.findByRole("button", { name: /start research/i });

    // draft -> running. handleStart awaits startTable then flips status, which
    // triggers the useEffect that opens the EventSource.
    await user.click(startBtn);
    await waitFor(() => {
      expect(api.startTable).toHaveBeenCalledWith("tbl_xyz");
    });
    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });

    const es = mockEventSourceInstances[0];
    expect(es.close).not.toHaveBeenCalled();

    unmount();

    expect(es.close).toHaveBeenCalledTimes(1);
  });

  it("applies SSE events from the EventSource to update cells", async () => {
    const user = userEvent.setup();
    vi.mocked(api.proposeColumns).mockResolvedValue(sampleColumns);
    vi.mocked(api.createTable).mockResolvedValue(sampleTable);
    vi.mocked(api.startTable).mockResolvedValue(undefined);

    render(<App />);
    await user.click(screen.getByRole("button", { name: /generate columns/i }));
    await screen.findByRole("button", { name: /approve & create table/i });
    await user.click(screen.getByRole("button", { name: /approve & create table/i }));
    const startBtn = await screen.findByRole("button", { name: /start research/i });
    await user.click(startBtn);

    await waitFor(() => {
      expect(mockEventSourceInstances.length).toBe(1);
    });
    const es = mockEventSourceInstances[0];

    act(() => {
      es.emit({
        type: "cell_done",
        rowId: "r1",
        columnId: "col_1",
        value: "Strong civil-law background",
        confidence: "high",
        sources: [],
      });
    });

    await waitFor(() => {
      expect(screen.getByText(/strong civil-law background/i)).toBeInTheDocument();
    });
  });
});
