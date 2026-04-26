export type OutputType = "short_text" | "long_text" | "boolean" | "number" | "date" | "list";

export interface Column {
  id: string;
  name: string;
  description: string;
  output_type: OutputType;
  required_evidence: boolean;
}

export interface Row {
  id: string;
  name: string;
}

export interface Source {
  title: string;
  url: string;
}

export interface Cell {
  id: string;
  row_id: string;
  column_name: string;
  status: "pending" | "working" | "done" | "failed";
  value?: string;
  confidence?: "low" | "medium" | "high";
  reasoning?: string;
  sources?: Source[];
}

export interface ResearchTable {
  id: string;
  research_goal: string;
  status: "draft" | "running" | "done" | "failed";
  rows: Row[];
  columns: Column[];
  cells: Cell[];
}

export interface CellWorkingEvent {
  type: "cell_working";
  rowId: string;
  columnId: string;
}

export interface CellDoneEvent {
  type: "cell_done";
  rowId: string;
  columnId: string;
  value: string;
  confidence: "low" | "medium" | "high";
  sources: Source[];
}

export interface CellFailedEvent {
  type: "cell_failed";
  rowId: string;
  columnId: string;
  error: string;
}

export type SSEEvent = CellWorkingEvent | CellDoneEvent | CellFailedEvent;
