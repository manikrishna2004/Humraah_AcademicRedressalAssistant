import { request } from "./transport.js";

const queryForm = document.querySelector("#query-form");
const query = document.querySelector("#query");
const modePicker = document.querySelector("#mode-picker");
const modeNote = document.querySelector("#mode-note");
const status = document.querySelector("#status");
const guidance = document.querySelector("#guidance");
const questionTitle = document.querySelector("#question-title");
const reset = document.querySelector("#reset");
const topics = document.querySelector("#topic-list");
const dialog = document.querySelector("#how-dialog");

const modeNotes = {
  campus: "Pilot coverage varies by issue and admission batch.",
  sample: "Fictional policy, senior accounts and contacts for trying the workflow.",
};
const topicIcons = {
  supplementary_exam: "↻",
  grade_review: "≡",
  escalation: "…",
  attendance_waiver: "✓",
};
let session = null;
let busy = false;

function element(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content) node.textContent = content;
  return node;
}

function showStatus(message = "", isError = false) {
  status.hidden = !message;
  status.textContent = message;
  status.classList.toggle("error", isError);
}

async function api(path, body) {
  const response = await request(path, body ? {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  } : undefined);
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : "Check the details and try again.";
    throw new Error(message);
  }
  return data;
}

function renderTopics(scenarios) {
  for (const scenario of scenarios) {
    const button = element("button", "topic");
    button.type = "button";
    const icon = element("span", "topic-icon", topicIcons[scenario.tag]);
    icon.setAttribute("aria-hidden", "true");
    button.append(icon, document.createTextNode(scenario.label));
    button.addEventListener("click", () => {
      if (busy) return;
      clearGuidance();
      query.value = scenario.query;
      query.focus();
    });
    topics.append(button);
  }
}

function clearGuidance() {
  if (session) {
    request(`/api/guidance/${session}`, { method: "DELETE" }).catch(() => {});
    session = null;
  }
  guidance.replaceChildren();
  modePicker.disabled = false;
  questionTitle.textContent = "What happened?";
  reset.hidden = true;
  queryForm.hidden = false;
  showStatus();
}

function showFollowUp(response) {
  session = response.session;
  const card = element("section", "guide");
  const heading = element("h3", "", response.question);
  heading.tabIndex = -1;
  card.append(element("p", "context", "A quick follow-up"), heading);
  const submitAnswer = (answer) => submitGuidance(
    `/api/guidance/${response.session}/answer`,
    { answer, turn: response.turn },
  );

  if (response.fields.length) {
    const form = element("form", "clarification");
    const selectGrid = element("div", "select-grid");
    for (const field of response.fields) {
      const label = element("label", "", field.label);
      const select = element("select");
      select.name = field.key;
      select.required = true;
      select.add(new Option("Select an option", ""));
      for (const option of field.options) select.add(new Option(option, option));
      label.append(select);
      selectGrid.append(label);
    }
    const button = element("button", "primary", "Continue");
    form.append(selectGrid, button);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitAnswer(Object.fromEntries(new FormData(form)));
    });
    card.append(form);
  } else {
    const choices = element("div", "choices");
    for (const option of response.choices) {
      const button = element("button", "choice", option.label);
      button.addEventListener("click", () => submitAnswer(option.value));
      choices.append(button);
    }
    card.append(choices);
  }
  guidance.replaceChildren(card);
  heading.focus();
}

function citation(label, url) {
  const node = element(url ? "a" : "span", "citation", label);
  if (url) {
    node.href = url;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
  }
  return node;
}

function sourceCard(title, items, empty, contacts = false) {
  const card = element("section", "source-card");
  card.append(element("h3", "", title));
  if (!items.length) card.append(element("p", "", empty));
  for (const item of items) {
    const row = element("div", "source-item");
    if (contacts) {
      row.append(element("strong", "", item.role));
      if (item.name) row.append(element("p", "", item.name));
      if (item.office) row.append(element("p", "", item.office));
      if (item.office_hours) row.append(element("p", "", item.office_hours));
      if (item.email) row.append(element("p", "citation", item.email));
      row.append(item.url ? citation(item.detail, item.url) : element("p", "context", item.detail));
    } else {
      row.append(element("p", "", item.text), citation(item.label, item.url));
    }
    card.append(row);
  }
  return card;
}

function showPlan(response) {
  session = null;
  const sample = modePicker.querySelector("input:checked").value === "sample";
  const result = element("section", "guide result");
  const context = [response.issue, response.department].filter(Boolean).join(" · ");
  const heading = element("h3", "", response.supported ? "What to do next" : response.issue);
  heading.tabIndex = -1;
  const next = element("div", "next-step");
  if (response.supported) next.append(element("p", "context", context));
  next.append(heading, element("p", "", response.next_step));
  result.append(next);
  for (const notice of response.notices) {
    const block = element("div", "notice");
    block.append(element("strong", "", notice.title), element("p", "", notice.text));
    result.append(block);
  }
  if (response.supported) {
    const cards = element("div", "sources");
    cards.append(
      sourceCard(sample ? "Sample rulebook" : "Official policy", response.rules, "No matching policy document in this mode."),
      sourceCard("Senior tips", response.tips, sample ? "No sample account matches these details." : "No verified senior account is available for this issue."),
      sourceCard("Who to contact", response.contacts, "Use the institute directory to confirm who handles this issue.", true),
    );
    result.append(cards);
  }
  guidance.replaceChildren(result);
  heading.focus();
}

async function submitGuidance(path, body) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("#submit, .choice, .clarification button, #topic-list button")];
  for (const control of controls) control.disabled = true;
  modePicker.disabled = true;
  reset.disabled = true;
  showStatus("Looking up guidance…");
  try {
    const response = await api(path, body);
    queryForm.hidden = true;
    questionTitle.textContent = "Your guidance";
    reset.hidden = false;
    showStatus();
    if (response.kind === "clarification") showFollowUp(response);
    else showPlan(response);
  } catch (error) {
    showStatus(error instanceof SyntaxError ? "Humraah is temporarily unavailable. Please try again." : error.message, true);
    if (!session) modePicker.disabled = false;
  } finally {
    busy = false;
    reset.disabled = false;
    for (const control of controls) control.disabled = false;
  }
}

queryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = query.value.trim();
  if (text.length < 3) {
    showStatus("Describe your issue in a few words.", true);
    query.focus();
    return;
  }
  const mode = modePicker.querySelector("input:checked").value;
  submitGuidance("/api/guidance", { query: text, mode });
});
reset.addEventListener("click", () => {
  clearGuidance();
  query.value = "";
  query.focus();
});
modePicker.addEventListener("change", (event) => {
  modeNote.textContent = modeNotes[event.target.value];
});
document.querySelector("#how-button").addEventListener("click", () => dialog.showModal());

try {
  const { scenarios } = await api("/api/options");
  renderTopics(scenarios);
} catch {
  topics.append(element("p", "helper", "Guided topics are temporarily unavailable. You can still type your issue."));
}
