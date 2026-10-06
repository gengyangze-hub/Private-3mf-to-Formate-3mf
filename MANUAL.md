# 手工做彩色 3MF / OBJ+MTL 的替代路线

这份文档给「不想用脚本、想自己动手」的用户。两条路线：**A. 用现成软件重新上色**，**B. 直接手改 3MF 里的 XML**。

---

## A. 用软件重新上色（不需要写代码）

适合：模型不大、零件块数不多（比如本单的顶板 + 底座两件）。

### 1. 在 Bambu Studio 里确认颜色
- 用 Bambu Studio 打开工程 3mf，看右侧/下方的 **AMS 槽位**，记下每个槽位的颜色（例如槽位1 白 `#FFFFFF`、槽位3 红 `#FF0000`）。
- 鼠标点选各个零件，看它是分给了哪个槽位。多色模型往往是靠 **「涂色」**（涂抹工具）把同一个零件的不同面刷成不同槽位——这种情况下颜色信息不在「零件」层级，而是在**每个三角面**上，手工是刷不回精确结果的，建议直接用脚本工具。
- 也可以看 `Metadata/plate_*.png`（切片预览图）确认成品配色的模样。

### 2. 拆件、导出 STL
- Bambu Studio：右键对象 →「拆分」→「按对象/按部件拆分」，把想单独上色的部分分开。
- 文件 → 导出 → 导出为 STL（每个部件一个 STL）。

### 3. 用软件给每块上色
- **Microsoft 3D Builder**（Win10/11 自带，最简单）：
  1. 打开一个 STL → 点「颜色/材质」→ 选一个颜色 → 点「涂色」刷满整块；
  2. 「插入」→ 把其它 STL 也加进来（3D Builder 会保留各自的颜色）；
  3. 另存为 **3MF**（3D Builder 保存的 3MF 自带颜色）。
  - 注意：3D Builder 的颜色是**按对象**的，不是逐三角面；只要每个颜色块是独立对象就没问题。
- **Blender**（免费，功能强）：
  1. 导入 OBJ/STL；
  2. 每个部件加一个材质，`Base Color` 填对应颜色的 **sRGB 十六进制**（注意 Blender 的颜色选择器要在 RGB 页签里填 0~255 或十六进制，别填线性值）；
  3. 导出：`文件 → 导出 → Wavefront (.obj)`，勾上「导出材质」，会同时得到 `.obj` + `.mtl`。

### 4. 交付给嘉立创
- 传 **3MF**，或者把 **OBJ + MTL 一起打包成 zip** 上传（两者不能分开传）。
- 上传后看订单缩略图是不是彩色的来自检。

> 这条路线的问题：**只能整块上色**。像 "TNT 按键玩具" 这种同一个零件表面有黑 / 白 / 红多色像素图案的模型，靠软件刷是刷不出原效果的——只能回退到路线 B 或直接用脚本。

---

## B. 直接手改 3MF 的 XML

3MF 本质是一个 **zip 压缩包**。把 `xxx.3mf` 复制一份、改名成 `xxx.zip`，解压就能看到里面的 XML。

一个 Bambu 工程 3mf 的典型结构：

```
[Content_Types].xml
_rels/.rels
3D/3dmodel.model                 ← 主模型（列出 build 和 object）
3D/_rels/3dmodel.model.rels      ← 声明子部件的路径关系
3D/Objects/object_1.model        ← 真正的网格在这里
3D/Objects/object_2.model
Metadata/project_settings.config ← 颜色表 filament_colour
Metadata/model_settings.config   ← 每个 object / part 的 extruder（槽位号）
```

### 要点 1：根节点要加材料扩展命名空间
在每个 `.model` 文件的 `<model>` 标签上加上：

```xml
<model unit="millimeter"
       xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
       xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
```

### 要点 2：在 `<resources>` 里定义颜色组
`id` 不能和同一文件里已有的 object id 冲突（取「现有最大 id + 1」最保险）：

```xml
<resources>
  <m:colorgroup id="100">
    <m:color color="#FFFFFF"/>
    <m:color color="#000000"/>
    <m:color color="#FF0000"/>
    <m:color color="#C0C0C0"/>
  </m:colorgroup>
  <object id="2" type="model" name="part">
    ...
  </object>
</resources>
```

### 要点 3：每个三角形写 `pid` + `p1`
- `pid` = 颜色组的 id（上面例子里的 100）
- `p1` = 颜色组里的**下标**（从 0 开始，第 1 个颜色是 0）

```xml
<triangles>
  <triangle v1="0" v2="1" v3="2" pid="100" p1="2"/>   <!-- 红色 -->
  <triangle v1="3" v2="2" v3="4" pid="100" p1="0"/>   <!-- 白色 -->
</triangles>
```

顺带把 Bambu 私有的 `paint_color="..."` 属性删掉（它不是标准属性，留着也无害，但会干扰阅读）。

### ⚠️ 要点 4（最容易踩坑）：`pid` 只在同一个 model 部件内有效
Bambu 工程的网格不在 `3D/3dmodel.model` 里，而在 `3D/Objects/object_N.model` 里。
**如果你在 `object_3.model` 的三角形上写 `pid="100"`，那颜色组就必须定义在 `object_3.model` 自己的 `<resources>` 里**，不能只写在主 `3dmodel.model` 里——写了也不生效，打开还是白的。

所以：**每个含网格的 `.model` 文件都要各自放一份 `<m:colorgroup>`。**

### 要点 5：重新打包
- 必须保留：`[Content_Types].xml`、`_rels/.rels`、`3D/3dmodel.model`、`3D/_rels/3dmodel.model.rels` 以及所有 `3D/Objects/*.model`。
- `[Content_Types].xml` 里要有 `.model` 扩展名的声明，否则整个包无效：

```xml
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels"  ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
```

- 把这些文件按**原来的相对路径**放进一个新 zip 的**根目录**（不要多套一层文件夹），压缩格式用普通 deflate，最后把扩展名改回 `.3mf`。
- 用 7-Zip 或 Windows 资源管理器「发送到 → 压缩(zipped)文件夹」都可以。

### 要点 6：检查
- 用支持多色的查看器打开（Bambu Studio 的「导入 3MF」、Windows 3D 查看器、Blender 装 3MF 插件、或在线 3MF 预览）确认颜色对不对。
- 上传嘉立创后看订单缩略图是否彩色。

---

## 附：颜色怎么定
| 十六进制 | MTL 里的 Kd（0~1） | 说明 |
|---|---|---|
| `#FF0000` | `1.000000 0.000000 0.000000` | 红 |
| `#FFFFFF` | `1.000000 1.000000 1.000000` | 白 |
| `#000000` | `0.000000 0.000000 0.000000` | 黑 |
| `#C0C0C0` | `0.752941 0.752941 0.752941` | 银（浅灰） |

Kd 的算法：把十六进制每两位转成 0~255 的整数，再除以 255。
（与脚本工具输出的 MTL 保持一致，方便两个来源的文件互相对照。）
