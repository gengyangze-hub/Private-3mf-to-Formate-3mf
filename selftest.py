#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自测脚本：调用 convert.py 转换样例文件到临时目录，再用独立解析代码重新读回
生成的 3mf，校验三角面数、逐面颜色、包围盒与颜色统计，结果写入 自测报告.txt。

用法： python selftest.py [文件1.3mf 文件2.3mf ...]
       不带参数时默认测试 TNT+AMS+Detailed.3mf 和 按键版.3mf（在其上级目录里找）。
"""
import os
import re
import sys
import glob
import time
import zipfile
import tempfile
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CONVERT = os.path.join(HERE, 'convert.py')
DEFAULT_SAMPLES = ['TNT+AMS+Detailed.3mf', '按键版.3mf']
MAT_NS = 'http://schemas.microsoft.com/3dmanufacturing/material/2015/02'

CN_NAMES = {
    '#FFFFFF': '白色', '#000000': '黑色', '#FF0000': '红色', '#C0C0C0': '银色',
    '#808080': '灰色', '#FF9016': '橙色', '#E8DBB7': '米色', '#9D432C': '棕红色',
    '#00FF00': '绿色', '#0000FF': '蓝色', '#FFFF00': '黄色', '#00FFFF': '青色',
    '#FF00FF': '品红', '#E5B03D': '金黄色', '#A8C6EE': '浅蓝色', '#008BDA': '蓝色',
    '#7D6556': '棕色', '#050572': '深蓝色', '#609EF7': '天蓝色', '#BB3D43': '砖红色',
    '#FFF144': '亮黄色', '#D3B7A7': '浅棕色', '#7C4B00': '深棕色', '#C12E1F': '暗红色',
    '#F5F5F5': '近白色', '#D9D9D9': '浅灰色', '#4D4D4D': '深灰色', '#C8C8C8': '浅灰色',
}


def local(t):
    return t.split('}')[-1]


def path_attr(el):
    for k, v in el.attrib.items():
        if k == 'path' or k.endswith('}path'):
            return v
    return None


def parse_tf(s):
    if not s:
        return None
    try:
        v = [float(x) for x in s.replace(',', ' ').split()]
    except ValueError:
        return None
    return v if len(v) == 12 else None


def mul(a, b):
    A = [[a[0], a[1], a[2], a[9]], [a[3], a[4], a[5], a[10]], [a[6], a[7], a[8], a[11]], [0, 0, 0, 1]]
    B = [[b[0], b[1], b[2], b[9]], [b[3], b[4], b[5], b[10]], [b[6], b[7], b[8], b[11]], [0, 0, 0, 1]]
    C = [[sum(A[i][k] * B[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
    return [C[0][0], C[0][1], C[0][2], C[1][0], C[1][1], C[1][2],
            C[2][0], C[2][1], C[2][2], C[0][3], C[1][3], C[2][3]]


def apply(m, p):
    if m is None:
        return p
    x, y, z = p
    return (x * m[0] + y * m[3] + z * m[6] + m[9],
            x * m[1] + y * m[4] + z * m[7] + m[10],
            x * m[2] + y * m[5] + z * m[8] + m[11])


def read_model_part(z, name):
    """返回 {objid: {'verts':[...], 'tris':[(a,b,c,pid,p1)], 'components':[...], 'mesh':bool}}"""
    root = ET.fromstring(z.read(name))
    out = {}
    for o in root.iter():
        if local(o.tag) != 'object':
            continue
        verts, tris, comps, has_mesh = [], [], [], False
        for ch in o:
            if local(ch.tag) == 'mesh':
                has_mesh = True
                for s in ch:
                    if local(s.tag) == 'vertices':
                        for v in s:
                            verts.append((float(v.get('x')), float(v.get('y')), float(v.get('z'))))
                    elif local(s.tag) == 'triangles':
                        for t in s:
                            tris.append((int(t.get('v1')), int(t.get('v2')), int(t.get('v3')),
                                         t.get('pid'), t.get('p1')))
            elif local(ch.tag) == 'components':
                for c in ch:
                    comps.append((c.get('objectid'), parse_tf(c.get('transform')), path_attr(c)))
        out[o.get('id')] = {'verts': verts, 'tris': tris, 'components': comps,
                            'mesh': has_mesh, 'name': o.get('name')}
    items = [(it.get('objectid'), parse_tf(it.get('transform')))
             for it in root.iter() if local(it.tag) == 'item']
    return out, items


def walk_project(z):
    """遍历一个 3mf，返回所有叶子网格（带变换链）。"""
    names = z.namelist()
    docs = {}
    for n in names:
        if n.lower().endswith('.model'):
            docs[n] = read_model_part(z, n)
    root_name = '3D/3dmodel.model' if '3D/3dmodel.model' in names else None
    if root_name is None and docs:
        root_name = sorted(docs)[0]

    def find_doc(p):
        if not p:
            return None
        p = p.lstrip('/')
        if p in docs:
            return p
        for n in docs:
            if n.lower() == p.lower():
                return n
        return None

    out = []

    def walk(doc_name, oid, m, depth):
        if depth > 12 or doc_name not in docs:
            return
        objs, _ = docs[doc_name]
        o = objs.get(oid)
        if o is None:
            return
        if o['mesh']:
            out.append({'doc': doc_name, 'obj': oid, 'matrix': m, 'verts': o['verts'], 'tris': o['tris']})
        for cid, ctf, cpath in o['components']:
            nd = find_doc(cpath) or doc_name
            nm = mul(m, ctf) if (m and ctf) else (ctf or m)
            walk(nd, cid, nm, depth + 1)

    objs, items = docs[root_name]
    for oid, tf in items:
        walk(root_name, oid, tf, 0)
    return out


def palette_of(z, docname):
    """读取某个 model 部件里的颜色组（pid 只在同一部件内有效）。"""
    pal = {}
    txt = z.read(docname).decode('utf-8', 'replace')
    for m in re.finditer(r'<m:colorgroup\b[^>]*\bid="(\d+)"[^>]*>(.*?)</m:colorgroup>', txt, re.S):
        pal[m.group(1)] = re.findall(r'<m:color\b[^>]*color="([^"]*)"', m.group(2))
    return pal


def bbox(pts):
    if not pts:
        return None
    return (min(p[0] for p in pts), max(p[0] for p in pts),
            min(p[1] for p in pts), max(p[1] for p in pts),
            min(p[2] for p in pts), max(p[2] for p in pts))


def rb(b):
    return tuple(round(x, 4) for x in b) if b else None


def analyse(path, is_output):
    z = zipfile.ZipFile(path)
    insts = walk_project(z)
    pals = {}
    ntri = 0
    stats = Counter()
    pts = []
    no_colour = 0
    bad_idx = 0
    for it in insts:
        n = len(it['tris'])
        ntri += n
        if it['doc'] not in pals:
            pals[it['doc']] = palette_of(z, it['doc'])
        pal = pals[it['doc']]
        for (a, b, c, pid, p1) in it['tris']:
            if is_output:
                if pid is None or p1 is None or pid not in pal or not (0 <= int(p1) < len(pal[pid])):
                    no_colour += 1
                else:
                    stats[pal[pid][int(p1)]] += 1
            for i in (a, b, c):
                if not (0 <= i < len(it['verts'])):
                    bad_idx += 1
        for v in it['verts']:
            pts.append(apply(it['matrix'], v))
    return {'tris': ntri, 'meshes': len(insts), 'stats': stats, 'bbox': bbox(pts),
            'no_colour': no_colour, 'bad_idx': bad_idx, 'palette': pals}


def count_obj(path):
    nv = nf = 0
    used = Counter()
    cur = None
    for line in open(path, encoding='utf-8'):
        if line.startswith('v '):
            nv += 1
        elif line.startswith('f '):
            nf += 1
            used[cur] += 1
        elif line.startswith('usemtl '):
            cur = line.split()[1]
    return nv, nf, used


def main():
    args = [a for a in sys.argv[1:]]
    samples = args or [os.path.join(os.path.dirname(HERE), s) for s in DEFAULT_SAMPLES]
    samples = [s for s in samples if os.path.exists(s)]
    if not samples:
        print('找不到样例文件，请把 .3mf 路径作为参数传入')
        return 1

    out_root = tempfile.mkdtemp(prefix='bambu3mf_selftest_')
    lines = []
    ok_all = True

    lines.append('Bambu3MF 一键转彩色 —— 自测报告')
    lines.append('=' * 66)
    lines.append('生成时间   : %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    lines.append('测试目录   : %s' % HERE)
    lines.append('临时输出   : %s' % out_root)
    lines.append('测试方法   : 用命令行方式运行 convert.py 转换样例文件，')
    lines.append('             再用独立解析代码（zipfile + XML，不复用 convert.py 的函数）')
    lines.append('             重新读回生成的 _color.3mf，逐项核对。')
    lines.append('')

    for s in samples:
        base = os.path.splitext(os.path.basename(s))[0]
        lines.append('-' * 66)
        lines.append('【样例】%s' % os.path.basename(s))
        t0 = time.time()
        p = subprocess.run([sys.executable, CONVERT, s, '-o', out_root],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        dt = time.time() - t0
        if p.returncode not in (0,) or '全部完成' not in (p.stdout or ''):
            ok_all = False
            lines.append('  转换失败！返回码 %s' % p.returncode)
            lines.append('  stdout: %s' % (p.stdout or '')[-800:])
            lines.append('  stderr: %s' % (p.stderr or '')[-800:])
            lines.append('')
            continue
        lines.append('  转换耗时 : %.1f 秒' % dt)

        src = os.path.join(os.path.dirname(s), base)
        a_src = analyse(s, False)
        out3mf = os.path.join(out_root, base + '_color.3mf')
        outobj = os.path.join(out_root, base + '_color.obj')
        outmtl = os.path.join(out_root, base + '_color.mtl')
        outzip = os.path.join(out_root, base + '_color.zip')
        a_out = analyse(out3mf, True)

        same_tris = (a_src['tris'] == a_out['tris'])
        same_box = (a_src['bbox'] is not None and a_out['bbox'] is not None
                    and max(abs(x - y) for x, y in zip(a_src['bbox'], a_out['bbox'])) < 1e-4)
        coloured = (a_out['no_colour'] == 0)
        idx_ok = (a_out['bad_idx'] == 0)
        nv, nf, used = count_obj(outobj)
        obj_ok = (nf == a_out['tris'])
        zip_ok = zipfile.is_zipfile(outzip) and sorted(zipfile.ZipFile(outzip).namelist()) == \
            sorted([base + '_color.3mf', base + '_color.obj', base + '_color.mtl'])
        use = all(os.path.exists(x) for x in (out3mf, outobj, outmtl, outzip))

        lines.append('  网格数量 : 源 %d 个 → 生成 %d 个' % (a_src['meshes'], a_out['meshes']))
        lines.append('  三角面数 : 源 %d → 生成 %d        %s' % (
            a_src['tris'], a_out['tris'], '一致 ✔' if same_tris else '不一致 ✘'))
        lines.append('  逐面颜色 : 缺色/越界三角面 %d 个，非法顶点索引 %d 个   %s' % (
            a_out['no_colour'], a_out['bad_idx'], '全部三角面都有颜色 ✔' if (coloured and idx_ok) else '有问题 ✘'))
        lines.append('  摆放包围盒: 源 %s' % (rb(a_src['bbox']),))
        lines.append('             生成 %s   最大偏差 %.3e  %s' % (
            rb(a_out['bbox']),
            max(abs(x - y) for x, y in zip(a_src['bbox'], a_out['bbox'])) if same_box else float('nan'),
            '一致 ✔' if same_box else '不一致 ✘'))
        lines.append('  颜色统计 :')
        tot = sum(a_out['stats'].values())
        for c, n in a_out['stats'].most_common():
            lines.append('      %-9s %-4s %8d 面' % (c, CN_NAMES.get(c.upper(), ''), n))
        lines.append('      合计 %d 面' % tot)
        lines.append('  OBJ/MTL  : 顶点 %d，面 %d %s；usemtl 分组颜色 %d 种 %s' % (
            nv, nf, '（与 3mf 三角面数一致 ✔）' if obj_ok else '（不一致 ✘）',
            len(used), '' if obj_ok else ''))
        lines.append('  打包 zip : %s' % ('内容正确 ✔' if zip_ok else '内容异常 ✘'))
        lines.append('  输出文件 : %s' % ('、'.join(os.path.basename(x) for x in (out3mf, outobj, outmtl, outzip))
                                     if use else '缺失 ✘'))
        lines.append('  convert.py 日志摘要：')
        for l in (p.stdout or '').splitlines():
            if l.startswith(('源文件', '网格数量', '三角面总数', 'AMS 颜色表', '全部完成')):
                lines.append('      %s' % l)
        lines.append('  判定     : %s' % ('通过 ✔' if (same_tris and same_box and coloured and idx_ok and obj_ok and zip_ok and use)
                                      else '未通过 ✘'))
        lines.append('')
        ok_all &= (same_tris and same_box and coloured and idx_ok and obj_ok and zip_ok and use)

    lines.append('=' * 66)
    lines.append('总体结论 : %s' % ('全部样例自测通过 ✔' if ok_all else '存在未通过项 ✘'))
    lines.append('说明     : 自测在临时目录中进行，未改动任何原始 3mf 文件。')

    txt = '\n'.join(lines) + '\n'
    with open(os.path.join(HERE, '自测报告.txt'), 'w', encoding='utf-8-sig', newline='\r\n') as fh:
        fh.write(txt)
    print(txt)
    return 0 if ok_all else 1


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.exit(main())
