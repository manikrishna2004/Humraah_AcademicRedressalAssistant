// The model can select existing claim IDs and a transition phrase. Source text,
// directory fields and the action plan always come from the local records.
export const TRANSITIONS = {
  none: "",
  context: "Here’s the official guidance for your case.",
  next_step: "You can use this official guidance to prepare your next step.",
};

export function composeFromClaims(selection, claims) {
  if (!selection || Object.keys(selection).sort().join(",") !== "claim_ids,transition" ||
      !Object.hasOwn(TRANSITIONS, selection.transition) || !Array.isArray(selection.claim_ids) ||
      selection.claim_ids.length < 1 || selection.claim_ids.length > 2 ||
      new Set(selection.claim_ids).size !== selection.claim_ids.length) return null;
  const allowed = new Map(claims.filter(({ type, url }) => type === "policy" && url).map((claim) => [claim.claim_id, claim]));
  const chosen = selection.claim_ids.map((id) => allowed.get(id));
  if (chosen.some((claim) => !claim)) return null;
  return {
    text: [TRANSITIONS[selection.transition], ...chosen.map(({ text }) => text)].filter(Boolean).join(" "),
    links: chosen.map(({ label, url }) => ({ label, url })),
    claim_ids: selection.claim_ids,
  };
}
