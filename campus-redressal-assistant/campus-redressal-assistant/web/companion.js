const CALENDAR = {
  label: "IIT Kharagpur academic calendar",
  url: "https://www.iitkgp.ac.in/academic-calendar-ug",
};
const ERP = { label: "IIT Kharagpur ERP", url: "https://erp.iitkgp.ac.in/" };

const EMAIL_NOTES = {
  supplementary_exam: [
    "Supplementary registration for [course code]",
    "I’m checking the supplementary registration process for [course code] for my admission batch [year]. Could you confirm which notice applies and whether there is a way to submit an application at this stage?",
  ],
  grade_review: [
    "Question about my grade in [course code]",
    "Could we review the mark for [assessment] in [course code]? The specific point I’d like to understand is [brief discrepancy]. Please let me know the right way to raise it.",
  ],
  mid_sem_review: [
    "Request to view my mid-sem answer script for [course code]",
    "Could you let me know when I can view my evaluated mid-sem answer script for [course code]? I’d like to understand the marking for [question number or topic].",
  ],
  end_sem_appeal: [
    "Request to check an end-sem grade discrepancy in [course code]",
    "Could you check the following discrepancy in [course code]: [one specific detail]? Please let me know the review procedure for my admission batch if it needs to go further.",
  ],
  attendance_waiver: [
    "Attendance guidance for [course code]",
    "I’m asking about attendance for [course code] during [dates]. Could you confirm the procedure that applies and which documents I should submit?",
  ],
  escalation: [
    "Help with an academic issue in [course code]",
    "I’m looking for guidance on [one-sentence description] for [course code]. Could you tell me the next step or who can help? The relevant deadline is [date, if applicable].",
  ],
};

function reference(contact) {
  return contact?.url ? { label: contact.source_label, url: contact.url } : null;
}

export function suggestions(state, plan) {
  if (!plan.supported) return [];
  return [
    "Help me write the email",
    "Can I go in person?",
    state.tag === "supplementary_exam" ? "Where do I check the deadline?" : "Who should I contact?",
    ...(plan.rules.some(({ url }) => url) ? ["Show me the official sources"] : []),
    "Switch issue",
  ];
}

const FOLLOW_UPS = [
  ["thanks", /^(?:thanks|thank you|okay thanks|got it|shukriya)[!. ]*$/i],
  ["draft", /\b(?:draft|template|write|wording|what (?:should|do|can) i (?:say|include|email|send))\b/i],
  ["visit", /\b(?:in person|visit|where (?:should|do|can) i go|which (?:room|building)|address|opening hours|office hours|what time|when (?:can|should) i (?:go|visit)|meet)\b/i],
  ["deadline", /\b(?:deadline|last date|how long|by when|application window|missed (?:it|the window)|today|tomorrow)\b/i],
  ["source", /\b(?:official (?:sources?|rules?|policy|guidance)|(?:show|send|share|link to)(?: me)? (?:the )?(?:policy|rules?|handbook|source|link)|(?:where|how) (?:can|do|should) i (?:verify|check|confirm) (?:that|this|it)|sources?|citations?)\b/i],
  ["no_reply", /\b(?:already (?:emailed|sent|mailed)|no (?:reply|response)|still waiting|follow[- ]?up)\b/i],
  ["contact", /\b(?:contact|whom|who|mail id|email|call|number|phone)\b/i],
];

export function followUpIntent(text) {
  return FOLLOW_UPS.find(([, pattern]) => pattern.test(text.trim()))?.[0] ?? "describe";
}

export function respond(text, state, plan, intent = followUpIntent(text)) {
  const contact = plan.contacts[0];
  const source = reference(contact);
  const result = (message, links = [], draft = null, claimIds = []) => ({
    text: message, links: links.filter(Boolean), draft, claim_ids: claimIds.filter(Boolean),
  });

  if (intent === "thanks") {
    return result("You’re welcome. If the office replies and you’re unsure what a step means, ask me here.");
  }
  if (!plan.supported) {
    return result("Tell me what happened in a few words, or pick one of the academic topics to start again.");
  }
  if (intent === "draft" || intent === "no_reply") {
    const note = EMAIL_NOTES[state.tag];
    if (note && contact) {
      const advisorEscalation = state.tag === "escalation" && state.sent === true;
      const [subject, body] = advisorEscalation ? [
        "Follow-up on [academic issue] in [course code]",
        "I emailed my faculty advisor on [date] about [one-sentence description] and haven’t heard back. Could you let me know who can help with the next step? I’ve included the original thread below. The deadline, if applicable, is [date].",
      ] : note;
      const lead = advisorEscalation
        ? `Forward your original email to ${contact.role} and mention any upcoming deadline. Here’s a draft you can adapt.`
        : `Here’s a draft for ${contact.role}. Replace the bracketed details before sending.`;
      const email = contact.email ? { label: contact.email, url: `mailto:${contact.email}` } : null;
      return result(lead, [email, source], `Subject: ${subject}\n\nHello,\n\n${body}\n\nThank you,\n[Your name]`, [contact.claim_id]);
    }
  }
  if (intent === "visit" && contact) {
    const office = contact.office ? `${contact.role} is listed at ${contact.office}.` : `Start with ${contact.role}.`;
    const hours = contact.office_hours ? `Published hours are ${contact.office_hours}.` : "The source doesn’t publish visiting hours.";
    const visit = contact.visit_note || "Ask which room to go to and when someone can meet you.";
    const phone = contact.phone ? { label: contact.phone, url: `tel:${contact.phone.replace(/[^+0-9]/g, "")}` } : null;
    const email = contact.email ? { label: contact.email, url: `mailto:${contact.email}` } : null;
    return result(`${office} ${hours} ${visit}`, [phone, email, source], null, [contact.claim_id]);
  }
  if (intent === "deadline") {
    if (state.tag === "supplementary_exam") {
      return result("Check the calendar and the latest ERP notice for your session. If the window has closed, ask the UG Academic Section whether a late request is possible for your batch.", [CALENDAR, ERP, source], null, [contact?.claim_id]);
    }
    const official = plan.rules.find((rule) => rule.url);
    return result("The timing depends on your course or admission batch. Ask the contact on your plan to confirm the date that applies to you.", [official, source], null, [official?.claim_id, contact?.claim_id]);
  }
  if (intent === "source") {
    const official = plan.rules.filter(({ url }) => url);
    if (official.length) {
      return result(`Here are the official sources I used for ${plan.issue.toLowerCase()}. If your batch or situation isn’t covered, ask the listed contact which instructions apply.`,
        official, null, official.map(({ claim_id }) => claim_id));
    }
    return result("I don’t have a published rule for this case. Ask the contact on your plan which procedure applies.",
      [source], null, [contact?.claim_id]);
  }
  if (intent === "contact" && contact) {
    const channels = [contact.email, contact.phone].filter(Boolean);
    const message = `For this issue, start with ${contact.role}.${channels.length ? ` ${channels.join(" · ")}.` : ""} ${contact.detail}`;
    const email = contact.email ? { label: contact.email, url: `mailto:${contact.email}` } : null;
    const phone = contact.phone ? { label: contact.phone, url: `tel:${contact.phone.replace(/[^+0-9]/g, "")}` } : null;
    return result(message, [email, phone, source], null, [contact.claim_id]);
  }
  return result("I can help with the next contact, an office visit, or a draft message for this issue. If something has changed, tell me what’s different.");
}
