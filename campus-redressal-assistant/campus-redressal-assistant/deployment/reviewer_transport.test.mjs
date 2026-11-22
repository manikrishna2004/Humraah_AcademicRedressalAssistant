import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import test from "node:test";
import { createConversation } from "../web/conversation.js";
import { lookupPlan, searchDirectory } from "./reviewer_transport.mjs";

const intake = JSON.parse(await readFile(process.argv[2], "utf8"));
const wasm = createRequire(import.meta.url)("./vendor/sql-wasm.js");
const SQL = await wasm();
const db = new SQL.Database(await readFile(join(dirname(process.argv[2]), "campus-directory.sqlite")));
const engine = createConversation(intake);
const start = (query, topic) => engine.start(query, topic);
const answer = (state, choice) => engine.answer(state, engine.question(state), choice);
const plan = (state) => lookupPlan(intake, db, engine.planInput(state));

test("vague academic intake asks the issue, then clarifies grades with no department gate", () => {
  const first = start("I have an academic issue and don't know whom to ask.");
  assert.equal(engine.question(first).text, "What is the issue about?");
  const second = answer(first, "grade_review");
  assert.equal(engine.question(second).key, "tag");
  const mid = answer(second, "mid_sem_review");
  assert.equal(engine.question(mid), null);
  assert.equal(plan(mid).issue, "Mid-sem answer script");
  assert.match(plan(mid).rules[0].label, /§30\.1\.3/);

  const end = answer(second, "end_sem_appeal");
  assert.equal(plan(end).issue, "End-sem grade concern");
  assert.match(plan(end).rules[0].label, /§30\.2/);
});

test("an identified marks concern asks about the procedure", () => {
  const state = start("My marks look wrong.");
  assert.deepEqual(engine.question(state).choices.map(([id]) => id), [
    "mid_sem_review", "end_sem_appeal", "grade_review",
  ]);
  const unsure = answer(state, "grade_review");
  assert.equal(engine.question(unsure), null);
  assert.equal(plan(unsure).contacts[0].role, "Your course instructor");
  assert.match(engine.question(start("My grades look wrong.")).text, /about your grade/);
});

test("a supplementary deadline goes straight to the cited plan", () => {
  const state = start("I missed the suppli form. Is there a late option?");
  assert.equal(engine.question(state), null);
  const result = plan(state);
  assert.equal(result.contacts[0].email, "arug@adm.iitkgp.ac.in");
  assert.ok(result.notices.some((notice) => notice.text.includes("item 9")));
  assert.ok(result.rules.every((rule) => rule.url.startsWith("https://")));
});

test("advisor follow-up selects the contact and handles details already provided", () => {
  const state = start("My FA hasn't replied.");
  assert.match(engine.question(state).text, /already emailed/);
  assert.equal(plan(answer(state, "yes")).contacts[0].role, "Your department office");
  assert.equal(plan(answer(state, "no")).contacts[0].role, "Your assigned faculty advisor");
  assert.match(plan(answer(state, "unknown")).next_step, /If you haven't emailed/);

  const sent = start("My FA is not replying. I already emailed them. I am in CSE.");
  assert.equal(engine.question(sent), null);
  assert.equal(plan(sent).contacts[0].email, "cseoffi@cse.iitkgp.ac.in");

  const notSent = start("My adviser is unresponsive, but I haven't emailed them.");
  assert.equal(engine.question(notSent), null);
  assert.equal(plan(notSent).contacts[0].role, "Your assigned faculty advisor");
});

test("attendance asks for a department and returns its real office and labeled examples", () => {
  const first = start("Attendance waiver", "attendance_waiver");
  assert.equal(engine.question(first).key, "department");
  const state = answer(first, "Computer Science and Engineering");
  const result = plan(state);
  assert.equal(result.contacts[1].email, "cseoffi@cse.iitkgp.ac.in");
  assert.match(result.contacts[1].url, /comdir\.pdf#page=32/);
  assert.equal(result.tips[0].label, "Prototype example");
});

test("search runs on the deployed SQLite file and preserves unknown visiting hours", () => {
  const contacts = searchDirectory(db, intake.directory, "");
  assert.equal(contacts.length, 17);
  assert.equal(contacts.filter((entry) => entry.kind === "department" && entry.department !== "General").length, 7);
  const [me] = searchDirectory(db, intake.directory, "ME");
  assert.equal(me.phone, "+91 3222 282277");
  assert.equal(me.office_hours, null);
  assert.equal(searchDirectory(db, intake.directory, "SETU")[0].office_hours, "Mon–Fri, 10 am–1 pm and 4–8 pm IST");
  assert.deepEqual(searchDirectory(db, intake.directory, "missing office name"), []);
});

test("follow-ups stop at two and a hostel request receives the scoped fallback", () => {
  const first = start("I need some help");
  const advisor = answer(first, "escalation");
  const emailed = answer(advisor, "yes");
  assert.equal(engine.question(emailed), null);
  assert.equal(plan(emailed).supported, true);

  const outside = start("Can I swap my hostel room?");
  assert.equal(engine.question(outside), null);
  assert.equal(plan(outside).supported, false);
  assert.deepEqual(plan(outside).rules, []);
});

test("typed clarification picks the office from an entire reply", () => {
  const first = start("My faculty advisor isn't replying.");
  const second = engine.interpretReply(first, engine.question(first), "I sent an email yesterday. I'm in CSE.");
  assert.equal(second.sent, true);
  assert.equal(engine.question(second), null);
  assert.equal(plan(second).contacts[0].email, "cseoffi@cse.iitkgp.ac.in");
  assert.equal(engine.interpretReply(first, engine.question(first), "What times?"), null);
});

test("typed topic reply keeps a specific grade procedure and remembers department", () => {
  const first = start("I'm dealing with an academic problem.");
  const context = engine.remember(first, "I'm from CSE.");
  const second = engine.interpretReply(context, engine.question(context), "I want to see my mid sem script.");
  assert.equal(second.department, "Computer Science and Engineering");
  assert.equal(engine.question(second), null);
  assert.equal(plan(second).issue, "Mid-sem answer script");
});

test("a later correction updates the existing contact without changing the issue", () => {
  const first = start("My CSE faculty advisor hasn't replied. I already sent an email.");
  const second = engine.reframe(first, "Actually I’m in Mechanical Engineering.");
  assert.equal(second.query, first.query);
  assert.equal(second.tag, first.tag);
  assert.equal(plan(second).contacts[0].email, "mechoffice@mech.iitkgp.ac.in");
  assert.equal(engine.reframe(first, "What if I haven't emailed yet?"), null);
});

test("the companion drafts a useful email and grounds visit and deadline replies", async () => {
  const { respond, suggestions } = await import("../web/companion.js");
  const state = start("I missed the suppli deadline.");
  const result = plan(state);
  const email = respond("What should I email them?", state, result);
  assert.match(email.draft, /Subject: Supplementary registration/);
  assert.match(email.text, /Academic Section/);
  assert.match(respond("Can I go in person?", state, result).text, /Main Building.*confirm/);
  assert.ok(respond("Where is the deadline?", state, result).links.some(({ url }) => url.includes("academic-calendar")));
  assert.ok(suggestions(state, result).includes("Help me write the email"));
});

test("model composition accepts cited policy text and rejects invented wording and contacts", async () => {
  const { composeFromClaims } = await import("../web/grounding.js");
  const guidance = plan(start("I missed my supplementary exam form deadline"));
  const policy = guidance.rules[0];
  const contact = guidance.contacts[0];
  const selected = { transition: "context", claim_ids: [policy.claim_id] };
  assert.deepEqual(composeFromClaims(selected, guidance.rules).links, [{ label: policy.label, url: policy.url }]);
  assert.ok(composeFromClaims(selected, guidance.rules).text.endsWith(policy.text));
  assert.equal(composeFromClaims({ ...selected, text: "Visit in Room 123 at 4 PM" }, guidance.rules), null);
  assert.equal(composeFromClaims({ ...selected, claim_ids: [contact.claim_id] }, [...guidance.rules, contact]), null);
  assert.equal(composeFromClaims({ ...selected, claim_ids: ["made-up"] }, guidance.rules), null);
});

test("model interpretation receives normalized campus slang and ignores ungrounded dates", async () => {
  const { createTurnEngine } = await import("../web/turn-engine.js");
  const { suggestInterpretation, mergeInterpretations, composeGuidance } = await import("../web/model-adapter.js");
  const turnEngine = createTurnEngine(intake);
  const original = globalThis.fetch;
  const text = "FA, suppli, HOD, DUGC";
  const normalized = turnEngine.normalize(text);
  const rules = turnEngine.interpret(null, { text });
  const candidate = {
    ...rules, deadline: { raw: "tomorrow at 3 pm", urgent: true }, department: "Electrical Engineering",
  };
  try {
    globalThis.fetch = async (_url, options) => {
      const input = JSON.parse(JSON.parse(options.body).messages[0].content);
      assert.match(input.text, /Faculty Advisor, supplementary exam, head of department, department undergraduate committee/);
      return Response.json({ content: [{ type: "text", text: JSON.stringify(candidate) }] });
    };
    const proposal = await suggestInterpretation({ key: "test-key", id: "test-model" }, intake, null, normalized, {});
    assert.deepEqual(proposal, candidate);
    const parsed = mergeInterpretations(rules, proposal, normalized);
    assert.equal(parsed.deadline, null);
    const change = turnEngine.transition(null, { text }, parsed, rules);
    assert.deepEqual(change.state.department, { value: "Electrical Engineering", source: "inferred" });
    globalThis.fetch = async () => { throw new Error("provider unavailable"); };
    assert.equal(await suggestInterpretation({ key: "test-key", id: "test-model" }, intake, null, normalized, {}), null);
    assert.equal(await composeGuidance({ key: "test-key", id: "test-model" }, plan(start("suppli")), "supplementary_exam"), null);
  } finally {
    globalThis.fetch = original;
  }
});
