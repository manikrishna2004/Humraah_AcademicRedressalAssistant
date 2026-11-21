import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createReviewerTransport } from "./reviewer_transport.mjs";

const data = JSON.parse(await readFile(process.argv[2], "utf8"));

async function guidance(request, query, mode = "campus") {
  const result = await request("/api/guidance", {
    method: "POST",
    body: JSON.stringify({ query, mode }),
  });
  assert.equal(result.status, 200);
  return result.json();
}

async function answer(request, prior, option) {
  return request(`/api/guidance/${prior.session}/answer`, {
    method: "POST",
    body: JSON.stringify({ turn: prior.turn, answer: option }),
  });
}

test("a free-text supplementary exam question returns the campus citations and conflict", async () => {
  const result = await guidance(createReviewerTransport(data), "I missed the suppli form. Is there a late option?");
  assert.equal(result.kind, "plan");
  assert.equal(result.issue, "Supplementary exam");
  assert.equal(result.contacts[0].email, "arug@adm.iitkgp.ac.in");
  assert.ok(result.rules.every((rule) => rule.url.startsWith("https://")));
  assert.ok(result.notices.some((notice) => notice.text.includes("item 9")));
  assert.deepEqual(result.tips, []);
});

test("a grade follow-up keeps only the chosen procedure", async () => {
  const request = createReviewerTransport(data);
  const initial = await guidance(request, "How do I request a marks review in comp sci?");
  assert.equal(initial.kind, "clarification");
  assert.deepEqual(initial.choices.map((choice) => choice.value), ["mid_sem_review", "end_sem_appeal"]);
  const submitted = await answer(request, initial, "mid_sem_review");
  assert.equal(submitted.status, 200);
  const result = await submitted.json();
  assert.equal(result.issue, "Mid-sem answer script");
  assert.equal(result.rules.length, 1);
  assert.match(result.rules[0].label, /§30\.1\.3/);
  assert.equal((await answer(request, initial, "end_sem_appeal")).status, 404);
});

test("the sample attendance plan shows the sample field-specific contact and discrepancy", async () => {
  const request = createReviewerTransport(data);
  const initial = await guidance(request, "How do I get an attendance waiver after missing classes?", "sample");
  assert.deepEqual(initial.fields.map((field) => field.key), ["department", "degree_program"]);
  assert.equal((await answer(request, initial, { department: "N/A" })).status, 422);
  const response = await answer(request, initial, {
    department: "Computer Science and Engineering",
    degree_program: "UG 4-Year B.Tech",
  });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.match(result.contacts[0].email, /@example\.edu$/);
  assert.ok(result.tips.length);
  assert.match(result.notices[0].title, /different instructions/);
});

test("multiple advisor follow-ups stay in one session and choose the escalation role", async () => {
  const request = createReviewerTransport(data);
  const first = await guidance(request, "My adviser hasn't replied to my message");
  const second = await (await answer(request, first, {
    department: "Mechanical Engineering",
    degree_program: "UG 4-Year B.Tech",
  })).json();
  assert.equal(second.session, first.session);
  assert.equal(second.turn, 2);
  assert.equal((await answer(request, first, "yes")).status, 409);
  const result = await (await answer(request, second, "yes")).json();
  assert.equal(result.contacts[0].role, "Department office");
  assert.ok(result.rules.length);
});

test("an unsupported question produces a scoped fallback without a policy or contact", async () => {
  const result = await guidance(createReviewerTransport(data), "Can I swap my hostel room?");
  assert.equal(result.supported, false);
  assert.deepEqual(result.rules, []);
  assert.deepEqual(result.contacts, []);
});
