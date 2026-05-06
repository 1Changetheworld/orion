The founder principle from `feedback_orion-must-be-alive.md` — "many small specialized parts coordinating like cells/bodies/cars" — is more than analogy. Cell biology is the most thoroughly-studied example of a working system built this way, and most of its design patterns are directly applicable.

Worth treating as a discipline, not a vibe.

## Patterns we should study and steal from

| Biology | Orion mapping |
|---|---|
| **Receptor-ligand signaling** (cell surface receptor recognizes a specific molecule, triggers an internal cascade) | Host presence agent recognizes the USB beacon, triggers the bootstrap cascade. Receptor = agent; ligand = beacon. |
| **Endocytosis** (cell engulfs an external molecule and brings it inside the membrane) | Bootstrap actor "absorbs" the host's state — discovers CLIs, reads configs, internalizes them into Orion's worldview. |
| **Mitochondrial endosymbiosis** (a separate organism became part of every cell, providing energy in exchange for membership) | Orion + AI model. The model provides compute (the energy); Orion provides identity, memory, continuity (the cell's body). Both benefit. Mutualistic. |
| **Apoptosis** (programmed cell death — clean self-destruction when conditions warrant) | Cleanup actor on USB unmount. Not a crash. A coordinated removal of every Orion footprint from the host. |
| **Selective membrane permeability** (some molecules pass, some don't — the cell controls what enters) | MCP registration boundary. Orion only writes to CLI configs the user explicitly consented to. The membrane is consent. |
| **Quorum sensing** (bacteria detect their own population density and change behavior collectively) | Multi-CLI awareness. When Orion is registered in 3 CLIs and the user opens a 4th, Orion can "sense" it and offer to integrate. |
| **Chaperone proteins** (escort molecules to ensure they fold correctly during synthesis) | The setup wizard. Walks the user through proto-Orion's first folding into a working state on this host. |
| **DNA repair mechanisms** (constant detection and correction of mutations) | Self-healing layer (`project_orion-deterministic-selfhealing.md`). Orion notices when his brain has drifted, attempts repair before damage propagates. |
| **Synaptic plasticity** (memory at the neural level — strength of connections changes with use) | Memory weighting. Frequently-recalled facts get higher confidence; unused facts decay (the half-life concept in `project_orion-temporal-memory.md`). |
| **Hormone signaling** (long-distance, slow, affects many cells at once) | Future: cross-instance Orion broadcasts — when one Orion learns something, the network of Orions can update (mesh mode, `project_orion-mesh-mode.md`). |
| **Antibody specificity** (immune system recognizes "self" vs "foreign") | Identity continuity (`project_orion-identity-continuity.md`). Orion recognizes its person through pattern, not credential — same way an antibody recognizes its antigen. |

## How to use this

When designing any new piece of Orion, ask: **what biological pattern is the closest analog?** If you can't find one, you're probably designing a wrapper instead of a part. Force the question.

When naming new architectural pieces, the cellular vocabulary is honest engineering language (receptor, beacon, cascade, membrane, signaling) without being cringy or Marvel-shaped. Use it.

When deciding whether a feature is worth building, check: does it create emergence (parts working together produce behavior none could alone)? If yes, build. If it's just one more procedure call that does one more thing, skip — you're adding complexity without coordination, the opposite of cellular.

## Reference reading worth doing (for the founder, post-launch)

- *Molecular Biology of the Cell* (Alberts et al.) — canonical text, especially chapters on signaling and membrane biology.
- *The Vital Question* (Nick Lane) — endosymbiosis origin, energy/information coupling. Orion's "model is jet fuel, memory is intelligence" is Lane's argument applied to AI.
- *Lehninger Principles of Biochemistry* — for the molecular-level mechanics of how small parts coordinate at scale.

These aren't for entertainment. They're for the design vocabulary.
