let data;

export function getIntake() {
  data ??= fetch(new URL("./demo-data.json", import.meta.url)).then((response) => {
    if (!response.ok) throw new Error("Humraah is temporarily unavailable. Try again.");
    return response.json();
  });
  return data;
}

export function lookupPlan(intake, input) {
  if (!input.tag) return intake.fallback;
  const sent = input.tag === "escalation" && input.sent !== null ? (input.sent ? "yes" : "no") : "";
  const key = [input.mode, input.tag, input.department || "", input.degree_program || "", sent].join("|");
  const plan = intake.plans[intake.index[key]];
  return plan ? { ...plan, department: input.department } : intake.fallback;
}

export async function getPlan(input) {
  return lookupPlan(await getIntake(), input);
}
