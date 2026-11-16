"""Низкополигональный человек по приметам (рост, телосложение, кожа, причёска, борода, одежда).

build_mesh(name, person, pose) → bpy.types.Mesh. Стопы в начале координат, лицом к +Y.
Поза — углы суставов в градусах (см. POSES / pose_*). Меш собирается через bmesh из примитивов,
у каждой части свой материал (кожа, верх, низ, обувь, волосы, борода, глаза, аксессуар).
"""
import math

import bmesh
import bpy
from mathutils import Matrix, Vector

BUILDS = {   # ширина плеч, толщина груди, толщина рук/ног, живот
    "slim": (0.36, 0.20, 0.050, 0.00),
    "athletic": (0.43, 0.24, 0.060, 0.00),
    "muscular": (0.50, 0.27, 0.075, 0.00),
    "heavy": (0.48, 0.30, 0.072, 0.10),
    "giant": (0.56, 0.32, 0.085, 0.04),
}
SLOTS = ["skin", "top", "bottom", "shoes", "hair", "beard", "eyes", "extra"]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple((int(h[i:i + 2], 16) / 255) ** 2.2 for i in (0, 2, 4)) + (1,)


def materials(prefix, p):
    cols = {"skin": p.get("skin", "#E0AC8A"), "top": p.get("top_color", p.get("skin", "#E0AC8A")),
            "bottom": p.get("bottom_color", "#334488"), "shoes": p.get("shoes", "#222222"),
            "hair": p.get("hair_color", "#3A2A1A"), "beard": p.get("beard_color", p.get("hair_color", "#3A2A1A")),
            "eyes": "#111111", "extra": p.get("extra_color", "#C0262D")}
    out = []
    for k in SLOTS:
        m = bpy.data.materials.new(f"{prefix}_{k}")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = hex_rgb(cols[k])
        b.inputs["Roughness"].default_value = 0.55 if k == "skin" else 0.8
        if k == "skin":
            b.inputs["Subsurface Weight"].default_value = 0.05
        out.append(m)
    return out


# ---------------------------------------------------------------- позы
def pose_stand():
    return dict(sh=(6, 6), el=(12, 12), ab=(9, 9), hip=(0, 0), kn=(2, 2), lab=(3, 3), lean=0, twist=0)


def pose_run(ph):
    s = math.sin(ph * 2 * math.pi)
    return dict(sh=(-40 * s, 40 * s), el=(85, 85), ab=(12, 12),
                hip=(38 * s, -38 * s), kn=(20 + 45 * max(0, -s), 20 + 45 * max(0, s)),
                lab=(3, 3), lean=12, twist=0)


def pose_fly():
    return dict(sh=(150, 160), el=(25, 20), ab=(70, 65), hip=(25, -10), kn=(35, 15), lab=(25, 20), lean=-10, twist=0)


def pose_punch(k, side):
    """k 0..1 — выпад и возврат; side 1 — правая, −1 — левая."""
    ext = math.sin(min(1, k) * math.pi)
    hit = (95 * ext, 70)             # (плечо, локоть) бьющей
    guard = (55, 115)
    sh = (guard[0], hit[0] + 50 * (1 - ext)) if side > 0 else (hit[0] + 50 * (1 - ext), guard[0])
    el = (guard[1], hit[1] * (1 - ext) + 5) if side > 0 else (hit[1] * (1 - ext) + 5, guard[1])
    return dict(sh=sh, el=el, ab=(20, 20), hip=(18, -12), kn=(25, 18), lab=(8, 8), lean=8,
                twist=-18 * ext * side)


def pose_walk(t):
    s = math.sin(t * 2 * math.pi)
    return dict(sh=(-20 * s, 20 * s), el=(25, 25), ab=(14, 14), hip=(22 * s, -22 * s),
                kn=(10 + 25 * max(0, -s), 10 + 25 * max(0, s)), lab=(3, 3), lean=4, twist=0)


def pose_struggle(t):
    s = math.sin(t * 9)
    return dict(sh=(120 + 30 * s, 120 - 30 * s), el=(40, 40), ab=(40, 40), hip=(30, -20), kn=(60, 40),
                lab=(10, 10), lean=-15, twist=10 * s)


# ---------------------------------------------------------------- геометрия
def rot_x(d):
    return Matrix.Rotation(math.radians(d), 4, "X")


def rot_y(d):
    return Matrix.Rotation(math.radians(d), 4, "Y")


def limb_dir(pitch, abduct, side):
    """Направление конечности из «вниз»: pitch вперёд (+Y), abduct в сторону (side ±1)."""
    v = Vector((0, 0, -1))
    v = rot_x(pitch) @ v.to_4d()           # +pitch — вперёд, к лицу (+Y)
    v = rot_y(-abduct * side) @ v
    return Vector(v[:3]).normalized()


class Builder:
    def __init__(self):
        self.bm = bmesh.new()

    def _mat(self, geom, mi):
        for f in geom:
            if isinstance(f, bmesh.types.BMFace):
                f.material_index = mi
                f.smooth = True

    def ellipsoid(self, c, r, mi, seg=10, rings=6, m=None):
        mat = Matrix.Translation(c) @ (m or Matrix()) @ Matrix.Diagonal((r[0], r[1], r[2], 1))
        g = bmesh.ops.create_uvsphere(self.bm, u_segments=seg, v_segments=rings, radius=1, matrix=mat)
        self._mat(set(f for v in g["verts"] for f in v.link_faces), mi)

    def capsule(self, a, b, r, mi, r2=None, seg=8):
        a, b = Vector(a), Vector(b)
        d = b - a
        L = max(d.length, 1e-4)
        q = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_matrix().to_4x4()
        mat = Matrix.Translation((a + b) / 2) @ q
        g = bmesh.ops.create_cone(self.bm, cap_ends=True, segments=seg, radius1=r, radius2=r2 or r,
                                  depth=L, matrix=mat)
        self._mat(set(f for v in g["verts"] for f in v.link_faces), mi)
        self.ellipsoid(a, (r, r, r), mi, seg=seg, rings=4)

    def box(self, c, s, mi, m=None):
        mat = Matrix.Translation(c) @ (m or Matrix()) @ Matrix.Diagonal((s[0], s[1], s[2], 1))
        g = bmesh.ops.create_cube(self.bm, size=1, matrix=mat)
        self._mat(set(f for v in g["verts"] for f in v.link_faces), mi)

    def mesh(self, name, dz=0.0):
        if dz:
            bmesh.ops.translate(self.bm, verts=self.bm.verts, vec=(0, 0, dz))
        me = bpy.data.meshes.new(name)
        self.bm.to_mesh(me)
        self.bm.free()
        return me


def build_mesh(name, p, pose, mats, center=False):
    """center=True — начало координат в тазу (для экземпляров толпы: вращение в полёте вокруг центра)."""
    H = p.get("height", 1.8)
    sw, cd, lt, belly = BUILDS[p.get("build", "athletic")]
    k = H / 1.8
    sw, cd, lt = sw * k * p.get("width", 1), cd * k * p.get("width", 1), lt * k * p.get("width", 1)
    SK, TOP, BOT, SHO, HAI, BEA, EYE, EXT = range(8)
    top = TOP if p.get("top", "none") != "none" else SK
    sleeves = p.get("top") in ("tshirt", "jacket", "gi", "hoodie")
    long_sleeves = p.get("top") in ("jacket", "gi", "hoodie")
    bot = p.get("bottom", "shorts")
    B = Builder()

    leg_len = 0.47 * H
    hip_z = leg_len + 0.04 * k
    torso_h = 0.30 * H
    sh_z = hip_z + torso_h
    lean = pose.get("lean", 0)
    tw = pose.get("twist", 0)
    body_m = rot_x(-lean) @ Matrix.Rotation(math.radians(tw), 4, "Z")

    def T(v):  # поворот корпуса вокруг таза
        return Vector((0, 0, hip_z)) + (body_m @ (Vector(v) - Vector((0, 0, hip_z))).to_4d()).to_3d()

    # таз и корпус
    B.ellipsoid(Vector((0, 0, hip_z + 0.02 * k)), (sw * 0.42, cd * 0.48, 0.11 * k), BOT if bot != "none" else SK,
                m=body_m)
    B.ellipsoid(T((0, 0.02 * belly, hip_z + torso_h * 0.42)), (sw * 0.40 + belly * 0.5, cd * 0.50 + belly, torso_h * 0.36),
                top, m=body_m)
    B.ellipsoid(T((0, 0, sh_z - torso_h * 0.18)), (sw * 0.52, cd * 0.52, torso_h * 0.26), top, m=body_m)
    if p.get("top") == "gi" or p.get("belt"):
        B.ellipsoid(T((0, 0, hip_z + 0.06 * k)), (sw * 0.44, cd * 0.54, 0.035 * k), EXT, m=body_m)
    # шея и голова
    neck = T((0, 0, sh_z + 0.03 * k))
    B.capsule(T((0, 0, sh_z - 0.05 * k)), neck, 0.055 * k * (1.2 if p.get("build") in ("muscular", "giant") else 1), SK)
    hc = T((0, 0.01, sh_z + 0.13 * k))
    hr = 0.115 * k
    hm = body_m
    B.ellipsoid(hc, (hr * 0.86, hr * 0.98, hr * 1.08), SK, seg=12, rings=8, m=hm)
    fwd = lambda x, y, z: hc + (hm @ Vector((x, y, z)).to_4d()).to_3d()  # noqa: E731
    for s in (-1, 1):  # глаза, брови
        B.ellipsoid(fwd(s * hr * 0.33, hr * 0.86, hr * 0.15), (hr * 0.11,) * 3, EYE, seg=6, rings=4)
        B.box(fwd(s * hr * 0.35, hr * 0.92, hr * 0.33), (hr * 0.32, hr * 0.06, hr * 0.07), HAI)
    B.ellipsoid(fwd(0, hr * 0.98, -hr * 0.02), (hr * 0.12, hr * 0.14, hr * 0.2), SK, seg=6, rings=4)
    hair = p.get("hair", "short")
    if hair in ("short", "buzz", "long", "spiky", "ponytail"):
        th = {"buzz": 1.03, "short": 1.08, "long": 1.1, "spiky": 1.08, "ponytail": 1.08}[hair]
        B.ellipsoid(fwd(0, -hr * 0.06, hr * 0.22), (hr * 0.9 * th, hr * 0.98 * th, hr * 0.9 * th), HAI, seg=12, rings=7)
        if hair == "long":
            B.ellipsoid(fwd(0, -hr * 0.55, -hr * 0.6), (hr * 0.85, hr * 0.45, hr * 0.95), HAI)
        if hair == "ponytail":
            B.capsule(fwd(0, -hr * 0.9, 0), fwd(0, -hr * 1.3, -hr * 1.4), hr * 0.18, HAI, r2=hr * 0.08)
        if hair == "spiky":
            for i in range(7):
                a = -1.2 + i * 0.4
                B.capsule(fwd(math.sin(a) * hr * 0.5, -hr * 0.1, hr * 0.85),
                          fwd(math.sin(a) * hr * 0.8, -hr * 0.3, hr * 1.35), hr * 0.13, HAI, r2=0.004, seg=5)
    elif hair == "mohawk":
        B.box(fwd(0, -hr * 0.1, hr * 0.9), (hr * 0.25, hr * 1.7, hr * 0.5), HAI)
    beard = p.get("beard", "none")
    if beard in ("full", "stubble", "goatee"):
        if beard == "full":
            B.ellipsoid(fwd(0, hr * 0.55, -hr * 0.55), (hr * 0.78, hr * 0.5, hr * 0.62), BEA)
            B.box(fwd(0, hr * 0.92, -hr * 0.17), (hr * 0.55, hr * 0.1, hr * 0.12), BEA)
        elif beard == "goatee":
            B.ellipsoid(fwd(0, hr * 0.8, -hr * 0.7), (hr * 0.3, hr * 0.25, hr * 0.32), BEA)
        else:
            B.ellipsoid(fwd(0, hr * 0.45, -hr * 0.45), (hr * 0.82, hr * 0.56, hr * 0.62), BEA)
    acc = p.get("accessory")
    if acc == "headband":
        B.ellipsoid(fwd(0, 0, hr * 0.35), (hr * 0.95, hr * 1.02, hr * 0.16), EXT, seg=12, rings=4)
    elif acc == "sunglasses":
        B.box(fwd(0, hr * 0.95, hr * 0.15), (hr * 1.2, hr * 0.08, hr * 0.25), EYE)
    elif acc == "cap":
        B.ellipsoid(fwd(0, 0, hr * 0.35), (hr * 0.95, hr * 1.0, hr * 0.7), EXT, seg=12, rings=6)
        B.box(fwd(0, hr * 1.05, hr * 0.38), (hr * 1.2, hr * 0.8, hr * 0.06), EXT)
    elif acc == "crown":
        B.capsule(fwd(0, 0, hr * 0.9), fwd(0, 0, hr * 1.25), hr * 0.65, EXT, r2=hr * 0.75, seg=8)

    # руки
    gloves = p.get("gloves")
    for i, s in enumerate((-1, 1)):    # 0 левая (x<0), 1 правая
        shp = T((s * sw * 0.5, 0, sh_z - 0.04 * k))
        up = limb_dir(pose["sh"][i], pose["ab"][i], s)
        up = (body_m @ up.to_4d()).to_3d()
        elb = shp + up * 0.19 * H
        fd = limb_dir(pose["sh"][i] + pose["el"][i], pose["ab"][i] * 0.6, s)
        fd = (body_m @ fd.to_4d()).to_3d()
        wr = elb + fd * 0.16 * H
        B.capsule(shp, elb, lt * 1.05, top if sleeves else SK, r2=lt * 0.9)
        B.capsule(elb, wr, lt * 0.85, top if long_sleeves else SK, r2=lt * 0.7)
        B.ellipsoid(wr + fd * 0.05 * k, (0.11 * k,) * 3 if gloves else (lt * 0.95, lt * 0.95, lt * 1.2),
                    EXT if gloves else SK, seg=8, rings=5)
    # ноги
    for i, s in enumerate((-1, 1)):
        hp = Vector((s * sw * 0.22, 0, hip_z))
        th = limb_dir(pose["hip"][i], pose["lab"][i], s)
        kn = hp + th * 0.245 * H
        sd = limb_dir(pose["hip"][i] - pose["kn"][i], pose["lab"][i], s)
        an = kn + sd * 0.23 * H
        thigh_m = BOT if bot != "none" else SK
        shin_m = BOT if bot in ("pants", "gi") else SK
        B.capsule(hp, kn, lt * 1.45, thigh_m, r2=lt * 1.15)
        if bot == "shorts":
            B.capsule(hp, hp + th * 0.16 * H, lt * 1.6, BOT, r2=lt * 1.45)
        B.capsule(kn, an, lt * 1.1, shin_m, r2=lt * 0.8)
        fm = Vector((0, 1, 0))
        foot_dir = (rot_x(pose["hip"][i] - pose["kn"][i]) @ fm.to_4d()).to_3d()
        B.box(an + foot_dir * 0.07 * k + Vector((0, 0, -0.03 * k)), (0.10 * k, 0.26 * k, 0.08 * k), SHO,
              m=rot_x(pose["hip"][i] - pose["kn"][i]))
    me = B.mesh(name, -hip_z if center else 0.0)
    for m in mats:
        me.materials.append(m)
    return me


def crowd_poses():
    """Позы для экземпляров толпы (порядок важен — индексы в sim.py)."""
    return [pose_stand()] + [pose_run(i / 4) for i in range(4)] + [pose_fly()]


def hip_height(p):
    return 0.47 * p.get("height", 1.8) + 0.04 * p.get("height", 1.8) / 1.8
