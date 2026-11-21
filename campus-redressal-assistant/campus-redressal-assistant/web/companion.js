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
  ];
}

export function respond(text, state, plan) {
  const input = text.trim();
  const contact = plan.contacts[0];
  const source = reference(contact);
  const result = (message, links = [], draft = null) => ({ text: message, links: links.filter(Boolean), draft });

  if (/^(?:thanks|thank you|okay thanks|got it|shukriya)[!. ]*$/i.test(input)) {
    return result("You’re welcome. If the office replies and you’re unsure what a step means, you can ask about it here.");
  }
  if (!plan.supported) {
    return result("Tell me what happened in a few words, or pick one of the academic topics to start again.");
  }
  if (/\b(?:draft|template|write|wording|what (?:should|do|can) i (?:say|include|email|send))\b/i.test(input)) {
    const note = EMAIL_NOTES[state.tag];
    if (note && contact) {
      const [subject, body] = state.tag === "escalation" && state.sent === true ? [
        "Follow-up on [academic issue] in [course code]",
        "I emailed my faculty advisor on [date] about [one-sentence description]. Could you advise who can help with the next step? I’ve included the original message below for context.",
      ] : note;
      return result(
        `Here’s a draft for ${contact.role}. Replace the bracketed details before sending.`,
        [source],
        `Subject: ${subject}\n\nHello,\n\n${body}\n\nThank you,\n[Your name]`,
      );
    }
  }
  if (/\b(?:in person|visit|where (?:should|do|can) i go|which (?:room|building)|address|opening hours|office hours|what time|when (?:can|should) i (?:go|visit)|meet)\b/i.test(input)) {
    if (contact) {
      const details = [contact.office, contact.office_hours].filter(Boolean);
      const location = details.length ? `${contact.role} — ${details.join(", ")}.` : `Start with ${contact.role}.`;
      const visit = contact.visit_note || "Check the office listing to arrange a visit.";
      return result(`${location} ${visit}`, [source]);
    }
  }
  if (/\b(?:deadline|last date|how long|by when|application window|missed (?:it|the window)|today|tomorrow)\b/i.test(input)) {
    if (state.tag === "supplementary_exam") {
      return result("Check the calendar and the latest ERP notice for your session. If the window has closed, ask the UG Academic Section whether a late request is possible for your batch.", [CALENDAR, ERP, source]);
    }
    const official = plan.rules.find((rule) => rule.url);
    return result("The timing depends on your course or admission batch. Ask the contact on your plan to confirm the date that applies to you.", [official, source]);
  }
  if (/\b(?:already (?:emailed|sent|mailed)|no (?:reply|response)|still waiting|follow[- ]?up)\b/i.test(input)) {
    const next = state.tag === "escalation"
      ? "Ask the department office who can take the issue forward if you’re still waiting."
      : `Follow up with ${contact?.role || "the listed contact"} on the same thread.`;
    return result(`Keep the original email and make the deadline clear. ${next}`, [source]);
  }
  if (/\b(?:contact|whom|who|mail id|email|call|number|phone)\b/i.test(input) && contact) {
    const channels = [contact.email, contact.phone].filter(Boolean);
    const text = `For this issue, start with ${contact.role}.${channels.length ? ` ${channels.join(" · ")}.` : ""} ${contact.detail}`;
    const email = contact.email ? { label: contact.email, url: `mailto:${contact.email}` } : null;
    const phone = contact.phone ? { label: contact.phone, url: `tel:${contact.phone.replace(/[^+0-9]/g, "")}` } : null;
    return result(text, [email, phone, source]);
  }
  return result("I can help with the next contact, an office visit, or a draft message for this issue. If something has changed, tell me what’s different.");
}
