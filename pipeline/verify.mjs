// Headless CDP verify of the live page. Node 26 has global fetch + WebSocket.
import { spawn } from "node:child_process";

const URL = process.argv[2] || "https://anandvaghasia.com/nfl-4th-down/?nocache=" + Date.now();
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;

const chrome = spawn(CHROME, [
  "--headless", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, "--user-data-dir=/tmp/nfl-verify-profile",
  "about:blank",
], { stdio: "ignore" });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const errors = [];
let ws;

try {
  // wait for devtools endpoint
  let target;
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://localhost:${PORT}/json`)).json();
      target = list.find(t => t.type === "page");
      if (target) break;
    } catch {}
    await sleep(250);
  }
  if (!target) throw new Error("no devtools page target");

  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pending = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown")
      errors.push("EXCEPTION: " + (m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text));
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error")
      errors.push("CONSOLE.ERROR: " + m.params.args.map(a => a.value || a.description).join(" "));
  };
  const send = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const evalJs = async expr => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;

  await send("Runtime.enable");
  await send("Log.enable");
  await send("Page.enable");
  await send("Page.navigate", { url: URL });
  await sleep(4000); // let fetch + render settle

  const call = await evalJs(`document.querySelector('#vCall')?.textContent || ''`);
  const bars = await evalJs(`[...document.querySelectorAll('.bar-val')].map(e=>e.textContent)`);
  const spot = await evalJs(`document.querySelector('#spotLabel')?.textContent || ''`);
  // exercise: set a clear GO state (4th & 1 at opp 40) and reread
  const goCall = await evalJs(`
    (()=>{const t=document.querySelector('#togo');t.value=1;t.dispatchEvent(new Event('input'));
      const y=document.querySelector('#yl');y.value=40;y.dispatchEvent(new Event('input'));
      return document.querySelector('#vCall').textContent;})()`);
  // switch to leaderboard tab, count rows + top coach
  const board = await evalJs(`
    (()=>{document.querySelector('.tab[data-view="board"]').click();
      const rows=document.querySelectorAll('#boardBody tr');
      return {n:rows.length, top:rows[0]?.querySelector('.coach-name')?.textContent||''};})()`);
  const ballLeft = await evalJs(`document.querySelector('#ball').style.left`);

  console.log(JSON.stringify({ call, bars, spot, goCall, board, ballLeft, errors }, null, 2));
  const ok = call && bars.length === 3 && board.n > 5 && errors.length === 0 && /GO|PUNT|FIELD/.test(goCall);
  console.log(ok ? "\nVERIFY: PASS" : "\nVERIFY: FAIL");
  process.exitCode = ok ? 0 : 1;
} catch (e) {
  console.error("verify error:", e.message, "\nerrors:", errors);
  process.exitCode = 1;
} finally {
  try { ws?.close(); } catch {}
  chrome.kill("SIGKILL");
}
