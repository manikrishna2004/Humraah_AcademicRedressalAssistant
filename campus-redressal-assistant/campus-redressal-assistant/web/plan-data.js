export function directoryTerms(term) {
  return term.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

export function planRoute(intake, input) {
  const status = input.sent === null ? "unknown" : input.sent ? "yes" : "no";
  const isEscalation = input.tag === "escalation";
  const key = `${input.tag}|${isEscalation ? status : ""}`;
  const plan = intake.plans[key];
  const kinds = isEscalation ? intake.directory.escalation[status] : intake.directory.routes[input.tag] ?? [];
  const routes = kinds.map((kind) => [kind, kind === "department" && input.department ? input.department : "General"]);
  return { plan, routes };
}

export function withContacts(intake, plan, department, rows) {
  const contacts = rows.map((row) => ({
    ...row, claim_id: `directory:${row.id}`, type: "directory", verified_at: intake.sourceReviewDate,
  }));
  const contact = contacts[0];
  const notices = plan.notices.map((notice) => notice.links && contact ? {
    ...notice, links: [...notice.links, { label: contact.source_label, url: contact.url }],
  } : notice);
  return { ...plan, contacts, department, notices };
}
