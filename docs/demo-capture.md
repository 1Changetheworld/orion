# Cross-model handoff demo — capture script

One 15-30 second GIF showing a fact being set in one AI CLI and recalled
in a different one. This is the single highest-leverage asset for the
public README — it is the product in motion.

## What the GIF must show

1. **Split terminal, two panes.** Left pane labeled `codex`, right pane
   labeled `gemini` (or any two MCP-wired AI CLIs on the host).
2. **Left pane**: user types a naturalistic fact. *"remember my favorite
   color is teal"*. Orion confirms. User exits (`Ctrl+D` or `/quit`).
3. **Right pane** (different tool): user types *"what's my favorite
   color?"*. Orion answers *"teal"* without the user mentioning memory,
   brain, or tool names.
4. Optional: show a third pane briefly running `orion chat` or
   `/selfcheck` so viewers see the brain has persistent state.

Total length target: 15–25 seconds. No title cards, no slow intros —
straight into the demo. Loopable.

## Tooling

### Option A — terminalizer (recommended, produces clean GIF)

```bash
npm install -g terminalizer

# Start recording in one terminal pane; repeat for the other.
terminalizer record demo-codex
# ...run the codex flow, exit...

terminalizer record demo-gemini
# ...run the gemini flow, exit...

# Render each to GIF:
terminalizer render demo-codex -o docs/demo-codex.gif
terminalizer render demo-gemini -o docs/demo-gemini.gif
```

Then composite the two side-by-side with ffmpeg:

```bash
ffmpeg -i docs/demo-codex.gif -i docs/demo-gemini.gif \
       -filter_complex "[0:v][1:v]hstack=inputs=2" \
       docs/demo.gif
```

### Option B — asciinema + agg (SVG + GIF, smallest file)

```bash
# Install (macOS/Linux):
brew install asciinema agg   # or apt / dnf equivalent

# Record each pane:
asciinema rec codex.cast       # run flow, Ctrl+D when done
asciinema rec gemini.cast

# Convert to GIF:
agg codex.cast docs/demo-codex.gif
agg gemini.cast docs/demo-gemini.gif

# Composite as above with ffmpeg, or embed the raw .cast with
# asciinema-player on a web page.
```

### Option C — screen capture (fallback, any OS)

Any screen recorder (ScreenToGif on Windows, Kap on macOS, peek on
Linux) aimed at a tmux split pane. Output as GIF, target ≤ 5 MB.

## Pre-flight before recording

```bash
python orion_preflight.py
python tests/run_all.py
```

Both green. If preflight surfaces a yellow row for a tool you plan to
use in the demo, fix it first — viewers will spot it.

Clear the target CLIs' state before recording so recall is genuinely
cross-tool and not a local cache answer:

```bash
# Codex: start fresh (closes any open session cleanly)
pkill -f 'codex' 2>/dev/null

# Gemini: same
pkill -f 'gemini' 2>/dev/null
```

## Where to drop the finished GIF

1. Commit the final `docs/demo.gif` at ≤ 5 MB. GitHub renders up to
   10 MB inline but smaller loads faster on slow networks.
2. Replace the placeholder in `README.md`:

   ```markdown
   <!-- DEMO: 15-30s GIF of cross-model handoff goes here. Capture script: docs/demo-capture.md -->
   ```

   with:

   ```markdown
   <div align="center">
     <img src="docs/demo.gif" alt="Orion — set a fact in Codex, recall it in Gemini" width="760">
   </div>
   ```

3. Cross-check the GIF renders on a GitHub preview (push to a branch,
   open the README on github.com, scroll the hero).

## What NOT to do

- No slow title cards. The first frame must be a terminal prompt.
- No background music when converting from a video — GIFs have no audio
  anyway and the temptation to upload an MP4 with music is real. Don't.
- Don't show your real username, home directory, or filesystem paths
  with personal info. Record as a throwaway user or scrub with a
  post-processing pass.
- Don't dub subtitles over the typing — the typing itself is the
  demonstration. Quiet is the vibe.
