import { createConversation } from "./conversation.js";
import { respond, suggestions } from "./companion.js";
import { getDirectory, getIntake, getPlan } from "./transport.js";

const form = document.querySelector("#query-form");
const input = document.querySelector("#query");
const submit = document.querySelector("#submit");
const intro = document.querySelector("#intro");
const workspace = document.querySelector(".workspace");
const conversation = document.querySelector("#conversation");
const thread = document.querySelector("#thread");
const current = document.querySelector("#current");
const topics = document.querySelector("#topic-list");
const followThrough = document.querySelector("#follow-through");
const replyForm = document.querySelector("#reply-form");
const replyLabel = document.querySelector("#reply-label");
const replyInput = document.querySelector("#reply");
const replySubmit = document.querySelector("#reply-submit");
const replySuggestions = document.querySelector("#reply-suggestions");
const error = document.querySelector("#error");
const reset = document.querySelector("#reset");
const guide = document.querySelector("#guide");
const guideNav = document.querySelector("#guide-nav");
const directoryNav = document.querySelector("#directory-nav");
const directory = document.querySelector("#directory");
const directoryForm = document.querySelector("#directory-form");
const directoryQuery = document.querySelector("#directory-query");
const directoryStatus = document.querySelector("#directory-status");
const directoryResults = document.querySelector("#directory-results");
const dialog = document.querySelector("#how-dialog");

const TOPICS = {
  supplementary_exam: ["Supplementary exam", "◷"],
  grade_review: ["Grades and answer scripts", "≡"],
  escalation: ["Faculty advisor", "…"],
  attendance_waiver: ["Attendance waiver", "✓"],
};

let engine;
let state;
let originalQuery;
let activePrompt;
let latestPlan;
let turns = [];
let directoryRevision = 0;
let directoryDebounce;
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
  latestPlan = undefined;
  activePrompt = undefined;
  replyInput.value = "";
  showReply(false);
  followThrough.replaceChildren();
  thread.replaceChildren();
  current.replaceChildren();
  conversation.removeAttribute("aria-busy");
  display(false);
  displayError();
  input.value = text;
  if (focus) input.focus();
}

function start(query, topic = null) {
  state = engine.start(query, topic);
  originalQuery = query;
  turns = [];
  followThrough.replaceChildren();
  replyInput.value = "";
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
  const editQuestion = button("quiet", "Edit question", () => clear(originalQuery));
  const entries = [message("user", originalQuery, editQuestion)];
  for (const [index, item] of turns.entries()) {
    const edit = button("quiet", "Edit answer", () => {
      state = item.before;
      turns = turns.slice(0, index);
      followThrough.replaceChildren();
      replyInput.value = "";
      render();
    });
    edit.setAttribute("aria-label", `Edit answer to: ${item.prompt.text}`);
    entries.push(message("assistant", item.prompt.text), message("user", item.label, edit));
  }
  thread.replaceChildren(...entries);
}

function accept(prompt, label, resolved) {
  const before = state;
  state = resolved;
  turns.push({ prompt, label, before });
  followThrough.replaceChildren();
  replyInput.value = "";
  render();
}

function renderFollowUp(prompt) {
  const panel = node("section", "follow-up");
  const question = message("assistant", "");
  const bubble = question.querySelector(".bubble");
  if (prompt.lead) bubble.append(node("span", "prompt-lead", prompt.lead));
  const heading = node("span", "prompt-question", prompt.text);
  bubble.append(heading);
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
      accept(prompt, select.selectedOptions[0].text, engine.answer(state, prompt, select.value));
    });
    panel.append(selection);
  } else {
    const choices = node("div", "choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-labelledby", heading.id);
    for (const [value, label] of prompt.choices) {
      choices.append(button("choice", label, () => accept(prompt, label, engine.answer(state, prompt, value))));
    }
    panel.append(choices);
  }
  current.replaceChildren(panel);
  showReply(true, prompt);
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

function renderContact(contact, standalone = false) {
  const item = node("article", standalone ? "directory-card" : "contact-card");
  item.append(node(standalone ? "h2" : "h4", "contact-role", contact.role));
  item.append(node("p", "contact-detail", contact.detail));
  if (contact.office) item.append(node("p", "contact-where", contact.office));
  if (contact.office || contact.office_hours) {
    item.append(node("p", "contact-when", contact.office_hours || "Visiting hours to confirm"));
  }
  if (contact.visit_note) item.append(node("p", "visit-note", contact.visit_note));

  const channels = node("div", "contact-channels");
  if (contact.phone) {
    channels.append(link(contact.phone, `tel:${contact.phone.replace(/[^+0-9]/g, "")}`, "contact-source"));
  }
  if (contact.email) channels.append(link(contact.email, `mailto:${contact.email}`, "contact-source"));
  if (channels.childElementCount) item.append(channels);
  const sources = node("div", "contact-references");
  sources.append(link(contact.source_label, contact.url, "contact-source"));
  if (contact.location_url) sources.append(link("Location reference", contact.location_url, "contact-source"));
  item.append(sources);
  return item;
}

function renderContacts(contacts) {
  const panel = node("section", "plan-panel plan-contacts");
  panel.append(node("h3", "", "Who to contact"));
  panel.append(...contacts.map((contact) => renderContact(contact)));
  return panel;
}

async function searchDirectory() {
  const revision = ++directoryRevision;
  directoryStatus.textContent = "Loading campus contacts…";
  directoryResults.replaceChildren();
  try {
    const contacts = await getDirectory(directoryQuery.value);
    if (revision !== directoryRevision) return;
    directoryStatus.textContent = contacts.length
      ? `${contacts.length} ${contacts.length === 1 ? "contact" : "contacts"}`
      : "No matching contacts. Try an office name or department abbreviation.";
    directoryResults.append(...contacts.map((contact) => renderContact(contact, true)));
  } catch (failure) {
    if (revision === directoryRevision) directoryStatus.textContent = failure.message;
  }
}

function showDirectory(open) {
  guide.hidden = open;
  directory.hidden = !open;
  (open ? guideNav : directoryNav).removeAttribute("aria-current");
  (open ? directoryNav : guideNav).setAttribute("aria-current", "page");
  if (open) {
    focusLatest(directory.querySelector("h1"));
    searchDirectory();
  }
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
  latestPlan = plan;
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
    if (plan.rules.length) body.append(renderSources("Official policy", plan.rules, false));
    if (plan.tips.length) body.append(renderSources("Senior fundae · Fictional examples", plan.tips, false));
    article.append(body);
  }
  current.replaceChildren(article);
  showReply(true);
  focusLatest(heading);
}

async function render() {
  const revision = ++generation;
  latestPlan = undefined;
  showReply(false);
  renderThread();
  displayError();
  const followUp = engine.question(state);
  activePrompt = followUp;
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

function showReply(visible, prompt = null) {
  replyForm.hidden = !visible;
  replySubmit.disabled = !visible;
  if (!visible) {
    replySuggestions.replaceChildren();
    return;
  }
  replyLabel.textContent = prompt ? "Your reply" : "Ask a follow-up";
  replyInput.placeholder = prompt ? "Reply in your own words…" : "What would you like to ask next?";
  replySuggestions.replaceChildren(...(latestPlan ? suggestions(state, latestPlan) : []).map(
    (label) => button("choice", label, () => handleReply(label))
  ));
}

function showExchange(text, response) {
  followThrough.append(message("user", text));
  const answer = message("assistant", response.text);
  const content = answer.lastElementChild;
  if (response.draft) {
    const draft = node("div", "email-draft");
    const status = node("span", "helper");
    status.setAttribute("role", "status");
    const copy = button("outline", "Copy draft", async () => {
      try {
        await navigator.clipboard.writeText(response.draft);
        status.textContent = "Copied.";
      } catch {
        status.textContent = "Select the draft text to copy it.";
      }
    });
    draft.append(node("p", "draft-copy", response.draft), copy, status);
    content.append(draft);
  }
  if (response.links?.length) {
    const links = node("div", "companion-links");
    for (const source of response.links) links.append(link(source.label, source.url));
    content.append(links);
  }
  followThrough.append(answer);
  focusLatest(answer.querySelector(".bubble"));
}

function handleReply(text) {
  if (!text || !state) return;
  if (activePrompt) {
    const updated = engine.interpretReply(state, activePrompt, text);
    if (updated) {
      accept(activePrompt, text, updated);
    } else {
      const remembered = engine.remember(state, text);
      const newDepartment = remembered.department !== state.department ? remembered.department : null;
      state = remembered;
      replyInput.value = "";
      showExchange(text, {
        text: newDepartment
          ? `I’ll keep ${newDepartment} in mind. What are you dealing with?`
          : "I’m still missing that detail. Could you reply in a few words or pick one of the options above?",
      });
    }
    return;
  }
  if (!latestPlan) return;
  replyInput.value = "";
  const updated = engine.reframe(state, text);
  if (updated) {
    state = updated;
    showExchange(text, { text: "That changes the next step. I’ll update the guidance." });
    render();
    return;
  }
  showExchange(text, respond(text, state, latestPlan));
}

replyForm.addEventListener("submit", (event) => {
  event.preventDefault();
  handleReply(replyInput.value.trim());
});
replyInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    replyForm.requestSubmit();
  }
});

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
guideNav.addEventListener("click", () => showDirectory(false));
directoryNav.addEventListener("click", () => showDirectory(true));
directoryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(directoryDebounce);
  searchDirectory();
});
directoryQuery.addEventListener("input", () => {
  clearTimeout(directoryDebounce);
  directoryDebounce = setTimeout(searchDirectory, 180);
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
