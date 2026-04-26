import { useState } from "react";

const ARBITRATORS = [
  "Prof. Eleanor Vance",
  "Hon. Michael Torres (Ret.)",
  "Dr. Amara Okonkwo",
  "James Whitfield, Esq.",
  "Dr. Yuki Tanaka",
];

interface Props {
  loading: boolean;
  onGenerate: (researchGoal: string) => void;
}

export default function ResearchSetup({ loading, onGenerate }: Props) {
  const [goal, setGoal] = useState(
    "Compare these arbitrators by background, notable arbitration cases, publications, and potential conflicts of interest."
  );

  return (
    <div className="max-w-2xl">
      <div className="mb-8">
        <h2 className="text-lg font-medium text-gray-900 mb-3">Arbitrators</h2>
        <ul className="space-y-2">
          {ARBITRATORS.map((name) => (
            <li key={name} className="flex items-center gap-2 text-sm text-gray-700">
              <span className="w-2 h-2 rounded-full bg-blue-400 flex-shrink-0" />
              {name}
            </li>
          ))}
        </ul>
      </div>

      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Research Goal
        </label>
        <textarea
          className="w-full rounded-lg border border-gray-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          rows={3}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="Describe what you want to research about these arbitrators..."
          disabled={loading}
        />
      </div>

      <button
        className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        onClick={() => onGenerate(goal.trim())}
        disabled={loading || !goal.trim()}
      >
        {loading && (
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
        )}
        {loading ? "Generating columns..." : "Generate Columns"}
      </button>
    </div>
  );
}
