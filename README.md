# Crowd Battle Shorts

Procedural "huge crowd vs one hero" battles for vertical Shorts. Original low-poly characters,
deterministic numpy crowd simulation, Blender Cycles rendering split across GitHub Actions runners.

- `fights/*.json` — battle specs (crowd, hero look, camera shots, titles)
- `engine/sim.py` — crowd simulation (numpy)
- `engine/person.py` — low-poly person builder from traits
- `engine/scene.py` — Blender scene + chunk renderer
- `engine/finalize.py` — titles, counter, synthesized audio, ffmpeg
- `.github/workflows/render.yml` — plan → parallel render → video

Fonts: Montserrat (SIL Open Font License).
