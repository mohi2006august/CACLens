// `pnpm dev`: run the metrics API (:8000) and the web app (:3000) together.
import { spawn } from "node:child_process";

const shell = process.platform === "win32";
const procs = [
  { name: "api", cmd: "uv", args: ["run", "caclens", "serve", "--reload"] },
  { name: "web", cmd: "pnpm", args: ["--filter", "web", "dev"] },
].map(({ name, cmd, args }) => {
  const child = spawn(cmd, args, { stdio: "inherit", shell });
  child.on("error", (err) => {
    console.error(`[${name}] failed to start ${cmd}: ${err.message}`);
    if (cmd === "uv") console.error("Install uv (https://docs.astral.sh/uv/) or run the web app alone: pnpm dev:web");
  });
  child.on("exit", (code) => {
    if (code) console.error(`[${name}] exited with code ${code}`);
    shutdown(code ?? 0);
  });
  return child;
});

let stopping = false;
function shutdown(code) {
  if (stopping) return;
  stopping = true;
  for (const p of procs) if (!p.killed) p.kill();
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
