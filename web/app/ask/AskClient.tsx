"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AnswerChart } from "@/components/AnswerChart";
import type { AskResponse } from "@/lib/api";

const EXAMPLES = [
  "Why did paid social CAC jump in March?",
  "Which channel's CAC grew most this quarter and why?",
  "What is LTV:CAC by channel last quarter?",
  "Which channel pays back fastest this year?",
  "Fully loaded CAC by channel last quarter",
  "Compare CAC across attribution models for Meta",
  "Monthly CAC trend for LinkedIn this year",
  "What share of customers are unattributed this quarter?",
];

type Turn = { id: number; response?: AskResponse; error?: string; question: string };

export function AskClient() {
  const params = useSearchParams();
  const input = useRef<HTMLInputElement>(null);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);

  useEffect(() => {
    if (params.get("focus")) input.current?.focus();
  }, [params]);

  async function ask(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    const id = Date.now();
    setTurns((t) => [{ id, question: q }, ...t]);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          question: q,
          fully_loaded: params.get("fully_loaded") === "true",
          attribution: params.get("attribution") ?? "position_based",
        }),
      });
      const body = (await res.json()) as AskResponse & { detail?: string };
      setTurns((t) =>
        t.map((turn) =>
          turn.id === id ? (res.ok ? { ...turn, response: body } : { ...turn, error: body.detail ?? "Request failed" }) : turn,
        ),
      );
    } catch {
      setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, error: "Could not reach the app server." } : turn)));
    } finally {
      setBusy(false);
      setQuestion("");
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void ask(question);
  }

  return (
    <div className="stack">
      <section className="card">
        <form className="ask-box" onSubmit={onSubmit} role="search">
          <label htmlFor="ask-input" className="sr-only">
            Ask a question about CAC, LTV or payback
          </label>
          <input
            id="ask-input"
            ref={input}
            type="search"
            placeholder="e.g. Why did paid social CAC jump in March?   (press / to focus)"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={500}
            autoComplete="off"
          />
          <button className="btn" type="submit" disabled={busy || question.trim().length < 3}>
            {busy ? "Thinking…" : "Ask"}
          </button>
        </form>
        <div className="chips" aria-label="Example questions">
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" className="chip" onClick={() => void ask(ex)} disabled={busy}>
              {ex}
            </button>
          ))}
        </div>
      </section>

      <div aria-live="polite" className="stack">
        {turns.map((turn) => (
          <article key={turn.id} className="card" aria-busy={!turn.response && !turn.error}>
            <div className="card-head">
              <h2>{turn.question}</h2>
              {turn.response && (
                <span className="pill pill-neutral" title={turn.response.model ?? undefined}>
                  {turn.response.planner === "claude" ? "Claude" : "Offline planner"}
                </span>
              )}
            </div>
            {!turn.response && !turn.error && <p className="muted">Querying the semantic layer…</p>}
            {turn.error && (
              <p role="alert" className="delta-bad">
                {turn.error}
              </p>
            )}
            {turn.response && (
              <>
                <p className="answer">{turn.response.answer}</p>
                {turn.response.chart && (
                  <div style={{ marginTop: 12 }}>
                    <AnswerChart chart={turn.response.chart} />
                  </div>
                )}
                <details style={{ marginTop: 12 }}>
                  <summary className="muted">Queries used ({turn.response.queries.length})</summary>
                  {turn.response.queries.map((q, i) => (
                    <div key={i} style={{ marginTop: 8 }}>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {q.tool} {q.ok ? "" : `— error: ${q.error ?? ""}`}
                      </div>
                      <pre className="code">{JSON.stringify(q.input, null, 2)}</pre>
                      {q.sql.map((s, j) => (
                        <pre className="code" key={j}>
                          {s}
                        </pre>
                      ))}
                    </div>
                  ))}
                </details>
              </>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
