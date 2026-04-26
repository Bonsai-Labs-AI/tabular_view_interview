import { useState } from "react";
import { Cell, Column, ResearchTable, Row, Source } from "../types";

interface Props {
  table: ResearchTable;
  onStart: (tableId: string) => void;
}

interface CellDetail {
  row: Row;
  column: Column;
  cell: Cell;
}

function getCell(table: ResearchTable, rowId: string, columnName: string): Cell | undefined {
  return table.cells.find((c) => c.row_id === rowId && c.column_name === columnName);
}

function CellStatusBadge({ status }: { status: Cell["status"] }) {
  if (status === "pending") return <span className="text-gray-300 text-xs">—</span>;
  if (status === "working") {
    return (
      <svg className="animate-spin h-4 w-4 text-amber-500 mx-auto" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
      </svg>
    );
  }
  if (status === "failed") return <span className="text-red-400 text-xs">Error</span>;
  return null;
}

function ConfidenceDot({ confidence }: { confidence?: string }) {
  const colors: Record<string, string> = {
    high: "bg-green-400",
    medium: "bg-amber-400",
    low: "bg-red-400",
  };
  if (!confidence) return null;
  return <span className={`inline-block w-2 h-2 rounded-full ${colors[confidence] ?? "bg-gray-300"} flex-shrink-0`} />;
}

export default function ResearchTableView({ table, onStart }: Props) {
  const [detail, setDetail] = useState<CellDetail | null>(null);
  const isRunning = table.status === "running";

  const pendingCount = table.cells.filter((c) => c.status === "pending").length;
  const doneCount = table.cells.filter((c) => c.status === "done").length;
  const total = table.cells.length;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <p className="text-sm text-gray-500 mb-1">Research goal</p>
          <p className="text-sm font-medium text-gray-800 max-w-xl">{table.research_goal}</p>
        </div>

        <div className="flex items-center gap-4">
          {total > 0 && (
            <span className="text-sm text-gray-500">
              {doneCount} / {total} cells done
            </span>
          )}
          <button
            onClick={() => onStart(table.id)}
            disabled={isRunning}
            className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isRunning && (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
            )}
            {isRunning ? "Running..." : pendingCount === total ? "Start Research" : "Restart"}
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200">
          <thead>
            <tr className="bg-gray-50">
              <th className="sticky left-0 bg-gray-50 px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide w-40">
                Arbitrator
              </th>
              {table.columns.map((col) => (
                <th
                  key={col.id}
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide min-w-48"
                >
                  <div>{col.name}</div>
                  <div className="font-normal normal-case text-gray-400 text-xs mt-0.5">{col.output_type.replace("_", " ")}</div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-100">
            {table.rows.map((row) => (
              <tr key={row.id} className="hover:bg-gray-50">
                <td className="sticky left-0 bg-white px-4 py-3 text-sm font-medium text-gray-900 whitespace-nowrap">
                  {row.name}
                </td>
                {table.columns.map((col) => {
                  const cell = getCell(table, row.id, col.name);
                  return (
                    <td
                      key={col.id}
                      className={`px-4 py-3 text-sm align-top cursor-pointer transition-colors ${
                        cell?.status === "working"
                          ? "bg-amber-50"
                          : cell?.status === "done"
                          ? "hover:bg-blue-50"
                          : cell?.status === "failed"
                          ? "bg-red-50"
                          : ""
                      }`}
                      onClick={() => {
                        if (cell?.status === "done") setDetail({ row, column: col, cell });
                      }}
                    >
                      {!cell || cell.status === "pending" ? (
                        <CellStatusBadge status="pending" />
                      ) : cell.status === "working" ? (
                        <CellStatusBadge status="working" />
                      ) : cell.status === "failed" ? (
                        <CellStatusBadge status="failed" />
                      ) : (
                        <div className="flex items-start gap-1.5">
                          <ConfidenceDot confidence={cell.confidence} />
                          <span className="text-gray-800 line-clamp-3 text-xs leading-relaxed">
                            {cell.value}
                          </span>
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail && (
        <CellDetailModal detail={detail} onClose={() => setDetail(null)} />
      )}
    </div>
  );
}

function CellDetailModal({ detail, onClose }: { detail: CellDetail; onClose: () => void }) {
  const { row, column, cell } = detail;

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <p className="text-xs text-gray-500">{row.name}</p>
            <h3 className="font-semibold text-gray-900">{column.name}</h3>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-sm font-medium text-gray-700">Answer</span>
              {cell.confidence && (
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  cell.confidence === "high"
                    ? "bg-green-100 text-green-700"
                    : cell.confidence === "medium"
                    ? "bg-amber-100 text-amber-700"
                    : "bg-red-100 text-red-700"
                }`}>
                  {cell.confidence} confidence
                </span>
              )}
            </div>
            <p className="text-sm text-gray-800 leading-relaxed whitespace-pre-wrap">{cell.value}</p>
          </div>

          {cell.reasoning && (
            <div>
              <p className="text-sm font-medium text-gray-700 mb-1">Reasoning</p>
              <p className="text-sm text-gray-600 leading-relaxed">{cell.reasoning}</p>
            </div>
          )}

          {cell.sources && cell.sources.length > 0 && (
            <div>
              <p className="text-sm font-medium text-gray-700 mb-2">Sources</p>
              <ul className="space-y-1">
                {cell.sources.map((src: Source, i: number) => (
                  <li key={i}>
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-blue-600 hover:underline"
                    >
                      {src.title || src.url}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
