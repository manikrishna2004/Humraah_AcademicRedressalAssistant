// Browser-only transport for the public prototype. Questions stay in the tab.
export function createReviewerTransport(data) {
  const sessions = new Map();
  const aliases = data.aliases.map(([pattern, replacement, flags]) => [
    new RegExp(pattern, flags),
    replacement,
  ]);
  const intents = data.intents.map(([pattern, tag]) => [new RegExp(pattern, "i"), tag]);
  const outOfDomain = new RegExp(data.outOfDomain, "i");
  const departmentHints = data.departments.map((name) => [name, name.split(" ")[0].toLowerCase()]);
  const fieldOptions = {
    department: { key: "department", label: "Department", options: data.departments },
    degree_program: { key: "degree_program", label: "Degree program", options: data.degreePrograms },
  };

  function classify(query) {
    for (const [pattern, replacement] of aliases) {
      query = query.replace(pattern, replacement);
    }
    const tag = intents.find(([pattern]) => pattern.test(query))?.[1];
    if (!Object.hasOwn(data.issues, tag) || outOfDomain.test(query)) return null;
    const normalized = query.toLowerCase();
    return {
      tag,
      department: departmentHints.find(([, first]) => normalized.includes(first))?.[0] ?? "",
      degree_program: data.programHints.find(([, hints]) => hints.some((word) => normalized.includes(word)))?.[0] ?? "",
    };
  }

  function followUp(state, question, fields = [], choices = []) {
    state.turn += 1;
    state.fields = fields;
    state.choices = choices;
    sessions.set(state.id, state);
    return {
      kind: "clarification",
      session: state.id,
      turn: state.turn,
      question,
      fields,
      choices: choices.map((value) => ({
        value,
        label: data.issues[value] ?? value[0].toUpperCase() + value.slice(1),
      })),
    };
  }

  function next(state) {
    const missing = [];
    if (!state.department && state.tag !== "supplementary_exam") {
      missing.push(fieldOptions.department);
    }
    if (!state.degree_program && ["attendance_waiver", "escalation"].includes(state.tag)) {
      missing.push(fieldOptions.degree_program);
    }
    if (missing.length) {
      const labels = missing.map((field) => field.label.toLowerCase()).join(" and ");
      return followUp(state, `What is your ${labels}?`, missing);
    }
    if (state.tag === "grade_review") {
      return followUp(state, "Which grade concern are you trying to resolve?", [], [
        "mid_sem_review",
        "end_sem_appeal",
      ]);
    }
    if (state.tag === "escalation" && !state.sent) {
      const question = state.mode === "sample"
        ? "In this example, have you already sent a formal email and waited 48 hours?"
        : "Have you already emailed your faculty advisor about this issue?";
      return followUp(state, question, [], ["yes", "no"]);
    }
    const key = [state.mode, state.tag, state.department, state.degree_program, state.sent].join("|");
    sessions.delete(state.id);
    return { kind: "plan", ...data.plans[data.index[key]], department: state.department || null };
  }

  return async function request(path, options = {}) {
    if (path === "/api/options") return Response.json({ scenarios: data.scenarios });
    if (path === "/api/guidance") {
      const { query, mode } = JSON.parse(options.body);
      if (typeof query !== "string" || query.trim().length < 3 || query.trim().length > 700) {
        return Response.json({ detail: "Describe your issue in 3 to 700 characters." }, { status: 422 });
      }
      const intent = classify(query.trim());
      if (!intent) return Response.json({ kind: "plan", ...data.fallback });
      const state = {
        ...intent,
        mode: mode === "sample" ? "sample" : "campus",
        id: crypto.randomUUID(),
        sent: "",
        turn: 0,
      };
      return Response.json(next(state));
    }

    const session = path.match(/^\/api\/guidance\/([\w-]+)(?:\/answer)?$/)?.[1];
    if (options.method === "DELETE") {
      sessions.delete(session);
      return new Response(null, { status: 204 });
    }

    const state = sessions.get(session);
    if (!state) {
      return Response.json({ detail: "This question has expired. Please start a new one." }, { status: 404 });
    }
    const { turn, answer } = JSON.parse(options.body);
    if (turn !== state.turn) {
      return Response.json({ detail: "This follow-up has already been answered." }, { status: 409 });
    }
    if (state.fields.length) {
      if (!state.fields.every(({ key, options }) => options.includes(answer?.[key]))) {
        return Response.json({ detail: "Choose one of the available answers." }, { status: 422 });
      }
      for (const { key } of state.fields) state[key] = answer[key];
    } else if (!state.choices.includes(answer)) {
      return Response.json({ detail: "Choose one of the available answers." }, { status: 422 });
    } else if (state.tag === "grade_review") {
      state.tag = answer;
    } else {
      state.sent = answer;
    }

    return Response.json(next(state));
  };
}

let transport;

export async function request(path, options) {
  transport ??= fetch(new URL("./demo-data.json", import.meta.url))
    .then((response) => {
      if (!response.ok) throw new Error("Humraah guidance is temporarily unavailable.");
      return response.json();
    })
    .then(createReviewerTransport);
  return (await transport)(path, options);
}
