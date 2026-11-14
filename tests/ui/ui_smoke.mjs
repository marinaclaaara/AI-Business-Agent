// Teste do painel: executa o app.js REAL no jsdom contra a API REAL. Uso: BASE=http://localhost:8010 KEY=segredo node ui_smoke.mjs
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const BASE = process.env.BASE, KEY = process.env.KEY || "";
const auth = KEY ? { Authorization: `Bearer ${KEY}` } : {};
const espera = (ms) => new Promise((r) => setTimeout(r, ms));
async function ate(cond, rotulo) { for (let i = 0; i < 60; i++) { if (cond()) return; await espera(50); } throw new Error("timeout: " + rotulo); }

const html = await (await fetch(BASE + "/")).text();
const dom = new JSDOM(html, {
  url: BASE + "/", runScripts: "outside-only", pretendToBeVisual: true,
  beforeParse(w) { w.fetch = (u, o) => fetch(new URL(u, BASE), o); w.Blob = Blob; },
});
const { window } = dom, { document } = window;
const app = await (await fetch(BASE + "/static/app.js")).text();
window.eval(app);

document.getElementById("chave").value = KEY;
document.getElementById("atualizar").click();
await ate(() => document.querySelectorAll("#tabela tbody tr").length >= 2, "tabela com linhas");
const linhas = [...document.querySelectorAll("#tabela tbody tr")];
console.log(`  tabela: ${linhas.length} linhas; KPIs: ${document.querySelectorAll("#kpis div").length}; gráficos svg: ${document.querySelectorAll("#graficos svg").length}`);
assert.equal(document.querySelectorAll("#kpis div").length, 4);
assert.equal(document.querySelectorAll("#graficos svg").length, 3);

// XSS: o nome de arquivo malicioso deve aparecer como TEXTO, nunca virar elemento
assert.ok(document.body.textContent.includes("<img src=x onerror"), "payload deve aparecer como texto");
assert.equal(document.querySelectorAll("img").length, 0, "nenhum <img> pode ter sido criado a partir do conteúdo");
assert.equal(window.__xss, undefined);

// abre o detalhe de uma solicitação pendente e revisa
const pendente = linhas.find((tr) => tr.textContent.includes("PENDENTE_REVISAO")) ?? linhas[0];
pendente.click();
await ate(() => !document.getElementById("detalhe").hidden && document.getElementById("revisor"), "detalhe");
assert.ok(document.getElementById("detalhe").textContent.includes("Trilha de auditoria"));
document.getElementById("revisor").value = "Carla Teste";
[...document.querySelectorAll("#detalhe button")].find((b) => b.textContent === "Aprovar").click();
await ate(() => document.getElementById("detalhe").textContent.includes("humano:Carla Teste"), "aprovação refletida na tela");
const id = Number(document.querySelector("#detalhe h2").textContent.match(/#(\d+)/)[1]);
const depois = await (await fetch(`${BASE}/api/solicitacoes/${id}`, { headers: auth })).json();
assert.equal(depois.status, "APROVADA"); assert.equal(depois.revisor, "Carla Teste");
assert.equal(document.getElementById("revisor"), null, "formulário some depois de revisado");

// chave errada -> mensagem em português, sem quebrar
document.getElementById("chave").value = "errada";
document.getElementById("atualizar").click();
await ate(() => document.getElementById("msg").textContent.includes("Chave de API inválida"), "mensagem de 401");
console.log("UI SMOKE OK: tabela, KPIs, gráficos SVG, XSS neutralizado, revisão humana ponta a ponta, erro 401 tratado");
