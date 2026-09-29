# Animation generation and review

A 4×4 sheet contains 16 distinct poses at 12 FPS (1.333 seconds). This is a short desktop micro-action; longer stories require more authored frames, not playback below target FPS. Use square sheets divisible by four, preferably 1024 or 1536 px. Equal cells, same padding/baseline, no dividing lines, labels, floor/shadows, bowls, floating Zs or effects. Eating is mimed unless props are explicitly requested.

Text mode generates an identity anchor first. Reference modes inspect the input, then generate an isolated cartoon anchor preserving visible identity and an existing cartoon's style. Use that same anchor for every action. With local-path reference tools, view the anchor then pass its path; otherwise include the smallest recent-image range containing it. Request actual alpha, not a painted checkerboard.

Lock color regions, ears/limb count, facial proportions, accessories and camera. Vary joints, eyelids, mouth, torso and tail. Do not generate unrelated characters per frame.

16-frame beats (numbers are prompt instructions, never image labels):
- Yawn: 1 neutral; 2–4 eyes narrow/mouth opens; 5–8 mouth widens, paws stretch overhead; 9–11 release; 12–15 paws lower/mouth closes; 16 almost neutral.
- Sleep: curled, eyes closed throughout; 1–8 slow inhalation; 9–16 exhalation. Tail relaxes. Turning over is optional and best reserved for a longer cycle.
- Eat: 1 head down; 2–6 small jaw/cheek motion; 7–10 head rises into satisfied expression; 11–16 lowers and resumes chewing. No separate bowl/crumbs.

The compiler applies one common scale across all actions and never independently rescales each frame. Bottom-centering suppresses layout drift but cannot repair changing anatomy/proportions. Choose cell alignment for meaningful authored root translation.

QA checks alpha, empty/cut-off cells, unique frames, decoded timing and seam difference. These do not determine whether the action is semantically correct or visually natural. Review contact sheets AND playback. Regenerate when identity or articulation fails.
