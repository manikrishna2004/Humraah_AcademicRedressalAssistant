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

const UNSURE = /\b(?:not sure|unsure|don['’]t know|no idea|pata nahi)\b/i;
const NOT_EMAILED = /^(?:no|nope|nah|not yet|nahi)[.!]?$|\b(?:haven['’]t|didn['’]t|never|not yet|nahi)\b.{0,30}\b(?:email|sent|send|mail)|\bmail.{0,14}nahi\b/i;
const EMAILED = /^(?:yes|yeah|yep|haan)[.!]?$|\b(?:already (?:emailed|sent|mailed|did)|sent (?:an? |the |my )?(?:email|mail)|(?:emailed|mailed) (?:my |the |them|him|her|faculty advisor)|mail (?:kar|bhej) diya)\b/i;

function emailStatus(text) {
  if (NOT_EMAILED.test(text)) return false;
  if (EMAILED.test(text)) return true;
  return null;
}

export function createConversation(intake) {
  const aliases = intake.aliases.map(([pattern, replacement, flags]) => [new RegExp(pattern, flags), replacement]);
  const intents = intake.intents.map(([pattern, tag]) => [new RegExp(pattern, "i"), tag]);
  const outOfDomain = new RegExp(intake.outOfDomain, "i");
  const departments = intake.departments;
  const campusTopicNames = new Set(ISSUE_CHOICES.map(([key]) => key));
  const gradeHint = /\b(?:marks?|grades?|answer script|recheck|marking)\b/i;
  const advisorHint = /(?:faculty advisor|head of department|department undergraduate committee).{0,45}(?:reply|repli|respond|reached|ignor|answer)|unresponsive/i;

  function normalize(query) {
    for (const [pattern, replacement] of aliases) query = query.replace(pattern, replacement);
    return query;
  }

  function classify(raw) {
    const query = normalize(raw);
    const normalized = query.toLowerCase();
    const matches = intents.filter(([pattern]) => pattern.test(query)).map(([, tag]) => tag);
    const matchedGradeRoutes = matches.filter((tag) => tag === "mid_sem_review" || tag === "end_sem_appeal");
    const broadGrade = matchedGradeRoutes.length > 1 || matches.includes("grade_review") || gradeHint.test(query);
    const gradeRoute = matchedGradeRoutes.length === 1 ? matchedGradeRoutes[0] : broadGrade ? "grade_review" : null;
    const advisor = matches.includes("escalation") || advisorHint.test(query);
    const academicRoutes = [
      ...matches.filter((tag) => tag === "supplementary_exam" || tag === "attendance_waiver"),
      gradeRoute,
      advisor && (advisorHint.test(query) || (!gradeRoute && matches.length === 1)) ? "escalation" : null,
    ].filter(Boolean);
    const outside = !academicRoutes.length && (matches.includes("hostel_admin") || outOfDomain.test(query));
    const sent = emailStatus(query);

    return {
      issues: academicRoutes,
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
    if (!state.tag) return {
      key: "tag",
      text: "What is the issue about?",
      lead: "Let’s figure out where to start.",
      choices: ISSUE_CHOICES,
    };
    if (state.tag === "grade_review" && !state.gradeAnswered) {
      return {
        key: "tag",
        text: "What are you trying to do about your grade?",
        lead: "Seeing an answer script and raising a final-grade concern go through different steps.",
        choices: GRADE_CHOICES,
      };
    }
    if (state.tag === "escalation" && !state.advisorAnswered) {
      return {
        key: "sent",
        text: "Have you already emailed your faculty advisor about this?",
        lead: "What you’ve tried so far changes who I’d suggest contacting.",
        choices: ADVISOR_CHOICES,
      };
    }
    if (
      !state.departmentAnswered && (state.tag === "attendance_waiver" || (state.tag === "escalation" && state.sent === true))
    ) {
      return {
        key: "department",
        text: "Which department office should I look up?",
        lead: "I can look up a phone number or office for your department.",
        choices: departments.map((name) => [name, name]).concat([["unknown", "I’m not sure"]]),
        dropdown: true,
      };
    }
    return null;
  }

  function interpretReply(state, prompt, raw) {
    const reply = raw.trim();
    const inferred = classify(reply);
    const allowed = (choice) => prompt.choices.some(([key]) => key === choice);
    let value = null;
    if (prompt.key === "department") {
      value = inferred.department ?? (UNSURE.test(reply) ? "unknown" : null);
    } else if (prompt.key === "sent") {
      value = inferred.sent === null
        ? (UNSURE.test(reply) ? "unknown" : /\b(?:i did|sent it|already tried)\b/i.test(reply) ? "yes" : null)
        : inferred.sent ? "yes" : "no";
    } else {
      value = inferred.tag;
      if (state.tag === "grade_review") {
        if (/\b(?:mid[- ]?sem(?:ester)?|answer script|see (?:my|the) (?:paper|script))\b/i.test(reply)) value = "mid_sem_review";
        if (/\b(?:end[- ]?sem(?:ester)?|final (?:grade|marks?|exam)|appeal)\b/i.test(reply)) value = "end_sem_appeal";
        if (value === "grade_review" && !UNSURE.test(reply)) value = null;
        if (UNSURE.test(reply)) value = "grade_review";
      } else if (value === "mid_sem_review" || value === "end_sem_appeal") {
        // Keep the procedure named in the reply, so the next turn can use it.
        const updated = answer(state, prompt, "grade_review", reply);
        return { ...updated, tag: value, gradeAnswered: true };
      }
      if (/^(?:something else|other|none of these)[.!]?$/i.test(reply)) value = "other";
    }
    return allowed(value) ? answer(state, prompt, value, reply) : null;
  }

  function answer(state, prompt, value, reply = "") {
    if (!prompt?.choices.some(([key]) => key === value)) throw new Error("Choose one of the available answers.");
    const updated = { ...remember(state, reply), turns: state.turns + 1 };
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

  function remember(state, reply) {
    const inferred = classify(reply);
    const department = inferred.department ?? state.department;
    const sent = (state.tag === "escalation" || /\b(?:email|mail|sent)/i.test(reply))
      ? inferred.sent ?? state.sent : state.sent;
    return {
      ...state, department, sent,
      degree_program: inferred.degree_program ?? state.degree_program,
      departmentAnswered: state.departmentAnswered || department !== null,
      advisorAnswered: state.advisorAnswered || sent !== null,
    };
  }

  function reframe(state, reply) {
    const inferred = classify(reply);
    const department = inferred.department;
    const contextChange = /\b(?:actually|correction|i(?: am|['’]m) in|(?:department|dept|branch) is|from|btech)\b/i.test(reply);
    const shortDepartment = department && reply.trim().split(/\s+/).length <= 4;
    if ((contextChange || shortDepartment) && department && department !== state.department) {
      return remember(state, reply);
    }
    if (state.tag === "escalation" && inferred.sent !== null && inferred.sent !== state.sent
        && !/^(?:what if|if|should|can|could|do i|would)/i.test(reply.trim())) {
      return { ...state, sent: inferred.sent, advisorAnswered: true };
    }
    const gradeTags = ["grade_review", "mid_sem_review", "end_sem_appeal"];
    if (gradeTags.includes(state.tag) && gradeTags.includes(inferred.tag) && inferred.tag !== "grade_review"
        && inferred.tag !== state.tag && /\b(?:actually|meant|rather|was)\b/i.test(reply)) {
      return { ...state, tag: inferred.tag, gradeAnswered: true };
    }
    if (inferred.tag && inferred.tag !== "other"
        && (!state.tag || state.tag === "other" || /^\s*(?:new question|different issue|switch to|can you also help with)\b/i.test(reply))) {
      return start(reply);
    }
    return null;
  }

  function planInput(state) {
    const { query, tag, department, degree_program, sent } = state;
    return {
      query, department, degree_program, sent,
      tag: tag && tag !== "other" ? tag : null,
    };
  }

  return { normalize, classify, start, question, answer, interpretReply, remember, reframe, planInput };
}
