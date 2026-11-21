import { createConversation } from "./conversation.js";
import { getIntake, getPlan } from "./transport.js";

const form = document.querySelector("#query-form");
const input = document.querySelector("#query");
const submit = document.querySelector("#submit");
const intro = document.querySelector("#intro");
const workspace = document.querySelector(".workspace");
const conversation = document.querySelector("#conversation");
const thread = document.querySelector("#thread");
const current = document.querySelector("#current");
const topics = document.querySelector("#topic-list");
const error = document.querySelector("#error");
const reset = document.querySelector("#reset");
const sample = document.querySelector("#sample");
const sampleBanner = document.querySelector("#sample-banner");
const dialog = document.querySelector("#how-dialog");

const TOPICS = {
  supplementary_exam: ["Supplementary exam", "◷"],
  grade_review: ["Grades and answer scripts", "≡"],
  escalation: ["Faculty advisor", "…"],
  attendance_waiver: ["Attendance waiver", "✓"],
};

let engine;
let state;
let turns = [];
let mode = "campus";
let generation = 0;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function button(className, label, action) {
  const element = node("button", className, label);
  element.type = "button";
  element.addEventListener("click", action);
  return element;
}

function displayError(message = "") {
  error.textContent = message;
  error.hidden = !message;
}

function display(active) {
  intro.hidden = active;
  form.hidden = active;
  conversation.hidden = !active;
  reset.hidden = !active;
  workspace.classList.toggle("active", active);
}

function clear(text = "", focus = true) {
  generation += 1;
  state = undefined;
  turns = [];
  thread.replaceChildren();
  current.replaceChildren();
  conversation.removeAttribute("aria-busy");
  display(false);
  displayError();
  input.value = text;
  if (focus) input.focus();
}

function start(query, topic = null) {
  state = engine.start(query, mode, topic);
  turns = [];
  display(true);
  render();
}

function message(role, text, edit) {
  const entry = node("div", `message ${role}`);
  const badge = node("span", "sr-only", role === "user" ? "You" : "Humraah");
  entry.append(badge);
  if (role === "assistant") {
    const mark = node("span", "assistant-mark");
    mark.setAttribute("aria-hidden", "true");
    mark.append(node("i"));
    entry.append(mark);
  }
  const content = node("div");
  content.append(node("p", "bubble", text));
  if (edit) content.append(edit);
  entry.append(content);
  return entry;
}

function focusLatest(element) {
  element.tabIndex = -1;
  element.focus({ preventScroll: true });
  element.scrollIntoView?.({ block: "nearest", behavior: "instant" });
}

function renderThread() {
  const editQuestion = button("quiet", "Edit question", () => clear(state.query));
  const entries = [message("user", state.query, editQuestion)];
  for (const [index, item] of turns.entries()) {
    const edit = button("quiet", "Edit answer", () => {
      state = item.before;
      turns = turns.slice(0, index);
      render();
    });
    edit.setAttribute("aria-label", `Edit answer to: ${item.prompt.text}`);
    entries.push(message("assistant", item.prompt.text), message("user", item.label, edit));
  }
  thread.replaceChildren(...entries);
}

function accept(prompt, value, label) {
  const before = state;
  state = engine.answer(state, prompt, value);
  turns.push({ prompt, label, before });
  render();
}

function renderFollowUp(prompt) {
  const panel = node("section", "follow-up");
  const question = message("assistant", prompt.text);
  const heading = question.querySelector(".bubble");
  heading.id = "follow-up-question";
  heading.setAttribute("role", "heading");
  heading.setAttribute("aria-level", "3");
  panel.append(question);
  if (prompt.dropdown) {
    const selection = node("form", "choices choice-form");
    const select = node("select");
    select.required = true;
    select.setAttribute("aria-labelledby", heading.id);
    select.add(new Option("Select a department", ""));
    for (const [value, label] of prompt.choices) select.add(new Option(label, value));
    selection.append(select, node("button", "primary", "Continue"));
    selection.addEventListener("submit", (event) => {
      event.preventDefault();
      accept(prompt, select.value, select.selectedOptions[0].text);
    });
    panel.append(selection);
  } else {
    const choices = node("div", "choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-labelledby", heading.id);
    for (const [value, label] of prompt.choices) {
      choices.append(button("choice", label, () => accept(prompt, value, label)));
    }
    panel.append(choices);
  }
  current.replaceChildren(panel);
  focusLatest(heading);
}

function link(label, url, className) {
  const anchor = node("a", className, label);
  anchor.href = url;
  if (url.startsWith("https:")) {
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
  }
  return anchor;
}

function renderContacts(contacts) {
  const panel = node("section", "plan-panel");
  panel.append(node("h3", "", "Who to contact"));
  for (const contact of contacts) {
    const item = node("div", "source-item");
    item.append(node("p", "contact-role", contact.role));
    for (const text of [contact.name, contact.office, contact.office_hours].filter(Boolean)) {
      item.append(node("p", "", text));
    }
    if (contact.email && mode === "campus") {
      item.append(link(contact.email, `mailto:${contact.email}`, "contact-source"));
    } else if (contact.email) {
      item.append(node("p", "contact-source", contact.email));
    }
    if (contact.url) item.append(link(contact.detail, contact.url, "contact-source"));
    else if (contact.detail) item.append(node("p", "helper", contact.detail));
    panel.append(item);
  }
  return panel;
}

function renderSources(title, items, expanded) {
  const panel = node("details", "plan-panel");
  panel.open = expanded;
  panel.append(node("summary", "", title));
  for (const source of items) {
    const item = node("div", "source-item");
    item.append(node("p", "", source.text));
    if (source.url) item.append(link(source.label, source.url, "citation"));
    else item.append(node("p", "citation", source.label));
    panel.append(item);
  }
  return panel;
}

function renderPlan(plan) {
  const article = node("article", "plan");
  const summary = node("div", "plan-summary");
  const heading = node("h3", "", plan.supported ? "What to do next" : "Find the right kind of help");
  if (plan.supported) {
    const context = [plan.issue, plan.department].filter(Boolean).join(" · ");
    summary.append(node("p", "plan-context", context));
  }
  summary.append(heading, node("p", "", plan.next_step));
  article.append(summary);
  if (plan.supported) {
    const body = node("div", "plan-body");
    if (plan.contacts.length) body.append(renderContacts(plan.contacts));
    for (const notice of plan.notices) {
      const panel = node("aside", "plan-notice");
      panel.append(node("strong", "", notice.title), node("p", "", notice.text));
      body.append(panel);
    }
    if (plan.rules.length) body.append(renderSources(mode === "sample" ? "Sample policy" : "Official policy", plan.rules, true));
    if (plan.tips.length) body.append(renderSources("Sample senior tips", plan.tips, false));
    article.append(body);
  }
  current.replaceChildren(article);
  focusLatest(heading);
}

async function render() {
  const revision = ++generation;
  renderThread();
  displayError();
  const followUp = engine.question(state);
  if (followUp) {
    conversation.removeAttribute("aria-busy");
    renderFollowUp(followUp);
    return;
  }
  current.replaceChildren(node("p", "helper", "Checking guidance…"));
  conversation.setAttribute("aria-busy", "true");
  try {
    const plan = await getPlan(engine.planInput(state));
    if (revision === generation) renderPlan(plan);
  } catch (failure) {
    if (revision === generation) {
      displayError(failure.message);
      current.replaceChildren(button("outline", "Try again", render));
    }
  } finally {
    if (revision === generation) conversation.removeAttribute("aria-busy");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = input.value.trim();
  if (query.length >= 3 && engine) start(query);
  else displayError("Enter a few words about what happened.");
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && engine) {
    event.preventDefault();
    form.requestSubmit();
  }
});
reset.addEventListener("click", () => clear());
sample.addEventListener("click", () => {
  mode = mode === "campus" ? "sample" : "campus";
  const sampleActive = mode === "sample";
  sample.textContent = sampleActive ? "Return to campus sources" : "Try sample data";
  sample.setAttribute("aria-pressed", String(sampleActive));
  sampleBanner.hidden = !sampleActive;
  clear();
});
document.querySelector("#how-button").addEventListener("click", () => dialog.showModal());

try {
  const intake = await getIntake();
  engine = createConversation(intake);
  for (const scenario of intake.scenarios) {
    const [title, icon] = TOPICS[scenario.tag] ?? [scenario.label, "·"];
    const topic = button("topic", "", () => start(title, scenario.tag));
    const mark = node("span", "topic-mark", icon);
    mark.setAttribute("aria-hidden", "true");
    topic.append(mark, node("span", "topic-name", title));
    topics.append(topic);
  }
  submit.disabled = false;
} catch (failure) {
  displayError(failure.message);
}
