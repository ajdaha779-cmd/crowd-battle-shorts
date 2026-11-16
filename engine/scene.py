"""Рендер куска кадров битвы.

    blender -b -P engine/scene.py -- fights/<id>.json <первый> <последний> <папка> [--preview]

Сцена собирается с нуля из spec (детерминированно), симуляция доводится до первого кадра
куска, затем каждый кадр: позиции толпы → точки с экземплярами (Geometry Nodes),
поза героя → новый меш, камера по плану → PNG. Готовые кадры пропускаются.
"""
import json
import math
import os
import random
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_np = os.path.join(os.path.dirname(HERE), ".np311")   # Mac (macOS 12): numpy Blender'а не грузится — свой
if sys.platform == "darwin" and os.path.isdir(_np):
    sys.path.insert(0, _np)
import person as P  # noqa: E402
import sim as S  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
SPEC_PATH, F0, F1, OUT = argv[0], int(argv[1]), int(argv[2]), argv[3]
PREVIEW = "--preview" in argv
CHARS = next((a.split("=", 1)[1] for a in argv if a.startswith("--chars=")), None)   # characters.blend (MakeHuman)
spec = json.load(open(SPEC_PATH, encoding="utf-8"))
FPS = spec.get("fps", 30)
RES = spec.get("render", {}).get("res", 1080)
SAMPLES = spec.get("render", {}).get("samples", 16)
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
rnd = random.Random(spec.get("seed", 1))


def mat(name, color, rough=0.9):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = P.hex_rgb(color)
    b.inputs["Roughness"].default_value = rough
    return m


def link(obj, coll=None):
    (coll or sc.collection).objects.link(obj)
    return obj


# ---------------------------------------------------------------- мир
def build_world():
    w = bpy.data.worlds.new("World")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    sky = nt.nodes.new("ShaderNodeTexSky")
    sky.sky_type = "NISHITA"
    sky.sun_elevation = math.radians(spec.get("sun_elevation", 38))
    sky.sun_rotation = math.radians(spec.get("sun_rotation", 200))
    sky.air_density = 1.2
    sky.dust_density = 2.5
    bg = nt.nodes["Background"]
    bg.inputs["Strength"].default_value = 0.4
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])

    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = 4.0
    sun.angle = math.radians(2)
    so = link(bpy.data.objects.new("Sun", sun))
    so.rotation_euler = (math.radians(90 - spec.get("sun_elevation", 38)), 0, math.radians(spec.get("sun_rotation", 200) - 90))

    # земля: смесь травы и сухой травы шумом
    bpy.ops.mesh.primitive_plane_add(size=900)
    g = bpy.context.object
    g.name = "Ground"
    m = bpy.data.materials.new("Ground")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 1.0
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.035
    noise.inputs["Detail"].default_value = 6
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ramp.color_ramp
    cr.elements[0].position, cr.elements[0].color = 0.35, P.hex_rgb("#4C7A1F")
    cr.elements[1].position, cr.elements[1].color = 0.62, P.hex_rgb("#A8862A")
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    fine = nt.nodes.new("ShaderNodeTexNoise")
    fine.inputs["Scale"].default_value = 3.0
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 0.35
    nt.links.new(tc.outputs["Object"], fine.inputs["Vector"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["A"])
    nt.links.new(fine.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], b.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.3
    nt.links.new(fine.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    g.data.materials.append(m)

    # дальние холмы и горы
    hill = mat("Hill", "#3E6630")
    rock = mat("Rock", "#4D5A52")
    for i in range(14):
        a = rnd.uniform(0, 2 * math.pi)
        d = rnd.uniform(260, 380)
        big = i < 5
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
        o = bpy.context.object
        r = rnd.uniform(90, 150) if big else rnd.uniform(40, 80)
        o.scale = (r, r * rnd.uniform(0.6, 1.0), r * (rnd.uniform(0.45, 0.7) if big else rnd.uniform(0.25, 0.4)))
        o.location = (math.cos(a) * d, math.sin(a) * d, -r * 0.15)
        o.data.materials.append(rock if big else hill)
        bpy.ops.object.shade_smooth()

    # деревья: экземпляры одного дерева
    trunk, crown = mat("Trunk", "#5A4027"), mat("Crown", "#3E6B2C")
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=0.18, depth=2.0, location=(0, 0, 1.0))
    t1 = bpy.context.object
    t1.data.materials.append(trunk)
    bpy.ops.mesh.primitive_cone_add(vertices=7, radius1=1.6, depth=5.0, location=(0, 0, 4.2))
    t2 = bpy.context.object
    t2.data.materials.append(crown)
    bpy.ops.object.select_all(action="DESELECT")
    t1.select_set(True)
    t2.select_set(True)
    bpy.context.view_layer.objects.active = t1
    bpy.ops.object.join()
    tree = t1
    tree.location = (0, 0, -100)
    for i in range(spec.get("trees", 420)):
        a = rnd.uniform(0, 2 * math.pi)
        d = rnd.uniform(75, 250)
        x, y = math.cos(a) * d, math.sin(a) * d
        o = link(bpy.data.objects.new(f"Tree{i}", tree.data))
        s = rnd.uniform(0.7, 1.5)
        o.scale = (s, s, s * rnd.uniform(0.8, 1.3))
        o.location = (x, y, 0)


# ---------------------------------------------------------------- толпа
def append_collection(name):
    with bpy.data.libraries.load(CHARS, link=False) as (src, dst):
        dst.collections = [name]
        dst.scenes = [s for s in src.scenes][:1]
    coll = dst.collections[0]
    sc.collection.children.link(coll)
    info = json.loads(dst.scenes[0].get("battle_info", "{}")) if dst.scenes else {}
    if dst.scenes:
        bpy.data.scenes.remove(dst.scenes[0])
    return coll, info


def build_crowd(sim):
    global HIP
    if CHARS and spec["crowd"].get("mh"):
        coll, info = append_collection("CrowdPoses")
        HIP = info.get("crowd_hip", 0.95)
    else:
        p = spec["crowd"]["person"]
        mats = P.materials("crowd", p)
        coll = bpy.data.collections.new("CrowdPoses")
        sc.collection.children.link(coll)
        for i, pose in enumerate(P.crowd_poses()):
            me = P.build_mesh(f"pose{i}", p, pose, mats, center=True)
            link(bpy.data.objects.new(f"{i}_pose", me), coll)
        HIP = P.hip_height(p)
    bpy.context.view_layer.layer_collection.children["CrowdPoses"].exclude = True

    me = bpy.data.meshes.new("CrowdPts")
    me.vertices.add(sim.n)
    me.attributes.new("rot", "FLOAT_VECTOR", "POINT")
    me.attributes.new("pose", "INT", "POINT")
    obj = link(bpy.data.objects.new("Crowd", me))
    gn = bpy.data.node_groups.new("CrowdGN", "GeometryNodeTree")
    gn.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    gn.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n = gn.nodes
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    iop = n.new("GeometryNodeInstanceOnPoints")
    ci = n.new("GeometryNodeCollectionInfo")
    ci.inputs["Collection"].default_value = coll
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True
    na_rot = n.new("GeometryNodeInputNamedAttribute")
    na_rot.data_type = "FLOAT_VECTOR"
    na_rot.inputs["Name"].default_value = "rot"
    na_pose = n.new("GeometryNodeInputNamedAttribute")
    na_pose.data_type = "INT"
    na_pose.inputs["Name"].default_value = "pose"
    e2r = n.new("FunctionNodeEulerToRotation")
    iop.inputs["Pick Instance"].default_value = True
    L = gn.links.new
    L(gi.outputs[0], iop.inputs["Points"])
    L(ci.outputs[0], iop.inputs["Instance"])
    L(na_pose.outputs["Attribute"], iop.inputs["Instance Index"])
    L(na_rot.outputs["Attribute"], e2r.inputs["Euler"])
    L(e2r.outputs["Rotation"], iop.inputs["Rotation"])
    L(iop.outputs["Instances"], go.inputs[0])
    mod = obj.modifiers.new("Crowd", "NODES")
    mod.node_group = gn
    return obj


def update_crowd(obj, sim, hip):
    import numpy as np
    pos = sim.pos.copy()
    upright = sim.mode <= S.RUN
    pos[upright, 2] += hip
    me = obj.data
    me.vertices.foreach_set("co", pos.astype(np.float32).ravel())
    me.attributes["rot"].data.foreach_set("vector", sim.rot.astype(np.float32).ravel())
    me.attributes["pose"].data.foreach_set("value", sim.poses().astype(np.int32))
    me.update()


# ---------------------------------------------------------------- герой
HERO_MATS = None
HIP = 0.95


def hero_pose_now(sim):
    hp = sim.hero_pose()
    return {"punch": lambda: P.pose_punch(hp["k"], hp["side"]),
            "walk": lambda: P.pose_walk(hp["t"]),
            "struggle": lambda: P.pose_struggle(hp["t"])}[hp["kind"]]()


def update_hero(obj, sim):
    pose = hero_pose_now(sim)
    if obj.type == "ARMATURE":          # живой герой MakeHuman: только поза скелета
        import rigpose as RP
        obj.location = Vector(sim.hero)
        obj.rotation_euler = (0, 0, math.pi)
        obj.scale = (spec["hero"].get("scale", 1.0),) * 3
        RP.apply(obj, pose)
        return
    old = obj.data
    obj.data = P.build_mesh("hero", spec["hero"]["person"], pose, HERO_MATS)
    bpy.data.meshes.remove(old)
    obj.location = Vector(sim.hero)
    obj.scale = (spec["hero"].get("scale", 1.0),) * 3


# ---------------------------------------------------------------- камера
def shot_at(t):
    cur = spec["shots"][0]
    for s in spec["shots"]:
        if t >= s["t"]:
            cur = s
    nxt = [s["t"] for s in spec["shots"] if s["t"] > cur["t"]]
    end = nxt[0] if nxt else spec["duration"]
    return cur, (t - cur["t"]) / max(1e-3, end - cur["t"]), t - cur["t"]


def place_camera(cam, sim):
    s, k, local = shot_at(sim.t)
    H = Vector(sim.hero)
    up = Vector((0, 0, 1.2))
    typ = s["type"]
    if typ == "aerial":
        loc = Vector(s["from"]) + Vector(s.get("drift", (0, 0, 0))) * k
        look = Vector(s["to"])
    elif typ == "behind":
        loc = H + Vector((s.get("side", 0.8), -s.get("dist", 6), s.get("height", 2.5)))
        look = H + Vector((0, 12, 0.6))
    elif typ == "front":
        loc = H + Vector((s.get("side", 1.5), s.get("dist", 5), s.get("height", 1.4)))
        look = H + up
    elif typ == "orbit":
        a = math.radians(s.get("start", -60)) + s.get("speed", 0.3) * local
        loc = H + Vector((math.cos(a) * s.get("radius", 14), math.sin(a) * s.get("radius", 14), s.get("height", 8)))
        look = H + up
    elif typ == "top":
        loc = H + Vector((0, -s.get("back", 15), s.get("height", 40)))
        look = H
    else:
        raise ValueError(typ)
    cam.location = loc
    d = look - loc
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = s.get("lens", 24)


# ---------------------------------------------------------------- сборка и рендер
sim = S.Sim(spec)
build_world()
crowd = build_crowd(sim)
if CHARS and spec["hero"].get("mh"):
    append_collection("Hero")
    hero = bpy.data.objects["HeroRig"]
else:
    HERO_MATS = P.materials("hero", spec["hero"]["person"])
    hero = link(bpy.data.objects.new("Hero", bpy.data.meshes.new("hero0")))
camd = bpy.data.cameras.new("Cam")
camd.clip_end = 1500
cam = link(bpy.data.objects.new("Cam", camd))
sc.camera = cam

sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = 6 if PREVIEW else SAMPLES
sc.cycles.use_denoising = True
sc.cycles.denoiser = "OPENIMAGEDENOISE"
sc.cycles.use_adaptive_sampling = True
sc.cycles.adaptive_threshold = 0.05
sc.cycles.max_bounces = 4
sc.cycles.diffuse_bounces = 2
sc.cycles.glossy_bounces = 1
sc.cycles.transmission_bounces = 0
sc.cycles.caustics_reflective = sc.cycles.caustics_refractive = False
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.resolution_percentage = 40 if PREVIEW else 100
sc.view_settings.view_transform = "Standard"
sc.view_settings.exposure = spec.get("exposure", -2.1)
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.compression = 30

hip = HIP
for f in range(F0, F1 + 1):
    sim.advance_to(f)
    path = os.path.join(OUT, f"{f:05d}.png")
    if os.path.exists(path):
        continue
    update_crowd(crowd, sim, hip)
    update_hero(hero, sim)
    place_camera(cam, sim)
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("FRAME_DONE", f, flush=True)
print("CHUNK_DONE", F0, F1)
