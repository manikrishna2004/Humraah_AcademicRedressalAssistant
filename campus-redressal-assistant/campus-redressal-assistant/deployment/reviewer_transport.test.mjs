import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createConversation } from "../web/conversation.js";
import { lookupPlan } from "./reviewer_transport.mjs";

const intake = JSON.parse(await readFile(process.argv[2], "utf8"));
const engine = createConversation(intake);
const start = (query, mode = "campus", topic) => engine.start(query, mode, topic);
const answer = (state, choice) => engine.answer(state, engine.question(state), choice);
const plan = (state) => lookupPlan(intake, engine.planInput(state));

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
  assert.equal(plan(unsure).contacts[0].role, "Course instructor");
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
  assert.equal(plan(answer(state, "yes")).contacts[0].role, "Department office");
  assert.equal(plan(answer(state, "no")).contacts[0].role, "Faculty advisor");
  assert.match(plan(answer(state, "unknown")).next_step, /If you haven't emailed/);

  const sent = start("My FA is not replying. I already emailed them.");
  assert.equal(engine.question(sent), null);
  assert.equal(plan(sent).contacts[0].role, "Department office");

  const notSent = start("My adviser is unresponsive, but I haven't emailed them.");
  assert.equal(engine.question(notSent), null);
  assert.equal(plan(notSent).contacts[0].role, "Faculty advisor");
});

test("a sample attendance topic asks for the department and returns a labeled discrepancy", () => {
  const first = start("Attendance waiver", "sample", "attendance_waiver");
  assert.equal(engine.question(first).key, "department");
  const state = answer(first, "Computer Science and Engineering");
  const result = plan(state);
  assert.match(result.contacts[0].email, /@example\.edu$/);
  assert.match(result.tips[0].text, /portal/);
  assert.match(result.notices[0].title, /different instructions/);
});

test("follow-ups stop at two and a hostel request receives the scoped fallback", () => {
  const first = start("I need some help", "sample");
  const advisor = answer(first, "escalation");
  const emailed = answer(advisor, "yes");
  assert.equal(engine.question(emailed), null);
  assert.equal(plan(emailed).supported, true);

  const outside = start("Can I swap my hostel room?");
  assert.equal(engine.question(outside), null);
  assert.equal(plan(outside).supported, false);
  assert.deepEqual(plan(outside).rules, []);
});
