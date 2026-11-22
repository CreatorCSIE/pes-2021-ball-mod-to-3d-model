# Blender headless 验证脚本：导入 .glb，统计几何/贴图，另存 .blend
# SPDX-License-Identifier: MIT
# 用法: blender -b -P scripts/blender_check.py -- <in.glb> <out.blend>
import bpy
import sys

argv = sys.argv[sys.argv.index("--") + 1:]
glb_path, blend_path = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)

print("=== 导入统计 ===")
for ob in bpy.context.scene.objects:
    if ob.type == "MESH":
        me = ob.data
        xs = [v.co[i] for v in me.vertices for i in range(3)]
        print(f"MESH {me.name}: verts={len(me.vertices)} "
              f"loops={len(me.loops)} polys={len(me.polygons)} "
              f"uv_layers={len(me.uv_layers)} materials={len(me.materials)}")
        print(f"  bbox min=({min(me.vertices, key=lambda v: v.co.x).co.x:.4f},"
              f"{min(me.vertices, key=lambda v: v.co.y).co.y:.4f},"
              f"{min(me.vertices, key=lambda v: v.co.z).co.z:.4f}) "
              f"max=({max(me.vertices, key=lambda v: v.co.x).co.x:.4f},"
              f"{max(me.vertices, key=lambda v: v.co.y).co.y:.4f},"
              f"{max(me.vertices, key=lambda v: v.co.z).co.z:.4f})")
for img in bpy.data.images:
    print(f"IMAGE {img.name}: size={tuple(img.size)} has_data={img.has_data} "
          f"file={img.filepath or '(embedded)'}")
for mat in bpy.data.materials:
    nt = mat.node_tree
    nodes = [n.type for n in nt.nodes] if nt else []
    print(f"MATERIAL {mat.name}: nodes={nodes}")

bpy.ops.wm.save_as_mainfile(filepath=blend_path)
print(f"SAVED {blend_path}")
