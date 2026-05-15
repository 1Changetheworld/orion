# Motion Tracking — Research + Implementation Path

> Founder vision 2026-05-15: Orion controlled by hand gestures against the projector wall, like the viral Obsidian-3D-graph demos. Make it a mode anyone can enable.

This memo gathers what's actually being done in the wild and lays out the path for Orion's motion-tracking mode.

## What others are using (2026 state of the art)

### MediaPipe Hands (Google)
- 21 3D landmarks per hand from a single RGB frame
- Runs locally — WebAssembly in the browser, no cloud, no images stored
- The standard for webcam-based hand tracking
- JS / Python / C++ SDKs

### Obsidian Gesture Control plugin (already exists)
- Repo: `github.com/with-geun/obsidian-gesture-control`
- MediaPipe WASM running locally
- 8 named gestures (Palm, Fist, Thumb Up / Down, Victory, ILoveYou, OK, Three) mapped to Obsidian commands
- Continuous mode: point with both hands → zoom / cursor / click / drag
- Currently macOS-focused (AVFoundation), adaptable
- **Quick win**: the founder can install this today for Obsidian-specific gestures while we build the Orion-wide layer.

### Common pipeline for 3D-graph hand control
The pattern across published demos:

```
webcam (or Kinect)
  → MediaPipe / Kinect SDK → 21 hand landmarks per frame
  → coordinate normalization + gesture classification
  → WebSocket / OSC / publish to substrate
  → 3D renderer (Three.js / TouchDesigner / OpenGL)
  → updated camera pose, selected node, gesture-triggered action
```

The `TouchDesigner + MediaPipe + OSC` stack is most common in installations. Pure-JS Three.js + MediaPipe Hands JS works in any browser tab.

### Depth cameras (vs. plain webcam)
- **Xbox 360 Kinect**: legacy but cheap. Drivers via `libfreenect` (open) or `OpenNI2`. Depth + IR, ignores projected RGB content — ideal when you're tracking hands against a projection.
- **Intel RealSense (D435 / D455)**: current production-grade depth camera. SDK is good, USB 3.
- **Leap Motion / Ultraleap**: dedicated hand tracker, very low latency, mounted on desk facing up.
- **Quest Pro / Apple Vision Pro hand APIs**: high quality but require the headset; less useful for projector-wall scenarios.

## Founder's setup — Orion-specific recommendation

The founder's room: projector covers a whole wall, founder faces away from his desk. OUTPOST (the iMac) currently has the only camera on the mesh, positioned wrong.

### Phase 1 — Webcam + MediaPipe in the browser (cheapest, fastest)
- Mount a USB webcam where it can see his hand against the projection.
- Add MediaPipe Hands JS into the existing `interactive-visualizer/index.html` (already loads d3 + 3d-force-graph; adding `@mediapipe/hands` is one more script).
- Map five gestures to graph actions:
  - **Pinch (thumb + index touch)** → select / drag node
  - **Open palm + sweep** → rotate camera
  - **Fist** → zoom in
  - **Spread fingers** → zoom out
  - **Point at panel** → open detail
- Publish gestures to substrate (`gesture.<name>.detected`) so other Orion surfaces can react.
- No depth, no extra hardware. Works if projector lighting on the hand isn't too overwhelming.

### Phase 2 — Kinect (depth-aware, robust against projector light)
- Plug the Xbox 360 Kinect into FORGE (USB) — the Pi is also fine via libfreenect on Linux.
- `libfreenect` exposes depth + IR streams.
- IR stream is invisible to the projector — perfect: the hand silhouette stands out clearly regardless of what's projected.
- Same Three.js / visualizer renderer. New input service: `motion_tracker.py` reads depth, segments hand, computes pose, publishes `gesture.<name>.detected`.
- Calibration once per room (corner-detection for projection-plane mapping).

### Phase 3 — Production "Motion Mode"
- Orion has a `motion-tracking` mode that the user toggles by saying or typing "Orion, enter motion mode."
- Brain marks the substrate state; the visualizer starts listening for gesture events; channels suppress non-urgent interruptions.
- Exit: "Orion, exit motion mode" or a five-finger spread held for 2 seconds.

## Implementation discipline

1. **All processing local.** MediaPipe WASM in the browser. No cloud video.
2. **Substrate-first.** Gestures publish `gesture.*` events; renderers + brain react. New surfaces (a future AR headset, a Vision Pro app) plug into the same substrate.
3. **Gesture vocabulary stays small.** Five primary gestures + chord combinations. More gestures = more accidental misfires.
4. **Calibration in the brain.** Per-room calibration (projector corners, depth zero-plane) memorized so it survives restarts.
5. **Fail loud, not silent.** If the camera drops, narrator fires "motion mode degraded — falling back to mouse/keyboard."

## Tasks queued

- `#20 Motion-tracking interaction mode (Kinect / projector wall)` — primary engineering item, covers Phase 1 + 2 above.
- `#21 Mind-shape visualization — embeddings-driven 3D thought network` — what the user is gesturing AT once motion mode is live.

## Why this is a real differentiator

Mem0 / Letta / Khoj / Cursor — none of them have a gesture-control surface. Obsidian has the gesture-control plugin but it controls *Obsidian*, not a personal AI. Orion + Motion Mode = the first personal-AI brain you reach by reaching toward it.

## Sources

- [On-Device, Real-Time Hand Tracking with MediaPipe — Google Research](https://research.google/blog/on-device-real-time-hand-tracking-with-mediapipe/)
- [Obsidian Gesture Control Plugin](https://github.com/with-geun/obsidian-gesture-control) — direct precedent, MediaPipe WASM, local
- [Hand Tracking in 3D Space using MediaPipe and PnP Method](https://ieeexplore.ieee.org/document/9641587/) — IEEE paper on the projection / 3D-cursor mapping
- [Real-time hand tracking visualization using MediaPipe and TouchDesigner](https://wjarr.com/content/real-time-hand-tracking-visualization-using-media-pipe-and-touch-designer) — pipeline reference
- [Hand Tracking with MediaPipe — Three.js sample](https://deepwiki.com/collidingScopes/threejs-handtracking-101/5.3-hand-tracking-with-mediapipe) — closest match to Orion's stack
