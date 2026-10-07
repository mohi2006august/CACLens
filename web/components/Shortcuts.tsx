"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

/** DESIGN.md §7: `/` focuses search (the Ask box), `?` opens the shortcuts list. */
export function Shortcuts() {
  const dialog = useRef<HTMLDialogElement>(null);
  const router = useRouter();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        const box = document.getElementById("ask-input") as HTMLInputElement | null;
        if (box) box.focus();
        else router.push("/ask?focus=1");
      } else if (e.key === "?") {
        e.preventDefault();
        dialog.current?.showModal();
      } else if (e.key === "g") {
        const next = (ev: KeyboardEvent) => {
          const map: Record<string, string> = { o: "/", c: "/cohorts", a: "/alerts", b: "/optimiser", t: "/attribution" };
          const href = map[ev.key];
          if (href) router.push(href);
          window.removeEventListener("keydown", next);
        };
        window.addEventListener("keydown", next, { once: true });
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  return (
    <dialog ref={dialog} className="shortcuts" aria-labelledby="shortcuts-title">
      <h2 id="shortcuts-title">Keyboard shortcuts</h2>
      <table className="data" style={{ marginTop: 12 }}>
        <tbody>
          <tr><td><kbd>/</kbd></td><td>Ask a question</td></tr>
          <tr><td><kbd>?</kbd></td><td>Show this list</td></tr>
          <tr><td><kbd>g</kbd> <kbd>o</kbd></td><td>Overview</td></tr>
          <tr><td><kbd>g</kbd> <kbd>c</kbd></td><td>Cohorts</td></tr>
          <tr><td><kbd>g</kbd> <kbd>t</kbd></td><td>Attribution</td></tr>
          <tr><td><kbd>g</kbd> <kbd>a</kbd></td><td>Alerts</td></tr>
          <tr><td><kbd>g</kbd> <kbd>b</kbd></td><td>Budget optimiser</td></tr>
          <tr><td><kbd>←</kbd> <kbd>→</kbd></td><td>Step through a focused chart</td></tr>
        </tbody>
      </table>
      <form method="dialog" style={{ marginTop: 16, textAlign: "right" }}>
        <button className="btn btn-ghost">Close</button>
      </form>
    </dialog>
  );
}
