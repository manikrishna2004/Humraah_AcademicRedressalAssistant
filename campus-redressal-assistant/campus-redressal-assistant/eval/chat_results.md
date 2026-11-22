# Humraah held-out chat evaluation

These six conversations were written separately from the indexed policies
and synthetic senior tips. The evaluator sends ordinary text through
`/api/chat/turn` and checks the question, resulting action, contact source and
whether any correction continues to the next turn.

| Conversation | Expected behavior | Observed behavior | Turns to action |
| --- | --- | --- | ---: |
| “My FA hasn’t replied and the suppli form closes soon” | Prioritize the registration deadline and keep the advisor issue open. | The plan linked ERP and the UG Academic Section, retained the faculty advisor route and asked the student to confirm the deadline. | 1 |
| “I’m worried about my grade” | Ask one question that distinguishes an appeal, an error or a low result. | The app asked what the concern was. A typed final-grade appeal led to §30.2 of the UG rules, which the citation identifies as applying through the 2023 admissions cohort. | 2 |
| “Actually, I’m in EE” after a plan for CSE | Replace the department contact immediately and retain it. | The CSE office changed to the Electrical Engineering office, with its published phone number. The next contact reply also used EE. | 2 |
| “Emailed my advisor 5 days ago, nothing” | Reuse the advisor issue, provide a draft and show the department escalation route. | The draft referenced the original email thread and linked to the CSE office and directory entry. | 2 |
| “Does a supplementary registration require a head of department signature?” | Show the conflicting instructions and the office that can clarify them. | The reply cited handbook items 9 and 17, the ERP workflow and the UG rules, with the Academic Section directory link for confirmation. | 1 |
| “Where do I go and when?” after a supplementary plan | Give the office, a published contact channel and what to ask about missing hours. | The reply gave the Institute Main Building and a phone link, and suggested calling to confirm the counter, floor and visiting hours. | 2 |

The conflict case uses an actual discrepancy between clauses in the same
handbook. The directory supports the office referral. All six cases passed
against FastAPI and the local Worker with SQLite. These are behavior checks
for six scenarios. Adoption, user satisfaction and general accuracy require
separate measurements.
