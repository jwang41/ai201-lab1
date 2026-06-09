# Spec: `generate_response()`

**File:** `generator.py`
**Status:** Spec incomplete — fill in all blank fields before implementing

---

## Purpose

Given a user query and a list of retrieved rule chunks, generate a response that directly answers the question using only the retrieved text as context. The response must be grounded — it should not draw on the model's general knowledge of board games, only on what was retrieved.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The user's original question |
| `retrieved_chunks` | `list[dict]` | Ranked list of chunks from `retrieve()`, each with `"text"`, `"game"`, and `"distance"` |

**Output:** `str`

A plain string containing the response to show the user. The response should:
- Answer the question using only the retrieved rule text
- Identify which game the answer comes from
- Acknowledge clearly when the answer is not found in the loaded rules

Returns a fallback string (not an error) when `retrieved_chunks` is empty.

---

## Design Decisions

*Complete the fields below before writing any code. Use your AI tool in Plan or Ask mode to help you reason through what belongs here — but the decisions are yours.*

---

### Context formatting

*How will you format the retrieved chunks before passing them to the LLM? Describe the structure — not the code. Consider: will you label chunks by game? Include distance scores? Separate chunks with delimiters?*

```
Build one labelled, delimited context block from the ranked chunks, in
the order retrieve() returned them (most relevant first). Each chunk is
rendered as a small section:

  [Source 1 — Catan]
  <chunk text>

  [Source 2 — Catan]
  <chunk text>

  [Source 3 — Uno]
  <chunk text>

Decisions:
  - LABEL each chunk with its game. This is what lets the model cite the
    right game, and it makes a mixed-game result set (e.g. "how do you
    win?") unambiguous — the model can see Source 1 is Catan, Source 3
    is Uno, and answer per game instead of blending them.
  - A numbered "Source N" header per chunk gives the model a stable
    handle to reference and a clear delimiter between chunks, so two
    adjacent rules don't read as one run-on passage.
  - DO NOT include distance scores. They're an internal ranking signal,
    not meaningful to the model, and a raw "0.62" could confuse it or
    leak into the answer. Order already encodes relevance.
```

---

### System prompt — grounding instruction

*Write the exact system prompt instruction you will use to prevent the model from answering beyond the retrieved text. This is the most important design decision in this function.*

```
Exact instruction:

"You are RulesBot, a board-game rules assistant. Answer the user's
question using ONLY the information in the SOURCES provided below. The
sources are excerpts from official rule books. Do not use any outside
knowledge of these games, and do not guess or infer rules that are not
stated in the sources, even if you think you know the answer. If the
sources do not contain enough information to answer the question, say so
plainly using the fallback wording rather than filling the gap from
memory. A short, honest 'the rules I have don't cover that' is always
better than a confident answer that isn't supported by the sources."

Why this wording:
  - "ONLY ... SOURCES" + "do not use outside knowledge" is the core
    grounding clamp.
  - It explicitly forbids inference ("even if you think you know"),
    because the failure mode for a 70B model on famous games like
    Monopoly is confidently reciting rules from training data.
  - It names the escape hatch (fallback) so the model has a sanctioned
    action when context is weak — this is the prompt-side half of the
    no-threshold decision in retrieve-spec: weak chunks get passed in,
    and THIS instruction is what stops them being over-trusted.
```

---

### System prompt — citation instruction

*Write the exact instruction you will use to tell the model to identify which game its answer comes from.*

```
Exact instruction:

"Each source is labelled with the game it comes from (e.g.
'[Source 1 — Catan]'). State which game your answer is about at the
start of your response, e.g. 'In Catan, ...'. If the relevant sources
come from more than one game, answer each game separately and label
each clearly, rather than blending rules from different games into one
answer."

Why:
  - Ties citation to the labels created in the context-formatting step,
    so the model has a concrete field to read from rather than guessing.
  - The multi-game clause directly handles retrieve()'s edge case (c):
    a query like "how do you win?" returns Monopoly + Risk + Ticket to
    Ride chunks, and we want three labelled mini-answers, not a mashed-
    together one.
```

---

### Fallback behavior

*What should the response say when the answer isn't found in the loaded rule books? Write the exact fallback message.*

```
There are two distinct "not found" situations, with two messages:

(1) retrieve() returned NOTHING (empty list — e.g. empty collection).
    This is handled in code before any LLM call, using the message
    already in generator.py:

    "I couldn't find anything relevant in the loaded rule books. Try
     rephrasing your question — or check that your ingestion pipeline
     is working."

(2) Chunks WERE retrieved, but they don't actually answer the question
    (weak/off-topic matches). The LLM produces this, instructed via the
    grounding prompt to use a consistent phrasing:

    "I couldn't find that in the rules I have for [game(s) in context].
     The loaded rule books don't seem to cover this, so I'd rather not
     guess. You could try rephrasing, or it may be a rule that isn't in
     the summaries I was given."

Both keep the same honest tone: name the limitation, don't fabricate,
and nudge the user toward a rephrase. Case (2) is a soft refusal phrased
by the model, not a hard string, so it can name the game(s) it did see.
```

---

### Handling low-relevance chunks

*`retrieved_chunks` may include chunks with high distance scores (weak relevance). Will you filter these out before building context, pass them all in, or handle them another way? What are the tradeoffs?*

```
Decision: pass ALL retrieved chunks into the context, and let the
grounding prompt — not a distance cutoff — decide whether they're good
enough to answer from. This mirrors the no-threshold choice in
retrieve-spec; the responsibility was deliberately handed here.

Tradeoffs:
  Pass all in (chosen):
    + No tuned magic number; robust across phrasings; the one chunk that
      mattered is never silently dropped.
    + A weak top result simply leads the model to the fallback, which is
      the behaviour we want.
    - Slightly more (sometimes irrelevant) text in the prompt; relies on
      the prompt being strong enough that the model ignores noise instead
      of latching onto a loose match. The grounding instruction is
      written precisely to do this.
  Filter by distance here:
    + Cleaner prompt.
    - Reintroduces the brittle cutoff we rejected; risks empty context
      and a needless fallback on a question the rules actually cover.

Practical note: with N_RESULTS = 3 the context is tiny regardless, so
there's no token-budget pressure pushing toward filtering.
```

---

### Message structure

*Describe how you will structure the messages list for the API call — what goes in the system message vs. the user message?*

```
Two messages, system + user:

  system:  RulesBot identity + the grounding instruction + the citation
           instruction + fallback wording. These are stable rules of
           behaviour that don't change per request, so they belong in
           the system role where the model weights them most heavily.

  user:    the formatted SOURCES block followed by the actual question,
           e.g.

             SOURCES:
             [Source 1 — Catan]
             ...
             [Source 2 — Catan]
             ...

             QUESTION:
             What happens if you roll a 7 in Catan?

Why this split:
  - Behaviour/policy (how to answer, when to refuse, how to cite) is
    request-independent -> system. Data (the retrieved context + this
    specific question) is request-specific -> user.
  - Putting the context in the user turn frames it as "here is the
    material for THIS question," which keeps the model from treating the
    rules as standing instructions.
  - Call: _client.chat.completions.create(model=LLM_MODEL,
    messages=[system, user], temperature low — ~0.2 — since we want
    faithful extraction, not creative writing). Return
    response.choices[0].message.content.
```

---

## Implementation Notes

*Fill this in after implementing and testing.*

**Test query and response:**

```
Query: What happens if you roll a 7 in Catan?
Response (abbreviated): "In Catan, when a 7 is rolled... no resources
  are produced; every player with more than 7 resource cards discards
  half (rounded down); the roller moves the robber and steals one
  resource from another player."
Correctly grounded? yes — matched the retrieved Catan rule text; did
  NOT pull in the irrelevant Uno chunk (distance 0.625) that was also
  in context.
Cited the right game? yes — opened with "In Catan, ...".

Grounding stress test: "How many players can play chess on this board?"
  retrieved only Pandemic/Monopoly chunks (no chess anywhere in the
  corpus). Response refused: "I couldn't find any information about
  chess in the rules I have for Pandemic or Monopoly..." — it did NOT
  recite chess rules from training data, which is the whole point.
```

**One thing you changed from your original spec after seeing the actual output:**

```
Nothing structural changed — the spec held up. The notable confirmation
was that passing the weak Uno chunk (0.625) into context alongside the
two Catan chunks did NOT pollute the answer: the grounding instruction
was strong enough that the model used only the on-topic sources and
ignored the loose match. That was the central bet of the no-threshold
design (retrieve passes everything, the prompt filters), and seeing it
hold in practice was the main payoff.

If anything to tighten later: the system prompt's fallback example uses
"[game(s) in context]" as a literal placeholder. The model substituted
it correctly ("...for Pandemic or Monopoly"), but a future revision
could state more explicitly that it should name the games rather than
echo the bracketed token, to remove any chance of it being copied
verbatim.
```
