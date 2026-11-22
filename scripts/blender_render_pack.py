# SPDX-License-Identifier: MIT
# Blender headless 渲染打包：把 .glb 渲成 AI 生图素材
# 用法: blender -b -P scripts/blender_render_pack.py -- <in.glb> <outdir>
#         [--views N] [--size 1024] [--transparent] [--passes]
#
# 产物（outdir/render/）：
#   ref_XX.png     多角度参考图（轨道 N 张 + 俯视 + 花纹特写），可直接喂
#                  IP-Adapter / img2img / 视觉参考
#   depth_XX.png   归一化深度图（--passes，近=白）
#   normal_XX.png  世界空间法线图（--passes，-1..1 映射到 0..1）
import bpy
import math
import os
import sys

from mathutils import Vector


def _emission_tree():
    mat = bpy.data.materials.new("PassMat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return mat, nt, em


def make_depth_mat(cam_data):
    """相机空间 Z 距离 -> 0..1（近=白）自发光材质。"""
    mat, nt, em = _emission_tree()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    vt = nt.nodes.new("ShaderNodeVectorTransform")
    vt.vector_type = "POINT"
    vt.convert_from = "WORLD"
    vt.convert_to = "CAMERA"
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    span = cam_data.clip_end - cam_data.clip_start
    m1 = nt.nodes.new("ShaderNodeMath"); m1.operation = "MULTIPLY"
    m1.inputs[1].default_value = -1.0          # 相机 -Z 前向 -> 正距离
    m2 = nt.nodes.new("ShaderNodeMath"); m2.operation = "SUBTRACT"
    m2.inputs[1].default_value = cam_data.clip_start
    m3 = nt.nodes.new("ShaderNodeMath"); m3.operation = "DIVIDE"
    m3.inputs[1].default_value = span
    m4 = nt.nodes.new("ShaderNodeMath"); m4.operation = "SUBTRACT"
    m4.inputs[0].default_value = 1.0           # 近=白
    for a, b in ((geo.outputs["Position"], vt.inputs["Vector"]),
                 (vt.outputs["Vector"], sep.inputs[0]),
                 (sep.outputs["Z"], m1.inputs[0]),
                 (m1.outputs[0], m2.inputs[0]),
                 (m2.outputs[0], m3.inputs[0]),
                 (m3.outputs[0], m4.inputs[1]),
                 (m4.outputs[0], em.inputs["Color"])):
        nt.links.new(a, b)
    return mat


def make_normal_mat():
    """世界法线 -1..1 -> 0..1 自发光材质。"""
    mat, nt, em = _emission_tree()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    ma = nt.nodes.new("ShaderNodeMath")
    ma.operation = "MULTIPLY_ADD"
    ma.inputs[1].default_value = 0.5
    ma.inputs[2].default_value = 0.5
    nt.links.new(geo.outputs["Normal"], ma.inputs[0])
    nt.links.new(ma.outputs[0], em.inputs["Color"])
    return mat


def parse_args(argv):
    glb, outdir = argv[0], argv[1]
    opts = {"views": 8, "size": 1024, "transparent": False, "passes": False}
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--views":
            opts["views"] = int(argv[i + 1]); i += 2
        elif a == "--size":
            opts["size"] = int(argv[i + 1]); i += 2
        elif a == "--transparent":
            opts["transparent"] = True; i += 1
        elif a == "--passes":
            opts["passes"] = True; i += 1
        else:
            raise SystemExit(f"未知参数: {a}")
    return glb, outdir, opts


def pick_engine(candidates):
    items = {e.identifier for e in
             bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    for c in candidates:
        if c in items:
            return c
    return "CYCLES"


def mesh_bounds():
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not objs:
        raise SystemExit("场景里没有网格")
    mn, mx = Vector((1e9,) * 3), Vector((-1e9,) * 3)
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            mn = Vector(map(min, zip(mn, w)))
            mx = Vector(map(max, zip(mx, w)))
    return mn, mx


def look_at(cam, loc, target):
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def main():
    glb, outdir, opts = parse_args(sys.argv[sys.argv.index("--") + 1:])
    render_dir = os.path.join(outdir, "render")
    os.makedirs(render_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene

    mn, mx = mesh_bounds()
    center = (mn + mx) / 2
    radius = (mx - mn).length / 2
    # 50mm 镜头、36mm 传感器 -> 水平视角 39.6°，留 20% 边距
    hfov = 2 * math.atan(36.0 / (2 * 50.0))
    dist = radius / math.tan(hfov / 2) * 1.2

    # 相机 + 随相机布光（三点式，保证每个视角光照一致）
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    cam.data.clip_start = dist * 0.1
    cam.data.clip_end = dist * 3.0

    lights = []
    for name, loc, energy, size in (
            ("Key", (1.2, -1.2, 1.0), 40.0, 2.5),
            ("Fill", (-1.5, -0.8, 0.3), 17.0, 3.5),
            ("Rim", (0.0, 1.8, 0.8), 30.0, 2.0),
            ("Head", (0.25, -0.25, -0.7), 13.0, 3.0)):  # 近相机柔光，压平凹面伪阴影
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy * dist * dist
        ld.size = size * dist
        ob = bpy.data.objects.new(name, ld)
        scene.collection.objects.link(ob)
        ob.parent = cam
        ob.location = tuple(v * dist for v in loc)
        look_at(ob, ob.location, (0.0, 0.0, -dist))  # 汇聚到球心
        lights.append(ob)

    # 世界环境：均匀中灰环境光为主，消除硬阴影（AI 参考图要干净）
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    wnt = world.node_tree
    bg = next((n for n in wnt.nodes if n.type == "BACKGROUND"), None)
    if bg is None:
        bg = wnt.nodes.new("ShaderNodeBackground")
        wout = next((n for n in wnt.nodes if n.type == "OUTPUT_WORLD"), None)
        wnt.links.new(bg.outputs[0], wout.inputs[0])
    bg.inputs["Color"].default_value = (0.12, 0.12, 0.12, 1)

    scene.render.resolution_x = scene.render.resolution_y = opts["size"]
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.render.film_transparent = opts["transparent"]
    scene.use_nodes = False
    beauty_engine = pick_engine(["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"])

    # 视角列表：轨道 N + 俯视 + 特写
    views = []
    n = opts["views"]
    for i in range(n):
        az = math.radians(360.0 * i / n)
        el = math.radians(12.0)
        views.append(("ref_%02d" % (i + 1),
                      center + Vector((math.cos(az) * math.cos(el),
                                       math.sin(az) * math.cos(el),
                                       math.sin(el))) * dist))
    views.append(("ref_top", center + Vector((0.01, 0, 1)) * dist))
    views.append(("ref_close", center + Vector((0.7, -0.7, 0.35)).normalized()
                  * dist * 0.55))

    # 压低法线贴图强度：PES 法线偏强，侧光下凹纹会产生大片伪阴影
    for m in bpy.data.materials:
        mnt = m.node_tree
        if mnt:
            for nd in mnt.nodes:
                if nd.type == "NORMAL_MAP":
                    nd.inputs["Strength"].default_value = 0.4

    print(f"=== 渲染 {len(views)} 个视角 -> {render_dir} ===")
    scene.render.engine = beauty_engine
    if beauty_engine == "CYCLES":
        scene.cycles.samples = 24

    for name, loc in views:
        look_at(cam, loc, center)
        scene.render.filepath = os.path.join(render_dir, name + ".png")
        bpy.ops.render.render(write_still=True)
        print("OK", name)

    if opts["passes"]:
        # Blender 5.0 合成器不再支持 PNG 输出；改用材质覆盖+自发光直接渲 pass
        vl = bpy.context.view_layer
        for out_name, mat in (("depth", make_depth_mat(cam.data)),
                              ("normal", make_normal_mat())):
            vl.material_override = mat
            for name, loc in views:
                if name == "ref_close":
                    continue
                look_at(cam, loc, center)
                scene.render.filepath = os.path.join(
                    render_dir, out_name + "_" + name[4:] + ".png")
                bpy.ops.render.render(write_still=True)
                print("OK", out_name, name)
            vl.material_override = None

    print("DONE", render_dir)


main()
