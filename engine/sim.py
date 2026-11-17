"""Симуляция битвы «толпа против героя» — чистый numpy, без Blender.

Детерминирована: одинаковый spec → одинаковые кадры на любой машине, поэтому кадры можно
рендерить кусками на разных машинах GitHub. Тот же модуль считает звук (удары по кадрам).

Режимы бойца: 0 стоит в строю, 1 бежит к герою, 2 летит после удара, 3 лежит (часть горы).
Гора — карта высот: каждое приземлившееся тело поднимает клетку, бегущие и герой идут по ней.
"""
import math

import numpy as np

G = 9.81
CELL = 0.5          # м, клетка карты высот
HALF = 160.0        # м, поле [-HALF, HALF]²
BODY = 0.32         # м, на сколько тело поднимает клетку

STAND, RUN, FLY, LIE = 0, 1, 2, 3
# индексы поз в коллекции экземпляров (см. scene.py): 0 стоит, 1–4 бег, 5 полёт/лежит
POSE_STAND, POSE_RUN0, POSE_FLY = 0, 1, 5


class Sim:
    def __init__(self, spec):
        self.spec = spec
        cr, he = spec["crowd"], spec["hero"]
        self.fps = spec.get("fps", 30)
        self.sub = 2
        self.dt = 1.0 / (self.fps * self.sub)
        rnd = np.random.default_rng(spec.get("seed", 1))
        self.rnd = rnd
        n = int(cr["count"])
        self.n = n
        sp = cr.get("spacing", 0.95)
        cols = int(math.ceil(math.sqrt(n * cr.get("aspect", 2.0))))
        rows = int(math.ceil(n / cols))
        ix = np.arange(n) % cols
        iy = np.arange(n) // cols
        x = (ix - (cols - 1) / 2) * sp + rnd.normal(0, 0.08, n)
        y = cr.get("front", 22.0) + iy * sp + rnd.normal(0, 0.08, n)
        self.pos = np.stack([x, y, np.zeros(n)], 1).astype(np.float64)
        self.vel = np.zeros((n, 3))
        self.rot = np.zeros((n, 3))
        self.rot[:, 2] = math.pi          # лицом к герою (модель смотрит на +Y)
        self.angv = np.zeros((n, 3))
        self.mode = np.zeros(n, np.int8)
        wave = cr.get("wave_speed", 9.0)
        self.t_start = cr.get("charge_at", 1.0) + iy * sp / wave + rnd.uniform(0, 0.4, n)
        lo, hi = cr.get("speed", [4.2, 6.5])
        self.speed = rnd.uniform(lo, hi, n)
        self.aim = rnd.normal(0, cr.get("aim_spread", 0.7), (n, 2))
        self.phase = rnd.uniform(0, 1, n)
        self.cadence = self.speed / 3.2           # шагов-циклов в секунду
        self.yaw_lie = rnd.uniform(-math.pi, math.pi, n)
        self.side = rnd.choice([-1.0, 1.0], n)

        self.hero = np.array(he.get("start", [0.0, 0.0, 0.0]), float)
        self.hero_walk = he.get("walk", 1.0)
        self.hit_r = he.get("hit_radius", 1.7)
        self.power = he.get("power", [7.0, 14.0])
        self.lift = he.get("lift", [5.0, 11.0])
        self.loses_at = he.get("loses_at")
        self.stop_at = he.get("stop_walk_at")
        self.walk_at = he.get("walk_at", cr.get("charge_at", 1.0))   # до атаки герой стоит в стойке
        k = int(2 * HALF / CELL)
        self.hm = np.zeros((k, k))
        self.t = 0.0
        self.frame = 0
        self.hits_frame = 0
        self.last_hit_t = -9.0
        self.punch_side = 1.0

    # ------------------------------------------------------------ карта высот
    def cells(self, xy):
        c = np.floor((xy + HALF) / CELL).astype(int)
        return np.clip(c, 0, self.hm.shape[0] - 1)

    def height(self, xy):
        c = self.cells(xy)
        return self.hm[c[..., 0], c[..., 1]]

    def deposit(self, xy):
        c = self.cells(xy)
        k = self.hm.shape[0] - 1
        np.add.at(self.hm, (c[:, 0], c[:, 1]), BODY)
        for dx, dy, w in ((1, 0, .3), (-1, 0, .3), (0, 1, .3), (0, -1, .3)):   # сглаживание склона
            np.add.at(self.hm, (np.clip(c[:, 0] + dx, 0, k), np.clip(c[:, 1] + dy, 0, k)), BODY * w)

    # ------------------------------------------------------------ шаг
    def hero_active(self):
        return self.loses_at is None or self.t < self.loses_at

    def step(self):
        dt, t = self.dt, self.t
        m = self.mode
        # герой идёт в толпу и поднимается по горе
        if t >= self.walk_at and (self.stop_at is None or t < self.stop_at):
            self.hero[1] += self.hero_walk * dt
        hz = self.height(self.hero[None, :2])[0]
        self.hero[2] += (hz - self.hero[2]) * min(1, dt * 6)

        go = (m == STAND) & (t >= self.t_start)
        m[go] = RUN

        run = m == RUN
        if run.any():
            p = self.pos[run]
            tgt = self.hero[:2] + self.aim[run] * np.clip(np.hypot(*(p[:, :2] - self.hero[:2]).T) / 25, 0, 1)[:, None]
            d = tgt - p[:, :2]
            dist = np.hypot(d[:, 0], d[:, 1]) + 1e-6
            v = d / dist[:, None] * self.speed[run][:, None]
            p[:, :2] += v * dt
            p[:, 2] += (self.height(p[:, :2]) - p[:, 2]) * min(1, dt * 10)
            self.pos[run] = p
            self.vel[run, :2] = v
            self.rot[run, 0] = 0
            self.rot[run, 1] = 0
            self.rot[run, 2] = np.arctan2(-v[:, 0], v[:, 1])

            rel = self.pos[run, :2] - self.hero[:2]
            close = np.hypot(rel[:, 0], rel[:, 1]) < self.hit_r
            idx = np.flatnonzero(run)[close]
            if len(idx):
                if self.hero_active():
                    self.launch(idx)
                else:               # герой выдохся — его заваливают телами
                    self.mode[idx] = LIE
                    self.pos[idx, 2] = self.height(self.pos[idx, :2]) + 0.15
                    self.rot[idx] = np.stack([self.side[idx] * math.pi / 2, np.zeros(len(idx)), self.yaw_lie[idx]], 1)
                    self.deposit(self.pos[idx, :2])
                    self.hero[2] = max(self.hero[2], self.height(self.hero[None, :2])[0])

        fly = m == FLY
        if fly.any():
            self.vel[fly, 2] -= G * dt
            self.pos[fly] += self.vel[fly] * dt
            self.rot[fly] += self.angv[fly] * dt
            ground = self.height(self.pos[fly, :2]) + 0.15
            land = (self.pos[fly, 2] <= ground) & (self.vel[fly, 2] < 0)
            idx = np.flatnonzero(fly)[land]
            if len(idx):
                self.mode[idx] = LIE
                self.pos[idx, 2] = self.height(self.pos[idx, :2]) + 0.15
                self.rot[idx] = np.stack([self.side[idx] * math.pi / 2, np.zeros(len(idx)), self.yaw_lie[idx]], 1)
                self.deposit(self.pos[idx, :2])
        self.t += dt

    def launch(self, idx):
        k = len(idx)
        rel = self.pos[idx, :2] - self.hero[:2]
        ang = np.arctan2(rel[:, 1], rel[:, 0]) + self.rnd.uniform(-0.5, 0.5, k)
        sp = self.rnd.uniform(*self.power, k)
        self.vel[idx, 0] = np.cos(ang) * sp
        self.vel[idx, 1] = np.sin(ang) * sp
        self.vel[idx, 2] = self.rnd.uniform(*self.lift, k)
        self.angv[idx] = self.rnd.uniform(-9, 9, (k, 3))
        self.pos[idx, 2] += 0.8
        self.mode[idx] = FLY
        self.hits_frame += k
        self.last_hit_t = self.t
        self.punch_side = -self.punch_side

    # ------------------------------------------------------------ кадры
    def advance_to(self, frame):
        """Довести симуляцию до кадра frame (1 = t 0). Возвращает число ударов за последний кадр."""
        hits = 0
        while self.frame < frame:
            self.hits_frame = 0
            if self.frame > 0:
                for _ in range(self.sub):
                    self.step()
            self.frame += 1
            hits = self.hits_frame
        return hits

    def poses(self):
        p = np.full(self.n, POSE_STAND, np.int32)
        run = self.mode == RUN
        cyc = np.floor((self.t * self.cadence[run] + self.phase[run]) * 4).astype(int) % 4
        p[run] = POSE_RUN0 + cyc
        p[self.mode >= FLY] = POSE_FLY
        return p

    def remaining(self):
        return int(np.count_nonzero(self.mode <= RUN))

    def hero_pose(self):
        """Поза героя: удар (чередуя руки), пока рядом бьют; иначе ходьба/стойка."""
        since = self.t - self.last_hit_t
        if self.hero_active() and since < 0.35:
            k = since / 0.35
            return {"kind": "punch", "k": k, "side": self.punch_side}
        if not self.hero_active():
            return {"kind": "struggle", "t": self.t}
        if self.t < self.walk_at:
            return {"kind": "guard", "t": self.t}
        return {"kind": "walk", "t": self.t * self.hero_walk / 1.2}


def frames_total(spec):
    return int(round(spec["duration"] * spec.get("fps", 30)))


def hit_track(spec):
    """Удары и численность по кадрам (для звука и счётчика) — без Blender."""
    s = Sim(spec)
    hits, left = [], []
    for f in range(1, frames_total(spec) + 1):
        hits.append(s.advance_to(f))
        left.append(s.remaining())
    return hits, left
