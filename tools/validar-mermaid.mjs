// Valida los diagramas Mermaid de un fichero markdown contra el parser real.
//
// No entra en la suite de tests porque necesita npm, y la regla del repo es que
// `./tests/run.sh` corra sin instalar nada. Un diagrama roto se ve peor que
// ninguno, asi que conviene pasarlo antes de tocar los diagramas del README:
//
//   npm install mermaid jsdom
//   node tools/validar-mermaid.mjs README.md
//
import { readFileSync } from "node:fs";
import { JSDOM } from "jsdom";
const dom = new JSDOM("<!doctype html><body></body>", { pretendToBeVisual: true });
for (const k of ["window", "document", "Element", "SVGElement", "Node",
                 "HTMLElement", "DocumentFragment", "NodeFilter", "DOMParser", "XMLSerializer"]) {
  Object.defineProperty(globalThis, k, {
    value: k === "window" ? dom.window : dom.window[k], configurable: true, writable: true,
  });
}
const mermaid = (await import("mermaid")).default;
const md = readFileSync(process.argv[2], "utf8");
const bloques = [...md.matchAll(/```mermaid\n([\s\S]*?)```/g)].map(m => m[1]);
mermaid.initialize({ startOnLoad: false });
let fallos = 0;
for (const [i, código] of bloques.entries()) {
  const tipo = código.trim().split("\n")[0].slice(0, 42);
  try {
    await mermaid.parse(código);
    console.log(`  [ok] #${i + 1}  ${tipo}`);
  } catch (e) {
    fallos++;
    console.log(`  [!!] #${i + 1}  ${tipo}\n       ${String(e.message).split("\n").slice(0,3).join(" | ")}`);
  }
}
console.log(`\n${bloques.length} diagramas, ${fallos} con error`);
process.exit(fallos ? 1 : 0);
