import { createConversation } from "./conversation.js";
import { followUpIntent, respond, suggestions } from "./companion.js";

const GRADE_ISSUES = new Set(["grade_review", "mid_sem_review", "end_sem_appeal"]);
const OPEN_ACTIONS = /^(?:\s*(?:can|should|could|would|what if|if|do i)\b)/i;
const SWITCH = /\b(?:new question|different issue|switch (?:to|issues?)|also help with)\b/i;
const CORRECTION = /\b(?:actually|correction|meant|rather|instead|i(?: am|['’]m) in|(?:department|dept|branch) is)\b/i;
const NOT_RESPONDING = /\b(?:no (?:reply|response)|nothing|still waiting|(?:hasn['’]t|isn['’]t|didn['’]t|not)\s+(?:repl\w*|respond\w*|answer\w*)|unresponsive)\b/i;
const EMAIL_TARGET = /\b(?:email(?:ed|ing)?|mail(?:ed)?)\b/i;
const DEADLINE = /\b(?:last date|deadline|(?:window|form|registration|applications?) (?:closes?|closing|ends?|ended|is (?:closing|due))|missed (?:the |my )?(?:form|window|registration))\b/i;
const TIMING = /\b(?:today|tomorrow|tonight|soon|(?:in |within )\d+ (?:hours?|days?)|(?:by|before|on) (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\d{1,2}\s+[A-Za-z]{3,9}|\d{4}-\d{2}-\d{2})|\d{1,2}[:.]\d{2}(?:\s*[ap]m)?|\d{1,2}\s*(?:am|pm))\b/i;
const URGENT = /\b(?:urgent|closes? soon|closing soon|today|tomorrow|tonight|missed|last day|within \d+ hours?)\b/i;
const choiceFor = (prompt, choice) => prompt?.choices.some(([id]) => id === choice);

function slot(value, source = "stated") {
  return value == null ? null : { value, source };
}

export function createTurnEngine(intake) {
  const language = createConversation(intake);

  function legacyState(state) {
    return {
      tag: state?.issue?.value ?? null,
      department: state?.department?.value ?? null,
      degree_program: state?.cohort?.value?.program ?? null,
      sent: state?.actions_taken.find(({ kind }) => kind === "emailed_advisor")?.value ?? null,
      gradeAnswered: state?.answered.includes("grade") ?? false,
      advisorAnswered: state?.answered.includes("sent") ?? false,
      departmentAnswered: state?.answered.includes("department") ?? false,
      turns: 0,
    };
  }

  function interpret(state, event) {
    const { text } = event;
    const normalized = language.normalize(text);
    const old = legacyState(state);
    const matched = language.classify(text);
    const prompt = state?.pending_question;
    const answer = choiceFor(prompt, event.choice) ? event.choice : null;
    const parsed = prompt && !answer ? language.interpretReply(old, prompt, text) : null;
    let pending_answer = answer;
    if (parsed) {
      pending_answer = prompt.key === "tag" ? parsed.tag
        : prompt.key === "department" ? parsed.department ?? "unknown"
          : parsed.sent === null ? "unknown" : parsed.sent ? "yes" : "no";
    }
    if (prompt?.id === "grade" && !answer && parsed?.tag === "grade_review") pending_answer = "unsure";
    if (prompt?.id === "grade" && (!pending_answer || pending_answer === "unsure") && /\b(?:low|poor|lower|bad|disappoint\w*)\b/i.test(text)) pending_answer = "low_result";
    if (prompt?.id === "grade" && (!pending_answer || pending_answer === "unsure") && /\b(?:error|discrepancy|wrong|mistake)\b/i.test(text)) pending_answer = "grade_review";
    const noReply = !OPEN_ACTIONS.test(text) && NOT_RESPONDING.test(normalized);
    const aboutAdvisor = /\b(?:faculty advisor|head of department|department undergraduate committee)\b/i.test(normalized)
      || old.tag === "escalation" || state?.related_issues.includes("escalation");
    const emailed = !OPEN_ACTIONS.test(text) && (aboutAdvisor || EMAIL_TARGET.test(text)) ? matched.sent : null;
    const actions = [];
    if (emailed !== null && (aboutAdvisor || old.tag === null)) {
      actions.push({ kind: "emailed_advisor", value: emailed, source: "stated" });
    }
    if (noReply && aboutAdvisor) actions.push({ kind: "advisor_no_reply", value: true, source: "stated" });
    const timing = normalized.match(TIMING)?.[0] ?? null;
    const newDeadline = DEADLINE.test(normalized) || Boolean(timing && (!state || (state.deadline && CORRECTION.test(text))));
    const year = normalized.match(/\b(?:(?:batch|cohort|admitted in|admission year)\s*(?:of\s+)?(20\d{2})|(20\d{2})\s*(?:batch|cohort))\b/i);
    const program = matched.degree_program;
    const corrections = CORRECTION.test(text) ? [
      ...(matched.department ? ["department"] : []),
      ...(year || program ? ["cohort"] : []),
      ...(newDeadline ? ["deadline"] : []),
      ...(matched.issues.length ? ["issue"] : []),
      ...(emailed !== null ? ["actions_taken"] : []),
    ] : [];
    return {
      intent: SWITCH.test(text) ? "switch" : noReply && old.tag && (aboutAdvisor || EMAIL_TARGET.test(text)) ? "no_reply"
        : followUpIntent(text),
      issues: event.topic ? [event.topic] : matched.issues.length ? matched.issues : matched.tag === "other" ? ["other"] : [],
      department: matched.department,
      cohort: year || program ? { program, admission_year: year ? Number(year[1] || year[2]) : null } : null,
      deadline: newDeadline ? { raw: timing ?? text.trim().slice(0, 160), urgent: URGENT.test(normalized) } : null,
      actions,
      corrections,
      pending_answer,
    };
  }

  const questions = [
    ["issue", (current) => !current.issue, (state) => language.question(legacyState(state))],
    ["grade", (current) => current.issue?.value === "grade_review" && !current.answered.includes("grade"),
      () => ({
        key: "tag",
        text: "What’s the concern about your grade?",
        lead: "That helps me work out whether to suggest a script viewing, a review or a grade appeal.",
        choices: [
          ["mid_sem_review", "I want to see my mid-sem script"],
          ["grade_review", "I think a mark is wrong"],
          ["end_sem_appeal", "I want to appeal my final grade"],
          ["low_result", "I’m worried about a low grade"],
          ["unsure", "I’m not sure"],
        ],
      })],
    ["sent", (current) => current.issue?.value === "escalation" &&
      !current.answered.includes("sent") && !current.actions_taken.some(({ kind }) => kind === "emailed_advisor"),
    (state) => language.question(legacyState(state))],
    ["department", (current) => !current.department && !current.answered.includes("department") &&
      (current.issue?.value === "attendance_waiver" || (current.issue?.value === "escalation" &&
        current.actions_taken.some(({ kind, value }) => kind === "emailed_advisor" && value))),
    (state) => language.question(legacyState(state))],
  ];

  function transition(previous, event, parsed = interpret(previous, event), rules = parsed) {
    const oldIssue = previous?.issue?.value;
    const pending = previous?.pending_question;
    const offered = parsed.pending_answer;
    const specificGrade = pending?.id === "issue" && GRADE_ISSUES.has(offered);
    const answer = choiceFor(pending, offered) || specificGrade ? offered : null;
    const issues = parsed.issues.filter((issue) => issue !== "other");
    const explicitlySwitching = parsed.intent === "switch";
    const restart = explicitlySwitching || oldIssue === "other" && issues.length > 0;
    const state = {
      issue: null, department: previous?.department ?? null, cohort: previous?.cohort ?? null,
      related_issues: [], deadline: null, actions_taken: [], answered: [], grade_concern: null,
      query: event.text, pending_question: null, stage: "intake", needs_replan: false,
      ...(!restart ? previous : null),
    };
    state.answered = [...state.answered];
    state.department = slot(parsed.department, rules.department ? "stated" : "inferred") ?? state.department;
    if (parsed.cohort) {
      state.cohort = {
        value: {
          program: parsed.cohort.program ?? state.cohort?.value.program ?? null,
          admission_year: parsed.cohort.admission_year ?? state.cohort?.value.admission_year ?? null,
        },
        source: {
          program: parsed.cohort.program ? (rules.cohort?.program ? "stated" : "inferred") : state.cohort?.source.program ?? null,
          admission_year: parsed.cohort.admission_year ? (rules.cohort?.admission_year ? "stated" : "inferred") : state.cohort?.source.admission_year ?? null,
        },
      };
    }
    if (parsed.deadline) state.deadline = { ...parsed.deadline, verified: false, source: "stated" };
    if (parsed.actions.length) {
      let actions = state.actions_taken.filter(({ kind }) => !parsed.actions.some((action) => action.kind === kind));
      if (parsed.actions.some(({ kind, value }) => kind === "emailed_advisor" && !value)) {
        actions = actions.filter(({ kind }) => kind !== "advisor_no_reply");
      }
      state.actions_taken = [...actions, ...parsed.actions];
    }

    const deadlineIssue = issues.includes("supplementary_exam") && parsed.deadline?.urgent;
    const gradeCorrection = parsed.corrections.includes("issue") && GRADE_ISSUES.has(oldIssue) && issues.some((issue) => GRADE_ISSUES.has(issue));
    const inferredIssue = deadlineIssue ? "supplementary_exam" : issues.find((issue) => issue !== "escalation") ?? issues[0];
    if (answer && pending.id === "issue") {
      state.issue = slot(answer);
      state.query = event.text;
    } else if (answer && pending.id === "grade") {
      state.issue = slot(GRADE_ISSUES.has(answer) ? answer : "grade_review");
      state.grade_concern = slot(answer);
    } else if (!state.issue || deadlineIssue || gradeCorrection || parsed.corrections.includes("issue") && inferredIssue) {
      const name = inferredIssue ?? (parsed.issues.includes("other") ? "other" : null);
      state.issue = slot(name, event.topic ? "stated" : "inferred");
      if (name && name !== oldIssue) state.query = event.text;
    }
    if (answer && pending.id === "sent" && answer !== "unknown") {
      state.actions_taken = [...state.actions_taken.filter(({ kind }) => kind !== "emailed_advisor"),
        { kind: "emailed_advisor", value: answer === "yes", source: "stated" }];
    }
    if (answer && pending.id === "department" && answer !== "unknown") state.department = slot(answer);
    if (answer && pending.id === "issue" && state.issue?.value !== "grade_review" && GRADE_ISSUES.has(answer)) state.answered.push("grade");
    if (answer && !state.answered.includes(pending.id)) state.answered.push(pending.id);
    if (state.issue?.value === "other") state.related_issues = [];
    else state.related_issues = [...new Set([...state.related_issues, ...issues,
      ...(deadlineIssue && oldIssue && oldIssue !== "other" ? [oldIssue] : [])])]
      .filter((issue) => issue !== state.issue?.value && !(GRADE_ISSUES.has(issue) && GRADE_ISSUES.has(state.issue?.value)));

    const contextChanged = !previous || state.issue?.value !== oldIssue ||
      JSON.stringify(state.department) !== JSON.stringify(previous.department) ||
      JSON.stringify(state.cohort) !== JSON.stringify(previous.cohort) ||
      JSON.stringify(state.deadline) !== JSON.stringify(previous.deadline) ||
      JSON.stringify(state.actions_taken) !== JSON.stringify(previous.actions_taken) ||
      JSON.stringify(state.related_issues) !== JSON.stringify(previous.related_issues);
    state.needs_replan = contextChanged || Boolean(answer) || restart;
    const next = state.issue?.value !== "other" ? questions.find(([, applies]) => applies(state)) : null;
    state.pending_question = next ? { id: next[0], ...next[2](state) } : null;
    const intent = explicitlySwitching || answer && parsed.intent !== "no_reply" ? "describe" : parsed.intent;
    state.stage = state.pending_question ? "clarifying" : previous && intent !== "describe" ? "follow-up" : "plan";
    const legacy = legacyState(state);
    const main = language.planInput({ ...legacy, query: state.query });
    const related = state.related_issues.includes("escalation") ? { ...main, tag: "escalation" } : null;
    const advisorFollowUp = related && /\bfaculty advisor\b/i.test(language.normalize(event.text));
    return { state, intent, main, related, advisorFollowUp, resolved: Boolean(answer) };
  }

  function finish(change, plan, relatedPlan, wording) {
    const { state, main, intent, resolved, advisorFollowUp } = change;
    const legacy = legacyState(state);
    const result = { state, question: state.pending_question, resolved, plan: null, response: null, suggestions: [] };
    if (!plan) return result;
    if (main.tag === "grade_review" && state.grade_concern?.value === "low_result") {
      plan = { ...plan, next_step: "Ask your instructor how the grade was calculated and which feedback or answer script you can review. Include the course code and assessment so you can work out which marks you would like to discuss." };
    }
    result.plan = plan;
    if (state.deadline && !state.deadline.verified && plan.supported) {
      const contact = plan.contacts[0];
      plan = { ...plan, notices: [{
        title: "Confirm the deadline",
        text: main.tag === "supplementary_exam"
          ? "I couldn’t verify the deadline for your batch. Check the current ERP notice and ask the UG Academic Section to confirm the closing time and any late-registration option."
          : "I couldn’t verify that deadline. Ask the listed contact to confirm the date, time and procedure that apply to your case.",
        links: main.tag === "supplementary_exam"
          ? [{ label: "IIT Kharagpur ERP", url: "https://erp.iitkgp.ac.in/" }, ...(contact ? [{ label: contact.source_label, url: contact.url }] : [])]
          : contact ? [{ label: contact.source_label, url: contact.url }] : [],
      }, ...plan.notices] };
      result.plan = plan;
    }
    if (relatedPlan) {
      result.plan = { ...plan, related: {
        issue: "Still waiting on your faculty advisor?",
        step: "Keep the original thread. If you’ve already emailed, ask your department office who can pick it up and mention the deadline.",
        contacts: relatedPlan.contacts.slice(0, 1),
      } };
    }
    if (intent !== "describe") {
      const useAdvisor = relatedPlan && (advisorFollowUp ||
        intent === "no_reply" && state.actions_taken.some(({ kind }) => kind === "advisor_no_reply"));
      result.response = respond("", useAdvisor ? { ...legacy, tag: "escalation" } : legacy, useAdvisor ? relatedPlan : plan, intent);
    } else if (wording) {
      result.response = wording;
    }
    result.suggestions = suggestions(legacy, plan);
    return result;
  }

  return { normalize: language.normalize, interpret, transition, finish };
}
