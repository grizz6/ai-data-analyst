import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, sampleResult } from "../test/fixtures";
import SuggestionsPanel from "./SuggestionsPanel";

const plan = {
  goal: "Reduce customer churn",
  steps: [
    {
      id: "logistic:churned",
      title: "Predict churned (yes/no)",
      why: "Shows who is likely to leave.",
      action: { tab: "models", target: "churned", column: null, label: "Train models on churned" },
    },
  ],
  note: "The file has no cost column, so savings can't be estimated.",
  configured: true,
  source: "llm",
  model: "test-model",
  fallback_reason: null,
};

describe("SuggestionsPanel", () => {
  it("turns a goal into steps whose buttons run them", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(plan));
    vi.stubGlobal("fetch", fetchMock);
    const onAction = vi.fn();
    const result = sampleResult();
    render(<SuggestionsPanel sessionId={result.session_id} recommendations={result.recommendations} onAction={onAction} />);

    await userEvent.click(screen.getByRole("button", { name: "Reduce customer churn" }));
    const steps = await screen.findByLabelText("Plan");
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/sessions/${result.session_id}/plan`);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ goal: "Reduce customer churn" });
    expect(within(steps).getByText("Plan by test-model, from the analyses this file supports.")).toBeInTheDocument();
    expect(within(steps).getByText(/no cost column/)).toBeInTheDocument();
    await userEvent.click(within(steps).getByRole("button", { name: "Train models on churned" }));
    expect(onAction).toHaveBeenCalledWith(plan.steps[0].action);
  });

  it("lists the top analyses to run next with the reason from the data, the rest on request", async () => {
    const result = sampleResult();
    expect(result.recommendations.length).toBeGreaterThan(5);
    render(<SuggestionsPanel sessionId="s" recommendations={result.recommendations} onAction={() => {}} />);
    const list = screen.getByRole("region", { name: "What to run next" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(within(list).getByText(result.recommendations[0].why)).toBeInTheDocument();
    await userEvent.click(within(list).getByRole("button", { name: `Show all ${result.recommendations.length}` }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(result.recommendations.length);
  });

  it("shows the server's message when planning fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "Too many questions." }, 429)));
    render(<SuggestionsPanel sessionId="s" recommendations={[]} onAction={() => {}} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Your goal" }), "grow sales{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many questions.");
  });
});
