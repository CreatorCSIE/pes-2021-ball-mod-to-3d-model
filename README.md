# PES 2021 Ball Mod → 3D 模型转换器

将 PES 2021（eFootball）中 ball mod 与游戏原版 ball 资源所采用的 Konami 专有
模型/贴图格式（FPK/FMDL/FTEX，两者同一格式）"去 PES 化"，转换为 Blender 可直接
使用的通用格式：**glTF 2.0（.glb）+ DDS 贴图**，并可导出 `.blend`。已以试点球
（Puma Orbita LaLiga EA Sports 26-27 / ball951）打通全链路，并完成
Ballpack 全量转换：**1646 个 ball 中 1644 成功**（2 个失败为 mod 作者对个别
贴图做的故意锁定保护，本工具不破解此类文件，不属转换器问题）。
Sider 散装 mod（91/91）与游戏原版球（存于 `Data\dt15_x64.cpk`，先用
`scripts/cpk_extract.py` 解包）同样验证通过。

## 工具链

- Python ≥ 3.6（仅标准库，无第三方依赖）
- Blender（仅用于验证/转 .blend/渲染素材；通过 `BLENDER` 环境变量指定可执行文件，或将其加入 PATH）
- 7-Zip（解 RAR5 分卷源包）

## 目录结构

```
├─ convert.bat / convert.sh   # 转换入口（参数透传给 pes_ball_convert.py）
├─ render.bat  / render.sh    # 渲染入口（参数透传给 blender_render_pack.py）
├─ scripts/
│  ├─ cpk_extract.py         # CRI CPK 容器解包（提取游戏原版资源 / cpk 形态 mod）
│  ├─ pes_ball_convert.py    # 核心转换器：ball.fpk → .glb，*.ftex → *.dds
│  ├─ blender_check.py       # Blender headless 验证脚本（导入 glb、统计、存 blend）
│  └─ blender_render_pack.py # AI 生图素材：多角度参考图 / 深度 / 法线 PNG 批量渲染
├─ docs/
│  └─ pes2021-model-format.md   # PES 2021 专有格式（FPK/FMDL/FTEX）逆向破解报告
├─ data/raw/ballpack/       # 开发用试点样本（本仓库解包产物；实际使用不依赖 data/，
│                           #   直接对任意已解包目录（mod 或游戏原版资源）处理即可）
└─ output/                  # 转换产物
   └─ Puma_Orbita_LaLiga_EA_Sports_26-27/
      ├─ *.glb              # 模型（872 顶点 / 1404 三角 / 2 层 UV，含材质与贴图引用）
      ├─ *.dds              # 4 张 2048×2048 贴图（baseColor/normal/spec/metalness）
      ├─ *.blend            # Blender 验证产物
      └─ render/            # AI 生图素材：ref_XX.png 参考图、depth_XX/normal_XX 控制图
```

## 用法

```bat
:: 输入是"解包后的目录"本身（如 7-Zip 解出的 content\omb\...）——
:: ball mod 与游戏原版 ball 资源同为 FPK/FMDL/FTEX 格式，均可直接转换。
:: 不需要也不依赖仓库内的 data\ 文件夹——那只是本仓库开发时的试点样本。

:: 0) 也可以直接用入口脚本（bat 供 Windows / sh 供 Linux、macOS、WSL，参数透传）
convert.bat "X:\解包目录\content\omb\Puma Orbita LaLiga EA Sports 26-27\Asset\model\ball\ball951\#Win\ball.fpk"
render.bat  "output\Puma_Orbita_LaLiga_EA_Sports_26-27\Puma_Orbita_LaLiga_EA_Sports_26-27.glb" "output\Puma_Orbita_LaLiga_EA_Sports_26-27" --passes
::    render 需要 Blender：set BLENDER=<blender.exe 路径>，或把 blender 加入 PATH

:: 1) 转换单个球（fpk 路径含空格时加引号）
python scripts\pes_ball_convert.py "X:\解包目录\content\omb\Puma Orbita LaLiga EA Sports 26-27\Asset\model\ball\ball951\#Win\ball.fpk"

:: 每个球的产物（glb+dds）各自落在 output\<球名>_<ballNNN>\ 文件夹下，
:: 同一目录下多个球（如 Sider 按联赛组织、一目录多球）也互不覆盖
::    -o 指定输出根目录（默认 output）；--texdir 显式指定 ftex 贴图目录
::    （默认自动找 fpk 同级 #windx*，贴图被挪走时才需要 --texdir）

:: 1b) 批量：直接传解包后的 omb 目录（如 Sider 的 SiderAddons\content\omb），
:: 递归找出所有 ball.fpk，逐个转换、各自入文件夹
python scripts\pes_ball_convert.py "X:\解包目录\content\omb" -o output

:: 1c) 游戏原版球：先解包 CPK 容器（原版球在 Data\dt15_x64.cpk），再按 1b 转换
python scripts\cpk_extract.py "X:\游戏目录\Data\dt15_x64.cpk" --list --filter ball   :: 查看条目
python scripts\cpk_extract.py "X:\游戏目录\Data\dt15_x64.cpk" -o extracted --filter ball
python scripts\pes_ball_convert.py "extracted\dt15_x64\Asset\model\ball" -o output

:: 2) （可选）Blender headless 验证并生成 .blend
"%BLENDER%" -b -P scripts\blender_check.py -- ^
  "output\Puma_Orbita_LaLiga_EA_Sports_26-27\Puma_Orbita_LaLiga_EA_Sports_26-27.glb" ^
  "output\Puma_Orbita_LaLiga_EA_Sports_26-27\Puma_Orbita_LaLiga_EA_Sports_26-27.blend"

:: 3) （可选）渲染 AI 生图素材：8 轨道视角 + 俯视 + 特写参考图
"%BLENDER%" -b -P scripts\blender_render_pack.py -- ^
  "output\Puma_Orbita_LaLiga_EA_Sports_26-27_ball951\Puma_Orbita_LaLiga_EA_Sports_26-27_ball951.glb" ^
  "output\Puma_Orbita_LaLiga_EA_Sports_26-27_ball951" --passes
::   默认只出 ref_XX.png（IP-Adapter/img2img 直接喂的参考图）
::   --passes 追加 depth_XX.png（近=白）与 normal_XX.png（世界空间），供 ControlNet
::   --format jpeg 把 ref 图输出为 .jpg（q92，体积约 1/10；pass 图始终 PNG 无损）
::
::   渲染策略建议：全量 1644 球 PNG 素材约 25GB，**不必预生成**——
::   单球渲染仅十秒级，用时对目标球现渲即可（即取即用）；
::   确需全量素材库时加 --format jpeg，总量约 1.3GB
::   其他参数：--views N（轨道视角数，默认 8） --size 1024 --transparent（透明底）
```

源包为 RAR5 分卷时，先用 7-Zip 解压首个分卷即可得到完整 `content\omb\` 目录。

## 转换内容

| 来源 | 去向 |
|---|---|
| `#Win/ball.fpk` 内 `ball.fmdl` | `.glb`：POSITION/NORMAL/TANGENT/TEXCOORD_0-1/索引，PBR 材质（baseColor+normal 贴图已接线） |
| `#windx11/*.ftex` | 同名 `.dds`（zlib chunk 解压 + DX10 头重建），glTF 经 `MSFT_texture_dds` 引用 |
| 材质元数据 | glTF `extras`：PES shader/technique 名、4 个贴图槽原始引用 |

已知限制（蒙皮、specular/metalness 通道、法线 Y 惯例、CPK 压缩条目、
作者锁定贴图等）见
[docs/pes2021-model-format.md](docs/pes2021-model-format.md) §7。

## 验证结果（试点）

- 几何与包内已解包 `ball.fmdl` 交叉一致；
- 转出 DDS 与 mod 作者自转 DDS 逐字节一致（仅 1 位 caps 标志写法差异）；
- Blender 5.0.1 导入：872 顶点 / 1404 面 / 2 UV 层，贴图与材质节点自动加载。

## 许可声明

本仓库**自研代码与文档**（`scripts/`、`docs/`、入口脚本、README）采用
[MIT 许可证](LICENSE)。

注意：MIT 仅覆盖上述内容，**不覆盖**任何游戏或 mod 素材——PES 2021 原版
ball 资源及 ball mod（FPK/FMDL/FTEX、贴图、试点样本等）的原始权利归
Konami 及相应 mod 作者所有；转换产物包含游戏版权素材，同样不获得 MIT 授权，
仅供个人学习/互操作使用。
