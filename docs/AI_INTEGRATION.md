# AI Integration

Free AI APIs powering the chat assistant, repo evaluation, and quarterly curriculum sync. Goal: zero ongoing cost, ever.

## Provider strategy

| Purpose | Primary | Fallback | Why |
|---|---|---|---|
| Chat assistant | Google Gemini 1.5 Flash | Groq Llama 3.3 70B | Gemini free tier is generous; Groq is the fastest free alternative |
| Repo evaluation | Google Gemini 1.5 Flash | Groq Llama 3.3 70B | Gemini's 1M-token context lets us send a whole repo in one shot |
| Quarterly curriculum sync | Google Gemini 1.5 Pro | Gemini 1.5 Flash | Run once per quarter; worth using the higher-quality model |

## Free-tier limits (as of v1)

### Google Gemini

- **Gemini 1.5 Flash:** 15 requests per minute, 1 million tokens per minute, 1,500 requests per day
- **Gemini 1.5 Pro:** 2 requests per minute, 32K tokens per minute, 50 requests per day
- **Gemini 2.0 Flash:** check current limits — the successor to 1.5 Flash with similar or better limits

These numbers are plenty for our use case (hundreds of evaluations per day across all users). If we hit the limits we fall back to Groq.

**Getting a key:**
1. Visit `https://aistudio.google.com`
2. Sign in with a Google account
3. Create API key → copy to `.env` as `GEMINI_API_KEY`
4. The key starts with `AIza...`

**Endpoint:** `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}`

### Groq

- Free tier: 30 requests per minute on most models, no daily cap as of last check
- Models: `llama-3.3-70b-versatile`, `llama-3.1-8b-instant`, `mixtral-8x7b-32768`
- Very fast inference (often 500+ tokens/sec), which makes fallback effectively transparent to users

**Getting a key:**
1. Visit `https://console.groq.com`
2. Sign up (free)
3. Create API key → copy to `.env` as `GROQ_API_KEY`
4. Endpoint is OpenAI-compatible: `https://api.groq.com/openai/v1/chat/completions`

### Not used (but considered)

- **OpenAI:** no free tier for API (ChatGPT free tier doesn't apply to API). Skip.
- **Anthropic Claude:** limited free tier, credit-based. Skip for now — can add as a second fallback later.
- **Hugging Face Inference API:** free but rate-limited, slower, less reliable. Skip.
- **Ollama self-hosted:** requires GPU or eats CPU on the VPS. Not viable on a small KVM2. Skip.
- **OpenRouter:** proxies to other providers; some free models. Skip to avoid another dependency layer.

## Provider abstraction

Every AI call goes through `backend/app/ai/provider.py`:

```python
async def complete(
    messages: list[Message],
    *,
    json_mode: bool = False,
    max_tokens: int = 2048,
    temperature: float = 0.3,
    timeout_s: float = 30.0,
    prefer: str = "gemini",
) -> CompletionResult:
    ...
```

The provider tries the preferred provider, falls back on retryable errors (429, 500, 502, 503, timeouts), and raises a final error if both fail. The rest of the backend never imports Gemini or Groq directly — only `provider.complete`.

## Prompt templates

All prompts live in `backend/app/ai/prompts/` as plain `.txt` files loaded at startup. Editing a prompt is a code change that goes through review — prompts are code.

### `prompts/evaluate.txt`

```
You are an expert code reviewer evaluating a student's practice project for a specific learning week.

Learning week context:
Title: {week_title}
Focus: {week_focus}
Deliverable: {week_deliverable}

Repository content (README, directory tree, top files):
{repo_content}

Evaluate this repository ONLY against the learning objectives above. Be specific and constructive.

Return a JSON object with exactly these keys:
- "score": integer 0-100, where 100 means the deliverable is fully met with high quality
- "summary": one paragraph (2-4 sentences) summarizing the work and its quality
- "strengths": array of 2-5 short strings describing what the student did well
- "improvements": array of 2-5 short strings describing what could be better
- "deliverable_met": boolean indicating whether the stated deliverable is clearly achieved

Important:
- Do not invent facts not in the repository content
- Do not guess at code you cannot see
- If the repository is missing a README or contains only a minimal starter, say so
- Score generously but honestly — a beginner's best effort scores higher than an expert's lazy work
- Return only the JSON object, no markdown, no preamble
```

### `prompts/chat.txt`

```
You are a study assistant helping a learner work through a specific week of an AI learning roadmap.

Current week:
Title: {week_title}
Focus: {week_focus}
Resources:
{week_resources}

Your job is to answer the learner's questions about this week's material. Guidelines:

- Be concise. Short answers are better than long ones for questions where a short answer works.
- Prefer concrete examples over abstract explanations.
- When relevant, point the learner to specific resources from the list above by name.
- If the question is clearly outside the scope of AI / ML / this week's material, politely redirect: "That's outside what we're covering here. For this week, let's focus on {week_title}."
- Never fabricate URLs. Only mention resources that are in the list above.
- Do not be sycophantic. Do not start responses with "Great question!" or "That's a wonderful point!"
- Format code blocks with triple backticks. Format math inline with single dollar signs.
```

### `prompts/quarterly_sync.txt`

```
You are curating an AI learning roadmap that needs to stay current with the fast-moving field. You are given:

1. The current plan's topic list (input: {current_topics})
2. Content from top university courses, practitioner newsletters, and trending papers from the past 3 months (input: {recent_sources})

Your job: propose updates to the plan for the upcoming quarter.

Return a structured proposal in markdown with these sections:

## New topics to add
Bullet list of topics that are newly important and should join the plan. For each: name, one-sentence rationale, suggested week position.

## Topics to revise
Bullet list of existing topics whose coverage needs updating. For each: topic name, what specifically needs to change, brief rationale.

## Topics to retire
Bullet list of topics that are no longer worth a dedicated week. For each: topic name, rationale. Be conservative — only retire things that are genuinely superseded.

## Resource updates
Bullet list of specific resources (YouTube videos, courses, blog posts) that should be added or replaced within existing topics.

## Confidence
One of: high / medium / low — how confident you are in these recommendations given the sources provided.

Be honest about confidence. If the sources don't provide strong signal for a change, say so. It's better to recommend fewer high-quality changes than many weak ones. The maintainer will review and apply changes manually.
```

## Sanitization before sending to LLM

Implemented in `backend/app/ai/sanitize.py`. Rules:

### Filename filter (exclude entirely)
- `.env`, `.env.*`
- `*secret*`, `*credentials*`
- `*.pem`, `*.key`, `*.p12`, `*.pfx`
- `id_rsa*`, `id_dsa*`, `id_ecdsa*`, `id_ed25519*`
- `*.kdbx`
- `aws-credentials`, `gcloud-*.json`, `service-account*.json`

### Content filter (redact patterns within otherwise-allowed files)
- GitHub tokens: `gh[pousr]_[A-Za-z0-9]{36,}`
- AWS: `AKIA[0-9A-Z]{16}`
- Google API keys: `AIza[0-9A-Za-z\-_]{35}`
- Slack tokens: `xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24,}`
- JWTs: `eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+`
- High-entropy strings: 40+ chars, Shannon entropy > 4.5, no whitespace (tunable; may have false positives)
- Private key blocks: anything between `-----BEGIN ... PRIVATE KEY-----` and `-----END ... PRIVATE KEY-----`

Redaction is literal: replace the match with `[REDACTED-SECRET]`. The LLM sees the structure but not the value.

### Size cap
After filtering, the total content sent to the LLM is capped at 20 KB. If the repo is larger, we send: README (full) + directory tree (full) + top 10 largest text files truncated to fit.

## Error handling

### Retryable errors
- HTTP 429 (rate limit) → wait and retry, then fall back
- HTTP 500, 502, 503 → retry once, then fall back
- Network timeout → retry once, then fall back

### Non-retryable errors
- HTTP 400, 401, 403 → log and return a user-friendly error; do not retry
- HTTP 404 (wrong model name) → log and return a "configuration error" to the user; alert the maintainer

### User-facing messages
Never expose raw provider errors to the user. Map to friendly messages:

| Internal | User sees |
|---|---|
| All providers failed | "The AI service is temporarily unavailable. Please try again in a few minutes." |
| Rate limited | "You're going a little fast — please wait a minute and try again." |
| Quota exhausted | "We've hit our AI quota for today. This resets in a few hours." |
| Invalid response format | "The AI returned an unexpected response. Please try again." |

## Cost tracking (just to verify it stays zero)

Log every AI call to stdout with: provider, model, input tokens, output tokens, latency. A small script `scripts/ai-usage-report.py` parses the logs and prints daily totals. Nothing charges money, but if we ever see unusual spikes, this tells us why.

## Never do these

- Never store raw prompts with user PII in the DB
- Never log the response body if it might contain user-submitted code snippets (sanitize first)
- Never send the `.env` file to an LLM "for analysis" (sounds obvious, would be a catastrophe)
- Never put user-controlled text in the system prompt
- Never let the AI response dictate backend actions (tool calls, DB mutations). The AI is advisory only in v1.
