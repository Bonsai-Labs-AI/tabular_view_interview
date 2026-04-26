import { useState } from "react";
import { Column, OutputType } from "../types";

const OUTPUT_TYPE_LABELS: Record<OutputType, string> = {
  short_text: "Short text",
  long_text: "Long text",
  boolean: "Yes / No",
  number: "Number",
  date: "Date",
  list: "List",
};

interface Props {
  researchGoal: string;
  initialColumns: Column[];
  loading: boolean;
  onApprove: (researchGoal: string, columns: Column[]) => void;
  onBack: () => void;
}

export default function ColumnEditor({ researchGoal, initialColumns, loading, onApprove, onBack }: Props) {
  const [columns, setColumns] = useState<Column[]>(initialColumns);

  function updateName(id: string, name: string) {
    setColumns((prev) => prev.map((c) => (c.id === id ? { ...c, name } : c)));
  }

  function updateType(id: string, output_type: OutputType) {
    setColumns((prev) => prev.map((c) => (c.id === id ? { ...c, output_type } : c)));
  }

  function deleteColumn(id: string) {
    setColumns((prev) => prev.filter((c) => c.id !== id));
  }

  function addColumn() {
    const id = `col_new_${Date.now()}`;
    setColumns((prev) => [
      ...prev,
      {
        id,
        name: "New column",
        description: "",
        output_type: "short_text",
        required_evidence: false,
      },
    ]);
  }

  return (
    <div className="max-w-3xl">
      <div className="mb-6">
        <p className="text-sm text-gray-500 mb-1">Research goal</p>
        <p className="text-sm font-medium text-gray-800">{researchGoal}</p>
      </div>

      <h2 className="text-lg font-medium text-gray-900 mb-4">Proposed Columns</h2>

      <div className="space-y-3 mb-6">
        {columns.map((col) => (
          <div
            key={col.id}
            className="bg-white border border-gray-200 rounded-lg p-4 flex items-start gap-3"
          >
            <div className="flex-1 min-w-0">
              <input
                type="text"
                value={col.name}
                onChange={(e) => updateName(col.id, e.target.value)}
                className="w-full text-sm font-medium text-gray-900 border-0 border-b border-transparent hover:border-gray-300 focus:border-blue-500 focus:outline-none bg-transparent pb-0.5 mb-1"
                disabled={loading}
              />
              {col.description && (
                <p className="text-xs text-gray-500 truncate">{col.description}</p>
              )}
            </div>

            <select
              value={col.output_type}
              onChange={(e) => updateType(col.id, e.target.value as OutputType)}
              className="text-xs border border-gray-200 rounded px-2 py-1 text-gray-600 bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
              disabled={loading}
            >
              {(Object.keys(OUTPUT_TYPE_LABELS) as OutputType[]).map((t) => (
                <option key={t} value={t}>
                  {OUTPUT_TYPE_LABELS[t]}
                </option>
              ))}
            </select>

            <button
              onClick={() => deleteColumn(col.id)}
              className="text-gray-400 hover:text-red-500 p-1 rounded"
              disabled={loading}
              title="Delete column"
            >
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </button>
          </div>
        ))}
      </div>

      <button
        onClick={addColumn}
        className="mb-8 text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1"
        disabled={loading}
      >
        <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clipRule="evenodd" />
        </svg>
        Add column
      </button>

      <div className="flex items-center gap-3">
        <button
          onClick={() => onApprove(researchGoal, columns)}
          disabled={loading || columns.length === 0}
          className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {loading && (
            <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
          )}
          {loading ? "Creating table..." : "Approve & Create Table"}
        </button>

        <button
          onClick={onBack}
          disabled={loading}
          className="px-4 py-2.5 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-50"
        >
          Back
        </button>
      </div>
    </div>
  );
}
