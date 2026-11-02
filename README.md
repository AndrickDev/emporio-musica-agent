# Empório da Música — Customer Service Agent

*Versão em português: [README.pt-BR.md](README.pt-BR.md)*

Technical case for the AI Engineer position at Artefact.

A text-based customer service agent for Empório da Música, a fictional musical instrument store in
Campo Grande/MS (Brazil). The agent talks to customers in Brazilian Portuguese, in the store's tone
of voice (informal but professional). It checks catalog, order, promotion and payment data before
stating any fact, and applies the store's policy manual to questions about returns, exchanges,
shipping, payment, warranty and opening hours.

## How it works

```
customer message
      │
      ▼
 agent loop (src/agent.py) ──► LLM, OpenAI-compatible API (Gemini free tier by default)
      ▲                            │ function calling
      │ tool results (JSON)        ▼
      └──────────────── tools (src/tools.py)
                          ├─ catalog / promotions ─► in-memory SQLite from data/*.csv
                          ├─ payment / shipping ──► manual §3, §5, §6.2 (src/pricing.py)
                          ├─ order status ────────► order id or tracking + e-mail or phone
                          ├─ store policies ──────► keyword search over the manual
                          ├─ store info ──────────► address, contacts, opening hours
                          └─ support ticket ──────► handoff to the team (local JSONL)
```

The system prompt sets persona and rules but **contains no store facts** (prices, phones, hours).
Every fact reaches the model through a tool result. The current date and time in Campo Grande are
injected on every message, so the agent can reason about opening hours and return windows.

| Tool | Typical question |
|---|---|
| `search_products` | "Quais violões até R$1000?" — accent/hyphen-insensitive, filters by the price the customer actually pays, flags truncated lists |
| `get_product_details` | "Quanto custa o Takamine GD20?" — fuzzy model match, asks back when ambiguous, suggests alternatives when unavailable |
| `list_active_promotions` | "Tem promoção?" — only `is_active = 1` promotions exist for the agent |
| `get_payment_options` | "Dá pra parcelar? E no PIX?" — PIX discount, installment tiers, combined payment |
| `estimate_shipping` | "Qual o frete para Campo Grande?" — free above R$ 500 locally; other cities get carrier times, never an invented price |
| `get_order_status` | "Cadê meu pedido?" — identity check, no personal data in the result |
| `get_store_policy` | returns, warranty, shipping, payment rules |
| `get_store_info` | address, phone, WhatsApp, e-mail, hours |
| `create_support_ticket` | complaints, return/exchange requests, human handoff |

## Setup

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # then put your key in LLM_API_KEY — .env is git-ignored
```

The only runtime dependency is the `openai` client (plus `tzdata` on Windows). Any OpenAI-compatible
endpoint works. The default is Google's Gemini free tier: create a key at
https://aistudio.google.com/app/apikey (no billing needed). Free-tier quotas are per model and per
day; check them at https://aistudio.google.com/rate-limit. Note that on the free tier Google may use
prompts and responses to improve its products, so only the anonymized dataset should be sent. A Groq
free-tier configuration is included in `.env.example` as an alternative.

## Running

```bash
python main.py                  # new conversation
python main.py --session ana    # named session, history kept in .sessions/ (git-ignored)
python main.py --debug          # also print each tool result
```

Inside the chat: `/sair` quits, `/limpar` restarts the conversation.

## Tests and example conversations

```bash
python tests/test_tools.py      # 33 deterministic checks of the tool layer (no LLM, no network)
python tests/test_agent.py      # 9 checks of the agent loop with a simulated OpenAI client
python -m pytest tests/         # same 42 tests, if pytest is installed
python scripts/generate_examples.py --translate   # runs 5 scenarios with the real model
python scripts/evaluate_agent.py --out examples/evaluation.md   # rule-based evaluation with the real model
```

The tests cover search (accents, hyphens, promotional prices, truncation, ambiguity, availability
states), promotions, payment and shipping rules, 10 real customer questions against the policy
manual, order privacy (identity check, no personal data, identical
failure messages, lock-out, no enumeration), policy retrieval, and the agent loop (tool dispatch,
round limit, provider errors, date in the prompt, sessions). They do **not** measure the quality of a
real model's answers. That is covered by the example conversations and by `scripts/evaluate_agent.py`,
which runs 11 questions with the real model and checks, with simple rules, whether the expected tool
was called, whether the reply contains what it must (e.g. the right price) and whether it leaks what it
must not (personal data, invented discounts, off-topic content). With `gemini-3.5-flash-lite` it
passed **11/11** (`examples/evaluation.md`). Reviewing the example conversations by hand found one
miss the rules did not catch: asked about an expired promotion, the agent said it had ended but did not
give the current price, which the manual requires (§7.3). The prompt rule was made explicit and that
scenario was regenerated.

`examples/` holds the conversations produced by `scripts/generate_examples.py`. Each file states the
model, the generation time and the store date used (fixed at 2026-03-23, the day after the last order
in the dataset, so that order dates make sense). Agent replies are not edited. The optional English
translation is produced by the same model and labelled as a machine translation.

## Technical decisions

**Approach: function calling over a small tool set.** The store's data is structured and the questions
map to a few operations. Function calling keeps every factual answer grounded in a query and makes the
agent's decisions inspectable (each reply lists the tools it used). A ReAct framework or a multi-agent
setup would add machinery without changing the outcome at this scope. An SQL agent was ruled out: the
model only fills parameters of fixed, parameterized queries and never writes SQL, which avoids leaking
customer data or running wrong joins.

**Business rules in code, not in the prompt.** Promotional prices, the PIX discount (which does not
stack with promotions, §6.2), installment tiers (§3.1), availability states and order verification are
plain Python, covered by tests. The manual itself warns that wrong price information can amount to
misleading advertising, and LLMs make arithmetic mistakes.

**Data layer: in-memory SQLite from the CSVs.** SQLite ships with Python: no service to run and no extra
dependency. The database is rebuilt on startup, so the CSVs remain the single source of truth. A
`catalog` view joins each product with its active promotion and current price, so every product tool
uses the same pricing rule. Two SQL functions (`norm`, `compact`) make search accent- and
hyphen-insensitive, because SQLite's `LOWER()` only handles ASCII.

**Policy retrieval: keyword/stem scoring, no vector store.** The manual is 8 pages split into section-sized
chunks. An accent-insensitive scorer with prefix stemming (devolver/devolução,
arrepender/arrependimento), plus a small synonym list for customer words that share no stem with the
manual ("horas" → horário, "quebrado" → avaria/defeito), puts the right section in the top 3 for the
10 customer questions in the tests, at zero cost and with no dependency. If the document set grew, this module could be swapped for embeddings or hybrid
search without touching the rest of the agent.

**Model and provider: configurable, defaulting to Gemini's free tier.** The agent speaks the OpenAI chat
completions protocol, so changing provider means changing three environment variables. This keeps the
project free to run. The examples and the evaluation were produced with **`gemini-3.5-flash-lite`**.
The first choice was Gemini 3.6 Flash, but its free tier allows only 5 requests per minute and 20 per
day, which one run of the example scenarios exceeds; 3.5 Flash Lite allows 15 per minute and 500 per
day. `LLM_MIN_SECONDS_BETWEEN_CALLS` spaces the calls to stay under the per-minute limit. A stronger
(paid) model would be the production choice; the agent code does not change.

**Interface: CLI** with optional named sessions persisted as JSON in a git-ignored folder.

**Language.** This README is in English, as requested by the hiring process, with a Portuguese version
alongside. Code identifiers are in English; code comments and the later commit messages are in
Portuguese, the author's working language. The agent converses in Brazilian Portuguese
because it serves the store's customers and the case's own example questions are in Portuguese; each
example conversation carries an English translation. Answering customers in English would be a
one-line change in the system prompt.

**Privacy (LGPD, manual §9).** Order lookups require the order id or tracking code **plus** the e-mail
or phone used in the purchase. A failed check returns the same message whether or not the order exists
(so order numbers cannot be enumerated), and after 3 failures order lookups are locked for that
conversation. The tool never returns the customer's name, e-mail, phone, city or internal id. Tickets
can only reference an order verified in the same conversation and do not store contact data. The
customer CSV in this repository is anonymized (`Cliente NNN`, `clienteNNN@example.com`).

## Assumptions

| Topic | Ambiguity | Decision |
|---|---|---|
| Language | The brief is in Portuguese; the hiring e-mail asks for English | README in English (plus a Portuguese version); agent in Portuguese; examples translated |
| Installments (§3 / §3.1) | "Up to 3x: no minimum (except below R$ 50.00)" | 2–3x need installments ≥ R$ 50; 4–6x ≥ R$ 80; 7–12x ≥ R$ 100 |
| Thresholds | "acima de R$ 2.000" | Strictly greater than |
| Contacts | §1.2 lists (67) 3341-4444 as phone/WhatsApp; §7 lists (67) 3321-4500 as the WhatsApp channel | Phone from §1.2, WhatsApp from §7 |
| E-mail | Spelled with and without an accent in the manual | Unaccented version from the cover page |
| Promotions | The manual mentions Black Friday in November; no Black Friday promotion is active in the data | Only promotions active in the data are offered (§7.3) |
| Returns | The right of withdrawal applies to online purchases and counts from receipt; the data has neither the channel nor the actual delivery date | The agent explains the rule using the estimated delivery date, states the assumption and registers a ticket instead of approving or refusing |
| Store date | Orders end in March 2026 | Real date by default; `STORE_TODAY` pins it (examples use 2026-03-23) |

## Data-quality findings

- Products 135, 137, 139, 140, 142 and 144 have descriptions that name another brand or model (e.g.
  *Music Man Bass 1X* described as a Fender Jazz Bass). This is detected automatically; the description
  is withheld and only the name, price and specs are used.
- Product 136 is `discontinued` but has 13 units in stock, so it is not offered. Product 130 is
  `coming_soon` with 2 units, so it is not for sale yet (orders 3 and 14 contain it).
- Categories 6, 7 and 8 (wind instruments and orchestral strings) have no products.
- The totals of orders 3 and 20 do not match the item prices; recorded totals are reported as they are.

## Known limitations and next steps

- The identity check is "something you know" (e-mail or phone). A real deployment would authenticate
  through the messaging channel (the customer's WhatsApp number) or a one-time code, and rate-limit per
  user, not per conversation.
- Keyword retrieval can miss paraphrases far from the manual's wording.
- The CSVs are a static snapshot; tickets go to a local file instead of a CRM.
- Holidays are not checked when telling whether the store is open.
- Shipping prices outside Campo Grande depend on CEP and weight and are not in the data.
- Conversation history grows within a session; a summarization step would bound token usage.
- The real-model results (examples and the 11/11 evaluation) come from a single run with a lightweight
  model; LLM output varies between runs, so they show the agent works, not that it never fails.
- With more time: a larger evaluation set, run several times and on more than one model, with
  LLM-graded checks for tone and faithfulness; a WhatsApp or web front-end; observability of tool calls,
  cost and latency.

## Use of AI assistants

This project was built with two AI coding assistants, at my request. All commits are under my name;
every commit produced by an assistant says so with a `Co-Authored-By` trailer (`Instinct` or `Claude`),
so `git log` shows exactly which tool wrote what.

- **Instinct** generated the first version: project structure, data access, tool layer, agent loop,
  CLI, example generator, the first example conversations and README — the first 15 commits
  (`Co-Authored-By: Instinct`). That part of the history was rewritten before publication (the
  customer data is anonymized in every commit), which is why several of those commits share the same
  timestamp.
- **Claude (Anthropic)** then reviewed that version against the brief and made the changes in the
  commits marked `Co-Authored-By: Claude`: order identity check and removal of personal data from tool
  results, accent/hyphen-insensitive search, promotional prices in search, truncation and ambiguity
  handling, the payment, shipping and support-ticket tools, the current date in the prompt, the
  data-quality checks, the extended tests, real customer questions as policy-retrieval tests (which
  exposed two retrieval misses, fixed with extra stop words and a synonym list), the rule-based
  evaluation script, the corrected example scenarios and this bilingual README. Claude ran the 42
  offline tests but did not run the agent against a real model.
- Before publication, the author field of the assistant commits was set to my name (original dates
  kept) and the `Co-Authored-By` trailers were added, so authorship is consistent and still transparent.

**My part.** I set the ground rules for both assistants (no invented store data, protected and
anonymized customer data, executed vs. proposed tests kept separate, honest AI disclosure, nothing
published without my approval). I reviewed Claude's assessment of the first version against the brief
and decided which findings to fix: order privacy, accent-insensitive search and promotional prices. I
also chose the extra changes: the shipping tool, the automatic evaluation and real customer questions as
tests. I decided on a bilingual README with the agent speaking Portuguese, and on keeping authorship
transparent with AI co-author trailers. I ran everything locally (API key, `.env`, tests, CLI, example
generation and evaluation), switched to Gemini 3.5 Flash Lite when the free-tier quota of 3.6 Flash ran
out, reviewed the examples with Claude (which caught the expired-promotion miss in scenario 5) and
committed the examples myself. The architecture itself (function calling, in-memory SQLite, keyword
policy retrieval) was proposed by the assistants; I am studying the code in depth as part of preparing
to defend it.

## Project structure

```
data/                    case dataset (CSVs, customers anonymized) + policy manual (PDF and text)
src/config.py            provider, model and store-date configuration via env vars
src/database.py          CSV -> in-memory SQLite loader, catalog view, accent-insensitive SQL functions
src/pricing.py           payment and shipping rules from the manual
src/policies.py          policy manual chunking and retrieval
src/tools.py             tool schemas and implementations
src/agent.py             LLM loop, system prompt, session persistence
main.py                  CLI
scripts/generate_examples.py   runs the example scenarios with the real model
scripts/evaluate_agent.py      rule-based evaluation with the real model
scripts/sanitize_customers.py  how the customer data was anonymized
tests/                   tool-layer and agent-loop tests
examples/                conversations with the agent
```
