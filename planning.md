# RulesBot — Planning Doc

Use this file to record your design decisions as you work through the lab.
There are no wrong answers — write enough that you could explain your reasoning to another group.

---

## Chunking Strategy

**Chunk size:** 300 characters (character-based sliding window).

**Overlap:** 50 characters between adjacent chunks. Minimum chunk length 50
chars (shorter segments are discarded as noise).

**Why this strategy fits rule book text:**
Rule books are semantically dense — a single rule is usually 1–3 sentences,
which fits comfortably in ~300 characters. Smaller windows would fragment
individual rules; larger ones would merge unrelated rules into one chunk and
blur retrieval. The 50-char overlap means a rule sitting on a chunk boundary
still appears intact in at least one chunk. Across the 8 rule books this
produced **149 chunks total** (16–23 per game), and chunk count tracked raw
document length almost exactly (~1 chunk per 250 chars = size − overlap),
which is the expected behaviour of a length-based splitter.

---

## Retrieval Observations

After implementing retrieval, try these test queries and record what comes back:

| Query | Top result game | Does it make sense? |
|-------|----------------|---------------------|
| "How do you win?" | Monopoly (0.507) | Loosely — generic phrasing; top 3 span Monopoly / Risk / Ticket to Ride (0.507–0.522), all plausible win-condition sources, none clearly dominant |
| "What happens when you roll a 7?" | Catan (0.466) | Yes — Catan is the only loaded game with a roll-a-7 / robber mechanic, so it leads cleanly |
| "Can two players share a route?" | Ticket to Ride (0.365) | Yes — strong match; all 3 results are Ticket to Ride |

**Anything surprising?**
How *specific* a query is matters more than how "easy" it sounds. The
game-specific queries ("roll a 7" → 0.466, "share a route" → 0.365) lock onto
one game with a low distance and a clear gap to the runner-up. The generic
"How do you win?" returns three *different* games clustered tightly at
0.507–0.522 — it matches everything weakly and nothing strongly. So vague
questions are the hard case for retrieval, not the obscure ones. The distance
gap between #1 and #2 is a better confidence signal than the absolute score.

---

## Response Quality

After implementing generation, try 2–3 questions and assess the answers:

| Query | Answer accurate? | Properly grounded? | Cited the right game? |
|-------|-----------------|-------------------|----------------------|
| "Can two players claim the same route in Ticket to Ride?" | Yes — explained no, but parallel routes are allowed | Yes — quoted the retrieved rule | Yes (Ticket to Ride) |
| "How does the Spymaster give clues in Codenames?" | Partial — context only had fragments, so it gave a partial answer and flagged the gap | Yes — didn't invent the full rule from memory | Yes (Codenames) |
| "What are the rules for chess?" | Correctly refused — chess isn't in the corpus | Yes — named the games it actually saw, recited nothing | N/A (no source) |

**What would you change about the prompt to improve grounding?**
Grounding itself held up well — the chess question was refused outright and
the Ticket to Ride answer quoted the rule. The weak spot is the *partial*
case (Codenames): when the retrieved chunks contain only fragments of a rule,
the model produces a half-answer with hedging rather than a clean "the loaded
rules don't fully cover this." I'd add an instruction that when the sources
only partially address the question, it should answer the part that's covered
and explicitly state which part is missing, instead of stitching the fragments
into something that reads more complete than it is. (Lower temperature already
helps keep answers extractive rather than inventive.)

