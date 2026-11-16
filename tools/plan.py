"""Делит кадры битвы на куски для параллельного рендера. Печатает строку для $GITHUB_OUTPUT."""
import json
import math
import sys

MAX_JOBS = 20     # бесплатный лимит одновременных машин
MIN_CHUNK = 8     # меньше — сборка сцены и прогон симуляции съедают выигрыш

spec = json.load(open(sys.argv[1], encoding="utf-8"))
n = int(round(spec["duration"] * spec.get("fps", 30)))
chunk = max(MIN_CHUNK, math.ceil(n / MAX_JOBS))
inc = [{"a": a, "b": min(n, a + chunk - 1)} for a in range(1, n + 1, chunk)]
print("matrix=" + json.dumps(inc))
print("mh=" + ("true" if spec["crowd"].get("mh") or spec["hero"].get("mh") else "false"))
