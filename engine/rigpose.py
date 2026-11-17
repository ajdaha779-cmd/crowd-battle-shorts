"""Позы для скелета MakeHuman «game_engine» по тем же углам суставов, что и person.py.

Персонаж MakeHuman смотрит на −Y, наши позы считаются для взгляда на +Y — направления
поворачиваем на 180° вокруг Z. Кость наводится на нужное направление вращением вокруг
своего начала (без возни с roll): pose_bone.matrix задаётся в пространстве арматуры.
"""
import math

import bpy
from mathutils import Matrix, Vector

import person as P

FLIP = Matrix.Rotation(math.pi, 4, "Z")      # +Y-пространство поз → −Y-пространство MakeHuman


def _dir(v):
    return (FLIP @ Vector(v).to_4d()).to_3d().normalized()


def _aim(arm, name, target_dir):
    pb = arm.pose.bones.get(name)
    if pb is None:
        return
    bpy.context.view_layer.update()
    cur = pb.matrix.copy()
    head = cur.to_translation()
    rest_dir = (cur.to_3x3() @ Vector((0, 1, 0))).normalized()     # ось Y кости — от начала к концу
    q = rest_dir.rotation_difference(target_dir)
    pb.matrix = Matrix.Translation(head) @ q.to_matrix().to_4x4() @ Matrix.Translation(-head) @ cur


def reset(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
        pb.scale = (1, 1, 1)


def apply(arm, pose):
    """pose — словарь углов (см. person.pose_*)."""
    reset(arm)
    lean = math.radians(pose.get("lean", 0))
    tw = math.radians(pose.get("twist", 0))
    up = Vector((0, math.sin(lean), math.cos(lean)))
    up = (Matrix.Rotation(tw, 4, "Z") @ up.to_4d()).to_3d()
    for b in ("spine_01", "spine_02", "spine_03"):
        _aim(arm, b, _dir(up))
    for i, (sfx, s) in enumerate((("l", -1), ("r", 1))):     # левая — x<0 при взгляде на +Y
        sh, el, ab = pose["sh"][i], pose["el"][i], pose["ab"][i]
        _aim(arm, f"upperarm_{sfx}", _dir(P.limb_dir(sh, max(ab, 8), s)))
        _aim(arm, f"lowerarm_{sfx}", _dir(P.limb_dir(sh + el, max(ab, 8) * 0.6, s)))
        hip, kn, lab = pose["hip"][i], pose["kn"][i], pose["lab"][i]
        _aim(arm, f"thigh_{sfx}", _dir(P.limb_dir(hip, lab, s)))
        _aim(arm, f"calf_{sfx}", _dir(P.limb_dir(hip - kn, lab, s)))
        foot = Vector((0, math.cos(math.radians(hip - kn)), math.sin(math.radians(hip - kn)) - 0.35))
        _aim(arm, f"foot_{sfx}", _dir(foot))
    if pose.get("fist", True):
        fist(arm)
    bpy.context.view_layer.update()


FIST_SIGN = 1.0


def fist(arm, deg=(55, 85, 70)):
    """Кулаки: сгибаем фаланги вокруг локальной оси X кости."""
    from mathutils import Quaternion
    for f in ("index", "middle", "ring", "pinky"):
        for k, d in zip(("01", "02", "03"), deg):
            for sfx in ("l", "r"):
                pb = arm.pose.bones.get(f"{f}_{k}_{sfx}")
                if pb:
                    pb.rotation_mode = "QUATERNION"
                    pb.rotation_quaternion = Quaternion((1, 0, 0), math.radians(d) * FIST_SIGN)
    for sfx in ("l", "r"):
        pb = arm.pose.bones.get(f"thumb_02_{sfx}")
        if pb:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = Quaternion((1, 0, 0), math.radians(40) * FIST_SIGN)
