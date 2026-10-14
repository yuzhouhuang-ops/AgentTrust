// 验证视频脚本中的演示效果描述是否稳定成立。
// 跑多次独立演示，统计「第 1 轮是否必然选中虚报型」以及后续轮次的行为。

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const html = fs.readFileSync(path.join(__dirname, "..", "demo", "index.html"), "utf-8");
const jsCode = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function makeEl() {
  return { innerHTML: "", textContent: "", scrollTop: 0, scrollHeight: 0,
           classList: { add() {}, remove() {} }, onclick: null, style: {} };
}
const elements = {};
const ctx = {
  document: { getElementById(id) { return (elements[id] ||= makeEl()); } },
  console, Math, Set, String, Number, Array, JSON,
};
vm.createContext(ctx);
vm.runInContext(jsCode, ctx, { filename: "demo" });

const REQUIRED = ["research"];
const ROUNDS = 20;
const TRIALS = 200;

let firstIsLiar = 0;
const liarCounts = [];
const firstFail = 0;
let secondRoundLiar = 0;

for (let t = 0; t < TRIALS; t++) {
  const agents = ctx.makeAgents();
  let liarPicks = 0;
  let firstPick = null;
  let secondPick = null;

  for (let r = 1; r <= ROUNDS; r++) {
    const scored = agents
      .filter(a => ctx.matchScore(a.capabilities, REQUIRED) > 0)
      .map(a => ({ a, t: ctx.totalScore(a, REQUIRED) }))
      .sort((x, y) => y.t - x.t);
    const chosen = scored[0].a;
    if (r === 1) firstPick = chosen;
    if (r === 2) secondPick = chosen;
    if (chosen.deceptive) liarPicks++;
    const ok = Math.random() < chosen.trueRate;
    if (ok) chosen.successes++; else chosen.failures++;
  }

  if (firstPick.deceptive) firstIsLiar++;
  if (secondPick.deceptive) secondRoundLiar++;
  liarCounts.push(liarPicks);
}

const avg = liarCounts.reduce((a, b) => a + b, 0) / TRIALS;
const maxLiar = Math.max(...liarCounts);
const zeroOrOne = liarCounts.filter(c => c <= 1).length;

console.log(`模拟 ${TRIALS} 次独立的 20 轮演示：\n`);
console.log(`  第 1 轮选中虚报型的次数        : ${firstIsLiar}/${TRIALS}  (${(firstIsLiar / TRIALS * 100).toFixed(1)}%)`);
console.log(`  第 2 轮仍选中虚报型的次数      : ${secondRoundLiar}/${TRIALS}  (${(secondRoundLiar / TRIALS * 100).toFixed(1)}%)`);
console.log(`  20 轮中被选中 <=1 次的比例     : ${zeroOrOne}/${TRIALS}  (${(zeroOrOne / TRIALS * 100).toFixed(1)}%)`);
console.log(`  20 轮中被选中次数 平均/最大    : ${avg.toFixed(2)} / ${maxLiar}`);
console.log();
console.log("视频脚本中的相关表述：");
console.log(`  「第一轮，系统按综合分选中了它」 -> ${firstIsLiar === TRIALS ? "必然成立 ✓" : `不必然（${firstIsLiar}/${TRIALS}）`}`);
console.log(`  「从第二轮开始，再也没有选过它」 -> ${secondRoundLiar === 0 ? "必然成立 ✓" : `不必然（${secondRoundLiar}/${TRIALS} 例外）`}`);
console.log();
if (secondRoundLiar > 0) {
  console.log("建议：把脚本措辞改为「从第二轮开始，系统几乎不再选它」以保持严谨。");
}
