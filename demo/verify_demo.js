// 验证脚本：把 demo/index.html 里的 JavaScript 真正跑起来，
// 检查它的计算结果是否与 app/scoring.py 一致。
//
// 做法：
//   1. 从 HTML 里抽出 <script> 内容
//   2. 提供一个假的 document 对象（最小 DOM 桩），让脚本能执行
//   3. 跑脚本，再调用里面的 scoring 函数做核对
//   4. 模拟跑 N 轮，检查统计结果是否符合预期

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const htmlPath = path.join(__dirname, "..", "demo", "index.html");
const html = fs.readFileSync(htmlPath, "utf-8");

// ---------- 抠出 <script> 里的代码 ----------
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: HTML 里找不到 <script> 段"); process.exit(1); }
const jsCode = m[1];

// ---------- 最小 DOM 桩 ----------
function makeEl() {
  return {
    innerHTML: "", textContent: "", scrollTop: 0, scrollHeight: 0,
    classList: { add() {}, remove() {} },
    onclick: null,
    style: {},
  };
}
const elements = {};
const document = {
  getElementById(id) {
    if (!elements[id]) {
      elements[id] = makeEl();
    }
    return elements[id];
  },
};

// ---------- 执行 ----------
const ctx = { document, console, Math, Set, String, Number, Array, JSON };
vm.createContext(ctx);
try {
  vm.runInContext(jsCode, ctx, { filename: "demo/index.html <script>" });
} catch (e) {
  console.error("FAIL: 脚本执行报错 ->", e.message);
  process.exit(1);
}
console.log("PASS: HTML 里的 JavaScript 能正常执行，无报错");

// ---------- 核对 scoring 函数 ----------
let pass = 0, fail = 0;
function check(label, got, expect, tol = 1e-9) {
  const ok = Math.abs(got - expect) < tol;
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${label}: got=${got} expect=${expect}`);
  ok ? pass++ : fail++;
}

console.log("\n--- trustScore 与 app/scoring.py 对比 ---");
const trustCases = [
  [0, 0, 0.5], [1, 0, 0.6], [0, 1, 0.4],
  [8, 2, 10 / 14], [5, 3, 7 / 12], [1, 7, 3 / 12],
  [100, 0, 102 / 104], [0, 100, 2 / 104],
];
for (const [s, f, expect] of trustCases) {
  check(`trustScore(${s},${f})`, ctx.trustScore(s, f), expect);
}

console.log("\n--- latencyScore 与 app/scoring.py 对比 ---");
for (const [ms, expect] of [[0, 1.0], [1000, 0.5], [5000, 1000 / 6000], [150, 1000 / 1150]]) {
  check(`latencyScore(${ms})`, ctx.latencyScore(ms), expect);
}

console.log("\n--- matchScore 与 app/scoring.py 对比 ---");
check("matchScore 完全匹配", ctx.matchScore(["research", "summarization"], ["research", "summarization"]), 1.0);
check("matchScore 一半", ctx.matchScore(["research"], ["research", "coding"]), 0.5);
check("matchScore 无关", ctx.matchScore(["research"], ["cooking"]), 0.0);
check("matchScore 大小写空格", ctx.matchScore(["  ReSearch "], ["research"]), 1.0);
check("matchScore 空需求", ctx.matchScore(["research"], []), 0.0);
check("matchScore 多余能力不加分", ctx.matchScore(["a", "b", "c"], ["a"]), 1.0);

console.log("\n--- 综合分与手算对比（冷启动，任务只需 research）---");
const cs = ctx.makeAgents();
const byName = Object.fromEntries(cs.map(a => [a.name, a]));
for (const [name, expCap, expTrust, expLat] of [
  ["Reliable-Researcher", 0.6, 0.5, 1000 / 1430],
  ["Claimed-Expert", 0.6, 0.5, 1000 / 1150],
]) {
  const a = byName[name];
  const total = ctx.totalScore(a, ["research"]);
  check(`${name} 综合分`, total, expCap + 0.3 * expTrust + 0.1 * expLat);
}

console.log("\n--- 冷启动时谁会被选中？（应是最快的 Claimed-Expert）---");
const cold = ctx.makeAgents();
const scores = cold.map(a => [a.name, ctx.totalScore(a, ["research"])]);
scores.sort((x, y) => y[1] - x[1]);
console.log("  排序:", scores.map(([n, s]) => `${n}=${s.toFixed(4)}`).join(" > "));
check("冷启动选中 Claimed-Expert", scores[0][0] === "Claimed-Expert" ? 1 : 0, 1);

// ---------- 模拟跑 300 轮，检查行为 ----------
console.log("\n--- 模拟 300 轮，检查抗欺骗行为 ---");
const simAgents = ctx.makeAgents();
// 直接复用页面逻辑的核心：按综合分挑选 + 概率决定成败
const REQUIRED = ["research"];
const picks = {}, wins = {};
let deceptivePicks = 0;
for (let i = 0; i < 300; i++) {
  const scored = simAgents
    .filter(a => ctx.matchScore(a.capabilities, REQUIRED) > 0)
    .map(a => ({ a, t: ctx.totalScore(a, REQUIRED) }))
    .sort((x, y) => y.t - x.t);
  const chosen = scored[0].a;
  picks[chosen.name] = (picks[chosen.name] || 0) + 1;
  if (chosen.deceptive) deceptivePicks++;
  const ok = Math.random() < chosen.trueRate;
  if (ok) { chosen.successes++; wins[chosen.name] = (wins[chosen.name] || 0) + 1; }
  else chosen.failures++;
}
console.log("  各智能体被选中次数:", JSON.stringify(picks));
const totalPicks = Object.values(picks).reduce((a, b) => a + b, 0);
console.log(`  虚报型被选中率: ${(deceptivePicks / totalPicks * 100).toFixed(1)}%`);
check("虚报型未被大量选中（<10%）", deceptivePicks / totalPicks < 0.10 ? 1 : 0, 1);
check("选了 300 次", totalPicks, 300);

console.log(`\n===== 结果: ${pass} 项通过, ${fail} 项失败 =====`);
process.exit(fail ? 1 : 0);
