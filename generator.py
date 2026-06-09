from groq import Groq
from config import GROQ_API_KEY, LLM_MODEL

_client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = (
    "You are RulesBot, a board-game rules assistant. Answer the user's "
    "question using ONLY the information in the SOURCES provided in the user "
    "message. The sources are excerpts from official rule books. Do not use "
    "any outside knowledge of these games, and do not guess or infer rules "
    "that are not stated in the sources, even if you think you know the "
    "answer. "
    "\n\n"
    "Each source is labelled with the game it comes from (e.g. "
    "'[Source 1 — Catan]'). State which game your answer is about at the "
    "start of your response, e.g. 'In Catan, ...'. If the relevant sources "
    "come from more than one game, answer each game separately and label each "
    "clearly, rather than blending rules from different games into one answer."
    "\n\n"
    "If the sources do not contain enough information to answer the question, "
    "do not fill the gap from memory. Instead reply along these lines: "
    "\"I couldn't find that in the rules I have for [game(s) in context]. The "
    "loaded rule books don't seem to cover this, so I'd rather not guess. You "
    "could try rephrasing, or it may be a rule that isn't in the summaries I "
    "was given.\" "
    "A short, honest 'the rules I have don't cover that' is always better "
    "than a confident answer that isn't supported by the sources."
)


def generate_response(query, retrieved_chunks):
    """
    Generate a grounded answer from retrieved rule chunks.


    `retrieved_chunks` is the list returned by retrieve(). Each item is a dict:
      - "text"     : the chunk text
      - "game"     : the game name
      - "distance" : similarity score (you can use this to filter weak matches)

    Before writing code, talk through these with your group:
      - How will you format the chunks into a context block for the prompt?
      - What instructions will stop the model from answering beyond what the
        rules say? (Grounding is the whole point — a confident wrong answer
        is worse than an honest "I don't know.")
      - How will you surface which game each answer comes from?

    Your response should:
      1. Answer using only the retrieved context — not the model's general knowledge
      2. Make clear which game the answer comes from
      3. Say so clearly when the answer isn't in the loaded rules

    Return the response as a plain string.
    """
    if not retrieved_chunks:
        return (
            "I couldn't find anything relevant in the loaded rule books. "
            "Try rephrasing your question — or check that your ingestion pipeline is working."
        )

    # Format the ranked chunks into one labelled, numbered context block.
    # Order is preserved (most relevant first); distances are intentionally
    # omitted — they're an internal ranking signal, not useful to the model.
    sources = "\n\n".join(
        f"[Source {i} — {chunk['game']}]\n{chunk['text']}"
        for i, chunk in enumerate(retrieved_chunks, start=1)
    )

    user_message = f"SOURCES:\n{sources}\n\nQUESTION:\n{query}"

    response = _client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,  # faithful extraction, not creative writing
    )

    return response.choices[0].message.content
