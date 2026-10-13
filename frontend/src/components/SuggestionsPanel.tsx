import { useState } from "react";
import { planForGoal } from "../api";
import type { PlanResponse, Recommendation, RecommendationAction } from "../types";
import Hint from "./Hint";

// The rest of the list is one click away, so the tab opens short.
const SHOWN_AT_FIRST = 5;

const EXAMPLE_GOALS = [
  "Reduce customer churn",
  "Forecast next quarter's sales",
  "Find customer segments to target",
  "Understand what drives revenue",
];

function CheckFirst({ items }: { items: string[] }) {
  if (!items.length) return null;
  return (
    <ul className="check-first" aria-label="Check first">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

interface Props {
  sessionId: string;
  recommendations: Recommendation[];
  onAction: (action: RecommendationAction) => void;
}

export default function SuggestionsPanel({ sessionId, recommendations, onAction }: Props) {
  const [goal, setGoal] = useState("");
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? recommendations : recommendations.slice(0, SHOWN_AT_FIRST);

  const makePlan = async (text: string = goal) => {
    const asked = text.trim();
    if (!asked || planning) return;
    setGoal(asked);
    setPlanning(true);
    setError(null);
    try {
      setPlan(await planForGoal(sessionId, asked));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make a plan");
    } finally {
      setPlanning(false);
    }
  };

  return (
    <>
      <section className="stats-section" aria-label="Plan for a goal">
        <h3>
          What are you trying to achieve?{" "}
          <Hint text="Describe the business goal in your own words. The plan picks from the analyses this data supports, and every figure in it comes from the exploration." />
        </h3>
        <div className="suggestions" aria-label="Example goals">
          {EXAMPLE_GOALS.map((g) => (
            <button key={g} type="button" className="chip" disabled={planning} onClick={() => makePlan(g)}>
              {g}
            </button>
          ))}
        </div>
        <div className="goal-box">
          <input
            type="text"
            className="builder-select"
            aria-label="Your goal"
            maxLength={1000}
            placeholder="e.g. Find out why customers cancel and who is likely to cancel next"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing) void makePlan();
            }}
          />
          <button type="button" className="btn" disabled={planning || !goal.trim()} onClick={() => makePlan()}>
            {planning ? "Planning…" : "Make a plan"}
          </button>
        </div>
        {error && (
          <p className="error-msg" role="alert">
            {error}
          </p>
        )}
        {plan && (
          <div className="plan" aria-label="Plan">
            <p className="source-note">
              {plan.source === "llm"
                ? `Plan by ${plan.model}, from the analyses this data supports.`
                : plan.fallback_reason
                  ? `Rule-based plan: the language model's plan wasn't used (${plan.fallback_reason}).`
                  : "Rule-based plan, matched on the goal's words and column names."}
            </p>
            {plan.note && <p className="plan-note">{plan.note}</p>}
            <ol className="plan-steps">
              {plan.steps.map((step) => (
                <li key={step.id}>
                  <div className="plan-step-text">
                    <strong>{step.title}</strong>
                    <span>{step.why}</span>
                    <CheckFirst items={step.check_first} />
                  </div>
                  <button type="button" className="btn secondary small-btn" onClick={() => onAction(step.action)}>
                    {step.action.label}
                  </button>
                </li>
              ))}
            </ol>
          </div>
        )}
      </section>

      <section className="stats-section" aria-label="What this data could be used for">
        <h3>
          What this data could be used for{" "}
          <Hint text="Analyses this data supports, ranked by how strongly the exploration backs them, each with what to check or fix first. The app explores; these are for you to run next." />
        </h3>
        {recommendations.length === 0 ? (
          <p className="muted">No analysis stands out for this file.</p>
        ) : (
          <ol className="plan-steps">
            {shown.map((rec) => (
              <li key={rec.id}>
                <div className="plan-step-text">
                  <strong>{rec.title}</strong>
                  <span>{rec.why}</span>
                  <CheckFirst items={rec.check_first} />
                </div>
                <button type="button" className="btn secondary small-btn" onClick={() => onAction(rec.action)}>
                  {rec.action.label}
                </button>
              </li>
            ))}
          </ol>
        )}
        {recommendations.length > SHOWN_AT_FIRST && (
          <button type="button" className="link-btn" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${recommendations.length}`}
          </button>
        )}
      </section>
    </>
  );
}
