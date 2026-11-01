# Empório da Música - Customer Service Agent

Technical case for the AI Engineer position at Artefact.

A text-based customer service agent for Empório da Música, a fictional musical
instrument store in Campo Grande/MS. The agent answers in Brazilian Portuguese
with the store's tone of voice (informal but professional), consults real
catalog, order and promotion data before stating any fact, and applies the
store's internal policy manual to questions about exchanges, returns,
shipping, payment and warranty.

## How it works

```
user message
     |
     v
LLM (OpenAI-compatible endpoint) ---- function calling ----+
     |                                                     |
     |                                             +-------v--------+
     |                                             |  tools layer   |
     |                                             |                |
     |                                             |  catalog SQL   |  products, categories,
     |                                             |  (SQLite,      |  order items (in memory,
     |                                             |   stdlib)      |  rebuilt from CSVs)
     |                                             |                |
     |                                             |  orders SQL    |  orders + customers
     |                                             |                |
     |                                             |  promotions    |  active only
     |                                             |                |
     |                                             |  policy        |  politicas_da_loja.txt,
     |                                             |  retrieval     |  chunked by section,
     |                                             |                |  keyword/stem scoring
     |                                             |                |
     |                                             |  store info    |  address, hours, contacts
     |                                             +----------------+
     v
reply in Portuguese, grounded in tool results
```

The LLM never answers from memory: the system prompt requires a tool call
before stating price, stock, delivery, promotion or policy facts, mirroring
the store's own rule that wrong information erodes trust.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your LLM_API_KEY
```

The only runtime dependency is the `openai` client. Any OpenAI-compatible
endpoint works; the defaults target Google's Gemini free tier (create a key at
https://aistudio.google.com/app/apikey). A Groq configuration is included in
`.env.example` as an alternative.

## Running

```bash
python main.py                  # new conversation
python main.py --session ana    # named session, history kept in .sessions/
```

Inside the chat: `/sair` quits, `/limpar` restarts the conversation.

## Tests and example conversations

```bash
python tests/test_tools.py            # deterministic checks, no LLM needed
python scripts/generate_examples.py   # regenerates examples/ (needs an API key)
```

The `examples/` folder holds 5 real conversations covering catalog search,
price + return policy, order tracking, out-of-scope redirection and expired
promotions. Each one shows the tool calls the agent made.

## Technical decisions

**Approach: function calling over a small tool set.** The store's data is
structured (CSVs), and the policy manual is a single static document. Function
calling keeps every factual answer grounded in a queryable source and makes
the agent's reasoning inspectable: each reply shows which queries were run.
A ReAct-style loop or a multi-agent framework would add machinery without
changing the outcome for this scope.

**Data layer: in-memory SQLite from the CSVs.** SQLite ships with Python, so
there is no service to run and no dependency to install. The database is
rebuilt on startup, which keeps the CSVs as the single source of truth and
makes updates trivial: replace the file, restart.

**Policy retrieval: keyword/stem scoring, no vector store.** The manual is 8
pages split into about 30 section-sized chunks. A small accent-insensitive
scorer with prefix stemming (devolver/devolução, arrependender/arrependimento)
retrieves the right section reliably at zero cost and zero dependencies. If
the document set grew, I would swap this module for embeddings without
touching the rest of the agent.

**Model and provider: configurable, defaulting to Gemini's free tier.** The
agent speaks the OpenAI chat-completions protocol, so the provider is three
environment variables. This keeps the project free to run and easy to switch
to a paid model for production quality.

**Interface: CLI.** The case focuses on the agent working correctly, so the
interface is a terminal loop with optional named sessions persisted as JSON.

**Guardrails:** the system prompt encodes the manual's hard rules (never state
price or stock without querying; instruments only, no accessories; never
promise an expired discount; order lookups require an identifier; the agent
does not close sales, it routes to WhatsApp). Prompt-level guardrails are the
simplest layer that fits this prototype; a production version would add
deterministic output checks.

## Known limitations and next steps

- Keyword retrieval can miss paraphrases far from the manual's wording;
  embeddings would close that gap.
- Order lookup trusts the identifier given; a real deployment would
  authenticate the customer before exposing order details.
- No WhatsApp integration; the CLI stands in for the channel.
- Conversation history grows unbounded within a session; a summarization
  step would bound token usage.
- With more time: evaluation suite with scripted scenarios, streaming
  replies, and a small web UI.

## Use of AI assistants

This project was developed with AI assistance (a coding agent) for
scaffolding, implementation of the data and tool layers, and drafting of this
README. Architecture choices, the tool contract, guardrails and validation
against the case data were directed and reviewed by me. The deterministic
test suite (`tests/test_tools.py`) checks the tool layer without any LLM
involvement.

## Project structure

```
data/                    case dataset (CSVs) + policy manual (PDF and text)
src/config.py            provider and model configuration via env vars
src/database.py          CSV -> in-memory SQLite loader
src/policies.py          policy manual chunking and retrieval
src/tools.py             tool schemas and implementations
src/agent.py             LLM loop, system prompt, session persistence
main.py                  CLI
scripts/generate_examples.py
tests/test_tools.py      deterministic tool-layer checks
examples/                real conversations with the agent
```
