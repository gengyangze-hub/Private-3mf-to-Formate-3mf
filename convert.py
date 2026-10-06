#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bambu / Orca 工程 3MF 一键转彩色
================================
把 Bambu Studio / OrcaSlicer 的多色工程 3MF，转成嘉立创全彩树脂打印能识别的
「带逐三角面颜色」的 3MF 和 OBJ+MTL。

用法：
    python convert.py 文件1.3mf [文件2.3mf ...] [-o 输出目录]
    （普通用户直接把这些文件拖到 拖拽转换.bat 上即可）

颜色来源：
    * Metadata/project_settings.config 的 filament_colour  → AMS 槽位颜色表
    * Metadata/model_settings.config 里每个 object / part 的 extruder → 默认槽位
    * 每个三角面自身的 paint_color（Bambu 涂抹多色位流）→ 该面实际使用的槽位
      未涂色的面回落到它所属 part（或 object）的 extruder

几何完全保真：顶点、三角面、object 划分、build/component 变换全部照抄源文件，
只增加颜色信息，不做简化、重网格、合并顶点或修复。
"""

import os
import re
import sys
import json
import argparse
import zipfile
import traceback
import xml.etree.ElementTree as ET
from collections import Counter

# ---------------------------------------------------------------- 常量
MAT_NS = 'http://schemas.microsoft.com/3dmanufacturing/material/2015/02'
ROOT_MODEL = '3D/3dmodel.model'

TRI_RE = re.compile(r'<triangle\b[^>]*?(/?)>')
OBJ_BLOCK_RE = re.compile(r'<object\b([^>]*?)>(.*?)</object>', re.S)
MESH_RE = re.compile(r'<mesh\b.*?</mesh>', re.S)

CN_COLOR_NAMES = {
    '#FFFFFF': '白色', '#000000': '黑色', '#FF0000': '红色', '#C0C0C0': '银色',
    '#808080': '灰色', '#FF9016': '橙色', '#E8DBB7': '米色', '#9D432C': '棕红色',
    '#00FF00': '绿色', '#0000FF': '蓝色', '#FFFF00': '黄色', '#FF00FF': '品红',
    '#00FFFF': '青色', '#E5B03D': '金黄色', '#A8C6EE': '浅蓝色', '#008BDA': '蓝色',
    '#7D6556': '棕色', '#050572': '深蓝色', '#609EF7': '天蓝色', '#BB3D43': '砖红色',
    '#FFF144': '亮黄色', '#D3B7A7': '浅棕色', '#7C4B00': '深棕色', '#C12E1F': '暗红色',
    '#F5F5F5': '近白色', '#D9D9D9': '浅灰色', '#4D4D4D': '深灰色', '#C8C8C8': '浅灰色',
}


def colname(hexstr):
    return CN_COLOR_NAMES.get(str(hexstr).upper(), '')


# ---------------------------------------------------------------- 位流解码
def decode_paint_leaves(hexstr, max_nodes=2000000):
    """解码一个三角面的 Bambu paint_color 位流，返回（叶子状态列表, 是否完整消费）。

    编码规则（源自 BambuStudio src/libslic3r/TriangleSelector.cpp）：
      每个节点 4 位：bit0..1 = split_sides；split_sides==0 为叶子。
        叶子状态 <3：state = code>>2
        叶子状态 >=3：若 (code & 0b1100)==0b1100，继续读 nibble 得 n，
                      state = n + 15*k + 3（每遇到一个 0b1111 就让 k+1）
      非叶子：code>>2 = special_side，子节点数 = split_sides+1
      bit 在 nibble 内按 LSB 优先排布；整个十六进制串是一个大端数字，
      所以 nibble 要从字符串最右边一个字符开始往左读。
    """
    if not hexstr:
        return [], True
    try:
        nib = [int(c, 16) for c in hexstr.strip()]
    except ValueError:
        return [], False
    i = len(nib)
    ok = True

    def nxt():
        nonlocal i, ok
        if i <= 0:
            ok = False
            return 0
        i -= 1
        return nib[i]

    leaves = []
    parents = []
    guard = 0
    while ok and guard < max_nodes:
        guard += 1
        code = nxt()
        if not ok:
            break
        split_sides = code & 3
        nch = 0 if split_sides == 0 else split_sides + 1
        is_split = nch != 0
        state = 0
        if not is_split:
            if (code & 0xC) == 0xC:
                ext = nxt()
                k = 0
                while ok and ext == 0xF:
                    k += 1
                    ext = nxt()
                if not ok:
                    break
                state = ext + 15 * k + 3
            else:
                state = code >> 2
        if not parents:
            if is_split:
                parents.append([0, nch])
                continue
            leaves.append(state)
            break
        if is_split:
            parents.append([0, nch])
        else:
            leaves.append(state)
            parents[-1][0] += 1
        while parents and parents[-1][0] == parents[-1][1]:
            parents.pop()
            if parents:
                parents[-1][0] += 1
        if not parents:
            break
    return leaves, (ok and i == 0)


# ---------------------------------------------------------------- 变换
def parse_transform(s):
    if not s:
        return None
    try:
        v = [float(x) for x in s.replace(',', ' ').split()]
    except ValueError:
        return None
    return v if len(v) == 12 else None


def mat_mul(a, b):
    A = [[a[0], a[1], a[2], a[9]], [a[3], a[4], a[5], a[10]], [a[6], a[7], a[8], a[11]], [0, 0, 0, 1]]
    B = [[b[0], b[1], b[2], b[9]], [b[3], b[4], b[5], b[10]], [b[6], b[7], b[8], b[11]], [0, 0, 0, 1]]
    C = [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    return [C[0][0], C[0][1], C[0][2], C[1][0], C[1][1], C[1][2],
            C[2][0], C[2][1], C[2][2], C[0][3], C[1][3], C[2][3]]


def mat_apply(m, p):
    if m is None:
        return p
    x, y, z = p
    return (x * m[0] + y * m[3] + z * m[6] + m[9],
            x * m[1] + y * m[4] + z * m[7] + m[10],
            x * m[2] + y * m[5] + z * m[8] + m[11])


def local(tag):
    return tag.split('}')[-1]


def attr_path(el):
    for k, v in el.attrib.items():
        if k == 'path' or k.endswith('}path'):
            return v
    return None


# ---------------------------------------------------------------- 读取工程
def read_project(path):
    z = zipfile.ZipFile(path)
    names = z.namelist()
    warn = []

    # 1) 主 model 部件：优先从 _rels/.rels 里找 3dmodel 关系
    root_name = ROOT_MODEL if ROOT_MODEL in names else None
    if '_rels/.rels' in names:
        try:
            for r in ET.fromstring(z.read('_rels/.rels')):
                if (r.get('Type') or '').endswith('/3dmodel'):
                    tgt = (r.get('Target') or '').lstrip('/')
                    if tgt in names:
                        root_name = tgt
                        break
        except ET.ParseError:
            pass
    if root_name is None:
        cands = [n for n in names if n.lower().endswith('3dmodel.model')]
        root_name = cands[0] if cands else None
    if root_name is None:
        raise ValueError('找不到 3D/3dmodel.model，这可能不是有效的 3MF 文件')

    # 2) 颜色表
    palette = []
    if 'Metadata/project_settings.config' in names:
        try:
            cfg = json.loads(z.read('Metadata/project_settings.config').decode('utf-8', 'replace'))
            for c in cfg.get('filament_colour', []):
                c = str(c).strip().lstrip('#')
                if len(c) == 8:
                    c = c[:6]                       # 去掉透明度
                if len(c) == 6 and re.fullmatch(r'[0-9a-fA-F]{6}', c):
                    palette.append('#' + c.upper())
                else:
                    palette.append('#FFFFFF')
        except Exception as e:
            warn.append('project_settings.config 解析失败（%s），颜色表按白色处理' % e)
    if not palette:
        txt = z.read(root_name).decode('utf-8', 'replace')
        for m in re.finditer(r'displaycolor="(#?[0-9a-fA-F]{6,8})"', txt):
            c = m.group(1).lstrip('#')[:6]
            if re.fullmatch(r'[0-9a-fA-F]{6}', c):
                palette.append('#' + c.upper())
        if not palette:
            palette = ['#FFFFFF']
            warn.append('这个 3mf 里没有 Metadata/project_settings.config，'
                        '可能不是 Bambu Studio / OrcaSlicer 保存的工程文件（颜色按白色处理）')

    # 3) object / part 的 extruder
    obj_ext, part_ext, obj_name, part_name = {}, {}, {}, {}
    if 'Metadata/model_settings.config' in names:
        try:
            for o in ET.fromstring(z.read('Metadata/model_settings.config')):
                if local(o.tag) != 'object':
                    continue
                oid, ext, parts = o.get('id'), 1, {}
                names_, pnames = {}, {}
                for ch in o:
                    if local(ch.tag) == 'metadata':
                        if ch.get('key') == 'extruder':
                            try:
                                ext = int(ch.get('value'))
                            except (TypeError, ValueError):
                                pass
                        elif ch.get('key') == 'name':
                            names_['self'] = ch.get('value')
                    elif local(ch.tag) == 'part':
                        pex, pnm = None, None
                        for pm in ch:
                            if local(pm.tag) == 'metadata':
                                if pm.get('key') == 'extruder':
                                    try:
                                        pex = int(pm.get('value'))
                                    except (TypeError, ValueError):
                                        pex = None
                                elif pm.get('key') == 'name':
                                    pnm = pm.get('value')
                        if pex:
                            parts[ch.get('id')] = pex
                        if pnm:
                            pnames[ch.get('id')] = pnm
                obj_ext[oid] = ext
                part_ext[oid] = parts
                obj_name[oid] = names_.get('self')
                part_name[oid] = pnames
        except Exception as e:
            warn.append('model_settings.config 解析失败（%s），所有 object 按槽位 1 处理' % e)

    # 4) 所有 model 部件
    docs = {}
    for n in names:
        if not n.lower().endswith('.model'):
            continue
        raw = z.read(n)
        try:
            docs[n] = {'text': raw.decode('utf-8', 'replace'), 'el': ET.fromstring(raw)}
        except ET.ParseError as e:
            warn.append('部件 %s 解析失败：%s' % (n, e))
    if root_name not in docs:
        raise ValueError('主模型部件 %s 无法解析' % root_name)

    return {'zip': z, 'names': names, 'root_name': root_name, 'docs': docs,
            'palette': palette, 'obj_ext': obj_ext, 'part_ext': part_ext,
            'obj_name': obj_name, 'part_name': part_name,
            'warn': warn, '_mcache': {}, '_ccache': {}, '_acache': {}}


def doc_objects(doc_el):
    out = {}
    for o in doc_el.iter():
        if local(o.tag) != 'object':
            continue
        comps, has_mesh = [], False
        for ch in o:
            if local(ch.tag) == 'components':
                for c in ch:
                    comps.append((c.get('objectid'), parse_transform(c.get('transform')), attr_path(c)))
            elif local(ch.tag) == 'mesh':
                has_mesh = True
        out[o.get('id')] = {'components': comps, 'has_mesh': has_mesh, 'name': o.get('name')}
    return out


def build_items(doc_el):
    return [(it.get('objectid'), parse_transform(it.get('transform')))
            for it in doc_el.iter() if local(it.tag) == 'item']


def find_doc_for_path(proj, path):
    if not path:
        return None
    p = path.lstrip('/')
    if p in proj['docs']:
        return p
    for n in proj['docs']:
        if n.lower() == p.lower():
            return n
    return None


def collect_instances(proj):
    """遍历 build items，收集所有叶子网格实例（带完整变换链）。"""
    docs = proj['docs']
    insts = []

    def walk(doc_name, objid, matrix, root_obj, depth):
        if depth > 12:
            return
        doc = docs.get(doc_name)
        if doc is None:
            return
        o = doc_objects(doc['el']).get(objid)
        if o is None:
            return
        if o['has_mesh']:
            nm = (proj['part_name'].get(root_obj, {}).get(objid)
                  or proj['obj_name'].get(root_obj) or o['name'])
            insts.append({'doc': doc_name, 'obj': objid, 'matrix': matrix,
                          'root_obj': root_obj, 'name': nm})
        for cid, ctf, cpath in o['components']:
            nd = find_doc_for_path(proj, cpath) or doc_name
            nm = mat_mul(matrix, ctf) if (matrix and ctf) else (ctf or matrix)
            walk(nd, cid, nm, root_obj, depth + 1)

    for objid, tf in build_items(docs[proj['root_name']]['el']):
        walk(proj['root_name'], objid, tf, objid, 0)
    return insts


def default_extruder(proj, root_objid, leaf_objid):
    parts = proj['part_ext'].get(root_objid, {})
    if leaf_objid in parts:
        return parts[leaf_objid]
    return proj['obj_ext'].get(root_objid, 1)


# ---------------------------------------------------------------- 缓存访问
def object_mesh_text(proj, doc_name, obj_id):
    key = (doc_name, obj_id)
    if key in proj['_mcache']:
        return proj['_mcache'][key]
    res = None
    doc = proj['docs'].get(doc_name)
    if doc:
        pat = re.compile(r'\bid="%s"' % re.escape(str(obj_id)))
        for mo in OBJ_BLOCK_RE.finditer(doc['text']):
            if pat.search(mo.group(1)):
                mm = MESH_RE.search(mo.group(2))
                if mm:
                    res = mm.group(0)
                    break
    proj['_mcache'][key] = res
    return res


def object_color_list(proj, doc_name, obj_id, root_obj, mesh_txt):
    key = (doc_name, obj_id, root_obj)
    if key not in proj['_ccache']:
        dext = default_extruder(proj, root_obj, obj_id)
        proj['_ccache'][key] = object_colors(mesh_txt, dext, proj['palette'])
    return proj['_ccache'][key]


def object_arrays(proj, doc_name, obj_id, mesh_txt):
    key = (doc_name, obj_id)
    if key not in proj['_acache']:
        proj['_acache'][key] = mesh_arrays(mesh_txt)
    return proj['_acache'][key]


def object_colors(mesh_txt, default_ext, palette):
    """该 mesh 每个三角面的颜色索引（0 基，指向 palette）。"""
    n = len(palette) or 1
    out = []
    for t in re.findall(r'<triangle\b[^>]*?/?>', mesh_txt):
        ext = default_ext
        pc = re.search(r'paint_color="([^"]*)"', t)
        if pc and pc.group(1):
            leaves, _ok = decode_paint_leaves(pc.group(1))
            if leaves:
                # 被细分过的三角面：取叶子中占优的状态（各子节点等面积）
                st = Counter(leaves).most_common(1)[0][0]
                if st:                        # 0 表示该处没涂色 → 回落默认槽位
                    ext = st
        try:
            ext = int(ext)
        except (TypeError, ValueError):
            ext = 1
        out.append(max(1, min(ext, n)) - 1)
    return out


def mesh_arrays(mesh_txt):
    verts = re.findall(r'<vertex\s+x="([^"]*)"\s+y="([^"]*)"\s+z="([^"]*)"\s*/>', mesh_txt)
    tris = []
    for t in re.findall(r'<triangle\b[^>]*?/?>', mesh_txt):
        g = re.search(r'v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"', t)
        if g:
            tris.append((int(g.group(1)), int(g.group(2)), int(g.group(3))))
    return verts, tris


# ---------------------------------------------------------------- 3MF 输出
def _add_color_namespace(tag):
    if 'xmlns:m=' in tag:
        return tag
    ins = ' xmlns:m="%s"' % MAT_NS
    return (tag[:-2] + ins + '/>') if tag.endswith('/>') else (tag[:-1] + ins + '>')


def rewrite_model_doc(txt, palette, tri_colors_by_obj):
    """给一个 model 部件加 m:colorgroup，并给每个三角面写 pid/p1。"""
    m = re.search(r'<model\b[^>]*>', txt)
    if m:
        txt = txt[:m.start()] + _add_color_namespace(m.group(0)) + txt[m.end():]

    ids = [int(x) for x in re.findall(r'\bid="(\d+)"', txt)]
    cg_id = (max(ids) + 1) if ids else 1
    group_txt = ('<m:colorgroup id="%d">' % cg_id
                 + ''.join('<m:color color="%s"/>' % c for c in palette)
                 + '</m:colorgroup>')

    if re.search(r'<resources\s*/>', txt):
        txt = re.sub(r'<resources\s*/>', '<resources>%s</resources>' % group_txt, txt, count=1)
    else:
        txt = re.sub(r'(<resources\b[^>]*>)', lambda mm: mm.group(1) + group_txt, txt, count=1)

    def do_obj(mo):
        attrs, body = mo.group(1), mo.group(2)
        om = re.search(r'\bid="([^"]+)"', attrs)
        cols = tri_colors_by_obj.get(om.group(1)) if om else None
        if not cols:
            return mo.group(0)
        k = [0]

        def do_tri(mt):
            tag = mt.group(0)
            i = k[0]
            k[0] += 1
            tag = re.sub(r'\s+paint_color="[^"]*"', '', tag)
            tag = re.sub(r'\s+(pid|p1)="[^"]*"', '', tag)
            t = tag[:-2] if tag.endswith('/>') else tag[:-1]
            p1 = cols[i] if i < len(cols) else 0
            return '%s pid="%d" p1="%d"/>' % (t.rstrip(), cg_id, p1)

        return '<object%s>%s</object>' % (attrs, TRI_RE.sub(do_tri, body))

    return OBJ_BLOCK_RE.sub(do_obj, txt)


def build_3mf(proj, path_out):
    """生成彩色 3mf（保留源文件的部件结构与全部变换）。"""
    z, names, palette = proj['zip'], proj['names'], proj['palette']

    reachable = {}
    for inst in proj['_insts']:
        reachable.setdefault(inst['doc'], {})[inst['obj']] = inst['root_obj']

    mod_docs = {}
    for doc_name, doc in proj['docs'].items():
        obj_cols = {}
        for mo in OBJ_BLOCK_RE.finditer(doc['text']):
            om = re.search(r'\bid="([^"]+)"', mo.group(1))
            if not om:
                continue
            oid = om.group(1)
            mm = MESH_RE.search(mo.group(2))
            if not mm:
                continue
            mesh = mm.group(0)
            root = reachable.get(doc_name, {}).get(oid)
            if root is None:
                # 没有被 build item 引用的网格：统一给颜色表第一个颜色，避免出现无颜色三角面
                obj_cols[oid] = [0] * len(re.findall(r'<triangle\b', mesh))
            else:
                obj_cols[oid] = object_color_list(proj, doc_name, oid, root, mesh)
        mod_docs[doc_name] = rewrite_model_doc(doc['text'], palette, obj_cols)

    def content_types(raw):
        t = raw.decode('utf-8', 'replace')
        if 'Extension="model"' not in t and "Extension='model'" not in t:
            t = t.replace('</Types>', '<Default Extension="model" '
                                      'ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        return t.encode('utf-8')

    written = []
    with zipfile.ZipFile(path_out, 'w', zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            if n in mod_docs:
                zo.writestr(n, mod_docs[n])
                written.append(n)
            elif n == '[Content_Types].xml':
                zo.writestr(n, content_types(z.read(n)))
            elif n.endswith('.rels'):
                zo.writestr(n, z.read(n))
    if not written:
        raise ValueError('没有写出任何模型部件')
    return written


# ---------------------------------------------------------------- OBJ / MTL
def mtl_name_for(hexstr):
    return 'color_%s' % str(hexstr).lstrip('#').upper()


def build_obj_mtl(proj, obj_path, mtl_name, stats):
    palette = proj['palette']
    lines = ['# Bambu3MF 一键转彩色 —— 逐三角面颜色 OBJ',
             '# 顶点坐标已按 build/component 变换摆放到原始位置',
             'mtllib %s' % mtl_name]
    base = 1
    total = 0
    for inst in proj['_insts']:
        mesh = object_mesh_text(proj, inst['doc'], inst['obj'])
        if not mesh:
            continue
        verts, tris = object_arrays(proj, inst['doc'], inst['obj'], mesh)
        cols = object_color_list(proj, inst['doc'], inst['obj'], inst['root_obj'], mesh)
        name = inst['name'] or ('object_%s' % inst['obj'])
        lines.append('o %s' % re.sub(r'\s+', '_', name))
        for (x, y, z) in verts:
            px, py, pz = mat_apply(inst['matrix'], (float(x), float(y), float(z)))
            lines.append('v %.9g %.9g %.9g' % (px, py, pz))
        cur = None
        for i, (a, b, c) in enumerate(tris):
            col = cols[i] if i < len(cols) else 0
            if col != cur:
                lines.append('usemtl %s' % mtl_name_for(palette[col]))
                cur = col
            stats[palette[col]] += 1
            lines.append('f %d %d %d' % (a + base, b + base, c + base))
        base += len(verts)
        total += len(tris)
    with open(obj_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')

    mtl_path = os.path.join(os.path.dirname(obj_path), mtl_name)
    with open(mtl_path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('# Bambu3MF 一键转彩色 —— 材质颜色\n'
                 '# Kd 为 0~1 的 sRGB 数值（十六进制色号 ÷ 255），与颜色表一一对应\n')
        for c in palette:
            h = c.lstrip('#')
            r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
            fh.write('\nnewmtl %s\nKd %.6f %.6f %.6f\nKa 0.000000 0.000000 0.000000\n'
                     'Ks 0.000000 0.000000 0.000000\nNs 10.000000\nd 1.000000\nillum 1\n'
                     % (mtl_name_for(c), r, g, b))
    return total


# ---------------------------------------------------------------- 主流程
def process_one(path, out_root=None, verbose=True):
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError('找不到文件：%s' % path)
    if not zipfile.is_zipfile(path):
        raise ValueError('这不是一个 3MF 文件（3MF 本质是 zip 压缩包），或者文件已损坏')

    stem = os.path.splitext(os.path.basename(path))[0]
    outdir = out_root or os.path.join(os.path.dirname(path), stem + '_color')
    os.makedirs(outdir, exist_ok=True)

    proj = read_project(path)
    proj['_insts'] = collect_instances(proj)
    if not proj['_insts']:
        raise ValueError('这个 3mf 里没有任何网格（没有可打印的三角面）')

    for w in proj['warn']:
        print('  [提示] %s' % w)

    total_tris = 0
    colour_stats = Counter()
    per_obj = []
    for inst in proj['_insts']:
        mesh = object_mesh_text(proj, inst['doc'], inst['obj'])
        if not mesh:
            continue
        cols = object_color_list(proj, inst['doc'], inst['obj'], inst['root_obj'], mesh)
        n = len(cols)
        total_tris += n
        cs = Counter(proj['palette'][c] for c in cols)
        colour_stats.update(cs)
        per_obj.append((inst['name'] or inst['obj'], n, cs))
    if total_tris == 0:
        raise ValueError('这个 3mf 里没有可用的三角面')

    out_3mf = os.path.join(outdir, stem + '_color.3mf')
    out_obj = os.path.join(outdir, stem + '_color.obj')
    mtl_name = stem + '_color.mtl'
    out_mtl = os.path.join(outdir, mtl_name)
    out_zip = os.path.join(outdir, stem + '_color.zip')

    build_3mf(proj, out_3mf)
    obj_stats = Counter()
    build_obj_mtl(proj, out_obj, mtl_name, obj_stats)

    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zo:
        zo.write(out_3mf, os.path.basename(out_3mf))
        zo.write(out_obj, os.path.basename(out_obj))
        zo.write(out_mtl, mtl_name)

    if verbose:
        print('=' * 68)
        print('源文件      : %s' % path)
        print('网格数量    : %d 个' % len(proj['_insts']))
        print('三角面总数  : %d' % total_tris)
        print('AMS 颜色表  : %s' % '  '.join(
            '%d=%s%s' % (i + 1, c, ('(' + colname(c) + ')') if colname(c) else '')
            for i, c in enumerate(proj['palette'])))
        print('实际用到颜色:')
        for c, n in colour_stats.most_common():
            print('    %-9s %-4s %8d 面' % (c, colname(c), n))
        print('各网格：')
        for nm, n, cs in per_obj:
            print('    %-30s %8d 面   (%s)' % (
                nm[:30], n, '，'.join('%s %d' % (c, v) for c, v in cs.most_common())))
        print('输出：')
        for p in (out_3mf, out_obj, out_mtl, out_zip):
            print('    %s' % p)

    return {'src': path, 'outdir': outdir, 'tris': total_tris, 'stats': colour_stats,
            'per_obj': per_obj, 'palette': proj['palette'],
            'files': [out_3mf, out_obj, out_mtl, out_zip],
            'obj_stats': obj_stats}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description='Bambu/Orca 多色工程 3MF 一键转彩色（用于嘉立创全彩树脂打印）')
    ap.add_argument('files', nargs='*', help='一个或多个 .3mf 文件（可直接拖拽传入）')
    ap.add_argument('-o', '--outdir', default=None,
                    help='统一输出目录（默认：源文件旁边的 <名字>_color 文件夹）')
    args = ap.parse_args(argv)

    targets = []
    for f in args.files:
        f = f.strip().strip('"')
        if not f:
            continue
        if os.path.isdir(f):
            targets += [os.path.join(f, n) for n in sorted(os.listdir(f))
                        if n.lower().endswith('.3mf')]
        else:
            targets.append(f)

    if not targets:
        print('用法：python convert.py 文件1.3mf [文件2.3mf ...]')
        print('      也可以把 .3mf 文件直接拖到「拖拽转换.bat」上')
        return 1

    print('Bambu3MF 一键转彩色   ——   共 %d 个文件' % len(targets))
    ok = fail = 0
    for t in targets:
        try:
            process_one(t, args.outdir)
            ok += 1
        except Exception as e:
            fail += 1
            print('=' * 68)
            print('[转换失败] %s' % t)
            print('  原因：%s' % e)
            if os.environ.get('BAMBU3MF_DEBUG'):
                traceback.print_exc()
            print('  建议：确认这是 Bambu Studio / OrcaSlicer 保存的工程 3mf，且文件没有损坏。')
    print('=' * 68)
    print('全部完成：成功 %d 个，失败 %d 个' % (ok, fail))
    if ok:
        print('把生成的 _color.3mf（或 _color.zip）上传给嘉立创即可。')
    return 0 if ok else 2


if __name__ == '__main__':
    # 输出编码：直接跑在控制台时沿用控制台编码（配合 bat 里的 chcp 65001），
    # 被重定向/管道捕获时用 UTF-8。只把无法编码的字符替换掉，避免中途报错。
    try:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass
    sys.exit(main())
