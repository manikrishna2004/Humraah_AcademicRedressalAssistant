const ISSUE_CHOICES = [
  ["supplementary_exam", "Supplementary exam"],
  ["grade_review", "Grades"],
  ["attendance_waiver", "Attendance"],
  ["escalation", "Faculty advisor"],
  ["other", "Something else"],
];
const GRADE_CHOICES = [
  ["mid_sem_review", "See my mid-sem answer script"],
  ["end_sem_appeal", "Raise an end-sem grade concern"],
  ["grade_review", "I’m not sure"],
];
const ADVISOR_CHOICES = [["yes", "Yes, already emailed"], ["no", "Not yet"], ["unknown", "I’m not sure"]];

export function createConversation(intake) {
  const aliases = intake.aliases.map(([pattern, replacement, flags]) => [new RegExp(pattern, flags), replacement]);
  const intents = intake.intents.map(([pattern, tag]) => [new RegExp(pattern, "i"), tag]);
  const outOfDomain = new RegExp(intake.outOfDomain, "i");
  const departments = intake.departments;
  const campusTopicNames = new Set(ISSUE_CHOICES.map(([key]) => key));
  const gradeHint = /\b(?:marks?|grades?|answer script|recheck|marking)\b/i;
  const advisorHint = /(?:faculty advisor|\bhod\b).{0,45}(?:reply|repli|respond|reached|ignor|answer)|unresponsive/i;

  function classify(query) {
    for (const [pattern, replacement] of aliases) query = query.replace(pattern, replacement);
    const normalized = query.toLowerCase();
    const matches = intents.filter(([pattern]) => pattern.test(query)).map(([, tag]) => tag);
    const matchedGradeRoutes = matches.filter((tag) => tag === "mid_sem_review" || tag === "end_sem_appeal");
    const broadGrade = matchedGradeRoutes.length > 1 || matches.includes("grade_review") || gradeHint.test(query);
    const gradeRoute = matchedGradeRoutes.length === 1 ? matchedGradeRoutes[0] : broadGrade ? "grade_review" : null;
    const advisor = matches.includes("escalation");
    const academicRoutes = [
      ...matches.filter((tag) => tag === "supplementary_exam" || tag === "attendance_waiver"),
      gradeRoute,
      advisor && (advisorHint.test(query) || (!gradeRoute && matches.length === 1)) ? "escalation" : null,
    ].filter(Boolean);
    const outside = !academicRoutes.length && (matches.includes("hostel_admin") || outOfDomain.test(query));
    let sent = null;
    if (/\b(?:haven['’]t|haven’t|didn['’]t|not yet)\b.{0,28}\b(?:email|sent|send|mail)/i.test(query)) sent = false;
    else if (/\b(?:already emailed|already sent|sent (?:an |a |the |my )?email|emailed (?:my |the )?faculty advisor)\b/i.test(query)) sent = true;

    return {
      tag: academicRoutes.length === 1 ? academicRoutes[0] : outside ? "other" : null,
      department: intake.departments.find((name) => (
        new RegExp(`\\b${name.split(" ")[0]}\\b`, "i").test(query)
      )) ?? null,
      degree_program: intake.programHints.find(([, hints]) => hints.some((hint) => normalized.includes(hint)))?.[0] ?? null,
      sent,
    };
  }

  function start(query, topic = null) {
    const state = classify(query);
    return {
      ...state,
      query,
      topic,
      tag: topic && campusTopicNames.has(topic) ? topic : state.tag,
      turns: 0,
      gradeAnswered: false,
      advisorAnswered: state.sent !== null,
      departmentAnswered: state.department !== null,
    };
  }

  function question(state) {
    if (state.turns >= 2 || state.tag === "other") return null;
    if (!state.tag) return { key: "tag", text: "What is the issue about?", choices: ISSUE_CHOICES };
    if (state.tag === "grade_review" && !state.gradeAnswered) {
      return { key: "tag", text: "What are you trying to do about your grade?", choices: GRADE_CHOICES };
    }
    if (state.tag === "escalation" && !state.advisorAnswered) {
      return {
        key: "sent",
        text: "Have you already emailed your faculty advisor about this?",
        choices: ADVISOR_CHOICES,
      };
    }
    if (
      !state.departmentAnswered && (state.tag === "attendance_waiver" || (state.tag === "escalation" && state.sent === true))
    ) {
      return {
        key: "department",
        text: "Which department office should I look up?",
        choices: departments.map((name) => [name, name]).concat([["unknown", "I’m not sure"]]),
        dropdown: true,
      };
    }
    return null;
  }

  function answer(state, prompt, value) {
    if (!prompt?.choices.some(([key]) => key === value)) throw new Error("Choose one of the available answers.");
    const updated = { ...state, turns: state.turns + 1 };
    if (prompt.key === "tag") {
      updated.tag = value;
      updated.gradeAnswered = state.tag === "grade_review";
    }
    if (prompt.key === "sent") {
      updated.sent = value === "unknown" ? null : value === "yes";
      updated.advisorAnswered = true;
    }
    if (prompt.key === "department") {
      updated.department = value === "unknown" ? null : value;
      updated.departmentAnswered = true;
    }
    return updated;
  }

  function planInput(state) {
    const { query, tag, department, degree_program, sent } = state;
    return {
      query, department, degree_program, sent,
      tag: tag && tag !== "other" ? tag : null,
    };
  }

  return { start, question, answer, planInput };
}
