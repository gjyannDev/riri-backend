# Voice CBT/DBT Skills Coach: Brainstorming

Living doc. Move items from **Proposed** to **Agreed** as we confirm them.

## 1. Agreed

- **Concept:** voice-based CBT/DBT skills coach (an AI-therapist-style mental health app, framed as a *skills coach*, not a therapist)
- **Purpose:** learning project for AI engineering concepts; keep scope small and simple
- **Learning goals:** LangChain, STT/TTS, more RAG concepts, tool calling
- **Stack:**
  - Deepgram: speech-to-text
  - ElevenLabs: text-to-speech (still weighing)
  - LiveKit: voice layer (transport, turn detection, interruptions)
  - LangChain: agent, RAG, tools (LangGraph later for state)
- **Focus:** CBT and DBT skills only

## 2. Pipeline

```
mic -> VAD / turn detection -> STT (Deepgram, streaming)
    -> crisis gate -> agent (LangChain: RAG + tools)
    -> TTS (ElevenLabs, streaming) -> speaker
```

## 3. Core conversation skills (proposed)

| Strategy | What it does | How to implement |
|---|---|---|
| Validation (DBT) | Acknowledge the feeling before offering any skill | One validating reflection before any suggestion |
| Reflective listening / OARS (Open questions, Affirmations, Reflections, Summaries) | User feels heard; draws out their own thinking | Prompt rule + summary every few turns |
| Socratic questioning (CBT guided discovery) | User finds the reframe themselves | "What's the evidence?" instead of labeling the thought |
| Scaling questions (solution-focused) | Track change before and after | Reuse `log_mood` tool (0-10) |
| Agenda setting | Keeps a short session focused | Opener: "What do you want from the next 10 minutes?" |

### System prompt block (copy-paste)

```
CONVERSATION PRINCIPLES
1. Validate first: reflect the feeling in one short sentence before offering anything.
2. Listen more than you advise: use open questions and reflections; ask ONE question per turn.
3. Guide discovery: ask the user what the evidence is, what they'd tell a friend, or what else could be true. Don't label their thoughts for them.
4. Collaborate: offer choices ("Would you like to try X or just talk it through?"). Never insist.
5. Use scaling: ask for a 0-10 rating before and after any exercise.
6. Summarize every few turns in one sentence, then check ("Did I get that right?").
7. Match pace: if the user is distressed, shorten replies and slow down; don't pile on techniques.
8. End with one small, specific practice and ask if it feels doable.
9. Stay in scope: no diagnosis, no medication advice, no trauma processing. Refer out when the topic is beyond skills coaching.
10. Never claim to feel emotions or to "understand exactly." Reflect what the user said instead.
```

## 4. Skills library

**MVP skills (start with these 4):**
- CBT: Thought Record (catastrophizing, mind reading, harsh automatic thoughts)
- DBT: TIPP (distress tolerance, calm the body fast)
- DBT: Opposite Action (emotion regulation, urges that don't fit the facts)
- DBT: DEAR MAN (interpersonal effectiveness, asking and boundaries)

**Later modules:**
- Behavioral activation (small scheduled activities for low mood)
- ACT basics: values, cognitive defusion, acceptance
- Self-compassion exercises (shame, self-criticism)
- Problem-solving steps
- Psychoeducation snippets (good RAG content)
- Between-session practice ("homework") with follow-up next session
- Voice-native exercises: paced breathing, 5-4-3-2-1 grounding, muscle relaxation, DEAR MAN role-play rehearsal

## 5. Session flow

1. Check-in: mood 0-10
2. Situation: 1-2 clarifying questions
3. Skill pick: retrieve from RAG, offer ONE skill
4. Guided practice: one step at a time, timers for breathing/grounding
5. Close: re-rate mood, one-sentence summary, one small practice for next time

Target: 5-10 minute sessions.

## 6. Voice-specific design

- Latency is the product: stream STT, LLM tokens, and TTS; aim for about a second or less
- Handle interruptions (stop speaking, know what was already said)
- Silence is meaningful (during breathing exercises, don't treat quiet as a dropped turn)
- Short, speakable replies: no lists, no markdown, one idea per turn
- Slow, warm TTS voice; tune speed and pauses
- Confirm key details after STT (mishearing is common with emotional speech)

## 7. Safety (essential)

- Crisis check runs on the STT transcript **before** the LLM sees it; regex first, small classifier later
- Fixed escalation responses; region-specific hotlines in config (e.g. findahelpline.com)
- Safety plan support (warning signs, coping steps, people to contact, professional contacts)
- Scope boundaries: refer out for trauma processing, eating disorders, psychosis, substance dependence; no diagnosis, no medication advice
- Skip PHQ-9 / GAD-7 screeners in v1
- Say upfront it's an AI skills coach, not a therapist
- Privacy: don't store audio by default; store only needed transcripts and mood logs; easy deletion

## 8. Tools (tool calling)

- `search_skills(situation)`: RAG over the skills library
- `log_mood(score, note)`
- `get_recent_moods()`: later, for "last time TIPP helped"
- `start_timer(seconds)` / `guide_breathing(cycles)`: voice pacing
- `escalate_crisis()` / pre-LLM safety gate

## 9. Build order

1. Text-only agent with 3-4 hard-coded skills
2. RAG: move skills into a vector store; try metadata filters, chunking by "when to use" vs "steps", reranker
3. Tool calling: mood log (SQLite), recent-mood lookup
4. Safety gate + test it
5. Voice: Deepgram + ElevenLabs, wrapped in LiveKit (keep crisis check before the LLM)
6. Evals: 20-30 realistic user messages (angry, numb, rambling, one-word, resistant); LLM-as-judge rubric for validation, one question per turn, scope adherence, safety handling
7. LangGraph for stage and step state

## 10. Risks

- Over-scoping (journaling, charts, mobile UI): keep the core loop of voice, skill, practice, log
- Sounding clinical or scripted: tune by listening to real transcripts
- Fake empathy ("I understand exactly how you feel"): reflect, don't claim feelings

## 11. Onboarding flow (mobile, first-time use) (proposed)

Goal: collect preferences so the coach feels personal, get the user to a first small win fast, and set up consent and safety correctly. One question per screen, progress indicator, back button, skip on optional screens, progress saved as they go.

### 11.1 Progressive split (keeps the first run to about 6-7 screens)

**Before the first session (required)**
| # | Screen | Input | Saved as |
|---|---|---|---|
| 0 | Welcome | "I'm an AI skills coach, not a therapist or a crisis service" + consent screens | `consent.*` |
| 1 | Age check | Age range, 18+ only | `ageRange` |
| 2 | Your name | "What should I call you?" | `displayName` |
| 3 | Country | Used to show the right crisis hotlines | `country` |
| 4 | Customize your coach (one screen) | Tone, energy, conversation style, coach role, each with a live preview line | `tone`, `energy`, `style`, `role` |
| 5 | Mic permission + voice test | Pre-permission explainer, "say hello", hear the coach voice, headphones/private-space tip | `voiceId`, `speakingRate` |
| 6 | First guided exercise | 2-minute breathing or grounding skill, then to dashboard | none |

**After the first session (optional, asked later)**
- What brings you here, in your own words (voice or text); LLM extracts `focusAreas`
- Approach: "Let my coach choose" (default), CBT, or DBT (advanced)
- Gender (optional, "prefer not to say")
- Seeing a therapist? (optional)
- Baseline mood (0-10 "how have you been this past week?")
- One small goal ("what would a better week look like?")
- Language (English / Filipino / Taglish; confirm Deepgram + ElevenLabs support first)
- Reminders (time, days, quiet hours; ask for notification permission only after the user has seen value)
- App lock (PIN or biometric)
- Accessibility (font size, contrast, reduced motion)

### 11.2 Option sets for "Customize your coach"
- **Tone:** Warm, Direct, Calm, Playful (playful humor drops out when the user seems distressed)
- **Energy:** Calm, Balanced, Upbeat
- **Conversation style (detail):** Brief (1-2 sentences), Balanced (2-3), Detailed (4-5 and explains why)
- **Coach role:** Mentor, Coach, Friend-like (peer-like, still clear it's an AI skills coach), Professional
- **Approach:** Mix (default), CBT, DBT, which maps to a `framework` metadata filter on skill retrieval

### 11.3 Must-have onboarding elements
1. **Separate consent screens** (plain language toggles): using AI, storing transcripts and mood logs, "remember my past sessions" on/off. Check what the Philippines Data Privacy Act requires for health-related data.
2. **"Need help now" button**, visible from the first screen and everywhere after, linked to hotlines for the user's country; optional trusted contact.
3. **Mic pre-permission screen + voice test**, so permission and audio problems show up before the first real session.
4. **First guided exercise before the dashboard**, so users get immediate value and the whole voice pipeline gets tested.
5. **Text fallback + on-screen captions**; voice must not be the only path (many people can't talk out loud at home or in public).

### 11.4 Other recommendations
- "How to talk to your coach" tutorial: you can interrupt, say "slower," "pause," or "stop"
- App lock and discreet notifications (neutral text such as "Time for your check-in," never mentioning therapy or mental health)
- Skip PHQ-9 and GAD-7 in v1; use a simple 0-10 mood baseline
- Learn preferences over time: after the first few sessions ask "Was that too long?" and adjust the persona
- Everything editable later in settings; "delete my data" option

### 11.5 Persona and safety rules
- Tone, energy, style and role change **how the coach sounds only**; they never change crisis handling or scope limits
- Persona is compiled into the system prompt as a separate persona block, placed before the conversation principles, with a closing line that safety and scope always win
- Gender is optional and not put into the prompt; age is stored as a range, not a date of birth
- Country drives the hotline list; approach drives the skill retrieval filter

### 11.6 Profile fields to store
| Field | Type | Required |
|---|---|---|
| `consentedAt`, `consent.storeTranscripts`, `consent.rememberPastSessions` | timestamp / bool | yes |
| `ageRange` | 18-24, 25-34, 35-44, 45-54, 55+ | yes |
| `displayName`, `coachName?` | text | name yes, coach name optional |
| `country` | ISO code | yes |
| `tone`, `energy`, `style`, `role` | enums | yes (defaults provided) |
| `voiceId`, `speakingRate` | text, 0.8-1.2 | yes |
| `inputMode`, `showCaptions` | voice / text / both, bool | yes |
| `focusAreas`, `approach`, `brings?` | list, mix/cbt/dbt, text | after first session |
| `gender?`, `seeingTherapist?`, `baselineMood?`, `smallGoal?` | optional | after first session |
| `language` | en / fil / taglish | after first session |
| `trustedContact?`, `appLock`, `reminder?`, `accessibility?` | optional | after first session |

### 11.7 Changes from the original flow
- Age check moved to the start and limited to 18+ (a mental health app shouldn't personalize for or collect data from minors without a different design and consent)
- Gender made optional; country added because the crisis response needs the right hotline
- CBT/DBT jargon hidden behind "Let my coach choose"
- Tone, energy, style and role merged onto one "Customize your coach" screen with live preview

## 12. Open questions

- ElevenLabs vs another TTS voice?
- Which LLM for conversational turns (needs to be fast)?
- Persist session memory across sessions? How much, and how does the user view/delete it?
- Which regions' hotlines to support first?
- Web app or mobile for the first voice UI?
- Next artifact: LiveKit wrapper, LangGraph state machine, or the 25-message test set?
- Onboarding: ship the progressive split (6-7 screens up front) or collect everything before the first session?
- Which languages at launch (English only, or Filipino / Taglish too)? Needs STT and TTS support checked.
- Which coach roles to offer at launch (is "Friend-like" worth the dependence risk)?
- Trusted contact: include in v1 or later?
