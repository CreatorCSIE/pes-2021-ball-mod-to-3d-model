# PES 2021 模型专有格式破解报告（FPK / FMDL / FTEX / CPK）

本报告记录对 Konami PES 2021（eFootball 引擎，内部代号 "fox"）ball mod 及
游戏原版资源所用专有格式的逆向破解过程与结论。全部字段均经过实测验证
（试点样本：`Ballpack_Season_2026-27_Update` 中的
`Puma Orbita LaLiga EA Sports 26-27 / ball951`；CPK 部分实测于
Football Life 26 安装目录的 `Data\*.cpk`）。

参考实现：社区项目 [the4chancup/pes-fmdl-blender](https://github.com/the4chancup/pes-fmdl-blender)
（Sollumz 生态，Blender 插件，含 `FmdlFile.py` / `Ftex.py`）。本报告在其基础上
用独立 dump 脚本对每个字段做了字节级交叉验证，并补充了 fpkd、chunk 压缩标志等细节。
本仓库 `scripts/` 代码基于二进制分析独立实现（MIT 许可），上述项目仅作格式结论
对照，未被复制进本仓库、也不在本仓库许可覆盖范围内。

---

## 1. ball mod 包总体结构

```
<球名>/
├─ installation.txt                      # lua.module = "common\omb.lua"（游戏挂载入口）
└─ content/omb/<球名>/
   ├─ Asset/model/ball/ballNNN/
   │  ├─ #Win/
   │  │  ├─ ball.fpk                     # FPK 容器，内含 ball.fmdl（模型本体）
   │  │  └─ ball.fpkd                    # FPK 附属数据（48B，见 §2.3）
   │  └─ #windx11/
   │     ├─ ballNNN_c_bsm_alp.ftex       # Base Color（含 Alpha）
   │     ├─ ballNNN_n_nrm.ftex           # 法线贴图
   │     ├─ ballNNN_s_srm.ftex           # 高光/粗糙度
   │     └─ ballNNN_t_mtl.ftex           # 金属度
   └─ common/render/thumbnail/ball/ball_NNN.dds   # 库存图标（已是 DDS）
```

`#Win` = 通用 DX11 资源，`#windx11` = DX11 平台贴图目录。整个更新包共 2319 个
`ball.fpk`，结构一致，本转换器可直接批量复用。

## 2. FPK 容器

### 2.1 头部（0x00–0x6F）

| 偏移 | 类型 | 含义 | 试点值 |
|---|---|---|---|
| 0x00 | 10B | magic `foxfpk\0win`（10 字节，第 7 字节为 0x00） | `foxfpk.win` |
| 0x0C | u32 | 文件大小（含头） | 41136 |
| 0x20 | u32 | 容器版本 | 2 |
| 0x24 | u32 | 条目数 | 1 |
| 0x30 | u64 | 数据区偏移 | 0x70 |
| 0x38 | u64 | 数据区长度 | 41023 |
| 0x40 | u64 | 目录区偏移（恒 0x60） | 0x60 |
| 0x44 | u32 | 目录区大小 / 16 | 9 |
| 0x50 | 16B | GUID | — |
| 0x60 | 16B | 第 1 条目文件名（`\0` 填充） | `ball.fmdl` |

数据区即 FMDL 本体：`fpk[0x70 : 0x70+41023]`。多条目 FPK 的目录排布未在本项目中
遇到（ball 均为单条目），转换器对 `条目数 != 1` 显式报错。

### 2.2 载荷魔数

载荷头 4 字节为 `FMDL`，与 `.fpk.xml` 侧车文件（部分解包样本带）声明的条目一致。

### 2.3 .fpkd

48 字节：magic `foxfpkdwin0` + 全零。ball 模型不依赖其内容，转换时忽略。

## 3. FMDL 模型格式

### 3.1 总体布局

```
0x00  头 56B
      magic(4s)="FMDL"  version(u32)=0x4001EB85  descOff(u64)=64
      s0Bitmap(u64)  s1Bitmap(u64)
      s0Cnt(u32) s1Cnt(u32)  s0Off(u64) s0Len(u64)  s1Off(u64) s1Len(u64)
descOff  s0 目录: s0Cnt × {id(u16), cnt(u16), off(u32 相对 s0Off)}
         s1 目录: s1Cnt × {id(u32), off(u32 相对 s1Off), len(u32)}
s0Off    segment0：定长"记录表"（元数据）
s1Off    segment1：变长数据块（顶点/索引/字符串/参数）
```

试点值：s0Bitmap=0x177FDE，s1Bitmap=0xD，s0 17 张表，s1 3 块。

### 3.2 segment0 块语义（id → 条目大小 → 内容）

| id | 大小B | 记录格式 | 语义 |
|---|---|---|---|
| 0 | 48 | — | 骨骼变换（球类无骨骼，本包未出现） |
| 1 | 8 | `<H H h h` | meshGroup：名称串、不可见、父级、-1 |
| 2 | 32 | `<4x HHHH 4x H 14x` | group→mesh 分配（组、mesh 数、首 mesh、bbox） |
| 3 | 48 | `<BB 2x HHHH 4x IIQ 16x` | **mesh**：alpha、shadow、材质实例、骨组、格式分配、**顶点数(u16)**、首面顶点、面顶点数、面索引表 id |
| 4 | 16 | `<H H H BB HH I` | 材质实例：名称串、材质、贴图数、参数数、首贴图、首参数 |
| 5 | 68 | — | 骨骼组（未出现） |
| 6 | 4 | `<H H` | 贴图引用：文件串、目录串 |
| 7 | 4 | `<H H` | 参数/贴图槽：参数名串、引用 id（前 texCnt 条即贴图槽，refID 指向 b6 序号） |
| 8 | 4 | `<H H` | 材质：shader 串、technique 串 |
| 9 | 8 | `<BB BB HH` | **格式分配**：meshFmt 条目数、vertFmt 条目数、firstUv、uvCnt、firstMeshFmt、firstVertFmt |
| 10 | 8 | `<BBBB I` | **meshFmt**：bufferID、vertFmt 条目数、**顶点步长**、类型、buffer 内偏移 |
| 11 | 4 | `<BB H` | **vertFmt**：datumType、datumFormat、属性偏移 |
| 12 | 8 | `<H H I` | 字符串：s1 块 id、长度、块内偏移 |
| 13 | 32 | `<8f` | 包围盒：max(xyzw) 后 min(xyzw) |
| 14 | 16 | `<IIII` | **bufferOffsets**：(eof 标志, 长度, 偏移(相对 s1[2]), pad) |
| 16 | 16 | `<I 3f` | LOD：层数(=1) + 3 个 float |
| 17 | 8 | `<II` | faceIndices：(首面顶点, 面顶点数) |
| 18 | 8 | — | 未使用（本包） |
| 20 | 128 | — | 未使用（本包） |

### 3.3 顶点数据寻址

顶点属性分布在 s1[2] 大缓冲内，寻址链：

```
mesh.b3.fmtAssign → b9 (firstMeshFmt, firstVertFmt, 条目数)
  对每个 b10 meshFmt：向该 mesh 贡献 vfc 个属性槽，
    基址 = bufferOffsets[b10.bufferID] + b10.bufferOffset，步长 = b10.increment
  第 i 个属性 = b11[firstVertFmt + i]：(datumType, datumFormat, 基址内偏移)
  第 v 个顶点某属性地址 = 基址 + 偏移 + v × 步长
```

datumType：`0=position 1=boneWeights 2=normal 3=color 7=boneIndices 8..11=uv0..uv3 14=tangent`

datumFormat：`1=3×f32 2=2×f32 6=4×f16 7=2×f16 8=4×u8 9=4×i8`

| 属性 | 类型 | 格式 | 字节 |
|---|---|---|---|
| position | 0 | 1 | 12（f32×3） |
| normal | 2 | 6 | 8（f16×4，第 4 分量弃用） |
| tangent | 14 | 6 | 8（f16×4，w=副切线手性 ±1） |
| uv0/uv1 | 8/9 | 7 或 2 | 4（f16×2）或 8（f32×2） |
| color | 3 | 8 | 4（u8×4） |
| boneWeights/Indices | 1/7 | 8/9 | 4+4 |

### 3.4 面索引

三角形索引为 **u16×3**，位于 s1[2] 的 bufferOffsets[2] 处：

```
起始 = mesh.b3.firstFaceVertex + b17[firstFaceIndexID].first
个数 = b17 的 faceVertexCount（= 3 × 三角面数）
```

试点：872 顶点 / 4212 面顶点 / 1404 三角；buffer0 位置 @0（872×12=10464），
buffer1 属性 @10464（872×24=20928，nrm8+tan8+uv4+uv4），faces @31392（4212×2=8424），
与 s1[2] 总长 39816 严丝合缝。

**正面绕序为顺时针**（DirectX 惯例，实测 1404 个三角形的几何法线全部与顶点法线
反向）。转 glTF（要求逆时针）时必须交换每个三角形的第 2、3 索引，并同步将
切线的 w 分量取反，否则模型"里翻外"、贴图呈水平镜像。

### 3.5 s1 块

| id | 内容 |
|---|---|
| 0 | 材质参数 vec4 数组（`<4f`，按 b4.firstParam/paramCnt 索引） |
| 2 | 顶点 + 面索引大缓冲 |
| 3 | 字符串池（b12 索引）；尾部可能附 `X-FMDL-Extensions:` HTTP 风格头 |

注意：s1 目录的 `len` 字段常偏小，实际块边界应取下一块起点（末块取文件尾）。

### 3.6 材质/贴图槽（试点实例）

shader `fox_3ddf_ggx_nrmuv`，technique `fox3DDF_GGX_NrmUV`，材质名 `basic_fx`，
4 个贴图槽（b7 前 4 条 paramStr → b6 fileStr）：

| 槽名 | 内部引用 | 实际文件（按后缀匹配） |
|---|---|---|
| Base_Tex_SRGB | ball951_c_bsm_alp.dds | `*_c_bsm_alp.ftex` |
| NormalMap_Tex_NRM | ball951_n_nrm.dds | `*_n_nrm.ftex` |
| SpecularMap_Tex_LIN | ball951_s_srm.tga | `*_s_srm.ftex` |
| MetalnessMap_Tex_LIN | ball951_t_mtl.tga | `*_t_mtl.ftex` |

mod 作者重导出时内部引用名可能仍指向模板球（如 ball802），因此槽→文件映射
按 `bsm/nrm/srm/mtl` 后缀匹配，而非按引用名。

包围盒 ±0.112 m，即直径约 22.4 cm——**FMDL 单位为米，模型为真实尺寸足球**。
meshGroup 名 `MESH_ROOT`，无骨骼、无蒙皮（b0/b5 缺席）。

## 4. FTEX 贴图格式 → DDS

### 4.1 头部（64B）

`<4s f HHHH BB HIII BB 14x 8s 8s`：

| 字段 | 类型 | 说明 |
|---|---|---|
| magic | 4s | `FTEX` |
| version | f32 | 2.025–2.045 |
| pixfmt | u16 | 像素格式（见 4.3） |
| w, h, depth | u16×3 | 尺寸 |
| mipCnt | u8 | mip 层数 |
| nrt, flags | u8, u16 | 未用/恒小值 |
| unk1, unk2, texType | u32×3 | texType & 4 = 立方体贴图；depth>1 = 体积纹理 |
| ftexsCnt | u8 | 必须为 0 |
| unk3 | u8 | — |
| hash1, hash2 | 8s×2 | 内容哈希 |

### 4.2 mip 表与 chunk

紧随头部，每 mip 16B：`<I I I BB H` = (数据偏移, 解压大小, 压缩大小, index, ftexsNo, chunkCnt)。

- `chunkCnt == 0`：数据直接在偏移处；`cmp==0` 存原始，否则 zlib。
- `chunkCnt > 0`：偏移处是 chunkCnt × 8B 表 `<H H I` = (压缩大小, 解压大小, 偏移|bit31)；
  表后数据偏移**相对 chunk 表起点**。bit31=1 表示未压缩。
- **实测补充**：最小 mip 的 chunk 常出现 `cmp==uncmp` 且 bit31=0 的**原始 BC 块**
  （如 16B 的 DXT5 单块），需按"大小相等即未压缩"处理，否则 zlib 报
  `incorrect header check`。

### 4.3 像素格式 → DXGI

| pixfmt | 格式 | DDS 写法 |
|---|---|---|
| 0 | R8G8B8A8_UNORM | 传统头 + RGBA bitfield（pitch 标志） |
| 1 | R8_UNORM | DX10 #61 |
| 2/3/4 | DXT1/DXT3/DXT5 | FourCC |
| 8 | BC4 | DX10 #80 |
| 9 | BC5 | DX10 #83 |
| 10 | BC6H | DX10 #95 |
| 11 | BC7 | DX10 #98 |
| 12 | RGBA16F | DX10 #10 |
| 13 | RGBA32F | DX10 #2 |
| 14 | RGB10A2 | DX10 #24 |
| 15 | R11G11B10 | DX10 #26 |

DDS 头 124B（+ 非 RGBA8 时 20B DX10 扩展头），随后按 mip 顺序拼接解压后的
原始块数据。试点 4 张贴图均为 2048×2048：bsm/srm 为 DXT5（pixfmt 4），
nrm/mtl 为 DXT1（pixfmt 2）。

## 5. CRI CPK 容器（游戏原版资源）

游戏原版资源（含全部原版球）打包在 `Data\*.cpk`（CRI Middleware CPK 格式，
社区用官方 cpkMaker 打包 mod 亦为此格式）。实测 FL26 即传统 CPK，未加密。

### 5.1 总体布局

```
[16B 文件头]  "CPK " + u32 0xFF + u64（值=0x2A0，用途未定）
[头部 UTF]    @UTF 表 @0x10，单行，给出各表位置与全局信息
[文件数据]    ContentOffset 起（对齐 Align=0x800）
[TOC 包]      "TOC " + @UTF @TocOffset，每文件一行
[ETOC/ITOC]   EtocOffset/ItocOffset（扩展名索引/目录索引，提取不需要）
```

### 5.2 UTF 表结构（大端字段，非 SEGA @UTF 布局）

```
0x00 "CPK "/"TOC " 等包 magic（4B）+ @UTF（4B）
+0x04 u32 表大小
+0x08 u32 rows 偏移    ┐
+0x0C u32 strings 偏移 ├ 均相对 "@UTF 起点+8"
+0x10 u32 data 偏移    ┘
+0x14 u32 表名（字符串偏移）
+0x18 u16 列数  +0x1A u16 行长  +0x1C u32 行数
列定义（变长条目）：flags==0 时 [00][pad3][flags][u32 nameoff]（8B），
  否则 [flags][u32 nameoff]（5B）。flags 低 4 位=类型
  （0/1=u8, 2/3=u16, 4/5=u32, 6/7/0xB=u64, 8=f32, 0xA=str），
  高 4 位=存储方式：0x50=行内常规；0x00/0x10/0x30=默认值/零，不占行内空间。
```

### 5.3 头部行列（实测 dt00）

`UpdateDateTime, FileSize, ContentOffset(0x800), ContentSize, TocOffset,
TocSize, TocCrc, EtocOffset, EtocSize, ItocOffset, ItocSize, ItocCrc,
GtocOffset..., EnabledPackedSize, EnabledDataSize, TotalDataSize, Tocs,
Files, Groups, Attrs, TotalFiles, Directories, Updates, Version, Revision,
Align(0x800), Sorted, EID, CpkMode, Tvers('N/A, DLL3.11.05'), Comment, Codec, DpkItoc`

### 5.4 TOC 行列

`DirName(str), FileName(str), FileSize(u32), ExtractSize(u32),
FileOffset(u32, 相对 ContentOffset), ID(u32), UserString(str)`

`ExtractSize == FileSize` 即未压缩（实测 ball 全部未压缩）；不等时为 CRI
压缩，`scripts/cpk_extract.py` 会跳过并提示。

### 5.5 原版球位置

`Data\dt15_x64.cpk`（5956 条目）含全部原版球：
`Asset/model/ball/ballNNN/#Win/ball.fpk` + `#windx11/*.ftex`，共 313 个
ball 相关文件。提取后目录结构与 mod 解包一致，可直接喂 `pes_ball_convert.py`。

## 6. 验证结论

1. `ball.fpk` → FMDL → 几何：872 顶点 / 1404 三角 / 2 层 UV，与包内已解包
   `ball_fpk/ball.fmdl` 交叉一致。
2. `ball951_c_bsm_alp.ftex` → DDS 与包内现成 `ball951_c_bsm_alp.dds`（mod 作者
   自转产物）**逐字节比对**：5592560B 全长一致，仅 DDS caps1 一位标志
   （0x08 COMPLEX 的写法差异）不同，数据区完全相同。
3. Blender 5.0.1 headless 导入 `.glb`：顶点/面/UV 统计与 FMDL dump 一致，
   bbox ±0.112 m，baseColor/normal 两张 DDS 正常加载，
   Principled BSDF + NormalMap 节点图自动生成。
4. Sider 散装 mod 批量：91 个 ball.fpk（9 种球模，顶点 822~10574，
   含 9-mesh LOD 球与 4096² 贴图球）91/91 转换成功，抽查 4 球 Blender 验证通过。
5. CPK 解包：dt00/dt15 等 50+ 个 cpk 头部与 TOC 全部解析成功；从
   `dt15_x64.cpk` 提取原版 ball000/ball001 并转换出 `.glb`+`.dds`，端到端通过。
6. modpack 全量：1646 个 ball.fpk 转换 **1644 成功**；仅 2 个失败，均为
   mod 作者对个别球贴图做的故意锁定保护（机制从略，尊重作者意愿不收录、
   不破解），非转换器问题；同款球模在其他球中完整可用。

## 7. 已知限制

- FPK 仅支持单条目容器（ball 全部如此）。
- 蒙皮/骨骼（b0/b5、boneWeights）未实现——球类模型不涉及。
- Specular/Metalness 槽仅记录在 glTF `extras`，未映射进 PBR 通道
  （PES 的 srm/mtl 打包语义与 glTF metallicRoughness 通道约定不同）。
- 法线贴图沿用 PES 原始（DirectX 惯例）数据，若渲染观感 Y 翻转，
  需在 Blender 中对 Normal Map 节点设 `invert Y` 或翻转 G 通道。
- version 仅实测 0x4001EB85（PES2021 ball）；其他 PES 世代字段可能漂移。
- CPK：`ExtractSize != FileSize` 的 CRI 压缩条目暂不解压（ball 无此情况）；
  个别视频类 cpk（SMK_*.cpk）TOC 含特殊列布局，未适配。
- mod 作者对个别球贴图做了故意锁定保护：本工具不识别、不破解此类文件，
  转换时按失败跳过处理（全包仅 2 例，同款球模其他球完整可用）。
