import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import ColumnEditor from "../ColumnEditor";
import type { Column } from "../../types";

const initialColumns: Column[] = [
  {
    id: "col_1",
    name: "Background",
    description: "Career background",
    output_type: "short_text",
    required_evidence: false,
  },
  {
    id: "col_2",
    name: "Notable Cases",
    description: "Notable arbitration cases",
    output_type: "long_text",
    required_evidence: false,
  },
];

function renderEditor(overrides: Partial<ComponentProps<typeof ColumnEditor>> = {}) {
  const onApprove = vi.fn();
  const onBack = vi.fn();
  const props = {
    researchGoal: "the goal",
    initialColumns,
    loading: false,
    onApprove,
    onBack,
    ...overrides,
  };
  render(<ColumnEditor {...props} />);
  return { ...props, onApprove, onBack };
}

describe("ColumnEditor", () => {
  it("renders each provided column", () => {
    renderEditor();
    expect(screen.getByDisplayValue("Background")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Notable Cases")).toBeInTheDocument();
  });

  it("can add a new column", async () => {
    const user = userEvent.setup();
    renderEditor();

    await user.click(screen.getByRole("button", { name: /add column/i }));

    expect(screen.getByDisplayValue("New column")).toBeInTheDocument();
  });

  it("can edit a column name", async () => {
    const user = userEvent.setup();
    renderEditor();

    const input = screen.getByDisplayValue("Background") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "Education");

    expect(screen.getByDisplayValue("Education")).toBeInTheDocument();
  });

  it("can delete a column", async () => {
    const user = userEvent.setup();
    renderEditor();

    // The delete button has title="Delete column"
    const deleteButtons = screen.getAllByTitle(/delete column/i);
    await user.click(deleteButtons[0]);

    expect(screen.queryByDisplayValue("Background")).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("Notable Cases")).toBeInTheDocument();
  });

  it("calls onApprove with the current columns and research goal", async () => {
    const user = userEvent.setup();
    const props = renderEditor();

    const input = screen.getByDisplayValue("Background") as HTMLInputElement;
    await user.clear(input);
    await user.type(input, "Education");

    await user.click(screen.getByRole("button", { name: /approve & create table/i }));

    expect(props.onApprove).toHaveBeenCalledTimes(1);
    const [goalArg, columnsArg] = props.onApprove.mock.calls[0];
    expect(goalArg).toBe("the goal");
    expect(columnsArg).toHaveLength(2);
    expect(columnsArg[0]).toMatchObject({ id: "col_1", name: "Education" });
    expect(columnsArg[1]).toMatchObject({ id: "col_2", name: "Notable Cases" });
  });
});
