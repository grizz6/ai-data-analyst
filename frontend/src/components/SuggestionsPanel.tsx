import { useState } from "react";
import { planForGoal } from "../api";
import type { AnalysisResult, PlanResponse, Recommendation, RecommendationAction } from "../types";
import Hint from "./Hint";

// The rest of the list is one click away, so the tab opens short.
const SHOWN_AT_FIRST = 5;

const EXAMPLE_GOALS = [
  "Reduce customer churn",
  "Forecast next quarter's sales",
  "Find customer segments to target",
  "Understand what drives revenue",
];

const READINESS: Record<Recommendation["readiness"], [string, string]> = {
  ready: ["Ready", "good"],
  needs_work: ["Needs work first", "warning"],
  weak: ["Weak evidence", "info"],
};

const VERDICT: Record<NonNullable<AnalysisResult["review"]>["readiness"], string> = {
  ready: "good",
  needs_work: "warning",
  not_ready: "error",
};

type Step = Pick<Recommendation, "title" | "why" | "readiness" | "risks" | "check_first" | "action">;

function List({ label, items, className }: { label: string; items: string[]; className: string }) {
  if (!items.length) return null;
  return (
    <ul className={className} aria-label={label}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function StepItem({ step, onAction }: { step: Step; onAction: (action: RecommendationAction) => void }) {
  const [label, tone] = READINESS[step.readiness];
  return (
    <li>
      <div className="plan-step-text">
        <span className="step-title">
          <strong>{step.title}</strong> <span className={`badge ${tone}`}>{label}</span>
        </span>
        <span>{step.why}</span>
        <List label="Risks" items={step.risks} className="risks" />
        <List label="Check first" items={step.check_first} className="check-first" />
      </div>
      <button type="button" className="btn secondary small-btn" onClick={() => onAction(step.action)}>
        {step.action.label}
      </button>
    </li>
  );
}

interface Props {
  sessionId: string;
  review: AnalysisResult["review"];
  recommendations: Recommendation[];
  onAction: (action: RecommendationAction) => void;
}

export default function SuggestionsPanel({ sessionId, review, recommendations, onAction }: Props) {
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
      {review && (
        <section className="stats-section analyst-read" aria-label="Analyst's read">
          <h3>
            Analyst's read{" "}
            <Hint text="A critical review of the whole dataset: what would mislead an analysis, what it does well, and what it can't support. Every point is computed from the exploration." />
          </h3>
          <p className={`verdict ${VERDICT[review.readiness]}`}>{review.verdict}</p>
          {review.concerns.length > 0 && (
            <>
              <h4>Concerns, most serious first</h4>
              <ol className="concerns" aria-label="Concerns">
                {review.concerns.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ol>
            </>
          )}
          <div className="grid-2">
            <div>
              <h4>What it does well</h4>
              <List label="Strengths" items={review.strengths} className="insight-list" />
            </div>
            <div>
              <h4>What it can't tell you</h4>
              <List label="Can't conclude" items={review.cannot_conclude} className="insight-list" />
            </div>
          </div>
        </section>
      )}

      <section className="stats-section" aria-label="What this data could be used for">
        <h3>
          What this data could be used for{" "}
          <Hint text="Analyses this data supports, ranked by how strongly the exploration backs them. Each says how ready the data is, what could make the answer wrong, and what to check first." />
        </h3>
        {recommendations.length === 0 ? (
          <p className="muted">No analysis stands out for this file.</p>
        ) : (
          <ol className="plan-steps">
            {shown.map((rec) => (
              <StepItem key={rec.id} step={rec} onAction={onAction} />
            ))}
          </ol>
        )}
        {recommendations.length > SHOWN_AT_FIRST && (
          <button type="button" className="link-btn" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${recommendations.length}`}
          </button>
        )}
      </section>

      <section className="stats-section" aria-label="Plan for a goal">
        <h3>
          Have a specific goal?{" "}
          <Hint text="Describe it in your own words. The plan picks from the analyses above, keeps their risks, and every figure in it comes from the exploration." />
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
                <StepItem key={step.id} step={step} onAction={onAction} />
              ))}
            </ol>
          </div>
        )}
      </section>
    </>
  );
}
