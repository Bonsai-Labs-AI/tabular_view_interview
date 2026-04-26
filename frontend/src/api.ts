import { Column, ResearchTable } from "./types";

const BASE = "http://localhost:8765";

export async function proposeColumns(researchGoal: string): Promise<Column[]> {
  const res = await fetch(`${BASE}/tables/propose-columns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ research_goal: researchGoal }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.columns.map((c: Column & { id?: string }, i: number) => ({
    ...c,
    id: c.id ?? `col_${i + 1}`,
  }));
}

export async function createTable(
  researchGoal: string,
  columns: Column[]
): Promise<ResearchTable> {
  const res = await fetch(`${BASE}/tables`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ research_goal: researchGoal, columns }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getTable(tableId: string): Promise<ResearchTable> {
  const res = await fetch(`${BASE}/tables/${tableId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function startTable(tableId: string): Promise<void> {
  const res = await fetch(`${BASE}/tables/${tableId}/start`, { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
}

export function openSSE(tableId: string): EventSource {
  return new EventSource(`${BASE}/tables/${tableId}/events`);
}
