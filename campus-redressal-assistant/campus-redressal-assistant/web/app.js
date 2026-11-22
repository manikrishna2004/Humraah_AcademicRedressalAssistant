import { closeChat, getDirectory, getIntake, sendTurn } from "./transport.js";

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
  supplementary_exam: ["Supplementary exams", "clock", "Registration, deadlines and ERP"],
  grade_review: ["Grades and answer scripts", "pages", "Script viewing and grade appeals"],
  escalation: ["Faculty advisor follow-up", "chat", "What to do when you’re waiting"],
  attendance_waiver: ["Attendance waiver", "check", "Absences, records and paperwork"],
};

let ready = false;
let session;
let revision = 0;
let activePrompt;
let quickReplies = [];
let editing;
let busy = false;
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
  if (session) closeChat(session);
  session = undefined;
  revision = 0;
  turns = [];
  quickReplies = [];
  activePrompt = undefined;
  editing = undefined;
  busy = false;
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
  clear("", false);
  display(true);
  thread.append(message("user", query, button("quiet", "Edit question", () => clear(query))));
  current.append(node("p", "loading-message", "Checking campus guidance…"));
  runTurn({ text: query, topic });
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
  const first = turns[0];
  const entries = [message("user", first.text, button("quiet", "Edit question", () => clear(first.text)))];
  for (const item of turns.slice(1)) {
    if (item.prompt && item.resolved) {
      const edit = button("quiet", "Edit answer", () => {
        editing = item;
        replyInput.value = item.text;
        showReply(true, item.prompt);
        replyInput.focus();
      });
      edit.setAttribute("aria-label", `Edit answer to: ${item.prompt.text}`);
      entries.push(message("assistant", item.prompt.text), message("user", item.text, edit));
    }
  }
  thread.replaceChildren(...entries);
  followThrough.replaceChildren();
  for (const item of turns) {
    if (item.response) showExchange(item.position === 0 || item.resolved ? null : item.text, item.response);
    else if (item.position && !item.resolved) followThrough.append(message("user", item.text));
  }
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
      handleReply(select.selectedOptions[0].text, select.value);
    });
    panel.append(selection);
  } else {
    const choices = node("div", "choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-labelledby", heading.id);
    for (const [value, label] of prompt.choices) {
      choices.append(button("choice", label, () => handleReply(label, value)));
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

function renderSources(title, items, examples = false) {
  const panel = node("details", `plan-panel source-panel${examples ? " tips-panel" : ""}`);
  const heading = node("summary", "", title);
  if (examples) heading.append(node("span", "source-badge", "Prototype examples"));
  panel.append(heading);
  for (const source of items) {
    const item = node("div", "source-item");
    if (source.title) item.append(node("h4", "tip-title", source.title));
    item.append(node("p", "", source.text));
    if (!examples) {
      if (source.url) item.append(link(source.label, source.url, "citation"));
      else item.append(node("p", "citation", source.label));
    }
    if (source.verified_at) item.append(node("p", "source-reviewed", `Source checked ${source.verified_at}`));
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
    for (const notice of plan.notices) {
      const panel = node("aside", "plan-notice");
      panel.append(node("strong", "", notice.title), node("p", "", notice.text));
      if (notice.links?.length) {
        const references = node("div", "companion-links");
        for (const source of notice.links) references.append(link(source.label, source.url, "citation"));
        panel.append(references);
      }
      body.append(panel);
    }
    if (plan.contacts.length) body.append(renderContacts(plan.contacts));
    if (plan.related) {
      const related = node("section", "plan-panel related-plan");
      related.append(node("h3", "", plan.related.issue), node("p", "", plan.related.step));
      related.append(...plan.related.contacts.map((contact) => renderContact(contact)));
      body.append(related);
    }
    if (plan.rules.length) body.append(renderSources("Official policy", plan.rules));
    if (plan.tips.length) body.append(renderSources("Senior tips", plan.tips, true));
    article.append(body);
  } else {
    const actions = node("div", "plan-actions");
    actions.append(button("outline", "Search campus directory", () => showDirectory(true)));
    article.append(actions);
  }
  current.replaceChildren(article);
  showReply(true);
  focusLatest(heading);
}

async function runTurn(event) {
  if (busy) return;
  const requestGeneration = generation;
  const previousPrompt = activePrompt;
  const editedPrompt = editing?.prompt;
  busy = true;
  displayError();
  conversation.setAttribute("aria-busy", "true");
  if (session) showReply(false);
  try {
    const outcome = await sendTurn({ ...event, session, revision });
    if (requestGeneration !== generation) {
      if (outcome.session !== session) closeChat(outcome.session);
      return;
    }
    session = outcome.session;
    revision = outcome.revision;
    activePrompt = outcome.question;
    quickReplies = outcome.suggestions;
    turns = [...turns.slice(0, outcome.position), {
      position: outcome.position, text: event.text, prompt: editedPrompt ?? previousPrompt,
      resolved: outcome.resolved, response: outcome.response,
    }];
    editing = undefined;
    replyInput.value = "";
    renderThread();
    if (activePrompt) renderFollowUp(activePrompt);
    else renderPlan(outcome.plan);
    if (outcome.response && outcome.position) focusLatest(followThrough.lastElementChild.querySelector(".bubble"));
  } catch (failure) {
    if (requestGeneration !== generation) return;
    displayError(failure.message);
    if (session) showReply(true, editing?.prompt ?? activePrompt);
    else current.replaceChildren(button("outline", "Try again", () => runTurn(event)));
  } finally {
    if (requestGeneration === generation) {
      busy = false;
      conversation.removeAttribute("aria-busy");
    }
  }
}

function showReply(visible, prompt = null) {
  replyForm.hidden = !visible;
  replySubmit.disabled = !visible;
  if (!visible) {
    replySuggestions.replaceChildren();
    return;
  }
  replyLabel.textContent = editing ? "Edit your reply" : prompt ? "Your reply" : "Ask a follow-up";
  replyInput.placeholder = prompt ? "Reply in your own words…" : "What would you like to ask next?";
  replySuggestions.replaceChildren(...(prompt ? [] : quickReplies).map(
    (label) => button("choice", label, () => handleReply(label))
  ));
}

function showExchange(text, response) {
  if (text) followThrough.append(message("user", text));
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

}

function handleReply(text, choice = null) {
  if (!text || !session) return;
  runTurn({ text, choice, rewind: editing?.position });
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
  if (query.length >= 3 && ready) start(query);
  else displayError("Enter a few words about what happened.");
});
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && ready) {
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
  ready = true;
  for (const scenario of intake.scenarios) {
    const [title, icon, detail] = TOPICS[scenario.tag] ?? [scenario.label, "pages"];
    const topic = button("topic", "", () => start(title, scenario.tag));
    const mark = node("span", `topic-mark ${icon}`);
    mark.setAttribute("aria-hidden", "true");
    const content = node("span", "topic-content");
    content.append(node("span", "topic-name", title));
    if (detail) content.append(node("span", "topic-detail", detail));
    topic.append(mark, content);
    topics.append(topic);
  }
  submit.disabled = false;
} catch (failure) {
  displayError(failure.message);
}
