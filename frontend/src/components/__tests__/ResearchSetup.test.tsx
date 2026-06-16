import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResearchSetup from "../ResearchSetup";

describe("ResearchSetup", () => {
  it("renders the default research goal", () => {
    render(<ResearchSetup loading={false} onGenerate={() => {}} />);
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toMatch(/Compare these arbitrators/i);
  });

  it("disables the Generate Columns button while loading", () => {
    render(<ResearchSetup loading={true} onGenerate={() => {}} />);
    const button = screen.getByRole("button", { name: /generating columns/i });
    expect(button).toBeDisabled();
  });

  it("calls onGenerate with the trimmed goal", async () => {
    const onGenerate = vi.fn();
    const user = userEvent.setup();
    render(<ResearchSetup loading={false} onGenerate={onGenerate} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.clear(textarea);
    await user.type(textarea, "  do the research  ");

    await user.click(screen.getByRole("button", { name: /generate columns/i }));

    expect(onGenerate).toHaveBeenCalledTimes(1);
    expect(onGenerate).toHaveBeenCalledWith("do the research");
  });

  it("disables the button when the goal is blank/whitespace", async () => {
    const user = userEvent.setup();
    render(<ResearchSetup loading={false} onGenerate={() => {}} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    await user.clear(textarea);
    await user.type(textarea, "   ");

    expect(screen.getByRole("button", { name: /generate columns/i })).toBeDisabled();
  });
});
