import { useState } from "react";
import { createTable, proposeColumns, startTable, openSSE } from "./api";
import { Column, ResearchTable, SSEEvent } from "./types";
import ResearchSetup from "./components/ResearchSetup";
import ColumnEditor from "./components/ColumnEditor";
import ResearchTableView from "./components/ResearchTable";

type Phase =
  | { name: "setup" }
  | { name: "proposing" }
  | { name: "editing"; columns: Column[]; researchGoal: string }
  | { name: "creating" }
  | { name: "table"; table: ResearchTable };

export default function App() {
  const [phase, setPhase] = useState<Phase>({ name: "setup" });
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate(researchGoal: string) {
    setError(null);
    setPhase({ name: "proposing" });
    try {
      const columns = await proposeColumns(researchGoal);
      setPhase({ name: "editing", columns, researchGoal });
    } catch (e) {
      setError(String(e));
      setPhase({ name: "setup" });
    }
  }

  async function handleApprove(researchGoal: string, columns: Column[]) {
    setError(null);
    setPhase({ name: "creating" });
    try {
      const table = await createTable(researchGoal, columns);
      setPhase({ name: "table", table });
    } catch (e) {
      setError(String(e));
      setPhase({ name: "setup" });
    }
  }

  async function handleStart(tableId: string) {
    if (phase.name !== "table") return;
    setError(null);
    try {
      await startTable(tableId);

      const es = openSSE(tableId);
      es.onmessage = (evt) => {
        const event: SSEEvent = JSON.parse(evt.data);
        setPhase((prev) => {
          if (prev.name !== "table") return prev;
          return { name: "table", table: applySSEEvent(prev.table, event) };
        });
      };
      es.onerror = () => es.close();

      setPhase((prev) =>
        prev.name === "table"
          ? { name: "table", table: { ...prev.table, status: "running" } }
          : prev
      );
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="min-h-screen">
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <h1 className="text-xl font-semibold text-gray-900">Arbitrator Research Table</h1>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {error && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {error}
          </div>
        )}

        {(phase.name === "setup" || phase.name === "proposing") && (
          <ResearchSetup
            loading={phase.name === "proposing"}
            onGenerate={handleGenerate}
          />
        )}

        {(phase.name === "editing" || phase.name === "creating") && (
          <ColumnEditor
            researchGoal={phase.name === "editing" ? phase.researchGoal : ""}
            initialColumns={phase.name === "editing" ? phase.columns : []}
            loading={phase.name === "creating"}
            onApprove={handleApprove}
            onBack={() => setPhase({ name: "setup" })}
          />
        )}

        {phase.name === "table" && (
          <ResearchTableView
            table={phase.table}
            onStart={handleStart}
          />
        )}
      </main>
    </div>
  );
}

function applySSEEvent(table: ResearchTable, event: SSEEvent): ResearchTable {
  const column = table.columns.find((c) => c.id === event.columnId);
  if (!column) return table;

  const updatedCells = table.cells.map((cell) => {
    if (cell.row_id !== event.rowId || cell.column_name !== column.name) return cell;

    if (event.type === "cell_working") {
      return { ...cell, status: "working" as const };
    }
    if (event.type === "cell_done") {
      return {
        ...cell,
        status: "done" as const,
        value: event.value,
        confidence: event.confidence,
        sources: event.sources,
      };
    }
    if (event.type === "cell_failed") {
      return { ...cell, status: "failed" as const };
    }
    return cell;
  });

  return { ...table, cells: updatedCells };
}
