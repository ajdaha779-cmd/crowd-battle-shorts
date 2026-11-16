"""Живые персонажи MakeHuman (MPFB) → characters.blend. Только в облаке (см. render.yml, job «characters»).

    blender -b -P engine/characters.py -- fights/<id>.json <assets.zip> <out.blend>

Сторона битвы со блоком "mh" собирается из MakeHuman:
  "mh": {"phenotype": {"gender": 1, "age": 0.5, "muscle": 0.7, "weight": 0.5, "height": 0.6,
                       "proportions": 0.5, "race": {"caucasian": 1, "african": 0, "asian": 0}},
         "face": {"nose-scale-horiz": 0.4, "chin-width": -0.3, "head-oval": 0.6},   # −1..1
         "skin": "young_caucasian_male", "hair": "short02", "eyebrows": "eyebrow001",
         "eyes": "brown", "clothes": ["male_casualsuit01", "shoes01"],
         "colors": {"hair": "#C9A040", "clothes": {"male_casualsuit01": "#22334A"}}}
Толпа → коллекция CrowdPoses (6 запечённых поз, как у person.crowd_poses, начало в тазу, лицом к +Y).
Герой → коллекция Hero: арматура HeroRig с мешами, позы ставит scene.py через rigpose.
"""
import json
import math
import os
import sys
import zipfile

import addon_utils  # noqa: F401
import bpy
from mathutils import Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import person as P  # noqa: E402
import rigpose as RP  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
SPEC, ASSETS, OUT = argv[0], argv[1], argv[2]
spec = json.load(open(SPEC, encoding="utf-8"))

PKG = "bl_ext.user_default.mpfb"
mpfb = __import__(PKG, fromlist=["services"])
from bl_ext.user_default.mpfb.services.humanservice import HumanService  # noqa: E402
from bl_ext.user_default.mpfb.services.objectservice import ObjectService  # noqa: E402

# ассеты MakeHuman (CC0) — в папку данных MPFB
DATA = os.path.join(bpy.utils.extension_path_user(PKG, create=True), "data")
if not os.path.isdir(os.path.join(DATA, "skins")):
    os.makedirs(DATA, exist_ok=True)
    with zipfile.ZipFile(ASSETS) as z:
        z.extractall(DATA)
    print("ASSETS", DATA)

TARGETS = json.load(open(os.path.join(os.path.dirname(mpfb.__file__), "data", "targets", "target.json")))
OPP = {}
for grp in TARGETS.values():
    for c in grp.get("categories", []):
        OPP[c["name"].rsplit("-", 2)[0] if c["name"].endswith("-decr-incr") else c["name"]] = c
        OPP[c["name"]] = c


def face_targets(face):
    """{"nose-scale-horiz": 0.4} → [{"target": "nose-scale-horiz-incr", "value": 0.4}] (и левую/правую сторону)."""
    out = []
    for name, v in (face or {}).items():
        c = OPP.get(name) or OPP.get(name + "-decr-incr")
        if not c:
            print("WARN нет такой настройки лица:", name)
            continue
        o = c.get("opposites") or {}
        sign = "positive" if v >= 0 else "negative"
        if c.get("has_left_and_right"):
            names = [o.get(f"{sign}-left"), o.get(f"{sign}-right")]
        else:
            names = [o.get(f"{sign}-unsided")] if o else [c["name"]]
        for n in names:
            if n:
                out.append({"target": n, "value": abs(float(v))})
    return out


def human_info(mh, name):
    ph = {"gender": 1.0, "age": 0.5, "muscle": 0.5, "weight": 0.5, "proportions": 0.5, "height": 0.5,
          "cupsize": 0.5, "firmness": 0.5, "race": {"asian": 0.0, "caucasian": 1.0, "african": 0.0}}
    ph.update({k: v for k, v in mh.get("phenotype", {}).items() if k != "race"})
    if "race" in mh.get("phenotype", {}):
        ph["race"] = mh["phenotype"]["race"]
    hi = HumanService._create_default_human_info_dict()
    hi.update({
        "name": name,
        "phenotype": ph,
        "targets": face_targets(mh.get("face")),
        "rig": "game_engine",
        "eyes": "high-poly.mhclo",
        "eyebrows": f"{mh.get('eyebrows', 'eyebrow001')}.mhclo",
        "eyelashes": "eyelashes01.mhclo",
        "teeth": "teeth_base.mhclo",
        "tongue": "",
        "hair": f"{mh['hair']}.mhclo" if mh.get("hair") else "",
        "proxy": "",
        "clothes": [f"{c}.mhclo" for c in mh.get("clothes", [])],
        "skin_mhmat": f"{mh.get('skin', 'young_caucasian_male')}.mhmat",
        "skin_material_type": "MAKESKIN",
        "eyes_material_type": "MAKESKIN",
        "clothes_material_type": "MAKESKIN",
    })
    return hi


def tint(objs, color):
    """Перекраска (волосы/одежда): умножаем базовый цвет текстуры на нужный оттенок."""
    rgba = P.hex_rgb(color)
    for o in objs:
        for slot in o.material_slots:
            m = slot.material
            if not m or not m.use_nodes:
                continue
            m = m.copy()
            slot.material = m
            nt = m.node_tree
            bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if not bsdf:
                continue
            base = bsdf.inputs["Base Color"]
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.inputs["B"].default_value = rgba
            if base.is_linked:
                src = base.links[0].from_socket
                nt.links.new(src, mix.inputs["A"])
                # светлая текстура × цвет: сначала обесцвечиваем, чтобы оттенок лёг ровно
            else:
                mix.inputs["A"].default_value = base.default_value
            nt.links.new(mix.outputs["Result"], base)


def build(mh, name):
    settings = HumanService.get_default_deserialization_settings()
    settings["subdiv_levels"] = 0
    settings["load_clothes"] = True
    base = HumanService.deserialize_from_dict(human_info(mh, name), settings)
    rig = ObjectService.find_object_of_type_amongst_nearest_relatives(base, "Skeleton")
    kids = [o for o in bpy.data.objects if o.type == "MESH" and (o == base or o.parent in (base, rig))]
    cols = mh.get("colors", {})
    if cols.get("hair"):
        tint([o for o in kids if "hair" in o.name.lower() or "eyebrow" in o.name.lower()], cols["hair"])
    for cname, c in (cols.get("clothes") or {}).items():
        tint([o for o in kids if cname.lower() in o.name.lower()], c)
    return base, rig, kids


def bake(rig, kids, pose, name, hip_z):
    """Текущая поза → один статичный меш (тело + одежда + волосы), начало в тазу, лицом к +Y."""
    RP.apply(rig, pose)
    dg = bpy.context.evaluated_depsgraph_get()
    parts = []
    for o in kids:
        ev = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=False, depsgraph=dg)
        me.transform(o.matrix_world)
        tmp = bpy.data.objects.new("tmp_" + o.name, me)
        bpy.context.scene.collection.objects.link(tmp)
        parts.append(tmp)
    bpy.ops.object.select_all(action="DESELECT")
    for t in parts:
        t.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    obj = parts[0]
    obj.name = name
    obj.data.name = name
    obj.data.transform(Matrix.Rotation(math.pi, 4, "Z") @ Matrix.Translation((0, 0, -hip_z)))
    for p in obj.data.polygons:
        p.use_smooth = True
    bpy.context.scene.collection.objects.unlink(obj)
    return obj


def hip_height(rig):
    pb = rig.pose.bones.get("pelvis")
    return (rig.matrix_world @ pb.head).z if pb else 0.95


def delete(objs):
    for o in objs:
        bpy.data.objects.remove(o, do_unlink=True)


sc = bpy.context.scene      # без read_factory_settings — он выключил бы MPFB
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
info = {}

cr = spec["crowd"].get("mh")
if cr:
    base, rig, kids = build(cr, "Crowd")
    RP.reset(rig)
    bpy.context.view_layer.update()
    hz = hip_height(rig)
    coll = bpy.data.collections.new("CrowdPoses")
    sc.collection.children.link(coll)
    for i, pose in enumerate(P.crowd_poses()):
        coll.objects.link(bake(rig, kids, pose, f"{i}_pose", hz))
    delete(kids + [rig])
    info["crowd_hip"] = hz

he = spec["hero"].get("mh")
if he:
    base, rig, kids = build(he, "Hero")
    rig.name = "HeroRig"
    coll = bpy.data.collections.new("Hero")
    sc.collection.children.link(coll)
    for o in [rig] + kids:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)
    RP.reset(rig)

sc["battle_info"] = json.dumps(info)
bpy.ops.file.pack_all()
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(OUT), compress=True)
print("CHARACTERS_DONE", OUT, info)
