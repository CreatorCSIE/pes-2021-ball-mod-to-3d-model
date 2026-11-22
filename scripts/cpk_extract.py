#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# -*- coding: utf-8 -*-
"""CRI CPK 容器解包器：从 PES 2021 / Football Life 26 的 *.cpk 中提取文件。

纯 Python 标准库实现，无第三方依赖。
格式细节见 docs/pes2021-model-format.md 第 5 节。

用法：
    # 列出 cpk 内全部条目
    python scripts/cpk_extract.py "N:\\...\\Data\\dt15_x64.cpk" --list

    # 按子串过滤提取（可多次 --filter，匹配 目录/文件名，不区分大小写）
    python scripts/cpk_extract.py "N:\\...\\Data\\dt15_x64.cpk" -o out --filter ball

    # 输入为目录时，扫描其下全部 *.cpk
    python scripts/cpk_extract.py "N:\\...\\Data" -o out --filter ball

提取出的目录结构与游戏挂载路径一致（DirName/FileName），
可直接作为 pes_ball_convert.py 的输入目录。
"""

import argparse
import glob
import os
import struct
import sys

# --------------------------------------------------------------------------
# CRI UTF 表（@UTF，大端字段，列条目变长——非 SEGA @UTF 布局）
# --------------------------------------------------------------------------

def read_utf(f, off):
    """解析 @UTF 表头与列定义，返回元信息字典。"""
    f.seek(off)
    if f.read(4) != b"@UTF":
        raise ValueError(f"{off:#x} 处不是 @UTF 表")
    (tsize, rows_off, str_off, data_off, tname) = struct.unpack(">5I", f.read(20))
    ncols, rlen = struct.unpack(">HH", f.read(4))
    nrows = struct.unpack(">I", f.read(4))[0]
    # CPK 内 UTF 的 rows/strings/data 偏移均相对 "表起点+8"
    rows_abs, str_abs, data_abs = off + 8 + rows_off, off + 8 + str_off, off + 8 + data_off
    raw = f.read(0x1000)
    cols, p = [], 0
    for _ in range(ncols):
        flags = raw[p]
        if flags == 0:  # 保留列：[00][pad x3][flags][u32 nameoff]
            p += 4
            flags = raw[p]
        p += 1
        nameoff = struct.unpack_from(">I", raw, p)[0]
        p += 4
        f.seek(str_abs + nameoff)
        nm = f.read(128).split(b"\x00")[0].decode("ascii", "replace")
        cols.append((nm, flags))
    return dict(tsize=tsize, rows_abs=rows_abs, str_abs=str_abs,
                data_abs=data_abs, ncols=ncols, rlen=rlen, nrows=nrows, cols=cols)


def read_rows(f, u):
    """按列定义读取全部行。仅解析常规存储（flags 高 4 位 == 0x50）的列。"""
    out = []
    for j in range(u["nrows"]):
        f.seek(u["rows_abs"] + j * u["rlen"])
        raw = f.read(u["rlen"])
        row, p = {}, 0
        for nm, flags in u["cols"]:
            stor, typ = flags & 0xF0, flags & 0x0F
            if stor != 0x50:  # 0x00/0x10/0x30：不占行内空间，值为默认/零
                row[nm] = None
                continue
            if typ in (0, 1):
                v = raw[p]; p += 1
            elif typ in (2, 3):
                v = struct.unpack_from(">H", raw, p)[0]; p += 2
            elif typ in (4, 5):
                v = struct.unpack_from(">I", raw, p)[0]; p += 4
            elif typ in (6, 7, 0xB):
                v = struct.unpack_from(">Q", raw, p)[0]; p += 8
            elif typ == 8:
                v = struct.unpack_from(">f", raw, p)[0]; p += 4
            elif typ == 0xA:
                so = struct.unpack_from(">I", raw, p)[0]; p += 4
                f.seek(u["str_abs"] + so)
                v = f.read(512).split(b"\x00")[0].decode("ascii", "replace")
            else:
                raise ValueError(f"列 {nm} 暂不支持的类型 {typ:#x}")
            row[nm] = v
        out.append(row)
    return out


# --------------------------------------------------------------------------
# CPK 容器
# --------------------------------------------------------------------------

def cpk_open(path):
    """打开 CPK，返回 (文件句柄, 头部行, TOC 行列表)。"""
    f = open(path, "rb")
    if f.read(4) != b"CPK ":
        f.close()
        raise ValueError("不是 CPK 容器（magic 不匹配）")
    hdr = read_rows(f, read_utf(f, 0x10))[0]
    toc_off = hdr.get("TocOffset")
    if not toc_off:
        f.close()
        raise ValueError("头部缺少 TocOffset")
    f.seek(toc_off)
    if f.read(4) != b"TOC ":
        f.close()
        raise ValueError(f"{toc_off:#x} 处不是 TOC 包（可能被 -mask 加密或版本不同）")
    rows = read_rows(f, read_utf(f, toc_off + 0x10))
    return f, hdr, rows


def cpk_extract_one(f, hdr, row, outdir, quiet=False):
    """提取单条目到 outdir/DirName/FileName，返回落盘路径。"""
    rel = (row.get("DirName") or "").replace("/", os.sep).replace("\\", os.sep)
    dst_dir = os.path.join(outdir, rel) if rel else outdir
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, row["FileName"])
    f.seek(hdr["ContentOffset"] + row["FileOffset"])
    data = f.read(row["FileSize"])
    if len(data) != row["FileSize"]:
        raise IOError(f"读取越界: {dst}")
    if row.get("ExtractSize") and row["ExtractSize"] != row["FileSize"]:
        raise ValueError("该条目经过 CRI 压缩，本工具暂不支持")
    with open(dst, "wb") as w:
        w.write(data)
    if not quiet:
        print(f"  + {os.path.join(rel, row['FileName'])}  ({row['FileSize']} B)")
    return dst


def process_cpk(path, outroot, filters, list_only, quiet=False):
    """处理单个 cpk，返回 (提取数, 跳过数, 失败数)。"""
    f, hdr, rows = cpk_open(path)
    print(f"== {os.path.basename(path)}  Files={hdr.get('Files')} 条目={len(rows)} ==")
    if list_only:
        for r in rows:
            if not filters or any(s in f"{r.get('DirName')}/{r.get('FileName')}".lower()
                                  for s in filters):
                print(f"  {r.get('DirName', '')}/{r.get('FileName', '')}  "
                      f"{r.get('FileSize')} B @ {r.get('FileOffset'):#x}")
        f.close()
        return 0, 0, 0
    outdir = os.path.join(outroot, os.path.splitext(os.path.basename(path))[0])
    ok = skip = fail = 0
    for r in rows:
        full = f"{r.get('DirName') or ''}/{r.get('FileName') or ''}".lower()
        if filters and not any(s in full for s in filters):
            continue
        try:
            cpk_extract_one(f, hdr, r, outdir, quiet)
            ok += 1
        except ValueError as e:
            print(f"  ! 跳过 {r.get('FileName')}：{e}")
            skip += 1
        except Exception as e:
            print(f"  ! 失败 {r.get('FileName')}：{e}")
            fail += 1
    f.close()
    print(f"-- 提取 {ok}，压缩跳过 {skip}，失败 {fail} -> {outdir}")
    return ok, skip, fail


def main():
    ap = argparse.ArgumentParser(description="CRI CPK 解包（PES 2021 / FL26）")
    ap.add_argument("input", help="*.cpk 文件或包含 cpk 的目录")
    ap.add_argument("-o", "--outdir", default="extracted", help="输出根目录（默认 extracted\\）")
    ap.add_argument("--filter", action="append", default=[],
                    help="子串过滤，匹配 目录/文件名（不区分大小写），可多次")
    ap.add_argument("--list", action="store_true", help="仅列出条目，不提取")
    ap.add_argument("-q", "--quiet", action="store_true", help="不逐条打印")
    args = ap.parse_args()

    if os.path.isdir(args.input):
        cpks = sorted(glob.glob(os.path.join(args.input, "*.cpk")))
    else:
        cpks = [args.input]
    if not cpks:
        sys.exit("未找到任何 .cpk 文件")

    filters = [s.lower() for s in args.filter]
    tot = [0, 0, 0]
    errs = 0
    for c in cpks:
        try:
            r = process_cpk(c, args.outdir, filters, args.list, args.quiet)
            tot = [a + b for a, b in zip(tot, r)]
        except Exception as e:
            print(f"== {os.path.basename(c)}: 打开失败：{e}")
            errs += 1
    if not args.list:
        print(f"\n总计：提取 {tot[0]}，压缩跳过 {tot[1]}，失败 {tot[2]}，无法打开 {errs}")


if __name__ == "__main__":
    main()
