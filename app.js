/* GradeMate front-end. Plain JavaScript, no libraries, no internet needed. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ helpers
  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // tiny, safe markdown: **bold**, *italic*, line breaks
  function formatText(text) {
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[^*\w])\*(?!\s)([^*\n]+?)\*(?!\w)/g, "$1<em>$2</em>");
    return html.replace(/\n/g, "<br>");
  }

  // 3.5 -> "3.5", 8.0 -> "8", 3.6625 -> "3.66"
  const trim = (n) => String(parseFloat(Number(n).toFixed(2)));
  const two = (n) => Number(n).toFixed(2);
  // server steps use plain ASCII; show proper maths symbols
  const pretty = (s) => escapeHtml(s).replace(/ x /g, " × ").replace(/-&gt;/g, "→")
    .replace(/sum\(/g, "Σ(").replace(/ \/ /g, " ÷ ");

  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  // ------------------------------------------------------------------ state
  const DEFAULT_SCALE = { "A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7, "D+": 1.3, "D": 1.0, "F": 0.0 };

  const state = {
    sessionId: uid(),
    busy: false,
    defaultScale: Object.assign({}, DEFAULT_SCALE),
    customScale: null,
  };

  function storageGet(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function storageSet(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* ignore */ } }
  function storageRemove(key) { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } }

  function activeScale() { return state.customScale || state.defaultScale; }
  function scalePayload() { return state.customScale ? state.customScale : undefined; }

  // ------------------------------------------------------------------ server calls
  async function postJson(url, payload) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let data = null;
    try { data = await response.json(); } catch (e) { /* not JSON */ }
    return { ok: response.ok, status: response.status, data };
  }

  const OFFLINE_MESSAGE = "I can't reach the GradeMate server. Make sure \"python app.py\" is still running in your terminal, then try again.";

  // ------------------------------------------------------------------ theme
  const root = document.documentElement;
  const themeButton = $("#theme-toggle");

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    themeButton.setAttribute("aria-label", theme === "dark" ? "Switch to light mode" : "Switch to dark mode");
  }
  applyTheme(root.getAttribute("data-theme") || "dark");
  themeButton.addEventListener("click", () => {
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    storageSet("grademate-theme", next);
  });

  // ------------------------------------------------------------------ views & tabs
  function setView(view) {
    document.body.dataset.view = view;
    $$(".mobile-nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  }
  $$(".mobile-nav button").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  function activateTab(name) {
    $$(".tab").forEach((tab) => {
      const on = tab.dataset.tab === name;
      tab.classList.toggle("active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    $$(".panel").forEach((panel) => {
      const on = panel.id === "panel-" + name;
      panel.classList.toggle("active", on);
      panel.hidden = !on;
    });
  }
  $$(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));

  // ------------------------------------------------------------------ result cards
  function ring(value, max, tone) {
    const circumference = 2 * Math.PI * 40;
    const ratio = Math.max(0, Math.min(1, value / max));
    return `<div class="ring" data-ratio="${ratio}">
      <svg viewBox="0 0 96 96" aria-hidden="true">
        <circle class="track" cx="48" cy="48" r="40"></circle>
        <circle class="bar" cx="48" cy="48" r="40" stroke-dasharray="${circumference}" stroke-dashoffset="${circumference}"></circle>
      </svg><div class="ring-num">${escapeHtml(two(value))}</div></div>`;
  }

  function animateRings(scope) {
    $$(".ring", scope).forEach((el) => {
      const bar = $(".bar", el);
      const circumference = 2 * Math.PI * 40;
      const target = circumference * (1 - parseFloat(el.dataset.ratio));
      if (reduceMotion) { bar.style.strokeDashoffset = target; return; }
      requestAnimationFrame(() => requestAnimationFrame(() => { bar.style.strokeDashoffset = target; }));
    });
  }

  function mathBlock(result, extra) {
    const lines = [];
    if (result.formula) lines.push(pretty(result.formula));
    (extra || []).forEach((l) => lines.push(pretty(l)));
    return `<div class="res-math">${lines.map((l) => `<div>${l}</div>`).join("")}</div>`;
  }

  function gpaCard(r) {
    const rows = r.courses.map((c) => `<tr><td>${escapeHtml(c.name)}</td><td>${trim(c.credits)}</td>
      <td class="grade">${escapeHtml(c.grade)}</td><td>${trim(c.grade_points)}</td><td>${trim(c.quality_points)}</td></tr>`).join("");
    return `<div class="res">
      <div class="res-top">${ring(r.gpa, r.max_gpa)}
        <div><div class="res-label">Semester GPA</div>
          <div class="res-title">${escapeHtml(r.performance)} <span class="res-label">out of ${two(r.max_gpa)}</span></div>
          <div class="res-stats"><div><b>${trim(r.total_credits)}</b><span>credit hours</span></div>
          <div><b>${trim(r.total_quality_points)}</b><span>quality points</span></div></div></div></div>
      <table class="res-table"><thead><tr><th>Course</th><th>Cr</th><th>Grade</th><th>Pts</th><th>QP</th></tr></thead><tbody>${rows}</tbody></table>
      ${mathBlock(r, [r.calculation])}</div>`;
  }

  function cgpaCard(r) {
    const change = r.change;
    const badge = change > 0 ? `<span class="badge up">▲ +${two(change)}</span>`
      : change < 0 ? `<span class="badge down">▼ −${two(Math.abs(change))}</span>`
      : `<span class="badge warn">No change</span>`;
    return `<div class="res">
      <div class="res-top">${ring(r.new_cgpa, r.max_gpa)}
        <div><div class="res-label">Updated CGPA</div>
          <div class="res-title">${badge}</div>
          <div class="res-stats"><div><b>${two(r.previous_cgpa)}</b><span>previous CGPA</span></div>
          <div><b>${trim(r.total_credits)}</b><span>total credits</span></div>
          <div><b>${trim(r.total_quality_points)}</b><span>quality points</span></div></div></div></div>
      ${mathBlock(r, r.steps)}</div>`;
  }

  function targetCard(r) {
    const tone = r.status === "impossible" ? "res-bad" : r.status === "secured" ? "res-ok" : "";
    const badge = r.status === "impossible" ? `<span class="badge bad">Not achievable</span>`
      : r.status === "secured" ? `<span class="badge ok">Already achieved</span>`
      : `<span class="badge ok">Achievable</span>`;
    const facts = [
      ["Current CGPA", two(r.current_cgpa)],
      ["Target CGPA", two(r.target_cgpa)],
      ["Completed credits", trim(r.completed_credits)],
      ["Remaining credits", trim(r.remaining_credits)],
      ["Highest possible CGPA", two(r.max_possible_cgpa)],
    ];
    if (r.minimum_average_grade) facts.push(["Roughly a", r.minimum_average_grade + " average"]);
    const factHtml = facts.map(([k, v]) => `<div>${escapeHtml(k)}<b>${escapeHtml(v)}</b></div>`).join("");
    return `<div class="res ${tone}">
      <div class="res-top">${ring(r.required_gpa, r.max_gpa)}
        <div><div class="res-label">Required average GPA</div>
          <div class="res-title">${badge}</div></div></div>
      <p class="res-note">${escapeHtml(r.message)}</p>
      <div class="facts">${factHtml}</div>
      ${mathBlock(r, r.steps)}</div>`;
  }

  function scaleCard(scale) {
    const chips = Object.keys(scale).map((g) => `<span>${escapeHtml(g)} <b>${trim(scale[g])}</b></span>`).join("");
    return `<div class="res"><div class="scale-chips">${chips}</div></div>`;
  }

  function buildResult(result) {
    if (!result) return null;
    let html = "";
    if (result.type === "gpa") html = gpaCard(result);
    else if (result.type === "cgpa") html = cgpaCard(result);
    else if (result.type === "target") html = targetCard(result);
    else if (result.type === "scale") html = scaleCard(result.scale);
    if (!html) return null;
    const holder = document.createElement("div");
    holder.innerHTML = html;
    const card = holder.firstElementChild;
    return card;
  }

  // ------------------------------------------------------------------ chat
  const messagesEl = $("#messages");
  const inputEl = $("#chat-input");
  const sendBtn = $("#send-btn");

  function scrollDown() {
    messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" });
  }

  const CHIP_MESSAGES = {
    "GPA formula": "What is the GPA formula?",
    "CGPA formula": "What is the CGPA formula?",
    "Required GPA formula": "How is required GPA calculated?",
    "Grade points": "What are grade points?",
    "Credit hours": "What are credit hours?",
    "Grade Scale": "Show the grade scale",
    "Cancel": "cancel",
  };
  const CHIP_FORMS = { "Show GPA form": "gpa", "Show CGPA form": "cgpa", "Show Planner form": "target" };

  function onChipClick(label) {
    if (CHIP_FORMS[label]) { activateTab(CHIP_FORMS[label]); setView("tools"); return; }
    sendMessage(CHIP_MESSAGES[label] || label);
  }

  function addMessage(role, text, options) {
    const opts = options || {};
    $$(".chips", messagesEl).forEach((c) => c.remove());       // only the newest message keeps suggestions

    const wrapper = document.createElement("div");
    wrapper.className = "msg " + role + (opts.error ? " error" : "");
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = role === "bot" ? formatText(text) : escapeHtml(text);
    wrapper.appendChild(bubble);

    const card = buildResult(opts.result);
    if (card) bubble.appendChild(card);

    if (opts.suggestions && opts.suggestions.length) {
      const chips = document.createElement("div");
      chips.className = "chips";
      opts.suggestions.forEach((label) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "chip";
        chip.textContent = label;
        chip.addEventListener("click", () => onChipClick(label));
        chips.appendChild(chip);
      });
      wrapper.appendChild(chips);
    }

    messagesEl.appendChild(wrapper);
    if (card) animateRings(card);
    scrollDown();
    return wrapper;
  }

  let typingEl = null;
  function showTyping() {
    typingEl = document.createElement("div");
    typingEl.className = "msg bot typing";
    typingEl.setAttribute("aria-label", "GradeMate is typing");
    typingEl.innerHTML = '<div class="bubble"><i></i><i></i><i></i></div>';
    messagesEl.appendChild(typingEl);
    scrollDown();
  }
  function hideTyping() { if (typingEl) { typingEl.remove(); typingEl = null; } }

  function setBusy(busy) {
    state.busy = busy;
    sendBtn.disabled = busy;
  }

  async function sendMessage(text) {
    text = String(text || "").trim();
    if (!text || state.busy) return;
    setBusy(true);
    addMessage("user", text);
    inputEl.value = "";
    showTyping();

    const started = performance.now();
    let res = null;
    try {
      res = await postJson("/chat", { message: text, session_id: state.sessionId, grade_scale: scalePayload() });
    } catch (e) { res = null; }
    await sleep(Math.max(0, 450 - (performance.now() - started)));
    hideTyping();

    if (!res || !res.data) {
      addMessage("bot", OFFLINE_MESSAGE, { error: true });
    } else if (!res.ok || res.data.ok === false) {
      addMessage("bot", res.data.error || "Something went wrong. Please try again.", { error: true });
    } else {
      addMessage("bot", res.data.reply, { result: res.data.result, suggestions: res.data.suggestions });
      if (res.data.ui_tab) activateTab(res.data.ui_tab);
    }
    setBusy(false);
    if (window.matchMedia("(min-width: 901px)").matches) inputEl.focus();
  }

  $("#chat-form").addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(inputEl.value);
  });

  // ------------------------------------------------------------------ quick actions
  $$("#quick-actions .chip").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      if (action === "reset") return resetAll();
      if (action === "gpa") { activateTab("gpa"); sendMessage("Calculate GPA"); }
      else if (action === "cgpa") { activateTab("cgpa"); sendMessage("Calculate CGPA"); }
      else if (action === "target") { activateTab("target"); sendMessage("Target planner"); }
      else if (action === "scale") { activateTab("scale"); sendMessage("Show the grade scale"); }
      else if (action === "help") sendMessage("Help");
    });
  });

  // ------------------------------------------------------------------ GPA form
  const rowsEl = $("#course-rows");
  const gpaError = $("#gpa-error");
  const gpaResult = $("#gpa-result");
  const gpaLive = $("#gpa-live");

  function gradeOptions(selected) {
    const keys = Object.keys(activeScale());
    return '<option value="">Grade</option>' + keys.map((g) =>
      `<option value="${escapeHtml(g)}"${g === selected ? " selected" : ""}>${escapeHtml(g)}</option>`).join("");
  }

  function addCourseRow(values) {
    const v = values || {};
    const row = document.createElement("div");
    row.className = "course-row";
    row.innerHTML = `
      <input class="c-name" type="text" maxlength="40" placeholder="e.g. Programming" aria-label="Course name" value="${escapeHtml(v.name || "")}">
      <input class="c-credits" type="number" min="0" max="30" step="any" inputmode="decimal" placeholder="3" aria-label="Credit hours" value="${v.credits != null ? escapeHtml(v.credits) : ""}">
      <select class="c-grade" aria-label="Grade">${gradeOptions(v.grade)}</select>
      <button type="button" class="row-remove" aria-label="Remove this course" title="Remove">×</button>`;
    row.addEventListener("input", updateLiveTotal);
    row.addEventListener("change", updateLiveTotal);
    $(".row-remove", row).addEventListener("click", () => {
      row.remove();
      if (!$$(".course-row", rowsEl).length) addCourseRow();
      updateLiveTotal();
    });
    rowsEl.appendChild(row);
    return row;
  }

  function resetCourseRows(count) {
    rowsEl.innerHTML = "";
    for (let i = 0; i < count; i++) addCourseRow();
    updateLiveTotal();
  }

  function updateLiveTotal() {
    let total = 0, courses = 0;
    $$(".course-row", rowsEl).forEach((row) => {
      const credits = parseFloat($(".c-credits", row).value);
      if (credits > 0 && $(".c-grade", row).value) { total += credits; courses += 1; }
    });
    gpaLive.textContent = `Total credit hours: ${trim(total)} · Courses ready: ${courses}`;
  }

  function clearInvalid(scope) {
    $$("[aria-invalid]", scope).forEach((el) => el.removeAttribute("aria-invalid"));
  }

  function collectCourses() {
    clearInvalid(rowsEl);
    const courses = [];
    let problem = "";
    $$(".course-row", rowsEl).forEach((row, index) => {
      const nameEl = $(".c-name", row), creditsEl = $(".c-credits", row), gradeEl = $(".c-grade", row);
      const name = nameEl.value.trim(), credits = creditsEl.value.trim(), grade = gradeEl.value;
      if (!name && !credits && !grade) return;                       // ignore empty rows
      const label = name ? `"${name}"` : `row ${index + 1}`;
      const number = parseFloat(credits);
      if (!credits || isNaN(number) || number <= 0) {
        creditsEl.setAttribute("aria-invalid", "true");
        problem = problem || `Enter credit hours greater than 0 for ${label}.`;
      } else if (number > 30) {
        creditsEl.setAttribute("aria-invalid", "true");
        problem = problem || `Credit hours for ${label} look too large (maximum 30).`;
      }
      if (!grade) {
        gradeEl.setAttribute("aria-invalid", "true");
        problem = problem || `Choose a grade for ${label}.`;
      }
      courses.push({ name, credits: number, grade });
    });
    if (!problem && !courses.length) problem = "Add at least one course with credit hours and a grade.";
    return { courses, problem };
  }

  function showCard(slot, result) {
    slot.innerHTML = "";
    const card = buildResult(result);
    if (card) { slot.appendChild(card); animateRings(card); }
  }

  async function calculateGpa() {
    gpaError.textContent = "";
    gpaResult.innerHTML = "";
    const { courses, problem } = collectCourses();
    if (problem) { gpaError.textContent = problem; return; }
    await runCalculation({ type: "gpa", courses, grade_scale: scalePayload() }, gpaError, gpaResult, null, "Semester GPA calculated.");
  }

  async function runCalculation(payload, errorEl, resultEl, formScope, chatIntro) {
    errorEl.textContent = "";
    let res;
    try { res = await postJson("/calculate", payload); } catch (e) { res = null; }
    if (!res || !res.data) { errorEl.textContent = OFFLINE_MESSAGE; return; }
    if (!res.ok || res.data.ok === false) {
      const message = res.data.error || "That calculation could not be completed.";
      const fieldEl = formScope && res.data.field ? $(`.field-error[data-for="${res.data.field}"]`, formScope) : null;
      if (fieldEl) {
        fieldEl.textContent = message;
        const input = $(`[name="${res.data.field}"]`, formScope);
        if (input) { input.setAttribute("aria-invalid", "true"); input.focus(); }
      } else {
        errorEl.textContent = message;
      }
      return;
    }
    showCard(resultEl, res.data);
    addMessage("bot", chatIntro + " " + res.data.message, { result: res.data });   // keep a record in the chat
  }

  $("#add-course").addEventListener("click", () => {
    const row = addCourseRow();
    $(".c-name", row).focus();
  });
  $("#calc-gpa").addEventListener("click", calculateGpa);
  $("#clear-gpa").addEventListener("click", () => {
    resetCourseRows(3);
    gpaError.textContent = "";
    gpaResult.innerHTML = "";
  });
  $("#load-example").addEventListener("click", () => {
    const keys = Object.keys(activeScale());
    const pick = (g, fallback) => (keys.includes(g) ? g : fallback);
    rowsEl.innerHTML = "";
    addCourseRow({ name: "Programming", credits: 3, grade: pick("A", "") });
    addCourseRow({ name: "Database", credits: 3, grade: pick("B+", "") });
    addCourseRow({ name: "English", credits: 2, grade: pick("A-", "") });
    updateLiveTotal();
    gpaError.textContent = "";
  });

  // ------------------------------------------------------------------ CGPA and planner forms
  const FIELD_RULES = {
    current_cgpa: { label: "Current CGPA", kind: "gpa" },
    completed_credits: { label: "Completed credit hours", kind: "credits", allowZero: true },
    semester_gpa: { label: "New semester GPA", kind: "gpa" },
    semester_credits: { label: "New semester credit hours", kind: "credits" },
    target_cgpa: { label: "Target CGPA", kind: "gpa" },
    remaining_credits: { label: "Remaining credit hours", kind: "credits" },
  };

  function validateField(name, raw) {
    const rule = FIELD_RULES[name];
    if (raw === "" || raw === null) return `${rule.label} is required.`;
    const value = Number(raw);
    if (!isFinite(value)) return `${rule.label} must be a number.`;
    if (rule.kind === "gpa") {
      if (value < 0) return `${rule.label} cannot be below 0.00.`;
      if (value > 4) return `${rule.label} cannot be above 4.00.`;
    } else {
      if (value < 0 || (value === 0 && !rule.allowZero)) {
        return name === "remaining_credits"
          ? "Remaining credit hours must be greater than 0."
          : `${rule.label} must be greater than 0.`;
      }
      if (value > 500) return `${rule.label} looks too large (maximum 500).`;
    }
    return "";
  }

  function wireForm(type, formId, errorId, resultId, intro) {
    const form = $(formId), errorEl = $(errorId), resultEl = $(resultId);

    function clearAll() {
      form.reset();
      clearInvalid(form);
      $$(".field-error", form).forEach((el) => { el.textContent = ""; });
      errorEl.textContent = "";
      resultEl.innerHTML = "";
    }
    form._clear = clearAll;

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearInvalid(form);
      errorEl.textContent = "";
      resultEl.innerHTML = "";
      const payload = { type };
      let firstBad = null;
      $$("input", form).forEach((input) => {
        const message = validateField(input.name, input.value.trim());
        $(`.field-error[data-for="${input.name}"]`, form).textContent = message;
        if (message) { input.setAttribute("aria-invalid", "true"); firstBad = firstBad || input; }
        payload[input.name] = input.value.trim() === "" ? null : Number(input.value);
      });
      if (firstBad) { firstBad.focus(); return; }
      if (type === "target") payload.grade_scale = scalePayload();
      await runCalculation(payload, errorEl, resultEl, form, intro);
    });

    // live: clear the message once the user edits the field
    form.addEventListener("input", (event) => {
      const target = event.target;
      if (target && target.name) {
        target.removeAttribute("aria-invalid");
        $(`.field-error[data-for="${target.name}"]`, form).textContent = "";
      }
    });
  }

  wireForm("cgpa", "#form-cgpa", "#cgpa-error", "#cgpa-result", "CGPA updated.");
  wireForm("target", "#form-target", "#target-error", "#target-result", "Target planned.");
  $$("[data-clear]").forEach((button) => {
    button.addEventListener("click", () => $(`#form-${button.dataset.clear}`)._clear());
  });

  // ------------------------------------------------------------------ grade scale editor
  const scaleGrid = $("#scale-grid");
  const scaleStatus = $("#scale-status");
  const scaleError = $("#scale-error");

  function renderScaleEditor() {
    const scale = activeScale();
    scaleGrid.innerHTML = Object.keys(scale).map((grade) => `
      <label class="scale-item">${escapeHtml(grade)}
        <input type="number" step="0.1" min="0" max="4" inputmode="decimal" data-grade="${escapeHtml(grade)}" value="${escapeHtml(scale[grade])}">
      </label>`).join("");
    scaleStatus.textContent = state.customScale ? "Using your custom scale." : "Using the default scale.";
  }

  function refreshGradeSelects() {
    $$(".c-grade").forEach((select) => {
      const current = select.value;
      select.innerHTML = gradeOptions(current);
    });
    updateLiveTotal();
  }

  $("#save-scale").addEventListener("click", () => {
    scaleError.textContent = "";
    const next = {};
    let problem = "";
    $$("#scale-grid input").forEach((input) => {
      const value = Number(input.value);
      input.removeAttribute("aria-invalid");
      if (input.value.trim() === "" || !isFinite(value) || value < 0 || value > 4) {
        input.setAttribute("aria-invalid", "true");
        problem = problem || `Grade points for ${input.dataset.grade} must be between 0 and 4.`;
      }
      next[input.dataset.grade] = value;
    });
    if (problem) { scaleError.textContent = problem; return; }
    const sameAsDefault = Object.keys(next).every((g) => next[g] === state.defaultScale[g]);
    state.customScale = sameAsDefault ? null : next;
    if (state.customScale) storageSet("grademate-scale", JSON.stringify(next)); else storageRemove("grademate-scale");
    renderScaleEditor();
    refreshGradeSelects();
    scaleStatus.textContent = state.customScale ? "Saved. Your custom scale is now used." : "Saved. This matches the default scale.";
  });

  $("#restore-scale").addEventListener("click", () => {
    state.customScale = null;
    storageRemove("grademate-scale");
    scaleError.textContent = "";
    renderScaleEditor();
    refreshGradeSelects();
    scaleStatus.textContent = "Default scale restored.";
  });

  function loadSavedScale() {
    const raw = storageGet("grademate-scale");
    if (!raw) return;
    try {
      const saved = JSON.parse(raw);
      const keys = Object.keys(state.defaultScale);
      const valid = saved && keys.every((g) => typeof saved[g] === "number" && saved[g] >= 0 && saved[g] <= 4);
      if (valid) state.customScale = saved; else storageRemove("grademate-scale");
    } catch (e) { storageRemove("grademate-scale"); }
  }

  // ------------------------------------------------------------------ reset
  function showWelcome() {
    addMessage("bot",
      "Hi! I'm **GradeMate**. I calculate semester GPA, update your CGPA and work out the GPA you need to reach a target. " +
      "Everything runs on your computer, with no internet or API key.\n\nTry typing: *Programming 3 A, Database 3 B+, English 2 A-*",
      { suggestions: ["Calculate GPA", "Calculate CGPA", "Target Planner", "Help"] });
  }

  async function resetAll() {
    // 1. chat history
    hideTyping();
    messagesEl.innerHTML = "";
    inputEl.value = "";
    // 2. calculator forms, course rows and temporary results
    resetCourseRows(3);
    gpaError.textContent = "";
    gpaResult.innerHTML = "";
    $("#form-cgpa")._clear();
    $("#form-target")._clear();
    // 3. conversation memory on the server (the trained model is never touched)
    state.sessionId = uid();
    try { await postJson("/chat", { reset: true, session_id: state.sessionId }); } catch (e) { /* offline is fine */ }
    activateTab("gpa");
    showWelcome();
    inputEl.focus();
  }

  // ------------------------------------------------------------------ start-up
  async function init() {
    loadSavedScale();
    try {
      const response = await fetch("/grade-scale");
      if (response.ok) {
        const data = await response.json();
        if (data && data.scale) state.defaultScale = data.scale;
        // a saved custom scale must use the same grades as the server's scale
        if (state.customScale && Object.keys(state.customScale).join() !== Object.keys(state.defaultScale).join()) {
          state.customScale = null;
          storageRemove("grademate-scale");
        }
      }
    } catch (e) { /* keep built-in defaults */ }

    renderScaleEditor();
    resetCourseRows(3);
    showWelcome();
  }
  init();
})();
