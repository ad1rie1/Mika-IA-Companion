# Generates every texture of Mika's room into frontend/Web/assets-src/textures.
# Photo textures come from Poly Haven (CC0); the rest is drawn here.
import math, random, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))  # expects ./ph/<name>_diff_1k.jpg (Poly Haven, CC0)
OUT = os.path.join(os.path.dirname(HERE), "textures")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(7)
random.seed(7)


def save(img, name, q=90):
    path = os.path.join(OUT, name)
    img.convert("RGB").save(path, quality=q)
    print("wrote", name, img.size)


def ph(name):
    return Image.open(os.path.join(HERE, "ph", f"{name}_diff_1k.jpg")).convert("RGB")


def gray_normalized(img, size, mean=0.86, contrast=1.0):
    """Luminance only, re-centred: the material colour (glTF baseColorFactor)
    tints it, so one weave serves every fabric of the room."""
    a = np.asarray(img.resize((size, size), Image.LANCZOS)).astype(np.float32) / 255
    lum = a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lum = (lum - lum.mean()) * contrast + mean
    lum = np.clip(lum, 0, 1)
    return Image.fromarray((np.stack([lum] * 3, -1) * 255).astype(np.uint8))


def pnoise(n, beta=2.0, seed=0, stretch=(1.0, 1.0)):
    """Periodic (tileable) fractal noise via a random power-law spectrum."""
    r = np.random.default_rng(seed)
    ky = np.fft.fftfreq(n) * n
    kx = np.fft.fftfreq(n) * n
    K = np.sqrt((kx[None, :] * stretch[0]) ** 2 + (ky[:, None] * stretch[1]) ** 2)
    K[0, 0] = 1
    amp = K ** (-beta / 2)
    amp[0, 0] = 0
    spec = amp * np.exp(1j * r.uniform(0, 2 * np.pi, (n, n)))
    out = np.real(np.fft.ifft2(spec))
    return (out - out.mean()) / (out.std() + 1e-9)


# ---------------------------------------------------------------- photos (CC0)
save(ph("wood_floor"), "floor_wood.jpg")           # 1.7 m tile
save(ph("oak_veneer_01"), "wood_grain.jpg")         # 1.83 m tile, tinted per piece
save(gray_normalized(ph("rough_linen"), 512, 0.88, 1.6), "fabric_linen.jpg")
save(gray_normalized(ph("knitted_fleece"), 512, 0.86, 1.4), "fabric_fleece.jpg")
save(gray_normalized(ph("velour_velvet"), 512, 0.84, 2.2), "fabric_velvet.jpg")
save(ph("wool_boucle").resize((512, 512), Image.LANCZOS), "fabric_plaid.jpg")

# ---------------------------------------------------------------- wall plaster
n = 512
w = 0.93 + 0.018 * pnoise(n, 2.4, 1) + 0.010 * pnoise(n, 1.2, 2)
w = np.clip(w, 0, 1)
save(Image.fromarray((np.stack([w] * 3, -1) * 255).astype(np.uint8)), "wall_plaster.jpg")

# ---------------------------------------------------------------- cork
n = 256
c = pnoise(n, 1.0, 3)
base = np.array([0.62, 0.43, 0.27])
cork = base[None, None, :] * (1 + 0.16 * c[..., None])
speck = (pnoise(n, 0.4, 4) > 1.8)[..., None]
cork = np.where(speck, cork * 0.55, cork)
save(Image.fromarray((np.clip(cork, 0, 1) * 255).astype(np.uint8)), "cork.jpg")

# ---------------------------------------------------------------- duvet print
# Lavender cotton with a scatter of small cream stars, woven texture on top.
n = 512
fleece = np.asarray(gray_normalized(ph("knitted_fleece"), n, 1.0, 1.0)).astype(np.float32)[..., 0] / 255
base = np.array([0.56, 0.47, 0.76])
img = np.ones((n, n, 3)) * base
pil = Image.fromarray((img * 255).astype(np.uint8))
d = ImageDraw.Draw(pil)


def star(draw, cx, cy, r, fill, points=5, inner=0.45, rot=0.0):
    pts = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * inner
        a = rot + math.pi * i / points - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


for i in range(26):
    x, y = random.uniform(0, n), random.uniform(0, n)
    r = random.uniform(7, 12)
    col = random.choice([(250, 236, 214), (255, 214, 226), (236, 230, 255)])
    for ox in (-n, 0, n):
        for oy in (-n, 0, n):
            star(d, x + ox, y + oy, r, col, rot=random.uniform(0, 1))
for i in range(60):
    x, y = random.uniform(0, n), random.uniform(0, n)
    for ox in (-n, 0, n):
        for oy in (-n, 0, n):
            d.ellipse([x + ox - 2, y + oy - 2, x + ox + 2, y + oy + 2], fill=(240, 232, 250))
a = np.asarray(pil).astype(np.float32) / 255 * (0.78 + 0.28 * fleece[..., None])
save(Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)), "duvet_print.jpg")

# ---------------------------------------------------------------- rug
n = 1024
yy, xx = np.mgrid[0:n, 0:n] / (n / 2) - 1
r = np.sqrt(xx ** 2 + yy ** 2)
ang = np.arctan2(yy, xx)
hexes = lambda h: np.array([int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)])
rings = [(1.01, "#2b1d48"), (0.97, "#3a2860"), (0.90, "#5a4390"), (0.86, "#3a2860"),
         (0.70, "#46337a"), (0.52, "#5a4390"), (0.48, "#c9a8e8"), (0.46, "#5a4390"),
         (0.28, "#6c56ad"), (0.10, "#8a73c8")]
rug = np.zeros((n, n, 3)) + hexes("#2b1d48")
for rad, col in rings:
    rug[r < rad] = hexes(col)
# scalloped pink motif ring
motif = (np.abs(r - 0.78) < 0.035 + 0.02 * np.cos(ang * 24)) & (r < 0.86)
rug[motif] = hexes("#d98ab4")
dots = (np.abs(r - 0.6) < 0.012) & (np.cos(ang * 40) > 0.6)
rug[dots] = hexes("#f0dcf5")
petals = (r < 0.24) & (np.cos(ang * 6) * 0.12 + 0.14 > r)
rug[petals] = hexes("#b79be0")
wool = pnoise(n, 0.9, 5) * 0.05 + pnoise(n, 2.2, 6) * 0.06
rug = rug * (1 + wool[..., None])
edge = np.clip((r - 0.95) / 0.06, 0, 1)[..., None]
rug = rug * (1 - 0.35 * edge)
save(Image.fromarray((np.clip(rug, 0, 1) * 255).astype(np.uint8)), "rug.jpg")


# ---------------------------------------------------------------- art helpers
def vgrad(w, h, stops):
    t = np.linspace(0, 1, h)[:, None]
    out = np.zeros((h, w, 3))
    ts = [s[0] for s in stops]
    for ch in range(3):
        vals = [hexes(s[1])[ch] for s in stops]
        out[..., ch] = np.interp(t, ts, vals)
    return out


def to_pil(a):
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def matte(img, px, col=(244, 238, 230)):
    out = Image.new("RGB", (img.width + 2 * px, img.height + 2 * px), col)
    out.paste(img, (px, px))
    return out


# ---------------------------------------------------------------- poster: moon
W, H = 460, 620
img = to_pil(vgrad(W, H, [(0, "#1d1640"), (0.55, "#5a3a86"), (0.85, "#c97aa6"), (1, "#f2b39a")]))
d = ImageDraw.Draw(img, "RGBA")
for i in range(90):
    x, y = random.uniform(0, W), random.uniform(0, H * 0.6)
    s = random.choice([1, 1, 1, 2])
    d.ellipse([x, y, x + s, y + s], fill=(255, 250, 240, random.randint(120, 255)))
mx, my, mr = W * 0.66, H * 0.26, 62
for k in range(10, 0, -1):
    d.ellipse([mx - mr - k * 9, my - mr - k * 9, mx + mr + k * 9, my + mr + k * 9], fill=(255, 230, 200, 6))
d.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=(255, 236, 205, 255))
d.ellipse([mx - mr + 30, my - mr - 12, mx + mr + 30, my + mr - 12], fill=(0, 0, 0, 0))
# crescent: repaint the bite with the sky behind it
sky = vgrad(W, H, [(0, "#1d1640"), (0.55, "#5a3a86"), (0.85, "#c97aa6"), (1, "#f2b39a")])
mask = Image.new("L", (W, H), 0)
ImageDraw.Draw(mask).ellipse([mx - mr + 30, my - mr - 12, mx + mr + 30, my + mr - 12], fill=255)
img.paste(to_pil(sky), (0, 0), mask)
d = ImageDraw.Draw(img, "RGBA")
for layer, (col, base_y, amp) in enumerate([("#3a2a66", 0.70, 40), ("#271c4c", 0.78, 34), ("#170f33", 0.86, 26)]):
    pts = [(0, H)]
    for x in range(0, W + 10, 10):
        y = H * base_y - amp * math.sin(x / W * math.pi * (1.3 + layer * 0.7) + layer) - 10 * math.sin(x / 37.0 + layer)
        pts.append((x, y))
    pts.append((W, H))
    d.polygon(pts, fill=col)
# tiny house with a warm window on the last hill
hx, hy = W * 0.28, H * 0.83
d.rectangle([hx, hy, hx + 34, hy + 26], fill="#120b28")
d.polygon([(hx - 5, hy), (hx + 17, hy - 18), (hx + 39, hy)], fill="#120b28")
d.rectangle([hx + 12, hy + 8, hx + 22, hy + 17], fill="#ffc97a")
for i in range(9):
    tx = random.uniform(0.5, 0.95) * W
    ty = H * 0.86 - random.uniform(0, 16)
    d.polygon([(tx, ty - 34), (tx - 10, ty), (tx + 10, ty)], fill="#0f0a22")
save(matte(img, 26), "poster_moon.jpg")

# ---------------------------------------------------------------- poster: peaks
W, H = 470, 470
img = to_pil(vgrad(W, H, [(0, "#13294a"), (0.5, "#2b6f86"), (1, "#7fd8cf")]))
d = ImageDraw.Draw(img, "RGBA")
sx, sy, sr = W * 0.3, H * 0.34, 46
for k in range(8, 0, -1):
    d.ellipse([sx - sr - k * 8, sy - sr - k * 8, sx + sr + k * 8, sy + sr + k * 8], fill=(255, 220, 170, 8))
d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill="#ffe2b0")
ranges = [("#4b7f9a", 0.50, 0.30), ("#2d5c78", 0.62, 0.26), ("#1a3a55", 0.74, 0.22), ("#0e2238", 0.86, 0.18)]
for i, (col, by, amp) in enumerate(ranges):
    pts = [(0, H)]
    xs = np.linspace(0, W, 9)
    for j, x in enumerate(xs):
        peak = (j % 2 == 1)
        y = H * by - (H * amp * random.uniform(0.6, 1.0) if peak else H * amp * random.uniform(0.0, 0.25))
        pts.append((x, y))
    pts.append((W, H))
    d.polygon(pts, fill=col)
    if i == 0:
        for j in range(1, len(pts) - 1):
            pass
save(matte(img, 22), "poster_peaks.jpg")

# ---------------------------------------------------------------- small prints
def print_cat():
    W, H = 300, 380
    img = to_pil(vgrad(W, H, [(0, "#f6d6e2"), (1, "#e9b9d3")]))
    d = ImageDraw.Draw(img)
    d.ellipse([90, 190, 210, 340], fill="#3a2b52")        # body
    d.ellipse([105, 120, 195, 210], fill="#3a2b52")       # head
    d.polygon([(110, 140), (118, 92), (140, 128)], fill="#3a2b52")
    d.polygon([(190, 140), (182, 92), (160, 128)], fill="#3a2b52")
    d.arc([180, 260, 270, 350], 180, 330, fill="#3a2b52", width=14)
    d.ellipse([60, 40, 110, 90], fill="#fff6e8")
    return matte(img, 18, (250, 246, 240))


def print_flower():
    W, H = 300, 380
    img = to_pil(vgrad(W, H, [(0, "#e8e2f6"), (1, "#c9c0ea")]))
    d = ImageDraw.Draw(img)
    d.line([(150, 360), (150, 170)], fill="#4f7a5a", width=8)
    d.ellipse([150, 250, 220, 280], fill="#5f8f68")
    d.ellipse([80, 210, 150, 240], fill="#5f8f68")
    for k in range(8):
        a = k / 8 * math.tau
        cx, cy = 150 + 42 * math.cos(a), 150 + 42 * math.sin(a)
        d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill="#e58fb4")
    d.ellipse([125, 125, 175, 175], fill="#ffd27a")
    return matte(img, 18, (250, 246, 240))


save(print_cat(), "print_cat.jpg")
save(print_flower(), "print_flower.jpg")

# ---------------------------------------------------------------- photos (polaroids)
def photo(kind, seed):
    random.seed(seed)
    W, H = 200, 200
    if kind == "sunset":
        a = vgrad(W, H, [(0, "#4a3c8c"), (0.55, "#f08a6a"), (0.62, "#ffd08a"), (0.63, "#2b3e6a"), (1, "#1b2a4a")])
        img = to_pil(a)
        d = ImageDraw.Draw(img)
        d.ellipse([80, 90, 120, 130], fill="#ffe0a0")
        img.paste(to_pil(vgrad(W, 75, [(0, "#2b3e6a"), (1, "#1b2a4a")])), (0, 125))
    elif kind == "friends":
        img = to_pil(vgrad(W, H, [(0, "#bfe3f2"), (1, "#f5e6c8")]))
        d = ImageDraw.Draw(img)
        for i, col in enumerate(["#5a4a7a", "#d97aa0", "#4a6f8a"]):
            x = 30 + i * 55
            d.ellipse([x, 70, x + 40, 110], fill="#f2c9a8")
            d.ellipse([x - 4, 62, x + 44, 92], fill=col)
            d.rounded_rectangle([x - 8, 110, x + 48, 200], 18, fill=col)
    elif kind == "cat":
        img = to_pil(vgrad(W, H, [(0, "#f2e2c8"), (1, "#d8b890")]))
        d = ImageDraw.Draw(img)
        d.ellipse([50, 90, 160, 180], fill="#e8a060")
        d.ellipse([60, 50, 130, 115], fill="#e8a060")
        d.polygon([(66, 66), (70, 32), (92, 58)], fill="#e8a060")
        d.polygon([(124, 66), (120, 32), (100, 58)], fill="#e8a060")
        d.ellipse([78, 76, 86, 84], fill="#2a2030")
        d.ellipse([104, 76, 112, 84], fill="#2a2030")
    else:  # city at night
        img = to_pil(vgrad(W, H, [(0, "#121638"), (1, "#3a2a62")]))
        d = ImageDraw.Draw(img)
        x = 0
        while x < W:
            bw = random.randint(18, 34)
            bh = random.randint(50, 130)
            d.rectangle([x, H - bh, x + bw, H], fill="#0b0d22")
            for wy in range(H - bh + 6, H - 6, 10):
                for wx in range(x + 4, x + bw - 4, 7):
                    if random.random() < 0.35:
                        d.rectangle([wx, wy, wx + 3, wy + 4], fill="#ffd38a")
            x += bw + 2
    # polaroid border
    out = Image.new("RGB", (W + 24, H + 60), (248, 246, 240))
    out.paste(img, (12, 12))
    return out


atlas = Image.new("RGB", (1024, 256), (248, 246, 240))
for i, k in enumerate(["sunset", "friends", "cat", "city"]):
    atlas.paste(photo(k, i).resize((224, 256)), (i * 256 + 16, 0))
save(atlas, "photos.jpg")

# ---------------------------------------------------------------- monitor screen
W, H = 640, 360
scr = to_pil(vgrad(W, H, [(0, "#1a1840"), (0.7, "#3b2a6a"), (1, "#6a3f7a")]))
d = ImageDraw.Draw(scr, "RGBA")
for i in range(60):
    x, y = random.uniform(0, W), random.uniform(0, H * 0.6)
    d.ellipse([x, y, x + 1.5, y + 1.5], fill=(255, 255, 255, 140))
d.ellipse([480, 50, 540, 110], fill=(255, 236, 210, 230))
# code editor window
d.rounded_rectangle([30, 40, 360, 300], 8, fill=(18, 18, 34, 235))
d.rectangle([30, 40, 360, 58], fill=(40, 38, 70, 255))
for k, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
    d.ellipse([40 + k * 14, 45, 48 + k * 14, 53], fill=c + (255,))
y = 70
cols = [(199, 146, 234), (130, 170, 255), (195, 232, 141), (255, 203, 107), (137, 221, 255), (160, 160, 190)]
for line in range(20):
    x = 44 + random.choice([0, 0, 14, 14, 28])
    while x < 330 and random.random() < 0.8:
        wlen = random.randint(14, 60)
        d.rounded_rectangle([x, y, min(x + wlen, 340), y + 6], 2, fill=random.choice(cols) + (220,))
        x += wlen + 8
    y += 11
# chat window
d.rounded_rectangle([380, 130, 610, 330], 8, fill=(24, 20, 44, 235))
d.rectangle([380, 130, 610, 148], fill=(120, 80, 170, 255))
y = 158
for m in range(8):
    col = random.choice([(255, 140, 190), (140, 200, 255), (180, 255, 190), (255, 220, 140)])
    d.rounded_rectangle([390, y, 390 + random.randint(20, 40), y + 6], 2, fill=col + (255,))
    d.rounded_rectangle([436, y, 436 + random.randint(60, 160), y + 6], 2, fill=(210, 210, 230, 200))
    y += 20
d.rectangle([0, H - 20, W, H], fill=(14, 12, 28, 230))
for k in range(6):
    d.rounded_rectangle([12 + k * 26, H - 16, 30 + k * 26, H - 4], 3, fill=(120 + k * 15, 110, 200, 255))
save(scr, "monitor_screen.jpg")

# ---------------------------------------------------------------- notebook cover / sticky labels
nb = to_pil(vgrad(256, 256, [(0, "#e7a3c0"), (1, "#d68bb0")]))
d = ImageDraw.Draw(nb)
d.rectangle([24, 90, 232, 140], fill="#fff4f8")
star(d, 128, 200, 22, "#fff4f8")
save(nb, "notebook.jpg")
print("ok")

# ---------------------------------------------------------------- poster: city pop sunset (landscape)
W, H = 640, 440
img = to_pil(vgrad(W, H, [(0, "#2a1b4e"), (0.45, "#a3488f"), (0.7, "#f2876f"), (1, "#ffd29a")]))
d = ImageDraw.Draw(img, "RGBA")
sx, sy, sr = W * 0.5, H * 0.62, 120
for k in range(10, 0, -1):
    d.ellipse([sx - sr - k * 7, sy - sr - k * 7, sx + sr + k * 7, sy + sr + k * 7], fill=(255, 210, 160, 7))
d.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill="#ffd27a")
# retro stripes cut through the lower half of the sun
for i, yy in enumerate(range(int(sy + 10), int(sy + sr), 16)):
    d.rectangle([sx - sr, yy, sx + sr, yy + 3 + i], fill=(242, 135, 111, 255))
random.seed(12)
x = 0
while x < W:
    bw = random.randint(26, 60)
    bh = random.randint(60, 190)
    col = random.choice(["#1c1236", "#241747", "#2e1d55"])
    d.rectangle([x, H - bh, x + bw, H], fill=col)
    for wy in range(H - bh + 8, H - 8, 13):
        for wx in range(x + 5, x + bw - 6, 9):
            if random.random() < 0.3:
                d.rectangle([wx, wy, wx + 4, wy + 6], fill=(255, 205, 140, 230))
    x += bw + random.randint(0, 6)
d.rectangle([0, H - 28, W, H], fill="#140c28")
for k in range(0, W, 40):
    d.line([(k, H - 14), (k + 18, H - 14)], fill=(255, 150, 200, 200), width=2)
save(matte(img, 24), "poster_city.jpg")
print("ok city")
