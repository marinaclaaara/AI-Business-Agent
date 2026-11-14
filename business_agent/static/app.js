// Painel de revisão. REGRA DE SEGURANÇA: todo texto vindo da API (que pode vir de um PDF malicioso)
// é inserido com textContent, NUNCA com innerHTML. Não há JS inline (a CSP do servidor proíbe).
"use strict";

const $ = (id) => document.getElementById(id);
const estado = { itens: [], selecionado: null };

/** Cria um elemento; filhos string viram nós de texto (seguros contra HTML injetado). */
function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const f of filhos.flat()) if (f !== null && f !== undefined) e.append(f instanceof Node ? f : document.createTextNode(String(f)));
  return e;
}

async function api(caminho, opcoes = {}) {
  const headers = { ...(opcoes.headers || {}) };
  const chave = $("chave").value;
  if (chave) headers.Authorization = `Bearer ${chave}`;
  if (opcoes.json) { headers["Content-Type"] = "application/json"; opcoes.body = JSON.stringify(opcoes.json); }
  const r = await fetch(caminho, { ...opcoes, headers });
  if (!r.ok) {
    let detalhe = `Erro ${r.status}`;
    try { const j = await r.json(); if (j.detail) detalhe = typeof j.detail === "string" ? j.detail : "Entrada inválida."; } catch { /* sem corpo JSON */ }
    throw new Error(r.status === 401 ? "Chave de API inválida ou ausente." : detalhe);
  }
  return r.json();
}

function barras(titulo, dados) {
  const NS = "http://www.w3.org/2000/svg";
  const itens = Object.entries(dados), max = Math.max(1, ...itens.map(([, v]) => v));
  const w = 360, largura = w / Math.max(itens.length, 1);
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 360 150"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", titulo);
  itens.forEach(([k, v], i) => {
    const h = (v / max) * 90, x = i * largura;
    const r = document.createElementNS(NS, "rect");
    for (const [a, b] of [["x", x + 6], ["y", 112 - h], ["width", largura - 12], ["height", h], ["rx", 3], ["class", "barra"]]) r.setAttribute(a, b);
    const tv = document.createElementNS(NS, "text"), tr = document.createElementNS(NS, "text");
    for (const t of [tv, tr]) { t.setAttribute("x", x + largura / 2); t.setAttribute("text-anchor", "middle"); }
    tv.setAttribute("y", 108 - h); tv.setAttribute("class", "val"); tv.textContent = v;
    tr.setAttribute("y", 128); tr.setAttribute("class", "rot"); tr.textContent = k.replaceAll("_", " ").slice(0, 16);
    svg.append(r, tv, tr);
  });
  return el("figure", {}, el("figcaption", {}, titulo), svg);
}

async function carregar() {
  try {
    const filtro = $("filtro").value;
    const [lista, rel] = await Promise.all([api(`/api/solicitacoes${filtro ? `?status=${encodeURIComponent(filtro)}` : ""}`), api("/api/relatorio")]);
    estado.itens = lista;
    const naRevisao = rel.por_status.PENDENTE_REVISAO || 0, bloq = rel.por_status.BLOQUEADO || 0;
    $("kpis").replaceChildren(
      ...[[rel.total, "solicitações"], [naRevisao, "aguardando revisão"], [bloq, "bloqueadas pela guarda"],
          [rel.tempo_medio_processamento_ms ?? "n/d", "ms médios por PDF (medido)"]]
        .map(([n, t]) => el("div", {}, el("b", {}, n), el("span", {}, t))));
    $("graficos").replaceChildren(barras("Por status", rel.por_status), barras("Por categoria", rel.por_categoria),
                                  barras("Por prioridade", rel.por_prioridade));
    desenharTabela();
    $("msg").textContent = "";
  } catch (e) { $("msg").textContent = e.message; $("msg").className = "erro"; }
}

function desenharTabela() {
  const cab = el("thead", {}, el("tr", {}, ...["#", "Arquivo", "Status", "Categoria", "Prioridade", "Guarda", "ms"].map((h) => el("th", {}, h))));
  const corpo = el("tbody", {}, ...estado.itens.map((s) => el("tr",
    { class: s.id === estado.selecionado ? "sel" : "", onclick: () => abrir(s.id) },
    el("td", {}, s.id), el("td", {}, s.arquivo), el("td", {}, el("span", { class: `selo s-${s.status}` }, s.status)),
    el("td", {}, s.categoria ?? "-"), el("td", {}, s.prioridade ?? "-"), el("td", {}, s.guarda_decisao ?? "-"), el("td", {}, s.tempo_ms ?? "-"))));
  $("tabela").replaceChildren(cab, corpo);
}

async function abrir(id) {
  estado.selecionado = id; desenharTabela();
  const d = await api(`/api/solicitacoes/${id}`);
  const painel = $("detalhe"); painel.hidden = false;
  const campos = d.campos || {};
  const podeRevisar = !["APROVADA", "REJEITADA"].includes(d.status);
  const revisor = el("input", { id: "revisor", placeholder: "Seu nome", maxlength: "80" });
  const nota = el("textarea", { id: "nota", rows: "2", maxlength: "1000", placeholder: "Nota (opcional)" });
  const reembolso = el("input", { type: "checkbox", id: "reembolso" });
  const decidir = async (decisao) => {
    try {
      await api(`/api/solicitacoes/${id}/revisao`, { method: "POST", json: { decisao, revisor: revisor.value, nota: nota.value || null,
        aprovar_reembolso: reembolso.checked } });
      await carregar(); await abrir(id);
    } catch (e) { $("msg").textContent = e.message; $("msg").className = "erro"; }
  };
  painel.replaceChildren(
    el("h2", {}, `Solicitação #${d.id}: ${d.arquivo}`),
    el("dl", {}, ...[["Status", d.status], ["Categoria", d.categoria ?? "-"], ["Prioridade", d.prioridade ?? "-"],
      ["Confiança", d.confianca ?? "-"], ["Cliente", campos.cliente ?? "-"], ["E-mail", campos.email ?? "-"],
      ["Pedido", campos.pedido ?? "-"], ["Valor (R$)", campos.valor_brl ?? "-"], ["Resumo", d.resumo ?? "-"],
      ["Guarda", `${d.guarda_decisao ?? "-"} (score ${d.guarda_score ?? "-"})`],
      ["Motivos da revisão", (d.motivos_revisao || []).join(", ") || "nenhum"],
      ["Sinais", (d.justificativa || []).join(", ") || "-"], ["Rascunho de resposta", d.rascunho_resposta ?? "-"]]
      .flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])),
    el("h3", {}, "Ações do agente"),
    el("ul", {}, ...d.acoes.map((a) => el("li", { class: a.status === "NEGADA" ? "neg" : "" },
      `${a.ferramenta}: ${a.status}${a.decidido_por ? ` (por ${a.decidido_por})` : ""}`))),
    el("h3", {}, "Trilha de auditoria"),
    el("ul", {}, ...d.auditoria.map((t) => el("li", { class: t.permitido ? "" : "neg" }, `${t.quando.slice(0, 19)} ${t.ator} ${t.evento} ${t.detalhe}`))),
    podeRevisar ? el("div", {}, el("h3", {}, "Revisão humana"), el("label", {}, "Revisor", revisor), nota,
      d.categoria === "reembolso" ? el("label", {}, reembolso, " Aprovar também o reembolso (ação financeira, só humano)") : null,
      el("div", { class: "linha" }, el("button", { class: "ok", onclick: () => decidir("aprovar") }, "Aprovar"),
        el("button", { class: "no", onclick: () => decidir("rejeitar") }, "Rejeitar"))) : null);
}

$("enviar").addEventListener("click", async () => {
  const arquivos = [...$("arquivos").files];
  if (!arquivos.length) { $("msg").textContent = "Escolha ao menos um PDF."; return; }
  $("enviar").disabled = true; let ok = 0; const falhas = [];
  for (const f of arquivos) {
    const fd = new FormData(); fd.append("arquivo", f);
    try { await api("/api/documentos", { method: "POST", body: fd }); ok++; } catch (e) { falhas.push(`${f.name}: ${e.message}`); }
  }
  $("enviar").disabled = false;
  $("msg").className = falhas.length ? "erro" : "mut";
  $("msg").textContent = `${ok} processado(s).` + (falhas.length ? ` Falhas: ${falhas.join(" | ")}` : "");
  await carregar();
});
$("atualizar").addEventListener("click", carregar);
$("filtro").addEventListener("change", carregar);
$("baixar").addEventListener("click", async (ev) => {
  ev.preventDefault();
  try {
    const headers = $("chave").value ? { Authorization: `Bearer ${$("chave").value}` } : {};
    const txt = await (await fetch("/api/relatorio.md", { headers })).text();
    const url = URL.createObjectURL(new Blob([txt], { type: "text/markdown" }));
    el("a", { href: url, download: "relatorio.md" }).click(); URL.revokeObjectURL(url);
  } catch (e) { $("msg").textContent = e.message; }
});
carregar();
