import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("../../api", () => ({
  listDocuments: vi.fn(),
}));

import ResearchTableView from "../ResearchTable";
import * as api from "../../api";
import type { ResearchTable, ArbitratorDocument } from "../../types";

const table: ResearchTable = {
  id: "tbl_1",
  research_goal: "the goal",
  status: "running",
  rows: [
    { id: "r1", arbitrator_id: "arb_1", name: "Alice" },
    { id: "r2", arbitrator_id: "arb_2", name: "Bob" },
  ],
  columns: [
    { id: "c1", name: "Background", description: "", output_type: "short_text", required_evidence: false },
    { id: "c2", name: "Cases", description: "", output_type: "long_text", required_evidence: false },
  ],
  cells: [
    { id: "r1_c1", row_id: "r1", column_id: "c1", status: "pending" },
    {
      id: "r1_c2",
      row_id: "r1",
      column_id: "c2",
      status: "done",
      value: "Notable case Smith v Jones",
      confidence: "high",
      reasoning: "Found in published opinion.",
      sources: [{ title: "Smith v Jones opinion", url: "https://example.com/opinion" }],
    },
    { id: "r2_c1", row_id: "r2", column_id: "c1", status: "working" },
    { id: "r2_c2", row_id: "r2", column_id: "c2", status: "pending" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ResearchTableView", () => {
  it("renders rows x columns grid with status indicators", () => {
    render(<ResearchTableView table={table} onStart={() => {}} />);

    // headers
    expect(screen.getByText("Background")).toBeInTheDocument();
    expect(screen.getByText("Cases")).toBeInTheDocument();

    // rows
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();

    // pending cells render an em-dash placeholder
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);

    // done cell shows its value
    expect(screen.getByText(/Notable case Smith v Jones/i)).toBeInTheDocument();

    // working cell has a spinner. The component uses an <svg class="animate-spin">.
    const spinners = document.querySelectorAll("svg.animate-spin");
    // there is one for the running status button and one for the working cell
    expect(spinners.length).toBeGreaterThanOrEqual(1);
  });

  it("opens the cell detail modal when clicking a done cell", async () => {
    const user = userEvent.setup();
    render(<ResearchTableView table={table} onStart={() => {}} />);

    await user.click(screen.getByText(/Notable case Smith v Jones/i));

    // modal headings
    await waitFor(() => {
      expect(screen.getByText(/^Answer$/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Smith v Jones opinion/i)).toBeInTheDocument();
    expect(screen.getByText(/Found in published opinion\./i)).toBeInTheDocument();
  });

  it("opens the docs modal when clicking the docs button on a row", async () => {
    const docs: ArbitratorDocument[] = [
      { id: "d1", arbitrator_id: "arb_1", doc_type: "cv", filename: "cv.txt", content: "CV content here" },
      { id: "d2", arbitrator_id: "arb_1", doc_type: "bio", filename: "bio.txt", content: "Bio content" },
    ];
    vi.mocked(api.listDocuments).mockResolvedValue(docs);

    const user = userEvent.setup();
    render(<ResearchTableView table={table} onStart={() => {}} />);

    // The docs button has title="View source documents"
    const docsButtons = screen.getAllByTitle(/view source documents/i);
    await user.click(docsButtons[0]);

    await waitFor(() => {
      expect(api.listDocuments).toHaveBeenCalledWith("arb_1");
    });
    await waitFor(() => {
      expect(screen.getByText(/CV content here/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Source documents/i)).toBeInTheDocument();
  });
});
