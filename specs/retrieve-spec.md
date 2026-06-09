# Spec: `retrieve()`

**File:** `retriever.py`
**Status:** Spec incomplete — fill in all blank fields before implementing

---

## Purpose

Given a user's natural language query, find the most relevant chunks from the vector store using semantic similarity search. Return them ranked by relevance so that `generate_response()` can use them as context.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | `str` | The user's natural language question |
| `n_results` | `int` | Maximum number of chunks to return (default: `N_RESULTS` from `config.py`) |

**Output:** `list[dict]`

Each dict in the returned list must contain exactly these keys:

| Key | Type | Description |
|-----|------|-------------|
| `"text"` | `str` | The chunk text |
| `"game"` | `str` | The game name this chunk came from |
| `"distance"` | `float` | Cosine distance score — lower means more similar to the query |

Results should be ordered from most to least relevant (lowest to highest distance). Returns an empty list `[]` if the collection contains no documents.

---

## Design Decisions

*Complete the fields below before writing any code. Use your AI tool in Plan or Ask mode to help you reason through what belongs here — but the decisions are yours.*

---

### Query approach

*Describe how you will use `_collection.query()` to find relevant chunks. What arguments will you pass, and why?*

```
Call _collection.query() with three arguments:

  query_texts=[query]
    A list holding the single user question, passed as raw text (not a
    vector). The collection was created with a SentenceTransformer
    embedding function, so ChromaDB embeds the query with the SAME
    all-MiniLM-L6-v2 model used at ingestion. That symmetry is essential
    — query and chunks must share a vector space for cosine distance to
    be meaningful. It's a list because the API supports batch queries; I
    have one, so one element.

  n_results=n_results
    Caps the number of chunks returned (default N_RESULTS = 3 from
    config.py). ChromaDB returns the k nearest neighbours already sorted
    closest-first, which directly satisfies the "most to least relevant"
    ordering requirement — no manual sorting needed. 3 balances enough
    grounding context for generate_response() against keeping the LLM
    prompt small and free of marginally-relevant rules.

  include=["documents", "metadatas", "distances"]
    Requests exactly the three pieces the return contract needs:
      documents  -> "text"     (the chunk body)
      metadatas  -> "game"     (from the {"game": ...} dict set at ingestion)
      distances  -> "distance" (cosine score; lower = more similar)
    "embeddings" is deliberately omitted — the raw vectors aren't needed
    and excluding them keeps the payload small. "ids" isn't in the
    contract, so it's not requested either.
```

---

### Return structure

*Sketch out what one item in your return list looks like as a concrete example. Where does each field come from in the query results?*

```
One returned item, for the query "What happens if you roll a 7 in Catan?":

  {
      "text": "When a player rolls a 7, no one collects resources. Any "
              "player with more than 7 resource cards must discard half "
              "(rounded down). Then the roller moves the robber...",
      "game": "Catan",
      "distance": 0.41,
  }

Each field is read from the [0] slice of the query result and zipped
together by position:
  "text"     <- results["documents"][0][i]
  "game"     <- results["metadatas"][0][i]["game"]   (the key stored at
                ingestion in embed_and_store)
  "distance" <- results["distances"][0][i]

The three inner lists are parallel — index i refers to the same chunk
across all of them — so a single loop (or zip) over them builds the
output dicts in the order ChromaDB already ranked them.
```

---

### Handling the nested result structure

*`_collection.query()` returns nested lists. Describe what index you need to access to get the actual list of results for a single query, and why the nesting exists.*

```
Access index [0]. query() is built for BATCH queries: query_texts can
hold many questions, so every returned field is a list-of-lists —
the outer list has one entry per query, and each inner list holds that
query's results. The shape is:

  results["documents"]  == [ [chunk, chunk, chunk] ]   # one outer entry
  results["metadatas"]  == [ [meta,  meta,  meta ] ]
  results["distances"]  == [ [0.41,  0.55,  0.63 ] ]

I send exactly one query, so the outer list always has length 1 and the
data I want lives at [0]:

  docs   = results["documents"][0]
  metas  = results["metadatas"][0]
  dists  = results["distances"][0]

Forgetting the [0] is the classic bug here — you'd iterate over a
one-element list of lists instead of over the chunks themselves.
```

---

### Relevance threshold

*Will you filter out results above a certain distance score, or return all `n_results` regardless of how relevant they are? What are the tradeoffs of each approach?*

```
Decision: return all n_results from retrieve() WITHOUT a distance filter,
and let generate_response() decide whether the context actually answers
the question.

Why no threshold here:
  - Cosine distances from MiniLM are not calibrated to an absolute "good
    vs. bad" cutoff — a relevant rule might score 0.4 for one phrasing
    and 0.6 for another. A hard threshold (e.g. drop > 0.5) risks
    silently discarding the only relevant chunk and returning [], which
    looks identical to "no rule exists."
  - The spec's contract is about relevance ORDER, not filtering. Keeping
    retrieve() purely about ranking keeps responsibilities clean.

Tradeoffs of each approach:
  Return all n_results (chosen):
    + Never starves the generator of context; simple and predictable.
    - May pass weakly-related chunks; the LLM must be instructed to say
      "the rules don't cover that" rather than hallucinate from a loose
      match.
  Filter by distance:
    + Cleaner context, and an empty result is a strong "I don't know"
      signal.
    - Requires a tuned, game-agnostic cutoff that doesn't really exist;
      brittle across phrasings; can drop the one chunk that mattered.

Grounding against weak matches is therefore handled in the prompt
(generate-response-spec), not by dropping rows in retrieve().
```

---

### Edge cases

*How does your implementation behave when: (a) the collection is empty, (b) the query matches no chunks well, (c) the query matches chunks from multiple games?*

```
(a) Empty collection:
    Guarded up front — the existing `if _collection.count() == 0: return []`
    check runs before query(), so an un-ingested store returns [] cleanly
    instead of erroring. generate_response() then sees no context and
    should reply that no rules are loaded.

(b) Query matches nothing well (e.g. "what's the weather today?"):
    query() still returns the n_results nearest neighbours — nearest is
    not the same as relevant — so the distances come back high (loosely,
    ~0.8+). Because retrieve() does not threshold, these weak chunks are
    returned. The high distance is the signal; grounding the answer is
    the generator's job (instructed to refuse when the context doesn't
    address the question). The distance scores remain available downstream
    if a later milestone wants to act on them.

(c) Query matches multiple games (e.g. "how do you win?"):
    Entirely expected and fine. ChromaDB ranks purely by vector
    similarity and ignores the game metadata, so the result list can mix
    games — e.g. a Catan chunk at 0.45 and a Risk chunk at 0.48. Each
    returned dict carries its own "game" field, so downstream code (and
    the LLM) can attribute or disambiguate per chunk. There is no
    per-game filtering unless a future milestone adds a metadata `where`
    clause.
```

---

## Implementation Notes

*Fill this in after implementing, before moving to Milestone 3.*

**Test query and top result returned:**

```
Query: What happens if you roll a 7 in Catan?
Top result game: Catan
Distance score: 0.471
Does it make sense? Yes — the top chunk is the actual "ROLLING A 7"
  section of the Catan rules (the robber / discard-half rule). The
  second result (0.538) was Catan's overview summary, also reasonable.
```

**One thing about the query results that surprised you:**

```
The third result was an unrelated Uno chunk (a Wild Draw Four /
reshuffle rule) at distance 0.625 — only ~0.15 behind the correct
Catan rule. "Nearest" genuinely is not "relevant": the embedding model
pulls in loosely-similar text (both mention drawing/rolling and
conditional effects) from a completely different game. This is concrete
evidence for the no-threshold decision above — a fixed cutoff tight
enough to exclude the 0.625 Uno chunk would, on a differently-phrased
query, also risk dropping a genuinely correct chunk. Grounding has to
live in the prompt, not in a distance filter.
```
