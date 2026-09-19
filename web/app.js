"use strict";

const view = document.getElementById("view");
let CONFIG = null;
let routeToken = 0;
let pollTimer = null;
const filters = { puzzles: { category: "", difficulty: "" }, graveyard: { category: "", reason: "" } };

const REASONS = {
  verifier_disagreement: "The two solvers disagreed",
  adversarial_ambiguity: "The wording allows another answer",
  code_execution_error: "The checking program crashed",
  code_timeout: "The checking program ran too long",
  code_output_unparseable: "The checking program gave no answer",
  proposer_malformed_output: "The proposal was malformed",
  pipeline_error: "The pipeline hit an error",
};
const FORMAT_HELP = {
  integer: "Enter a whole number.",
  fraction: "Enter a fraction in lowest terms, like 3/4.",
  decimal: (places) => `Enter a decimal rounded to ${places} decimal places.`,
};
const STAGES = ["proposing", "verifying", "polishing"];

// ---------- helpers ----------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "html") el.innerHTML = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Markdown + LaTeX. Math is lifted out first so Markdown can't mangle it; "$5 and $10" is left alone.
function renderRich(text) {
  const math = [];
  const stash = (tex, display) => { math.push({ tex, display }); return `@@M${math.length - 1}@@`; };
  let src = String(text ?? "")
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => stash(tex, true))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, tex) => stash(tex, true))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, tex) => stash(tex, false))
    .replace(/\$(?=\S)([^$\n]*?\S)\$(?!\d)/g, (_, tex) => stash(tex, false));
  let html;
  if (window.marked && window.DOMPurify) {
    html = DOMPurify.sanitize(marked.parse(src));
  } else {
    html = src.split(/\n{2,}/).map((p) => `<p>${escapeHtml(p)}</p>`).join("");
  }
  return html.replace(/@@M(\d+)@@/g, (_, i) => {
    const { tex, display } = math[Number(i)];
    if (window.katex) return katex.renderToString(tex, { displayMode: display, throwOnError: false });
    return escapeHtml(display ? `$$${tex}$$` : `$${tex}$`);
  });
}

function rich(tag, cls, text) {
  return h(tag, { class: cls, html: renderRich(text) });
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Check the values you entered.";
    throw new Error(detail);
  }
  return body;
}

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(`pf:${key}`); return v == null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(`pf:${key}`, JSON.stringify(value)); } catch { /* storage unavailable */ }
  },
};

function categoryName(id) {
  return CONFIG?.categories.find((c) => c.id === id)?.name ?? id;
}

function difficultyBadge(level) {
  const n = { easy: 1, medium: 2, hard: 3 }[level] ?? 0;
  return h("span", { class: "difficulty" },
    h("span", { class: "cells", "aria-hidden": "true" }, [1, 2, 3].map((i) => h("i", { class: i <= n ? "on" : "" }))),
    level[0].toUpperCase() + level.slice(1));
}

function formatDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function svgImage(svg, title) {
  const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  return h("figure", { class: "illustration" }, h("img", { src, alt: `Illustration for ${title}` }));
}

function mount(token, ...nodes) {
  if (token === routeToken) view.replaceChildren(...nodes);
}

function select(label, value, options, onChange) {
  return h("label", { class: "field" }, label,
    h("select", { onchange: (e) => onChange(e.target.value) },
      options.map(([v, text]) => h("option", { value: v, selected: v === value }, text))));
}

async function refreshSpend() {
  try {
    const stats = await api("/stats");
    document.getElementById("spend").textContent = `API spend so far: $${stats.total_spend_usd.toFixed(2)}`;
  } catch { /* non-essential */ }
}

function confirmDialog(message) {
  const dialog = document.getElementById("confirm");
  document.getElementById("confirm-body").textContent = message;
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
    document.getElementById("confirm-ok").focus();
  });
}

// ---------- puzzles ----------

async function showPuzzles(token) {
  const f = filters.puzzles;
  const params = new URLSearchParams({ status: "valid" });
  if (f.category) params.set("category", f.category);
  if (f.difficulty) params.set("difficulty", f.difficulty);
  const rows = await api(`/problems?${params}`);

  const rerender = () => showPuzzles(routeToken);
  const list = rows.length
    ? h("ul", { class: "rows" }, rows.map((r) => {
        const attempt = store.get(`attempt:${r.id}`, null);
        const side = attempt
          ? h("span", { class: `row-side ${attempt.correct ? "correct" : "wrong"}` }, attempt.correct ? "Solved" : "Attempted")
          : null;
        return h("li", {}, h("a", { class: "row", href: `#/puzzle/${r.id}` },
          h("span", { class: "row-title" }, r.title),
          h("span", { class: "row-meta" }, h("span", {}, categoryName(r.category)), difficultyBadge(r.difficulty),
            h("span", {}, formatDate(r.created_at))),
          side));
      }))
    : h("div", { class: "empty" },
        h("p", {}, f.category || f.difficulty
          ? "No puzzles match these filters yet."
          : "No puzzles yet. Generate a batch and the ones that pass every check will appear here."),
        h("a", { class: "button primary", href: "#/generate" }, "Generate puzzles"));

  mount(token, h("section", { class: "sheet" },
    h("h1", {}, "Puzzles"),
    h("p", { class: "lede" }, "Each puzzle here was solved independently by Fable and by a computer program that reached the same answer, and passed a check for ambiguous wording."),
    h("div", { class: "filters" },
      select("Category", f.category, [["", "All categories"], ...CONFIG.categories.map((c) => [c.id, c.name])],
        (v) => { f.category = v; rerender(); }),
      select("Difficulty", f.difficulty, [["", "Any difficulty"], ["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]],
        (v) => { f.difficulty = v; rerender(); })),
    list));
}

async function showPuzzle(token, id) {
  const p = await api(`/problems/${encodeURIComponent(id)}`);
  if (p.status !== "valid") { location.hash = `#/graveyard/${id}`; return; }

  const precise = h("div", { class: "precise", hidden: true, html: renderRich(p.statement.original) });
  const toggle = h("button", {
    class: "linklike small", type: "button", "aria-expanded": "false",
    onclick: () => {
      precise.hidden = !precise.hidden;
      toggle.setAttribute("aria-expanded", String(!precise.hidden));
      toggle.textContent = precise.hidden ? "Show the original, precise wording" : "Hide the original wording";
    },
  }, "Show the original, precise wording");

  const answerSection = h("section", {});
  mount(token, h("article", { class: "sheet" },
    h("a", { class: "back", href: "#/puzzles" }, "All puzzles"),
    h("h1", {}, p.title),
    h("div", { class: "meta-line" }, h("span", {}, categoryName(p.category)), difficultyBadge(p.difficulty)),
    p.illustration_svg ? svgImage(p.illustration_svg, p.title) : null,
    rich("div", "statement", p.statement.final),
    toggle, precise,
    hintLadder(p),
    answerSection));

  const previous = store.get(`attempt:${p.id}`, null);
  if (previous) await showResult(answerSection, p, previous.value, false);
  else renderAnswerForm(answerSection, p);
}

function hintLadder(p) {
  const key = `hints:${p.id}`;
  const section = h("section", {}, h("h2", {}, "Hints"));
  if (!p.hints.length) {
    section.append(h("p", { class: "muted" }, "This puzzle has no hints."));
    return section;
  }
  const ladder = h("ol", { class: "ladder" });
  section.append(ladder);
  const draw = (justRevealed) => {
    const shown = store.get(key, 0);
    ladder.replaceChildren(...p.hints.map((hint, i) => {
      if (i < shown) {
        return h("li", { class: `rung revealed${i === justRevealed ? " just-revealed" : ""}` },
          h("span", { class: "rung-num" }, hint.level), rich("div", "rung-body", hint.text));
      }
      const body = i === shown
        ? h("button", {
            class: "button quiet", type: "button",
            onclick: () => { store.set(key, shown + 1); draw(i); ladder.querySelector("button")?.focus(); },
          }, `Reveal hint ${i + 1} of ${p.hints.length}`)
        : h("span", {}, `Hint ${i + 1}`);
      return h("li", { class: `rung locked` }, h("span", { class: "rung-num" }, hint.level), h("div", { class: "rung-body" }, body));
    }));
  };
  draw(-1);
  return section;
}

function formatHelp(fmt) {
  const help = FORMAT_HELP[fmt.format];
  return typeof help === "function" ? help(fmt.decimal_places ?? 4) : help;
}

function renderAnswerForm(container, p) {
  const input = h("input", { type: "text", id: "answer", inputmode: "decimal", autocomplete: "off", required: true });
  const error = h("p", { class: "form-error", role: "alert" });
  const button = h("button", { class: "button primary", type: "submit" }, "Check answer");
  const form = h("form", {
    class: "answer-form",
    onsubmit: async (e) => {
      e.preventDefault();
      const value = input.value.trim();
      error.textContent = "";
      if (!value) { error.textContent = "Type an answer first."; return; }
      if (!(await confirmDialog(`You're submitting ${value}. Once submitted, the answer and Fable's solution are revealed.`))) return;
      button.disabled = true;
      try {
        await showResult(container, p, value, true);
      } catch (err) {
        error.textContent = err.message;
        button.disabled = false;
      }
    },
  },
  h("label", { class: "field", for: "answer" }, h("span", { class: "sr-only" }, "Your answer"), input),
  button,
  h("p", { class: "hint-text" }, formatHelp(p.answer_format)),
  error);
  container.replaceChildren(h("h2", {}, "Your answer"), form);
}

async function showResult(container, p, value, fresh) {
  const result = await api(`/problems/${encodeURIComponent(p.id)}/answer`, {
    method: "POST", body: JSON.stringify({ value }),
  });
  if (fresh) store.set(`attempt:${p.id}`, { value, correct: result.correct });

  const code = result.code;
  container.replaceChildren(
    h("h2", {}, "Your answer"),
    h("div", { class: `verdict ${result.correct ? "correct" : "wrong"}`, role: "status" },
      h("p", { class: "verdict-title" }, result.correct ? "Correct!" : "Not quite."),
      h("p", {}, "The answer is ", h("span", { class: "key" }, result.answer.display),
        result.answer.expression && result.answer.expression !== result.answer.display
          ? h("span", { class: "muted" }, ` (${result.answer.expression})`) : null),
      h("p", { class: "muted" }, `You answered ${result.submitted}.`)),
    h("h2", {}, "How Fable solved it"),
    rich("div", "solution", result.fable.solution),
    code ? h("details", {},
      h("summary", {}, "The program that checked it"),
      h("p", {}, code.approach),
      h("pre", {}, h("code", {}, code.script)),
      h("p", { class: "muted small" }, "Output"),
      h("pre", {}, h("code", {}, code.stdout || "(no output)"))) : null,
    h("p", {}, h("button", {
      class: "linklike small", type: "button",
      onclick: () => { store.set(`attempt:${p.id}`, null); store.set(`hints:${p.id}`, 0); route(); },
    }, "Reset this puzzle and try again")));
  if (fresh) container.querySelector(".verdict").scrollIntoView({ behavior: "smooth", block: "center" });
}

// ---------- graveyard ----------

async function showGraveyard(token) {
  const f = filters.graveyard;
  const params = new URLSearchParams({ status: "graveyard" });
  if (f.category) params.set("category", f.category);
  if (f.reason) params.set("reason", f.reason);
  const rows = await api(`/problems?${params}`);
  const rerender = () => showGraveyard(routeToken);

  const list = rows.length
    ? h("ul", { class: "rows" }, rows.map((r) => h("li", {}, h("a", { class: "row", href: `#/graveyard/${r.id}` },
        h("span", { class: "row-title" }, r.title),
        h("span", { class: "row-meta" }, h("span", { class: "reason" }, REASONS[r.reason] ?? r.reason),
          h("span", {}, categoryName(r.category)), difficultyBadge(r.difficulty), h("span", {}, formatDate(r.created_at)))))))
    : h("div", { class: "empty" }, h("p", {}, f.category || f.reason
        ? "Nothing buried matches these filters."
        : "Nothing buried yet. Every puzzle so far has passed its checks."));

  mount(token, h("section", { class: "sheet graveyard" },
    h("h1", {}, "Graveyard"),
    h("p", { class: "lede" }, "Puzzles that didn't make it. Each one failed a check: the solvers disagreed, the checking program failed, or the wording allowed a different answer."),
    h("div", { class: "filters" },
      select("Reason", f.reason, [["", "Any reason"], ...CONFIG.reasons.map((r) => [r, REASONS[r] ?? r])],
        (v) => { f.reason = v; rerender(); }),
      select("Category", f.category, [["", "All categories"], ...CONFIG.categories.map((c) => [c.id, c.name])],
        (v) => { f.category = v; rerender(); })),
    list));
}

async function showBuried(token, id) {
  const p = await api(`/problems/${encodeURIComponent(id)}`);
  if (p.status === "valid") { location.hash = `#/puzzle/${id}`; return; }
  const rej = p.rejection;
  const answers = [];
  if (p.proposer?.believed_answer != null) answers.push(["Proposer's answer", p.proposer.believed_answer]);
  if (p.reasoning_verifier) answers.push(["Fable's answer", p.reasoning_verifier.answer_expression || p.reasoning_verifier.answer]);
  if (p.code_verifier) answers.push(["Program's answer", p.code_verifier.answer ?? "no answer"]);

  mount(token, h("article", { class: "sheet graveyard" },
    h("a", { class: "back", href: "#/graveyard" }, "Graveyard"),
    h("h1", {}, p.title),
    h("div", { class: "meta-line" }, h("span", {}, categoryName(p.category)), difficultyBadge(p.difficulty)),
    h("div", { class: "rejection" }, h("div", { class: "reason" }, REASONS[rej.reason] ?? rej.reason), h("p", {}, rej.detail)),
    answers.length ? h("dl", { class: "compare" }, answers.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))) : null,
    p.statement.original ? [h("h2", {}, "The puzzle"), rich("div", "statement", p.statement.original)] : null,
    p.adversarial ? [h("h2", {}, "Ambiguity check"),
      h("p", {}, p.adversarial.blocking ? "Blocking: the reviewer found another reasonable reading." : "Not blocking."),
      rich("div", "solution", p.adversarial.concerns),
      p.adversarial.alternate_interpretation ? rich("div", "solution", `**Alternate reading:** ${p.adversarial.alternate_interpretation}`) : null] : null,
    p.reasoning_verifier ? [h("h2", {}, "Fable's solution"), rich("div", "solution", p.reasoning_verifier.reasoning)] : null,
    p.proposer ? h("details", {}, h("summary", {}, "The proposer's own solution"), rich("div", "solution", p.proposer.reasoning)) : null,
    (p.code_verifier?.attempts ?? []).map((a, i) => h("details", {},
      h("summary", {}, `Program, attempt ${i + 1}: ${a.execution.success ? `answered ${a.execution.answer}` : a.execution.error}`),
      h("p", {}, a.approach),
      h("pre", {}, h("code", {}, a.script)),
      a.execution.stderr ? h("pre", {}, h("code", {}, a.execution.stderr)) : null)),
    h("p", { class: "muted small" }, `Cost to generate and check: $${p.metadata.cost_usd.toFixed(3)}`)));
}

// ---------- generate ----------

async function showGenerate(token) {
  const b = CONFIG.batch;
  const count = h("input", { type: "number", id: "count", min: 1, max: b.max_count, value: b.default_count });
  const concurrency = h("input", { type: "number", id: "concurrency", min: 1, max: 6, value: b.default_concurrency });
  const submit = h("button", { class: "button primary", type: "submit" });
  const error = h("p", { class: "form-error", role: "alert" });
  const label = () => { const n = Number(count.value) || 0; submit.textContent = `Generate ${n} puzzle${n === 1 ? "" : "s"}`; };
  count.addEventListener("input", label);
  label();

  const chips = (legend, name, options) => h("fieldset", { class: "chips" }, h("legend", {}, legend),
    options.map(([value, text]) => h("label", { class: "chip" }, h("input", { type: "checkbox", name, value }), h("span", {}, text))));
  const batchesBox = h("div", { id: "batches" });

  const form = h("form", {
    onsubmit: async (e) => {
      e.preventDefault();
      error.textContent = "";
      const checked = (name) => [...form.querySelectorAll(`input[name=${name}]:checked`)].map((i) => i.value);
      const body = {
        count: Number(count.value),
        concurrency: Number(concurrency.value),
        categories: checked("category").length ? checked("category") : null,
        difficulties: checked("difficulty").length ? checked("difficulty") : null,
      };
      submit.disabled = true;
      try {
        await api("/generate", { method: "POST", body: JSON.stringify(body) });
        await pollBatches(batchesBox, routeToken);
      } catch (err) {
        error.textContent = err.message;
      } finally {
        submit.disabled = false;
      }
    },
  },
  chips("Categories (leave all unselected to mix every category)", "category", CONFIG.categories.map((c) => [c.id, c.name])),
  chips("Difficulty (leave unselected for a mix)", "difficulty", [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]]),
  h("div", { class: "form-row" },
    h("label", { class: "field", for: "count" }, "How many puzzles", count),
    h("label", { class: "field", for: "concurrency" }, "Worked on at once", concurrency),
    submit),
  error);

  mount(token, h("section", { class: "sheet" },
    h("h1", {}, "Generate puzzles"),
    h("p", { class: "lede" }, "Opus proposes each puzzle. Fable solves it, a program Fable writes computes the answer separately, and a reviewer looks for a second reading. Puzzles that pass get a fun rewrite, an illustration and hints; the rest go to the graveyard. Expect 2 to 4 minutes and roughly $0.15 to $1 per puzzle."),
    form,
    h("h2", {}, "Recent batches"),
    batchesBox));
  await pollBatches(batchesBox, token);
}

async function pollBatches(box, token) {
  clearTimeout(pollTimer);
  if (token !== routeToken) return;
  let batches;
  try {
    batches = await api("/batches");
  } catch (err) {
    box.replaceChildren(h("p", { class: "notice" }, `Couldn't load batch progress: ${err.message}`));
    return;
  }
  if (token !== routeToken) return;
  box.replaceChildren(...(batches.length
    ? batches.slice(0, 5).map(renderBatch)
    : [h("p", { class: "muted" }, "No batches started since the server was launched.")]));
  if (batches.some((b) => !b.finished)) {
    pollTimer = setTimeout(() => pollBatches(box, token), 2000);
  } else {
    refreshSpend();
  }
}

function renderBatch(batch) {
  const started = new Date(batch.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const status = batch.finished
    ? `Finished: ${batch.valid} valid, ${batch.graveyard} in the graveyard, $${batch.cost_usd.toFixed(2)}`
    : `Working: ${batch.completed} of ${batch.requested} done`;
  const waiting = Math.max(0, batch.requested - batch.items.length);
  return h("div", { class: "batch" },
    h("div", { class: "batch-head" }, h("span", {}, `Batch started ${started}`), h("span", { class: "muted" }, status)),
    batch.error ? h("p", { class: "notice" }, `The batch stopped: ${batch.error}`) : null,
    batch.items.map(renderJob),
    waiting ? h("div", { class: "job" }, h("span", { class: "job-meta" }, `${waiting} more waiting for a free slot`)) : null);
}

function renderJob(item) {
  const stageIndex = STAGES.indexOf(item.stage);
  const done = item.stage === "done";
  const track = h("span", { class: "track", "aria-label": done ? "Finished" : `Step ${stageIndex + 1} of 3: ${item.stage}` },
    STAGES.map((_, i) => h("i", { class: done || i < stageIndex ? "on" : i === stageIndex ? "now" : "" })));
  let outcome = null;
  if (done && item.status === "valid") {
    outcome = h("a", { class: "outcome-valid", href: `#/puzzle/${item.problem_id}` }, `Valid, open puzzle ($${item.cost_usd.toFixed(2)})`);
  } else if (done) {
    outcome = h("a", { class: "outcome-grave", href: `#/graveyard/${item.problem_id}` }, `${REASONS[item.reason] ?? item.reason} ($${item.cost_usd.toFixed(2)})`);
  }
  const stageText = { proposing: "Proposing a puzzle", verifying: "Verifying: Fable, program and ambiguity check", polishing: "Rewriting, illustrating and writing hints" }[item.stage];
  return h("div", { class: "job" },
    h("span", { class: "job-title" }, item.title ?? "New puzzle"),
    h("span", { class: "job-meta" }, `${categoryName(item.category)}, ${item.difficulty}. `, outcome ?? stageText ?? ""),
    track);
}

// ---------- routing ----------

const ROUTES = [
  [/^#\/puzzles$/, showPuzzles, "puzzle"],
  [/^#\/puzzle\/([\w-]+)$/, showPuzzle, "puzzle"],
  [/^#\/generate$/, showGenerate, "generate"],
  [/^#\/graveyard$/, showGraveyard, "graveyard"],
  [/^#\/graveyard\/([\w-]+)$/, showBuried, "graveyard"],
];

async function route() {
  clearTimeout(pollTimer);
  const hash = location.hash || "#/puzzles";
  const match = ROUTES.map(([re, fn, nav]) => [hash.match(re), fn, nav]).find(([m]) => m);
  if (!match) { location.hash = "#/puzzles"; return; }
  const [m, fn, nav] = match;
  const token = ++routeToken;
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === nav) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  try {
    await fn(token, ...m.slice(1));
    if (token === routeToken) { view.focus({ preventScroll: true }); window.scrollTo(0, 0); }
  } catch (err) {
    mount(token, h("section", { class: "sheet" }, h("h1", {}, "Something went wrong"),
      h("p", { class: "notice" }, err.message), h("a", { class: "button", href: "#/puzzles" }, "Back to puzzles")));
  }
}

async function init() {
  try {
    CONFIG = await api("/config");
  } catch (err) {
    view.replaceChildren(h("p", { class: "notice" }, `The server isn't responding: ${err.message}. Start it with python -m forge.api.`));
    return;
  }
  window.addEventListener("hashchange", route);
  refreshSpend();
  route();
}

init();
