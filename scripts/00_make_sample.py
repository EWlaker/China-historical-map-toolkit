# -*- coding: utf-8 -*-
"""
00_make_sample.py — 生成合成示例扫描件, 用于验证环境、跑通全流程

生成若干幅带图廓与等高线纹理的合成"地图", 每幅带随机轻微倾斜与纸张噪声,
文件名遵循 <CCRR>-图名 规则, 可直接被 01 / 02 / 03 处理。

它只用于自测, 与真实数据无关。真实使用时请把自己的扫描件放进 ./input。

用法
  python scripts/00_make_sample.py            # 生成 6 幅到 ./input
  python scripts/00_make_sample.py -n 12
"""
import argparse
import os
import random
from pathlib import Path

import cv2
import numpy as np

# 覆盖 2x3 的小网格, 便于检验拼接与配准
SHEETS = [(21, 8, "甲幅"), (21, 9, "乙幅"), (21, 10, "丙幅"),
          (22, 8, "丁幅"), (22, 9, "戊幅"), (22, 10, "己幅")]


def make_one(w=2000, h=1540, seed=0):
    """画一幅合成地图: 纸张 + 图廓 + 等高线 + 河流 + 少量噪声。"""
    rnd = random.Random(seed)
    np.random.seed(seed)

    img = np.full((h, w), 240, np.uint8)
    # 纸张不均匀
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.clip(img - 12 * np.sin(xx / 190.0) - 9 * np.cos(yy / 150.0), 0, 255).astype(np.uint8)

    m = 72                                   # 图廓边距
    x0, y0, x1, y1 = m, m, w - m, h - m
    # 外图廓(粗) + 内图廓(细)
    cv2.rectangle(img, (x0, y0), (x1, y1), 30, 9)
    cv2.rectangle(img, (x0 + 16, y0 + 16), (x1 - 16, y1 - 16), 90, 2)

    ix0, iy0, ix1, iy1 = x0 + 16, y0 + 16, x1 - 16, y1 - 16
    # 等高线: 按网格布点画同心闭合曲线, 让纹理铺满整个图廓。
    # 注意必须铺满 —— 若内容只占局部, 内容边界识别会(正确地)判为不可信并
    # 走安全兜底, 那样就测不出"紧贴内容裁切"这条主路径了。
    NGX, NGY = 9, 7
    stepx, stepy = (ix1 - ix0) / NGX, (iy1 - iy0) / NGY
    for gx in range(NGX):
        for gy in range(NGY):
            cx = ix0 + (gx + 0.5) * stepx + rnd.uniform(-12, 12)
            cy = iy0 + (gy + 0.5) * stepy + rnd.uniform(-12, 12)
            base = rnd.uniform(34, 62)
            for j in range(rnd.randint(3, 5)):
                r = base + j * rnd.uniform(15, 26)
                pts = []
                for t in np.linspace(0, 2 * np.pi, 90):
                    rr = r * (1 + 0.16 * np.sin(3 * t + gx) + 0.09 * np.cos(5 * t + gy))
                    pts.append([cx + rr * np.cos(t), cy + rr * np.sin(t) * 0.80])
                cv2.polylines(img, [np.array(pts, np.int32)], True, 120, 1, cv2.LINE_AA)
    # 河流
    for _ in range(3):
        pts, px, py = [], rnd.uniform(ix0, ix1), iy0
        while py < iy1:
            pts.append([px, py])
            px += rnd.uniform(-16, 16)
            py += rnd.uniform(18, 34)
        cv2.polylines(img, [np.array(pts, np.int32)], False, 60, 3, cv2.LINE_AA)
    # 零散注记
    for _ in range(90):
        px = rnd.randint(ix0 + 10, ix1 - 40)
        py = rnd.randint(iy0 + 14, iy1 - 10)
        cv2.rectangle(img, (px, py), (px + rnd.randint(9, 26), py + 5), 70, -1)

    img = cv2.GaussianBlur(img, (0, 0), 0.6)
    # 轻微倾斜, 用来验证纠斜
    a = rnd.uniform(-1.2, 1.2)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=245)
    img = np.clip(img.astype(np.int16) + np.random.normal(0, 3.5, img.shape), 0, 255).astype(np.uint8)
    return img, a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="./input")
    ap.add_argument("-n", "--num", type=int, default=len(SHEETS))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    for i, (c, r, nm) in enumerate(SHEETS[:a.num]):
        img, ang = make_one(seed=100 + i)
        p = out / ("%02d%02d-%s.jpg" % (c, r, nm))
        cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tofile(str(p))
        print("  %-22s %dx%d  倾斜 %+.2f°" % (p.name, img.shape[1], img.shape[0], ang))

    print("\n示例已生成到: %s" % out.resolve())
    print("接着运行:")
    print("  python scripts/01_crop.py")
    print("  python scripts/02_georef.py")
    print("  python scripts/03_build_vrt.py")


if __name__ == "__main__":
    main()
