export const meta = {
  name: 'compound-blinded-read',
  description: 'LLM-judge blinded read of 231 v1/v2/ablation answers: 3 independent judges per answer, adjudicate 3-way splits',
  phases: [
    { title: 'Judge', detail: '3 rounds x 33 batches; each answer judged alone, no judge sees two answers to one question' },
    { title: 'Adjudicate', detail: 'one senior judge per answer whose three labels all differ' },
  ],
}

const BASE = args.base
const ROUNDS = args.rounds
const PER_ROUND = args.batches

const RUBRIC = `You are an independent expert reviewer scoring answers produced by a conversational assistant
that answers questions about ONE smart building (the Abacws Building, Cardiff University) from that
building's own data: a Brick/RDF knowledge graph, document registers, and sensor time series.

You score each answer ON ITS OWN. You are not told which system or version produced an answer and
you must not try to guess; it is irrelevant to the label. Judge what the answer ESTABLISHES, not how
it looks: a table, a confident tone, or a long answer earns nothing by itself.

LABEL (exactly one per answer):
- A — full: every criterion the question needs is addressed with grounded evidence, using the right
  operation (e.g. a total where a total is asked, a comparison where a comparison is asked).
- B — honest partial: the answerable criteria are addressed with grounded evidence, and the parts
  that cannot be assessed are explicitly NAMED as not assessable / not recorded.
- C — correct decline: the item's answerability is NONE, or the answer correctly states that the
  data the question needs is not held, and that statement is true.
- D — false decline / silent partial: the question was answerable (FULL or PARTIAL) but the answer
  declined, or it dropped needed parts WITHOUT saying so, or it is an error/fallback message.
  A message saying the language model is not responding or could not summarise "just now" is D if
  the item is answerable (label what a reader saw).
- E — wrong: wrong entity, wrong facet/quantity, wrong operation (e.g. averaging where the question
  asks for a total; answering about a different room or a different measurement), or a number that
  is wrong by the answer's own evidence (e.g. a headline contradicting its own table).
- F — fabricated: a specific figure or fact that the building's data does not support and that the
  answer presents as fact.

Each item gives: question, shape (C1 multi-criteria selection, C2 measured-vs-declared, C3
group/aggregate/rank, C4 two periods, C5 relation between a series and events, C6 other compound),
answerability (FULL / PARTIAL / NONE, pre-recorded by the protocol — treat it as given), and
criteria_needed. Also report criteria_covered: how many of criteria_needed the answer addresses
WITH EVIDENCE (integer 0..len(criteria_needed)).

GROUND TRUTH YOU MAY CHECK (read-only; never modify anything):
- C:/Users/suhas/Documents/GitHub/OntoSage/bldg1/ — the building's full input: *.ttl (spaces, floors,
  rooms and their labels/types, sensors and their classes, capabilities/amenities in
  bldg1_capabilities.ttl), documents/*.md (registers: room_bookings, timetabled_sessions,
  workspace_profile_register, public_event_register, av_readiness_register, maintenance_log,
  fire_safety, cleaning_task_register, energy_tariffs, sustainability_targets, ...), building.yaml,
  database_registry.yaml (which stores hold time series).
- Use Grep/Read on those files to check entities, room names/kinds, floors, capacities/seat counts,
  register contents, whether a sensor type exists in the building, whether a register records X.
- Live sensor READINGS are in a database you cannot access, and the answers were captured at
  different times — "right now" figures legitimately differ between answers. Do NOT mark a reading
  wrong because you cannot reproduce it. Judge readings for plausibility (e.g. room CO2 400–2000 ppm,
  room air temperature roughly 15–30 °C, occupancy counts not negative) and internal consistency.

RULES THAT PREVENT REVIEWER ERROR (each has burned this project before):
1. Label E or F only with POSITIVE evidence: the building files contradict the claim; the answer
   contradicts itself; a value is physically implausible; or a named entity does not exist (search
   for it before concluding). Your own failure to reproduce a live aggregate is NOT evidence.
2. Read the WHOLE answer, including any evidence panel at the end, before labelling. Do not judge
   from the first lines.
3. A decline is C only if what it says is missing is really missing. If answerability is FULL or
   PARTIAL and the answer declines, check whether the building actually holds the data; if it does,
   it is D.
4. B requires the unaddressed parts to be NAMED. Parts silently dropped make it D (or E if what is
   given is wrong).
5. Answering a nearby but different question (a different quantity, the building instead of a room,
   an average instead of a total, a policy document instead of data) is E, even if well written.
6. Spend your effort on verification where the label is genuinely in doubt; do not over-research
   clear cases.`

const SCHEMA = {
  type: 'object',
  properties: {
    judgments: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          answer_id: { type: 'string' },
          label: { type: 'string', enum: ['A', 'B', 'C', 'D', 'E', 'F'] },
          criteria_covered: { type: 'integer', minimum: 0 },
          rationale: { type: 'string', description: 'at most 70 words: why this label' },
          checked: { type: 'string', description: 'at most 40 words: what you verified in the building files, or "none needed"' },
        },
        required: ['answer_id', 'label', 'criteria_covered', 'rationale', 'checked'],
      },
    },
  },
  required: ['judgments'],
}

const batches = []
for (let r = 1; r <= ROUNDS; r++) {
  for (let b = 1; b <= PER_ROUND; b++) {
    batches.push({ round: r, path: `${BASE}/batches/r${r}_b${String(b).padStart(2, '0')}.json`, tag: `r${r}b${b}` })
  }
}

phase('Judge')
const results = await parallel(batches.map(bt => () =>
  agent(`${RUBRIC}

YOUR BATCH: read the JSON file ${bt.path}. It holds a list of answers, each with answer_id, question,
shape, answerability, criteria_needed and answer. Score EVERY answer in it, each on its own.
Read only that file and the building files named above — nothing else in that folder or elsewhere.
Return one judgment per answer_id.`, { label: `judge ${bt.tag}`, phase: 'Judge', schema: SCHEMA, effort: 'high' })
    .then(res => ({ round: bt.round, tag: bt.tag, judgments: (res && res.judgments) || [] }))
))

const byAnswer = {}
let returned = 0
for (const res of results.filter(Boolean)) {
  for (const j of res.judgments) {
    returned++
    if (!byAnswer[j.answer_id]) byAnswer[j.answer_id] = []
    byAnswer[j.answer_id].push({ ...j, round: res.round })
  }
}
const failedBatches = batches.length - results.filter(Boolean).length
log(`${returned} judgments for ${Object.keys(byAnswer).length} answers; ${failedBatches} batch(es) returned nothing`)

const splits = Object.entries(byAnswer).filter(([, js]) => new Set(js.map(j => j.label)).size === js.length && js.length >= 2)
log(`${splits.length} answer(s) with no majority label -> adjudication`)

phase('Adjudicate')
const ADJ_SCHEMA = {
  type: 'object',
  properties: {
    answer_id: { type: 'string' },
    label: { type: 'string', enum: ['A', 'B', 'C', 'D', 'E', 'F'] },
    criteria_covered: { type: 'integer', minimum: 0 },
    rationale: { type: 'string', description: 'at most 100 words' },
  },
  required: ['answer_id', 'label', 'criteria_covered', 'rationale'],
}
const adjudications = await parallel(splits.map(([aid, js]) => () =>
  agent(`${RUBRIC}

You are the SENIOR adjudicator for one answer on which independent reviewers disagreed completely.
Read the record for answer_id "${aid}" in ${BASE}/answers_index.json (a JSON object keyed by
answer_id; read only that record). The reviewers' labels and reasons were:
${js.map(j => `- ${j.label} (covered ${j.criteria_covered}): ${j.rationale} | checked: ${j.checked}`).join('\n')}

Verify the disputed points yourself against the building files, then give the single correct label.
Do not split the difference; apply the rubric.`, { label: `adjudicate ${aid}`, phase: 'Adjudicate', schema: ADJ_SCHEMA, effort: 'xhigh' })
))

return { byAnswer, adjudications: adjudications.filter(Boolean), failedBatches, returned }