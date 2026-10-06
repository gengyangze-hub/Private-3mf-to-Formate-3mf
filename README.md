# Private-3mf-to-Formate-3mf

**把 Bambu Studio / OrcaSlicer 多色工程 3MF 里「藏起来」的颜色，转成任何软件和打印服务商都能读懂的彩色 3MF / OBJ+MTL。**

纯 Python 标准库实现，零第三方依赖，Windows 下拖拽即可运行。

---

## 为什么需要它

在 MakerWorld 之类的平台下载到的多色模型，通常是 **Bambu Studio 工程 3MF**（`.3mf`）。用 Bambu Studio 打开是彩色的，但把它直接上传给全彩打印服务商（例如嘉立创、JLC），对方常常回复：

> 全彩彩色打印需要上传彩色格式文件，目前模型没有颜色，OBJ 格式需要上传 MTL 路径文件……也可以上传 3mf 彩色文件。

原因是：**这些颜色并不写在标准 3MF 的颜色字段里**，而是分别藏在 Bambu 私有的三处：

| 位置 | 内容 |
|---|---|
| `Metadata/project_settings.config` | `filament_colour`，AMS 各槽位的颜色 |
| `Metadata/model_settings.config` | 每个 `object` / `part` 的 `extruder`（默认用哪个槽位） |
| 每个 `<triangle>` 的 `paint_color` | 该三角面被"涂抹"成哪个槽位（私有位流） |

通用 3D 软件和打印服务商的系统只认标准 3MF 的 `<m:colorgroup>` + 每个三角形的 `pid`/`p1`，读不到上面这些字段，于是**打开就是白模**。

本工具做的就是把这三处信息还原出来，写成标准颜色字段，并且**完全不动几何**。

---

## 特性

- **逐三角面颜色**，不是整块上色：同一个零件表面的多色图案（文字、像素花纹、描边）都能还原。
- **几何零改动**：顶点、三角面、object 划分、build/component 变换全部照抄源文件；不简化、不重网格、不合并顶点、不修退化面。
- **同时输出两种格式**：标准彩色 3MF，以及 OBJ + MTL（服务商明确说收 OBJ+MTL 时用）。
- **支持 object 内部的多个 part**：每个 part 各自的 `extruder` 都会被正确取用。
- **零依赖**：只用 Python 标准库，不需要装任何 pip 包。
- **批量**：一次可以拖入多个 3MF。
- **自带自测**：`selftest.py` 会用独立解析代码重新读回生成的文件，核对三角面数、逐面颜色、包围盒与颜色统计。

---

## 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11（`convert.py` 本身跨平台，macOS / Linux 可直接命令行运行） |
| Python | 3.8 或更高（推荐 3.10+）。安装时务必勾选 **Add python.exe to PATH** |
| 第三方库 | 无 |
| 输入 | Bambu Studio / OrcaSlicer 保存的**工程 3MF**（含 `Metadata/project_settings.config`） |

---

## 快速开始

### 方式一：拖拽（推荐给不写代码的用户）

1. 把要转换的 `.3mf` 文件（可以多选）**拖到 `拖拽转换.bat` 上**松手。
   非中文系统可以用内容完全相同的 `drag_and_drop.bat`。
2. 弹出的窗口会自动转换，几秒钟后显示识别到的颜色、每种颜色的三角面数以及输出路径。
3. 转换完成后，**源文件旁边**会出现一个同名文件夹，里面就是彩色文件。

```
TNT+AMS+Detailed.3mf                    ← 原文件，不会被修改
TNT+AMS+Detailed_color\                 ← 新出现的文件夹
    TNT+AMS+Detailed_color.3mf          ← 上传给打印服务商用这个
    TNT+AMS+Detailed_color.obj
    TNT+AMS+Detailed_color.mtl
    TNT+AMS+Detailed_color.zip
```

### 方式二：命令行

```bash
# 单个文件
python convert.py TNT+AMS+Detailed.3mf

# 多个文件
python convert.py 模型A.3mf 模型B.3mf

# 指定统一的输出目录
python convert.py 模型A.3mf 模型B.3mf -o D:\输出

# 也可以直接传一个目录，转换里面所有 .3mf
python convert.py D:\下载\模型
```

输出目录默认是 `<源文件所在目录>\<源文件名>_color\`。

### 跑一遍自测

```bash
python selftest.py                     # 默认测试仓库里的样例路径
python selftest.py 你的文件.3mf        # 也可以指定任意 3MF
```

结果会打印到屏幕，同时写入 `自测报告.txt`。自测在临时目录中进行，**不会改动原始文件**。

---

## 输出文件说明

| 文件 | 说明 | 建议 |
|---|---|---|
| `<原名>_color.3mf` | 标准彩色 3MF。`<m:colorgroup>` 定义颜色表，每个三角形用 `pid` + `p1` 指定颜色 | **首选上传件**，兼容性最好、体积最小 |
| `<原名>_color.obj` | 通用 OBJ，顶点已按原始摆放位置输出，按颜色用 `usemtl` 分组 | 必须和 `.mtl` 一起使用 |
| `<原名>_color.mtl` | 材质库，每个材质用 `Kd` 给出对应 RGB（0~1，即十六进制色号 ÷ 255） | 必须和 `.obj` 放在同一目录 |
| `<原名>_color.zip` | 上面三个文件打包 | 平台「只收压缩包」或要求 OBJ+MTL 时用它 |

> 如果目标平台要求 OBJ+MTL：把 `.obj` 和 `.mtl` **一起打包成 zip** 上传，两个文件不能分开传，否则颜色会丢失。

命令行输出示例：

```
源文件      : TNT+AMS+Detailed.3mf
网格数量    : 4 个
三角面总数  : 10248
AMS 颜色表  : 1=#FFFFFF(白色)  2=#000000(黑色)  3=#FF0000(红色)  4=#C0C0C0(银色)
实际用到颜色:
    #FF0000   红色       6532 面
    #FFFFFF   白色       2276 面
    #000000   黑色        736 面
    #C0C0C0   银色        704 面
各网格：
    top.test.stl        1622 面   (#FF0000 1002，#C0C0C0 352，#000000 244，#FFFFFF 24)
    base.test.stl       1796 面   (#FFFFFF 1116，#FF0000 556，#000000 124)
    ...
```

---

## 原理简述

### 1. 读取三个颜色来源

```text
Metadata/project_settings.config   →  filament_colour = ["#FFFFFF", "#000000", "#FF0000", ...]
Metadata/model_settings.config     →  <object id="6"><metadata key="extruder" value="1"/>
                                      <part id="5"><metadata key="extruder" value="3"/>
每个 <triangle paint_color="…"/>   →  该面实际使用的槽位（Bambu 私有位流）
```

优先级：三角面自己的 `paint_color` > 所属 part 的 `extruder` > 所属 object 的 `extruder`。

### 2. 解码 `paint_color` 位流

`paint_color` 是 BambuStudio `TriangleSelector` 的序列化结果（**不是**简单的一个数字）。规则：

- 每个节点占 4 bit（一个 nibble）：低 2 位是 `split_sides`；
  - `split_sides == 0` 是叶子节点，状态（= AMS 槽位号）取 `code >> 2`；
  - 状态 ≥ 3 时走转义：当前 nibble 的低 4 位为 `0b1100`，继续读下一个 nibble `n`，状态 = `n + 15×k + 3`；
  - `split_sides > 0` 表示该三角面被细分过，子节点数 = `split_sides + 1`，此时取叶子中占比最高的状态。
- bit 在 nibble 内按 LSB 优先排列；整个十六进制串是一个**大端数字**，所以要从最右边一个字符开始往左读。

这套规则已用「按 BambuStudio 源码重写序列化器 → 随机生成 2000 棵树 → 反向解码比对」做过往返验证，0 处不一致；生成的短码也与实际文件完全吻合（槽位 1→`4`，2→`8`，3→`0C`，4→`1C`）。

### 3. 写成标准颜色字段

- 3MF：在 `<model>` 根节点声明材料扩展命名空间
  `xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02"`，
  在 `<resources>` 里写 `<m:colorgroup>`，每个三角形写 `pid`（颜色组 id）+ `p1`（颜色下标）。
- OBJ / MTL：按颜色分组 `usemtl`，MTL 里 `Kd` = 十六进制 ÷ 255。

> ⚠️ 一个容易踩的坑：Bambu 工程的网格通常不在 `3D/3dmodel.model` 里，而在 `3D/Objects/object_N.model`。**`pid` 只在同一个 model 部件内有效**，所以颜色组必须写进每个含网格的子部件自己的 `<resources>` 里。本工具已正确处理。

---

## 自测结果

对两个真实工程 3MF 的自动校验结果（用独立解析代码重新读回生成的文件）：

| 样例 | 三角面数（源 → 生成） | 逐面颜色 | 摆放包围盒偏差 | 颜色统计 |
|---|---|---|---|---|
| `TNT+AMS+Detailed.3mf` | 10248 → 10248 ✔ | 0 个缺色 / 0 个越界 ✔ | `0.000e+00` ✔ | 红 `#FF0000` 6532、白 `#FFFFFF` 2276、黑 `#000000` 736、银 `#C0C0C0` 704 |
| `按键版.3mf`（含 object 内多 part） | 280068 → 280068 ✔ | 0 个缺色 / 0 个越界 ✔ | `0.000e+00` ✔ | 棕红 `#9D432C` 122926、米 `#E8DBB7` 101452、橙 `#FF9016` 53050、黑 `#000000` 2640 |

完整报告见 [`自测报告.txt`](自测报告.txt)。

---

## 常见问题

### Q1. 打印服务商说「模型没有颜色」，怎么办？

说明上传的是**原始工程 3MF**。用本工具生成 `<原名>_color.3mf`，然后重新上传这一个文件即可。

### Q2. 全彩下单到底该传 3MF 还是 zip？

两种都行，看对方要求：

- 对方说「可以上传 3mf 彩色文件」→ 传 `<原名>_color.3mf`，最省事。
- 对方说「OBJ 需要 MTL，打包成压缩包上传」→ 传 `<原名>_color.zip`（里面已含 OBJ + MTL + 3MF）。
- 自己打包时注意：`.obj` 和 `.mtl` **必须同时在压缩包里**，只传 OBJ 会丢颜色。

### Q3. 怎么自检颜色有没有被识别？

上传后看订单页/预览页的**模型缩略图**：

- 是彩色的 → 成功；
- 还是灰白 → 传错了文件，或者传的还是原始工程 3MF，换成 `_color.3mf` 重传。

本地也可以先看：用支持多色的查看器打开 `_color.3mf`（Windows「3D 查看器」、Blender 装 3MF 插件、部分在线 3MF 预览站），或者直接看 MTL 里的 `Kd` 是否与预期色号对应。

### Q4. 订单被判「有问题」之后怎么处理？

1. **优先走「替换文件」**：多数平台在订单详情里有「替换模型 / 重新上传文件」入口，把 `_color.3mf` 传上去即可，不用重新下单。
2. 如果订单已经无法修改，就**取消后用彩色文件重新下单**。
3. 订单备注里可以写明：*文件内已含逐三角面 RGB 颜色，请按 3MF/OBJ 中的材质颜色对应选材*。
4. 需要人工核对时，把 `自测报告.txt` 里的颜色统计一并提供给对方，说明每种颜色各占多少个三角面。

### Q5. 哪些文件不支持 / 有什么限制？

| 情况 | 结果 |
|---|---|
| 普通 3MF、STL、STEP、无 MTL 的 OBJ | **不支持**（没有 AMS 颜色信息），只能输出单色 |
| 已经是彩色的 3MF（含 `<m:colorgroup>`） | 会被重新按本工具的颜色表处理；不需要重复转换 |
| 贴图 / 纹理（image texture） | **不支持**，只处理逐三角面的纯色 |
| 颜色准不准 | 取的是**工程里的 AMS 槽位色**，不是真实耗材色。作者在工程里把槽位设成什么色，输出就是什么色 |
| 一个工程有多个盘（plate） | 整份转换，所有 object 保留原位置，不按盘拆分 |
| 几何有退化面 / 重复面 / 非流形 | **原样保留**，本工具只加颜色，不做任何修复 |
| 超大模型 | 会慢一些，28 万三角面约 12 秒 |
| 输出的 3MF 能否用 Bambu Studio 打开 | 可以，但会当作普通 3MF 导入：**只保留几何与颜色**，不含打印参数、缩略图、切片信息 |

---

## 手工替代方案

如果不想用脚本，也可以靠现成软件和手改 XML 完成，思路与注意事项见 **[MANUAL.md](MANUAL.md)**，内容包括：

- 用 Bambu Studio 拆件看 AMS 颜色 → 导出 STL → Microsoft 3D Builder / Blender 逐块上色 → 另存 3MF 或导出 OBJ+MTL；
- 手改 3MF 的 XML 要点：`m:colorgroup`、`pid`/`p1`、`pid` 只在同一 model 部件内有效、重新打包 zip 时 `[Content_Types].xml` 等文件必须保留。

> 注意：手工路线只能**整块上色**。像同一个零件表面有黑白红像素图案的模型，手工刷不出原效果，这种情况请直接用本工具。

---

## 目录结构

```
Private-3mf-to-Formate-3mf/
├── convert.py              # 主程序（命令行入口）
├── 拖拽转换.bat             # Windows 拖拽入口（中文系统）
├── drag_and_drop.bat       # 同上，内容一致，方便非中文系统
├── selftest.py             # 自测脚本（转换两个样例 + 独立校验 + 写报告）
├── 自测报告.txt             # 自测输出（UTF-8 BOM）
├── 使用说明.txt             # 面向普通用户的三步说明
├── MANUAL.md               # 手工替代路线 + 手改 XML 要点
├── README.md               # 本文件
├── LICENSE                 # MIT
└── .gitignore
```

---

## 许可

本项目采用 [MIT License](LICENSE)。可自由用于个人与商业用途。

Copyright (c) 2026 gengyangze-hub

---

## English overview

**Private-3mf-to-Formate-3mf** converts multi-colour **Bambu Studio / OrcaSlicer project 3MF files** into standard, colour-carrying **3MF** and **OBJ+MTL**, so generic 3D software and full-colour print services (e.g. JLC) can actually see the colours.

**The problem.** In a Bambu project the colours are not stored in standard 3MF colour fields. They live in three proprietary places: the AMS slot palette (`Metadata/project_settings.config` → `filament_colour`), the per-object/per-part slot index (`Metadata/model_settings.config` → `extruder`), and a per-triangle `paint_color` bitstream. Naive importers ignore all three and render a plain white model.

**What it does.** It decodes the `paint_color` bitstream (BambuStudio `TriangleSelector` encoding), resolves unpainted triangles to their part/object slot, then rewrites the file with a standard `<m:colorgroup>` plus `pid`/`p1` on every triangle — and emits an OBJ + MTL alongside it. Geometry is copied verbatim: no decimation, no remeshing, no vertex welding, no repair.

**Requirements.** Windows 10/11 (the script itself is cross-platform) and Python 3.8+. No third-party packages.

**Usage.**

```bash
# drag & drop
#   drag one or more .3mf files onto  drag_and_drop.bat

# command line
python convert.py model.3mf                 # -> model_color.3mf / .obj / .mtl / .zip
python convert.py a.3mf b.3mf -o out_dir    # batch, custom output folder
python selftest.py model.3mf                # convert + independently verify
```

Output goes to a `<input_name>_color/` folder next to each source file. Upload the `_color.3mf` (or the `_color.zip` when the service asks for OBJ+MTL). After uploading, check that the order thumbnail is in colour — that is the quickest self-check.

See [MANUAL.md](MANUAL.md) for a no-code manual workflow, and [自测报告.txt](自测报告.txt) for the verification report.

Licensed under the [MIT License](LICENSE).
