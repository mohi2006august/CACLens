"use client";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="card error-card" role="alert">
      <h2>Something went wrong</h2>
      <p className="secondary">{error.message}</p>
      <button className="btn btn-ghost" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
