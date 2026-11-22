#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# -*- coding: utf-8 -*-
"""PES 2021 ball mod 转换器：ball.fpk -> glTF 2.0 (.glb)，ball 贴图 .ftex -> .dds。

纯 Python 标准库实现，无第三方依赖。
格式细节见 docs/pes2021-model-format.md。

用法：
    python scripts/pes_ball_convert.py "<...>/ball951/#Win/ball.fpk" [-o output目录]

输出：
    <outdir>/<球名>.glb          模型（位置/法线/切线/UV/索引 + 材质与贴图引用）
    <outdir>/<球名>_<槽>.dds     #windx11 内全部 ftex 转换出的 DDS 贴图
"""

import argparse
import glob
import json
import os
import struct
import sys
import zlib

# --------------------------------------------------------------------------
# FPK 容器
# --------------------------------------------------------------------------

def fpk_extract(data):
    """解析单条目 FPK 容器，返回 (条目文件名, 载荷字节)。"""
    if data[:10] != b"foxfpk\x00win":
        raise ValueError("不是 FPK 容器（magic 不匹配）")
    entry_count = struct.unpack_from("<I", data, 0x24)[0]
    data_off, data_len = struct.unpack_from("<QQ", data, 0x30)
    name = data[0x60:0x70].split(b"\x00")[0].decode("ascii", "replace")
    if entry_count != 1:
        raise ValueError(f"当前仅支持单条目 FPK（条目数={entry_count}）")
    return name, data[data_off:data_off + data_len]


# --------------------------------------------------------------------------
# FMDL 解析
# --------------------------------------------------------------------------

S0_ESIZES = {0: 48, 1: 8, 2: 32, 3: 48, 4: 16, 5: 68, 6: 4, 7: 4, 8: 4,
             9: 8, 10: 8, 11: 4, 12: 8, 13: 32, 14: 16, 16: 16, 18: 8,
             17: 8, 20: 128}

# 顶点属性语义（datumType）与编码（datumFormat），与社区实现一致
DT_POSITION, DT_BONEW, DT_NORMAL, DT_COLOR = 0, 1, 2, 3
DT_BONEIDX, DT_UV0, DT_UV1, DT_UV2, DT_UV3, DT_TANGENT = 7, 8, 9, 10, 11, 14
DF_3F32, DF_2F32, DF_4F16, DF_2F16, DF_4U8, DF_4I8 = 1, 2, 6, 7, 8, 9


class Fmdl:
    def __init__(self, data):
        self.data = data
        (magic, self.version, desc_off, s0bm, s1bm, s0cnt, s1cnt,
         self.s0off, s0len, self.s1off, s1len) = struct.unpack_from(
            "<4s I Q QQ II II II", data, 0)
        if magic != b"FMDL":
            raise ValueError(f"不是 FMDL（magic={magic!r}）")

        o = desc_off
        s0desc, s1desc = [], []
        for _ in range(s0cnt):
            bid, cnt, off = struct.unpack_from("<H H I", data, o)
            o += 8
            s0desc.append((bid, cnt, off))
        for _ in range(s1cnt):
            bid, off, ln = struct.unpack_from("<I I I", data, o)
            o += 12
            s1desc.append((bid, off, ln))

        # segment0：定长记录数组
        self.s0 = {}
        for bid, cnt, off in s0desc:
            es = S0_ESIZES.get(bid)
            if es is None:
                raise ValueError(f"未知 s0 块 {bid}（条目大小未知）")
            base = self.s0off + off
            self.s0[bid] = [data[base + i * es: base + (i + 1) * es]
                            for i in range(cnt)]

        # segment1：变长数据块。目录里的 len 常偏小，真实边界取下一块起点/文件尾
        self.s1 = {}
        s1sorted = sorted(s1desc, key=lambda t: t[1])
        for i, (bid, off, ln) in enumerate(s1sorted):
            start = self.s1off + off
            end = (self.s1off + s1sorted[i + 1][1]) if i + 1 < len(s1sorted) \
                else len(data)
            self.s1[bid] = data[start:end]

        # 字符串池
        self.strings = []
        for rec in self.s0.get(12, []):
            bid, ln, off = struct.unpack_from("<H H I", rec)
            self.strings.append(
                self.s1[bid][off:off + ln].decode("utf-8", "replace"))

    def string(self, idx):
        return self.strings[idx] if idx < len(self.strings) else ""

    def buffer_offsets(self):
        """b14 -> 相对 s1[2] 大缓冲的各 buffer 起始偏移。"""
        offs = []
        for rec in self.s0.get(14, []):
            _eof, _ln, off, _pad = struct.unpack_from("<I I I I", rec)
            offs.append(off)
        return offs

    def mesh_formats(self):
        """b10 -> [(bufferID, bufferOffset, increment, vFmtCnt)]。"""
        out = []
        for rec in self.s0.get(10, []):
            buf, vfc, inc, _type, off = struct.unpack_from("<B B B B I", rec)
            out.append((buf, off, inc, vfc))
        return out

    def vertex_formats(self):
        """b11 -> [(datumType, datumFormat, offset)]。"""
        out = []
        for rec in self.s0.get(11, []):
            dt, df, off = struct.unpack_from("<B B H", rec)
            out.append((dt, df, off))
        return out

    def mesh_vertex_format(self, fmt_assign_id):
        """b9 分配 -> 该 mesh 的 [(datumType, datumFormat, 绝对偏移, 步长)] 列表。"""
        rec = self.s0[9][fmt_assign_id]
        mf_cnt, vf_cnt, _fu, _uc, first_mf, first_vf = \
            struct.unpack_from("<B B B B H H", rec)
        buf_offs = self.buffer_offsets()
        mfmts, vfmts = self.mesh_formats(), self.vertex_formats()
        entries = []
        for i in range(first_mf, first_mf + mf_cnt):
            buf, boff, inc, vfc = mfmts[i]
            for _ in range(vfc):
                entries.append((buf_offs[buf] + boff, inc))
        if len(entries) != vf_cnt:
            raise ValueError("b9/b10 顶点格式条目数不一致")
        out = []
        for i in range(vf_cnt):
            dt, df, voff = vfmts[first_vf + i]
            block_off, inc = entries[i]
            out.append((dt, df, block_off + voff, inc))
        return out


def _read_attr(buf, pos, dt, df):
    """按 datumType/datumFormat 读取单个顶点属性，返回分量列表。"""
    if dt == DT_POSITION:
        if df != DF_3F32:
            raise ValueError(f"position 编码异常 {df}")
        return list(struct.unpack_from("<3f", buf, pos))
    if dt in (DT_NORMAL, DT_TANGENT):
        if df != DF_4F16:
            raise ValueError(f"normal/tangent 编码异常 {df}")
        return list(struct.unpack_from("<4e", buf, pos))
    if dt == DT_COLOR:
        if df != DF_4U8:
            raise ValueError(f"color 编码异常 {df}")
        return [v / 255.0 for v in struct.unpack_from("<4B", buf, pos)]
    if dt in (DT_UV0, DT_UV1, DT_UV2, DT_UV3):
        if df == DF_2F16:
            return list(struct.unpack_from("<2e", buf, pos))
        if df == DF_2F32:
            return list(struct.unpack_from("<2f", buf, pos))
        raise ValueError(f"uv 编码异常 {df}")
    return None  # 骨骼权重/索引等：球类模型不涉及蒙皮，跳过


def extract_meshes(fmdl):
    """遍历 b3，返回 [{name, positions, normals, tangents, uvs, indices,
    material_index, bbox}]。"""
    buf = fmdl.s1[2]
    face_indices = [struct.unpack_from("<I I", r) for r in fmdl.s0.get(17, [])]
    buf_offs = fmdl.buffer_offsets()
    meshes = []
    for idx, rec in enumerate(fmdl.s0.get(3, [])):
        (alpha, shadow, mat_inst, bone_grp, fmt_id, vcount,
         first_fv, fv_count, first_fi) = \
            struct.unpack_from("<B B 2x H H H H 4x I I Q 16x", rec)
        fmt = fmdl.mesh_vertex_format(fmt_id)

        positions, normals, tangents, uvs, colors = [], [], [], [], []
        for v in range(vcount):
            for dt, df, off, inc in fmt:
                vals = _read_attr(buf, off + v * inc, dt, df)
                if vals is None:
                    continue
                if dt == DT_POSITION:
                    positions.append(vals)
                elif dt == DT_NORMAL:
                    normals.append(vals[:3])
                elif dt == DT_TANGENT:
                    tangents.append(vals)
                elif dt == DT_COLOR:
                    colors.append(vals)
                elif dt in (DT_UV0, DT_UV1, DT_UV2, DT_UV3):
                    while len(uvs) <= dt - DT_UV0:
                        uvs.append([])
                    uvs[dt - DT_UV0].append(vals)

        lod_first, lod_cnt = face_indices[first_fi]
        start = first_fv + lod_first
        indices = list(struct.unpack_from(
            "<%dH" % (lod_cnt // 3 * 3), buf, buf_offs[2] + start * 2))
        # PES/DirectX 正面绕序为顺时针，glTF 要求逆时针：交换每三角形后两个索引
        for t in range(0, len(indices) - 2, 3):
            indices[t + 1], indices[t + 2] = indices[t + 2], indices[t + 1]
        # 绕序镜像后切线手性同步取反
        tangents = [v[:3] + [-v[3]] for v in tangents]

        bbox = None
        if 13 in fmdl.s0 and idx < len(fmdl.s0[13]):
            mx = struct.unpack_from("<8f", fmdl.s0[13][idx])
            bbox = (list(mx[4:7]), list(mx[0:3]))  # (min, max)

        meshes.append({
            "name": f"mesh_{idx}",
            "positions": positions, "normals": normals,
            "tangents": tangents, "uvs": uvs, "colors": colors,
            "indices": indices, "material_index": mat_inst,
            "vertex_count": vcount, "bbox": bbox,
        })
    return meshes


def extract_materials(fmdl):
    """返回 [{name, shader, tech, slots:[(槽名, 引用文件名)]}]，按 b4 顺序。"""
    out = []
    b6 = fmdl.s0.get(6, [])
    b7 = fmdl.s0.get(7, [])
    b8 = fmdl.s0.get(8, [])
    for rec in fmdl.s0.get(4, []):
        name_s, _p0, material, tex_cnt, param_cnt, first_tex, first_param, _p1 \
            = struct.unpack_from("<H H H B B H H I", rec)
        slots = []
        for j in range(tex_cnt):
            file_s, _dir_s = struct.unpack_from("<H H", b6[first_tex + j])
            # b7 前 tex_cnt 条为纹理槽参数：paramStr=槽名, refID=纹理序号
            slot = fmdl.string(file_s)
            if first_tex + j < len(b7):
                param_s, ref = struct.unpack_from("<H H", b7[first_tex + j])
                if ref == j:
                    slot = fmdl.string(param_s)
            slots.append((slot, fmdl.string(file_s)))
        shader = tech = ""
        if material < len(b8):
            sh_s, tc_s = struct.unpack_from("<H H", b8[material])
            shader, tech = fmdl.string(sh_s), fmdl.string(tc_s)
        out.append({"name": fmdl.string(name_s) or shader,
                    "shader": shader, "tech": tech, "slots": slots})
    return out


# --------------------------------------------------------------------------
# FTEX -> DDS
# --------------------------------------------------------------------------

PIXFMT_DXGI = {1: 61, 8: 80, 9: 83, 10: 95, 11: 98, 12: 10, 13: 2, 14: 24,
               15: 26}
PIXFMT_4CC = {2: b"DXT1", 3: b"DXT3", 4: b"DXT5"}


def ftex_to_dds(ftex_path, dds_path):
    with open(ftex_path, "rb") as fh:
        data = fh.read()
    (magic, version, pixfmt, w, h, depth, mip_cnt, _nrt, _flags,
     _u1, _u2, tex_type, ftexs_cnt, _u3, _h1, _h2) = struct.unpack_from(
        "<4s f H H H H B B H I I I B B 14x 8s 8s", data, 0)
    if magic != b"FTEX":
        raise ValueError(f"{os.path.basename(ftex_path)} 不是 FTEX")
    if not (2.025 <= version <= 2.045) or ftexs_cnt != 0 or mip_cnt == 0:
        raise ValueError(f"{os.path.basename(ftex_path)} FTEX 版本/结构不支持")

    if tex_type & 4:            # 立方体贴图
        image_count, dds_depth = 6, 1
        caps1, caps2 = 0x1008, 0xFE00
        ext_dim, ext_flags = 3, 0x4
    elif depth > 1:             # 体积纹理
        image_count, dds_depth = 1, depth
        caps1, caps2 = 0x1000, 0x200000
        ext_dim, ext_flags = 4, 0
        flags_extra = 0x800000
    else:                       # 普通 2D
        image_count, dds_depth = 1, 1
        caps1, caps2 = 0x1000, 0
        ext_dim, ext_flags = 3, 0
    flags = 0x1007 | (0x800000 if depth > 1 else 0)
    if mip_cnt > 1:
        flags |= 0x20000
        caps1 |= 0x40008
        dds_mip, mipmap_count = mip_cnt, mip_cnt
    else:
        dds_mip, mipmap_count = 0, 1

    # 收集各 mip 帧
    frames = []
    o = 64
    for _i in range(image_count):
        for j in range(mipmap_count):
            off, uncmp, cmpsz, index, _ftexs_no, chunk_cnt = \
                struct.unpack_from("<I I I B B H", data, o)
            o += 16
            if index != j:
                raise ValueError("mip 序号异常")
            frames.append(_read_image(data, off, chunk_cnt, uncmp, cmpsz))

    if pixfmt == 0:             # RGBA8：传统头 + bitfield
        pitch, flags2 = 4 * w, flags | 0x8
        fflags, fourcc = 0x41, b"\x00\x00\x00\x00"
        rgb_bits, masks = 32, (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
        use_dx10 = False
    else:
        pitch, flags2 = len(frames[0]), flags | 0x80000
        fflags, rgb_bits, masks = 0x4, 0, (0, 0, 0, 0)
        if pixfmt in PIXFMT_4CC:
            fourcc, use_dx10 = PIXFMT_4CC[pixfmt], False
            ext_fmt = None
        elif pixfmt in PIXFMT_DXGI:
            fourcc, use_dx10, ext_fmt = b"DX10", True, PIXFMT_DXGI[pixfmt]
        else:
            raise ValueError(f"不支持的像素格式 {pixfmt}")

    hdr = struct.pack("<4s 7I 44x 2I 4s 5I 2I 12x",
                      b"DDS ", 124, flags2, h, w, pitch, dds_depth, dds_mip,
                      32, fflags, fourcc, rgb_bits, *masks, caps1, caps2)
    if use_dx10:
        hdr += struct.pack("<5I", ext_fmt, ext_dim, ext_flags, 1, 0)
    with open(dds_path, "wb") as fh:
        fh.write(hdr)
        for fr in frames:
            fh.write(fr)
    return w, h, mip_cnt, pixfmt


def _read_image(data, image_off, chunk_cnt, uncmp_sz, cmp_sz):
    if chunk_cnt == 0:
        if cmp_sz == 0:
            return data[image_off:image_off + uncmp_sz]
        return zlib.decompress(data[image_off:image_off + cmp_sz])
    out = []
    o = image_off
    chunks = []
    for _ in range(chunk_cnt):
        csz, usz, coff = struct.unpack_from("<H H I", data, o)
        o += 8
        # bit31=1 表示未压缩；另外最小 mip 常见 cmp==uncmp 的原始块（无标志）
        raw = (coff & (1 << 31)) != 0 or csz == usz
        chunks.append((coff & ~(1 << 31), csz, raw))
    for coff, csz, raw in chunks:
        blob = data[image_off + coff: image_off + coff + csz]
        out.append(blob if raw else zlib.decompress(blob))
    return b"".join(out)


# --------------------------------------------------------------------------
# glTF 2.0 (.glb) 构建
# --------------------------------------------------------------------------

def _slot_kind(slot_name, file_name):
    s = (slot_name + " " + file_name).lower()
    if "base" in s or "bsm" in s:
        return "baseColor"
    if "normal" in s or "nrm" in s:
        return "normal"
    if "specular" in s or "srm" in s:
        return "specular"
    if "metal" in s or "mtl" in s:
        return "metalness"
    return "other"


class GlbBuilder:
    def __init__(self):
        self.bin = bytearray()
        self.views, self.accessors, self.images = [], [], []
        self.textures = []

    def add_view(self, blob, target=None):
        pad = (-len(self.bin)) % 4
        self.bin += b"\x00" * pad
        bv = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(blob)}
        if target:
            bv["target"] = target
        self.bin += blob
        self.views.append(bv)
        return len(self.views) - 1

    def add_accessor(self, view, ctype, csize, comp_type, count,
                     vtype, minv=None, maxv=None):
        a = {"bufferView": view, "componentType": comp_type, "count": count,
             "type": vtype}
        if minv is not None:
            a["min"], a["max"] = minv, maxv
        self.accessors.append(a)
        return len(self.accessors) - 1

    def add_image_dds(self, uri):
        self.images.append({"uri": uri, "mimeType": "image/vnd-ms.dds",
                            "extensions": {"MSFT_texture_dds": {"uri": uri}}})
        return len(self.images) - 1

    def add_texture(self, image_idx):
        self.textures.append({"source": image_idx,
                              "sampler": 0})
        return len(self.textures) - 1


def build_glb(meshes, materials, dds_files, ball_name):
    """生成 (glb 字节, 说明 dict)。dds_files: {槽类别: 文件名}。"""
    g = GlbBuilder()
    gltf_meshes, gltf_mats, used_images, mat_cache = [], [], {}, {}

    def image_for(kind):
        fn = dds_files.get(kind)
        if not fn:
            return None
        if fn not in used_images:
            used_images[fn] = g.add_image_dds(fn)
        tex = g.add_texture(used_images[fn])
        return {"index": tex, "texCoord": 0}

    for m in meshes:
        attrs = {}
        pos = m["positions"]
        if pos:
            flat = [c for v in pos for c in v]
            v = g.add_view(struct.pack("<%df" % len(flat), *flat), 34962)
            mn = [min(c[i] for c in pos) for i in range(3)]
            mx = [max(c[i] for c in pos) for i in range(3)]
            attrs["POSITION"] = g.add_accessor(
                v, None, None, 5126, len(pos), "VEC3", mn, mx)
        if m["normals"]:
            flat = [c for v in m["normals"] for c in v]
            v = g.add_view(struct.pack("<%df" % len(flat), *flat), 34962)
            attrs["NORMAL"] = g.add_accessor(v, None, None, 5126,
                                             len(m["normals"]), "VEC3")
        if m["tangents"]:
            flat = [c for v in m["tangents"] for c in v]
            v = g.add_view(struct.pack("<%df" % len(flat), *flat), 34962)
            attrs["TANGENT"] = g.add_accessor(v, None, None, 5126,
                                              len(m["tangents"]), "VEC4")
        for uv_i, uv in enumerate(m["uvs"]):
            if not uv:
                continue
            flat = [c for v in uv for c in v]
            v = g.add_view(struct.pack("<%df" % len(flat), *flat), 34962)
            attrs[f"TEXCOORD_{uv_i}"] = g.add_accessor(v, None, None, 5126,
                                                       len(uv), "VEC2")
        prim = {"attributes": attrs}
        idx = m["indices"]
        if idx:
            if m["vertex_count"] < 65536:
                blob, comp = struct.pack("<%dH" % len(idx), *idx), 5123
            else:
                blob, comp = struct.pack("<%dI" % len(idx), *idx), 5125
            v = g.add_view(blob, 34963)
            prim["indices"] = g.add_accessor(v, None, None, comp, len(idx),
                                             "SCALAR")

        mi = m["material_index"]
        if mi in mat_cache:
            mat_idx = mat_cache[mi]
        else:
            mat = materials[mi] if mi < len(materials) else None
            mat_idx = 0
            if mat is not None:
                pbr = {"baseColorFactor": [1, 1, 1, 1],
                       "metallicFactor": 0.0, "roughnessFactor": 1.0}
                gltf_mat = {"name": mat["name"], "doubleSided": False,
                            "pbrMetallicRoughness": pbr,
                            "extras": {"pes_shader": mat["shader"],
                                       "pes_technique": mat["tech"],
                                       "texture_slots": [
                                           {"slot": s, "ref_file": f,
                                            "kind": _slot_kind(s, f)}
                                           for s, f in mat["slots"]]}}
                kinds = {_slot_kind(s, f) for s, f in mat["slots"]}
                if "baseColor" in kinds:
                    t = image_for("baseColor")
                    if t:
                        pbr["baseColorTexture"] = t
                if "normal" in kinds:
                    t = image_for("normal")
                    if t:
                        gltf_mat["normalTexture"] = {"index": t["index"],
                                                     "scale": 1.0,
                                                     "texCoord": 0}
                gltf_mats.append(gltf_mat)
                mat_cache[mi] = mat_idx = len(gltf_mats) - 1
        prim["material"] = mat_idx
        gltf_meshes.append({"name": f"{ball_name}_{m['name']}",
                            "primitives": [prim]})

    nodes = [{"name": f"{ball_name}_{m['name']}", "mesh": i}
             for i, m in enumerate(meshes)]
    doc = {
        "asset": {"version": "2.0",
                  "generator": "pes_ball_convert.py (PES2021 FMDL 逆向)"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": gltf_meshes,
        "materials": gltf_mats,
        "textures": g.textures,
        "images": g.images,
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497,
                      "wrapT": 10497}],
        "buffers": [{"byteLength": len(g.bin)}],
        "bufferViews": g.views,
        "accessors": g.accessors,
        "extensionsUsed": sorted({"MSFT_texture_dds"} if g.images else set()),
    }
    jblob = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    jblob += b" " * (-len(jblob) % 8)
    bblob = bytes(g.bin)
    bblob += b"\x00" * (-len(bblob) % 4)
    total = 12 + 8 + len(jblob) + 8 + len(bblob)
    glb = bytearray()
    glb += struct.pack("<III", 0x46546C67, 2, total)
    glb += struct.pack("<II", len(jblob), 0x4E4F534A) + jblob
    glb += struct.pack("<II", len(bblob), 0x004E4942) + bblob
    return bytes(glb), doc


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def find_texture_dir(fpk_path):
    """ball.fpk 同级 #Win 的兄弟目录 #windx11（存放 ftex）。"""
    ball_dir = os.path.dirname(os.path.dirname(fpk_path))  # .../ballNNN
    cands = [d for d in os.listdir(ball_dir)
             if d.lower().startswith("#windx")] if os.path.isdir(ball_dir) else []
    for d in cands:
        full = os.path.join(ball_dir, d)
        if glob.glob(os.path.join(full, "*.ftex")):
            return full
    return None


def ball_display_name(fpk_path):
    parts = os.path.normpath(fpk_path).split(os.sep)
    if "Asset" in parts:
        i = parts.index("Asset")
        if i > 0:
            return parts[i - 1]
    return os.path.basename(os.path.dirname(os.path.dirname(fpk_path)))


def collect_fpks(inputs):
    """展开输入：.fpk 文件路径原样保留，目录则递归收集其中所有 *.fpk。"""
    out = []
    for p in inputs:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "**", "*.fpk"),
                                         recursive=True)))
        else:
            out.append(p)
    return out


def convert_one(fpk_path, root, texdir=None):
    """转换单个 ball.fpk，产物落在 root/<球名>/ 下，返回该目录。"""
    data = open(fpk_path, "rb").read()
    entry_name, payload = fpk_extract(data)
    print(f"[1/4] FPK 容器: 条目 {entry_name}，载荷 {len(payload)} B")

    fmdl = Fmdl(payload)
    print(f"[2/4] FMDL v0x{fmdl.version:08X}: s0 块 {sorted(fmdl.s0)}, "
          f"s1 块 {sorted(fmdl.s1)}, 字符串 {len(fmdl.strings)}")

    meshes = extract_meshes(fmdl)
    materials = extract_materials(fmdl)
    for m in meshes:
        print(f"      mesh {m['name']}: 顶点 {m['vertex_count']}, "
              f"三角 {len(m['indices']) // 3}, "
              f"UV 层 {len(m['uvs'])}, 材质 [{m['material_index']}] "
              f"{materials[m['material_index']]['name'] if m['material_index'] < len(materials) else '?'}")
    for mt in materials:
        for s, f in mt["slots"]:
            print(f"      贴图槽 {s} -> {f} (kind={_slot_kind(s, f)})")

    ball_name = ball_display_name(fpk_path)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in ball_name)
    # 拼上 ballNNN 编号，避免同一名称目录下多个球互相覆盖
    ball_id = os.path.basename(os.path.dirname(os.path.dirname(fpk_path)))
    if not safe.endswith(ball_id):
        safe = f"{safe}_{ball_id}"
    outdir = os.path.join(root, safe)
    os.makedirs(outdir, exist_ok=True)

    # ftex -> dds，并按后缀建立 槽类别 -> 文件名 映射
    dds_files = {}
    tex_dir = texdir or find_texture_dir(fpk_path)
    if tex_dir:
        print(f"[3/4] 贴图目录: {tex_dir}")
        suffix_kind = {"bsm": "baseColor", "nrm": "normal",
                       "srm": "specular", "mtl": "metalness"}
        for ftex in sorted(glob.glob(os.path.join(tex_dir, "*.ftex"))):
            stem = os.path.splitext(os.path.basename(ftex))[0]
            dds_name = stem + ".dds"
            w, h, mip, pf = ftex_to_dds(ftex, os.path.join(outdir, dds_name))
            tokens = stem.lower().split("_")
            kind = next((suffix_kind[t] for t in tokens
                         if t in suffix_kind), None)
            if kind:
                dds_files.setdefault(kind, dds_name)
            print(f"      {os.path.basename(ftex)} -> {dds_name} "
                  f"({w}x{h}, mip {mip}, pixfmt {pf}, kind={kind})")
    else:
        print("[3/4] 未找到 ftex 贴图目录，仅导出几何")

    glb, doc = build_glb(meshes, materials, dds_files, safe)
    glb_path = os.path.join(outdir, safe + ".glb")
    open(glb_path, "wb").write(glb)
    print(f"[4/4] 写出 {glb_path} ({len(glb)} B, "
          f"accessors={len(doc['accessors'])}, images={len(doc['images'])})")
    return outdir


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fpk", nargs="+",
                    help="ball.fpk 路径（可多个），或包含球目录的根路径（递归找 *.fpk）")
    ap.add_argument("-o", "--outdir", default="output",
                    help="输出根目录（默认 output）；每个球在其下各建一个同名子文件夹")
    ap.add_argument("--texdir", default=None,
                    help="显式指定 ftex 贴图目录（默认自动找 fpk 同级 #windx*）；"
                         "仅单 fpk 时可用")
    args = ap.parse_args()

    fpks = collect_fpks(args.fpk)
    if not fpks:
        raise SystemExit("未找到任何 .fpk")
    if len(fpks) > 1 and args.texdir:
        ap.error("--texdir 仅支持单个 fpk（批量时按各自 #windx* 自动查找）")
    root = os.path.abspath(args.outdir)
    print(f"共 {len(fpks)} 个 fpk，输出根目录: {root}")

    ok = 0
    fails = []
    for fpk_path in fpks:
        print(f"\n===== {fpk_path} =====")
        try:
            convert_one(fpk_path, root,
                        os.path.abspath(args.texdir) if args.texdir else None)
            ok += 1
        except Exception as e:
            fails.append((fpk_path, repr(e)))
            print(f"      失败: {e!r}")
    print(f"\n完成 {ok}/{len(fpks)}")
    for p, e in fails:
        print("  FAIL", p, e)
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
