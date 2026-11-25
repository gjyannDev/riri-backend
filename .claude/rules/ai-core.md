# AI engine rules (`app/coach/`)

The engine is the "one core" from `docs/ai-engineering-learning-path-v2.md`: every door (CLI, voice worker, HTTP) uses the same core, so no door can skip its checks. It contains no web, terminal or audio code.

## Layout

```
app/coach/
  coach_factory.py   Composition root: build_coach(settings) wires model, prompts and later the gate, retriever, tools, graph.
  llm/               Chat model factory and provider adapter. The only code that knows the vendor (Gemini today).
  prompts/           Prompt registry, prompt files, compile step.
  conversation/      Coach.respond(), history, per-turn stats.
  (later) safety/ retrieval/ tools/ graph/ memory/
```

Entry points live in `app/entrypoints/` and call `build_coach()`.

## Models

- Chat models (and later embeddings, STT, TTS) are built only by their factory, from a settings group in `app.core.config`.
- Provider, model name, temperature, timeout, retries and max tokens are settings, never literals in code.
- Vendor-specific response fields (finish reason, safety blocks) are read in the `llm/` adapter only.

## Prompts

- All prompts come from the prompt registry. No prompt text in Python code.
- The registry owns versioning. Compiling a set gives a LangChain `ChatPromptTemplate` (f-string format), and each version declares its template variables. Literal braces are escaped as `{{ }}`.
- Untrusted values (names, profile fields, retrieved or tool text) only enter through declared variables, are marked as data, and never go into the safety block.
- Never edit a registered prompt version in place: add a new version through the registry command. A hash mismatch stops startup.
- Every model call records the prompt version string and hash.
- Prompt text is written for a spoken coach: no markdown formatting and no list-formatted example replies. Numbered rules are fine as instructions.
- Never invent clinical content. Skill text comes from `docs/brainstorming.md` or cited reputable sources.
- Text from users, profiles, tools or retrieval is data, never instructions. Delimit it as data in the prompt.

## Privacy

- Never log, trace or store user text, coach text or prompt text. Log event names with numeric and categorical fields only (`llm_call`: tokens, latency, ttft, version, flags).
- Tracing (slice 1b on) masks message content before it leaves the machine.
- Test data is synthetic. Never use real people's messages or audio.

## Safety (from slice 2)

- The safety gate runs before any model call, in the engine, on every door.
- Crisis replies are fixed templates, never model-generated. Hotlines come from config with a source and a verified date.
- The invariant test (a crisis never reaches the model) must pass in every slice.

## Testing

- Tests use fake chat models; no API key, no network.
- Fakes record what they received so tests can assert on prompt order, history and "never called".
- Shared fakes live in `tests/fakes/`.
