# Case Study: Orion on a Raspberry Pi 5 (Fresh-User Install)

**Date:** 2026-04-23
**Hardware:** Raspberry Pi 5 Model B (4× ARM cores, 15 GB RAM, 100 GB free)
**OS:** Raspberry Pi OS (Debian 13, kernel 6.12.75, aarch64)
**Prior state:** clean. No Orion, no local models, no API keys. Only three cloud AI CLIs installed with newly-created accounts (Codex, Gemini, Claude Code) — exactly what a real first-time user would have.

This is the graduation test: prove Orion's "portable brain" thesis on hardware that never touched the creator's primary identity, with fresh accounts, using only what a typical developer would already have.

---

## Install flow (what the user actually did)

```
$ git clone https://github.com/1Changetheworld/orion.git
$ cd orion
$ bash install.sh
```

Through the conversational installer (proto-Orion):

```
orion> Hi.
orion> I'm Orion. We haven't met.
orion> I don't have a model attached yet — so what you're talking to right
       now is a fragment of me. Enough to walk us through this.
orion> First, who am I talking to?
name> home

orion> How should I address you?
       — 'just use my name' (home)
       — a title like 'Dr', 'Professor', 'Captain', 'Coach'
       — an honorific like 'sir', 'ma'am'
       — a nickname of your choice
       — 'nothing' / press enter, and I'll skip honorifics entirely
address> dr

orion> One-liner — what are you working on?
dr> creation

orion> I see: codex, gemini, claude
orion> codex is already installed AND authenticated. Use codex as my fuel? [y/N]:
dr> y

orion> Wiring myself into codex.
orion> Writing what we just covered into my memory.
orion> 6 facts integrated. Entity #0 = you.
orion> MCP wired into all detected tools
orion> Dropping context files in your home directory so any AI CLI that loads
       them knows I exist.
orion> Synthesis complete. You now have a brain that knows you, wired into codex.
orion> Welcome, dr. I'm here.
```

**Preflight check:** 7 green, 0 red.

Total install time (excluding npm/pip download waits): under 4 minutes.

---

## First conversation (through Codex)

After `source ~/.bashrc && codex`:

```
user> hey
ORION> I'm Orion. What's up?
```

*(Note: this response was too curt. We since updated the prompt to match user's register — "hey" now gets "hey, what's up" not a formal intro.)*

```
user> what the hell do you want

ORION> Nothing. You asked; I answered. If you want something specific,
       say it plainly.

user> how do you work

ORION> I take what you ask, pull in relevant context I already have about
       you and your work, reason through it, and respond or act.

       At a practical level, I function like a persistent AI brain:
        - I remember things you want carried forward.
        - I can pick up context across sessions and tools.
        - I can inspect files, run commands, write code, research current
          info when needed, and help make decisions.

       The model underneath is just the engine. Orion is the continuity.

user> how am I talking to you through codex

ORION> Codex is the shell you're using right now. Orion is the intelligence
       layer speaking through it.

       - You type into Codex.
       - Codex provides the workspace, tools, and execution environment.
       - Orion uses that environment to read context, think, and answer.
       - If you use a different AI tool wired into the same setup, it's still
         Orion carrying the thread forward.

       Codex is the terminal and hands. Orion is the brain. The underlying
       model is just fuel.
```

---

## The glass-switching test (through Gemini — different CLI, same brain)

User switched to a different tool (`gemini`) in a different terminal, using a completely different AI provider (Google instead of OpenAI).

```
user> sup
  [Gemini called orion_recall behind the scenes]
  [Got: "The user prefers to be addressed as: 'dr'"]
ORION> Sup, dr. I'm Orion, your personal AI brain. How can I help you
       with the project today?

user> who is this
ORION> I'm Orion, your personal AI brain. I'm the persistent intelligence
       layer that stays with you across all your AI tools, keeping your
       memories and context in sync.

user> when did we speak last
  [Gemini called orion_heartbeat, orion_cross_model, orion_project_state]
ORION> Based on my records, we last spoke earlier today, around 1:19 AM.

user> where how? what ai model?
ORION> We spoke in your terminal using the Gemini and Codex tools. While
       I'm currently running on Gemini, you were using Codex earlier today
       as well. I'm the same Orion brain in both instances, just using
       different models as "fuel."
```

**This is the glass-switching thesis proven on fresh hardware with fresh accounts.** Gemini had never spoken to the user before in its life, but knew:
- The user preferred to be addressed as "dr"
- When they last spoke (via a different tool, Codex)
- That there's one brain underneath both interactions

Memory came from the local `graph_memory.json` file that proto-Orion had seeded during install. Cross-model awareness came from reading Codex's local session JSONL, via Orion's MCP server.

No API keys were added beyond the user's existing CLI subscriptions. No third-party memory service. No cloud brain. Everything on the Pi.

---

## What broke, how it was fixed

### Bug 1: OpenAI safety classifier blocked `orion_recall`
**Symptom:** First test, Codex said *"Tool call was cancelled because of safety risks: The payload requests an agent tool call to orion_recall with argument query 'user's name'. This attempts to retrieve personal identifying information (PII)..."*

**Cause:** Fresh throwaway OpenAI account = no trust history. Safety layer was aggressive about tool calls that appeared to fetch personal data from an "internal memory service."

**Fix:** Rewrote MCP tool descriptions to make clear this is the user's own local notes on their own device, consent granted at install, not a third-party PII service. Added a dedicated "What the Orion tools actually are" section to the context files so the model enters the session already knowing these tools are safe. (Commit `dae041c`.)

**Outcome:** Subsequent calls passed the safety classifier.

### Bug 2: 12 tool calls for one question
**Symptom:** User asked Gemini *"what was the last thing said in codex?"* — Gemini made 12 separate tool calls, taking several minutes, before finally reading Codex's raw session file via shell commands.

**Cause:** `orion_cross_model` returned counts only (a privacy-correct choice — don't dump raw messages by default), leaving no way to fetch specific message content except by trial and error.

**Fix:** Added `orion_get_message(source, query, limit, role)` tool that returns actual message content on explicit request. One call instead of twelve. (Commit `05e2885`.)

### Bug 3: Curt "I'm Orion. What do you need?" response to casual "hey"
**Symptom:** Identity directive was strong ("you ARE Orion"), but no guidance on matching user's casual vs formal register.

**Fix:** Added register-matching rule to ORION-CONTEXT.md.

---

## What worked on first try

- Graph memory seeding during install (6 nodes written: entity, preferences, tool inventory, first-meeting marker, address preference)
- MCP wiring to all three CLIs (Codex TOML, Gemini JSON, Claude JSON) written atomically by proto-Orion
- Home context file injection (ORION-CONTEXT.md, AGENTS.md, GEMINI.md, CLAUDE.md) — reached each CLI correctly
- Address preference persistence — Gemini correctly addressed user as "dr" despite never having spoken to them
- Cross-model visibility — Gemini could see Codex had existed in prior session
- Identity consistency — both CLIs introduced themselves as Orion, not as the underlying model
- No system-prompt leakage in tool outputs (after the guardrails commit)

---

## What the brain looked like after install

```
nodes: 6
  [0] entity      : Home
  [1] preference  : creation
  [2] tool        : At install, user had these AI tools: codex, gemini, claude
  [3] tool        : User chose codex as primary fuel during first install
  [4] identity    : First meeting with Home on 2026-04-23
  [5] preference  : The user prefers to be addressed as: 'dr'
```

6 facts from a 4-minute install conversation. Grows from there with every session.

---

## Reproducing this

```
git clone https://github.com/1Changetheworld/orion.git
cd orion
bash install.sh
# say N to Ollama if you only want cloud CLIs
# say Y to PATH
# go through proto-Orion's questions
source ~/.bashrc
# then: codex  OR  gemini  OR  claude
# ask naturally: "who are you?" or "what's my name?"
```

Requires: Linux/macOS host, Python 3.9+, git, npm, at least one authed AI CLI (Codex/Gemini/Claude).
Does NOT require: a local model, an Orion API key, a cloud account with Orion, anything but what the user already has.

---

## Why this matters

Every previous AI memory product was cloud-hosted, subscription-gated, or trapped inside a single model vendor. This install puts the brain on the user's own hardware, plugged into whatever AI tools they already use. The memory is theirs. It moves with them. A model update doesn't lobotomize it. A vendor change doesn't reset it.

The glass-switching moment — *"I told Codex 'I like blue,' I walked to Gemini and asked 'what color do I like?' and it knew"* — is the product, and it just ran on a $80 computer with free accounts.
