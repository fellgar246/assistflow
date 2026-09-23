import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import HomePage from "./page";

describe("home page", () => {
  it("renders without contacting a model", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(<HomePage />);

    expect(screen.getByRole("heading", { name: "AssistFlow" })).toBeInTheDocument();
    expect(
      screen.getByText("Customer support, running on this machine."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
