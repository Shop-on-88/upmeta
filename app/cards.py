"""UP META 데모봇 카드 이미지 그리기 (Pillow)."""
import io
import os
from PIL import Image, ImageDraw, ImageFont

W = 1080
PAD = 56

BG = "#EEF2FA"
CARD = "#FFFFFF"
NAVY = "#0A2A6E"
NAVY2 = "#071535"
INK = "#0B1530"
MUTED = "#5A6684"
LINE = "#E3E8F4"
BLUE = "#2F6BFF"
SOFT = "#F4F6FB"

TILE = {
    "all": ("#0A2A6E", "#FFFFFF"),
    "dup": ("#D92D20", "#FFFFFF"),
    "y2k": ("#E8590C", "#FFFFFF"),
    "black": ("#111827", "#FFFFFF"),
    "talk": ("#2F6BFF", "#FFFFFF"),
    "lead": ("#0369A1", "#FFFFFF"),
    "win": ("#15803D", "#FFFFFF"),
    "none": ("#64748B", "#FFFFFF"),
}
PILL = {
    "중복": ("#FDE7E2", "#B42318"),
    "00년생↑": ("#FEF0E1", "#B54708"),
    "블랙": ("#E5E7EB", "#111827"),
    "선톡": ("#E3EDFF", "#1A56DB"),
    "리딩": ("#E0F2FE", "#075985"),
    "뽑장": ("#DCFCE7", "#166534"),
    "신규": ("#F1F5F9", "#334155"),
    "담당 없음": ("#F1F5F9", "#475569"),
    "staff": ("#EEF2FF", "#0A2A6E"),
}

_FONT_CANDIDATES = {
    "bold": [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
        ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 1),
        ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0),
        ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
    ],
    "black": [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 1),
        ("/usr/share/fonts/noto-cjk/NotoSansCJK-Black.ttc", 1),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
        ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0),
    ],
    "regular": [
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc", 1),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 1),
        ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 1),
        ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 0),
    ],
}
_cache = {}
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
_icons = {}
ICON = {"all": "00", "dup": "01", "y2k": "02", "black": "03", "talk": "04", "lead": "05",
        "win": "06", "none": "07", "staff": "07", "today": "08", "week": "09", "month": "10",
        "alltime": "11", "auto": "12", "team": "14", "test": "15", "bell": "18", "logo": "logo",
        "선톡": "04", "리딩": "05", "뽑장": "06", "블랙": "03", "중복": "01", "신규": "00"}


def icon(img, key, x, y, size):
    """3D 아이콘 붙이기 (없으면 건너뜀). x,y = 왼쪽 위."""
    code = ICON.get(key, key)
    k = (code, size)
    if k not in _icons:
        p = os.path.join(ASSETS, code + ".png")
        if not os.path.exists(p):
            _icons[k] = None
        else:
            _icons[k] = Image.open(p).convert("RGBA").resize((size, size), Image.LANCZOS)
    im = _icons[k]
    if im is not None:
        img.paste(im, (int(x), int(y)), im)
    return im is not None


def F(size, weight="bold"):
    key = (size, weight)
    if key in _cache:
        return _cache[key]
    for path, idx in _FONT_CANDIDATES[weight]:
        if os.path.exists(path):
            f = ImageFont.truetype(path, size, index=idx)
            _cache[key] = f
            return f
    f = ImageFont.load_default(size)
    _cache[key] = f
    return f


def tw(d, text, font):
    return d.textlength(text, font=font)


def pill(d, x, y, text, colors, size=26, padx=18, h=48, right=False):
    f = F(size, "bold")
    w = tw(d, text, f) + padx * 2
    if right:
        x = x - w
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=colors[0])
    d.text((x + padx, y + h / 2), text, font=f, fill=colors[1], anchor="lm")
    return w


def logo(d, x, y, s=64, bg="#FFFFFF", fg=NAVY):
    d.rounded_rectangle([x, y, x + s, y + s], radius=int(s * 0.26), fill=bg)
    k = s / 220
    pts = [(46, 150), (104, 92), (130, 116), (170, 66)]
    d.line([(x + a * k, y + b * k) for a, b in pts], fill=fg, width=max(4, int(20 * k)), joint="curve")
    d.line([(x + 140 * k, y + 64 * k), (x + 174 * k, y + 62 * k), (x + 172 * k, y + 96 * k)],
           fill=fg, width=max(4, int(20 * k)), joint="curve")


def header(img, d, title, sub, badge=None):
    """Navy header band. Returns y below it."""
    h = 210
    d.rectangle([0, 0, W, h], fill=NAVY2)
    if not icon(img, "logo", PAD - 6, 42, 80):
        logo(d, PAD, 52, 64)
    d.text((PAD + 86, 84), "UP META", font=F(34, "black"), fill="#FFFFFF", anchor="lm")
    if badge:
        pill(d, W - PAD, 60, badge, ("#2F6BFF", "#FFFFFF"), size=24, h=46, right=True)
    d.text((PAD, 150), title, font=F(44, "black"), fill="#FFFFFF", anchor="lm")
    if sub:
        d.text((W - PAD, 152), sub, font=F(26, "regular"), fill="#C9D4F2", anchor="rm")
    return h


def footer(d, y):
    d.text((W / 2, y + 30), "※ 모든 이름·번호는 가짜 예시 데이터입니다  ·  UP META 체험판",
           font=F(22, "regular"), fill=MUTED, anchor="mm")
    return y + 64


def finish(img, height):
    img = img.crop((0, 0, W, height))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
    buf.seek(0)
    buf.name = "card.jpg"
    return buf


def canvas(h=2000):
    img = Image.new("RGB", (W, h), BG)
    return img, ImageDraw.Draw(img)


# ---------------- cards ----------------

def home_card(counts, period, auto, staff_counts):
    img, d = canvas()
    y = header(img, d, "DB 관리봇", f"{period} · 자동 배분 {'ON' if auto else 'OFF'}", "체험판")
    y += 40
    order = [("all", "전체"), ("dup", "중복"), ("y2k", "00년생↑"), ("black", "블랙"),
             ("talk", "선톡"), ("lead", "리딩"), ("win", "뽑장"), ("none", "담당 없음")]
    gap = 20
    cw = (W - PAD * 2 - gap * 3) / 4
    ch = 182
    for i, (k, label) in enumerate(order):
        cx = PAD + (i % 4) * (cw + gap)
        cy = y + (i // 4) * (ch + gap)
        bg, fg = TILE[k]
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=28, fill=bg)
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch - 9], radius=28, fill=CARD)
        icon(img, k, cx + 18, cy + 18, 78)
        d.text((cx + cw - 22, cy + 62), str(counts[k]), font=F(64, "black"), fill=bg if k != "none" else INK, anchor="rm")
        d.text((cx + cw / 2, cy + 140), label, font=F(28, "bold"), fill=INK, anchor="mm")
    y += ch * 2 + gap + 40

    # staff
    sw = (W - PAD * 2 - gap) / 2
    for i, (name, n) in enumerate(staff_counts):
        sx = PAD + i * (sw + gap)
        d.rounded_rectangle([sx, y, sx + sw, y + 120], radius=24, fill=CARD)
        if not icon(img, "staff", sx + 18, y + 20, 80):
            d.ellipse([sx + 28, y + 32, sx + 84, y + 88], fill="#E3EDFF")
        d.text((sx + 104, y + 60), name, font=F(32, "bold"), fill=INK, anchor="lm")
        d.text((sx + sw - 32, y + 60), f"{n}건", font=F(36, "black"), fill=NAVY, anchor="rm")
    y += 120 + 28

    # hint
    d.rounded_rectangle([PAD, y, W - PAD, y + 92], radius=22, fill=CARD)
    d.text((PAD + 32, y + 46), "아래 버튼을 누르면 명단 카드가 나와요", font=F(28, "bold"), fill=INK, anchor="lm")
    d.text((W - PAD - 32, y + 46), "▼", font=F(28, "bold"), fill=BLUE, anchor="rm")
    y += 92 + 12
    y = footer(d, y)
    return finish(img, y)


def list_card(title, period, total, rows, page, pages):
    img, d = canvas(2400)
    sub = f"{period} · {total}건" + (f" · {page + 1}/{pages}" if pages > 1 else "")
    y = header(img, d, title, sub, "명단")
    y += 36
    if not rows:
        d.rounded_rectangle([PAD, y, W - PAD, y + 260], radius=28, fill=CARD)
        d.text((W / 2, y + 110), "해당하는 명단이 없어요", font=F(36, "bold"), fill=INK, anchor="mm")
        d.text((W / 2, y + 170), "테스트 DB를 넣거나 다른 버튼을 눌러 보세요", font=F(26, "regular"), fill=MUTED, anchor="mm")
        y += 260 + 20
        return finish(img, footer(d, y))
    rh = 150
    box_h = rh * len(rows)
    d.rounded_rectangle([PAD, y, W - PAD, y + box_h], radius=28, fill=CARD)
    for i, x in enumerate(rows):
        ry = y + i * rh
        if i:
            d.line([PAD + 30, ry, W - PAD - 30, ry], fill=LINE, width=2)
        key = "중복" if x["dup"] else (x["status"] or "신규")
        if not icon(img, key, PAD + 22, ry + 31, 88):
            d.ellipse([PAD + 30, ry + 41, PAD + 98, ry + 109], fill=SOFT)
        d.text((PAD + 124 + tw(d, x["name"], F(34, "black")) + 14, ry + 54), f"#{x['id']}", font=F(24, "bold"), fill=MUTED, anchor="lm")
        d.text((PAD + 124, ry + 54), x["name"], font=F(34, "black"), fill=INK, anchor="lm")
        d.text((PAD + 124, ry + 102), f"{x['phone']}  ·  {x['year']}년생", font=F(26, "regular"), fill=MUTED, anchor="lm")
        # pills right
        px = W - PAD - 30
        tags = [(x["staff"] or "담당 없음", PILL["staff"] if x["staff"] else PILL["담당 없음"])]
        st = x["status"] or "신규"
        tags.append((st, PILL[st]))
        if x["dup"]:
            tags.append(("중복", PILL["중복"]))
        top = ry + 51
        for text, col in tags:
            w = pill(d, px, top, text, col, size=24, padx=16, h=48, right=True)
            px -= w + 10
    y += box_h + 20
    return finish(img, footer(d, y))


def lead_card(x):
    img, d = canvas()
    st = x["status"] or "신규"
    y = header(img, d, f"DB #{x['id']}", x["hotel"], st)
    y += 36
    d.rounded_rectangle([PAD, y, W - PAD, y + 200], radius=28, fill=CARD)
    icon(img, "중복" if x["dup"] else st, PAD + 28, y + 20, 160)
    d.text((PAD + 220, y + 74), x["name"], font=F(54, "black"), fill=INK, anchor="lm")
    d.text((PAD + 220, y + 136), f"상태 · {st}", font=F(30, "bold"), fill=MUTED, anchor="lm")
    y += 200 + 20
    rows = [
        ("생년월일", x["birth"]),
        ("연락처", x["phone"]),
        ("신청 시간", x["created"].strftime("%m/%d %H:%M")),
        ("담당", x["staff"] or "담당 없음"),
    ]
    rh = 104
    d.rounded_rectangle([PAD, y, W - PAD, y + rh * len(rows)], radius=28, fill=CARD)
    for i, (k, v) in enumerate(rows):
        ry = y + i * rh
        if i:
            d.line([PAD + 32, ry, W - PAD - 32, ry], fill=LINE, width=2)
        d.text((PAD + 36, ry + rh / 2), k, font=F(28, "regular"), fill=MUTED, anchor="lm")
        d.text((W - PAD - 36, ry + rh / 2), v, font=F(34, "bold"), fill=INK, anchor="rm")
    y += rh * len(rows) + 24
    # tags row
    d.rounded_rectangle([PAD, y, W - PAD, y + 112], radius=28, fill=CARD)
    d.text((PAD + 36, y + 56), "상태", font=F(28, "regular"), fill=MUTED, anchor="lm")
    px = W - PAD - 36
    tags = [(st, PILL[st])]
    if x["year"] >= 2000:
        tags.append(("00년생↑", PILL["00년생↑"]))
    if x["dup"]:
        tags.append(("중복", PILL["중복"]))
    for text, col in tags:
        w = pill(d, px, y + 30, text, col, size=26, h=52, right=True)
        px -= w + 12
    y += 112 + 24
    d.text((W / 2, y + 20), "아래 버튼으로 상태와 담당을 바꿔 보세요", font=F(26, "bold"), fill=BLUE, anchor="mm")
    y += 50
    return finish(img, footer(d, y))


def staff_card(stats):
    img, d = canvas()
    y = header(img, d, "직원 관리", "자동 배분 순서대로", "직원")
    y += 36
    for name, total, talk, lead, win in stats:
        d.rounded_rectangle([PAD, y, W - PAD, y + 250], radius=28, fill=CARD)
        if not icon(img, "staff", PAD + 22, y + 18, 104):
            d.ellipse([PAD + 32, y + 34, PAD + 112, y + 114], fill="#E3EDFF")
        d.text((PAD + 136, y + 74), name, font=F(38, "black"), fill=INK, anchor="lm")
        d.text((W - PAD - 36, y + 74), f"배분 {total}건", font=F(32, "bold"), fill=NAVY, anchor="rm")
        bw = (W - PAD * 2 - 64 - 32) / 3
        for j, (lab, n, key) in enumerate([("선톡", talk, "talk"), ("리딩", lead, "lead"), ("뽑장", win, "win")]):
            bx = PAD + 32 + j * (bw + 16)
            col = PILL[lab]
            d.rounded_rectangle([bx, y + 140, bx + bw, y + 222], radius=18, fill=col[0])
            d.text((bx + 28, y + 181), lab, font=F(26, "bold"), fill=col[1], anchor="lm")
            d.text((bx + bw - 28, y + 181), str(n), font=F(36, "black"), fill=col[1], anchor="rm")
        y += 250 + 20
    d.rounded_rectangle([PAD, y, W - PAD, y + 120], radius=24, fill=NAVY)
    d.text((PAD + 36, y + 42), "실제 봇에서는 직원 수·이름을 원하는 대로 등록", font=F(27, "bold"), fill="#FFFFFF", anchor="lm")
    d.text((PAD + 36, y + 84), "새 DB가 들어오면 순서대로 자동 배분돼요", font=F(25, "regular"), fill="#C9D4F2", anchor="lm")
    y += 120 + 12
    return finish(img, footer(d, y))


def new_lead_card(x):
    img, d = canvas()
    h = 230
    d.rectangle([0, 0, W, h], fill=BLUE)
    if not icon(img, "logo", PAD - 6, 42, 80):
        logo(d, PAD, 52, 64, bg="#FFFFFF", fg=BLUE)
    d.text((PAD + 86, 84), "UP META", font=F(34, "black"), fill="#FFFFFF", anchor="lm")
    d.text((PAD, 162), "새 DB 도착", font=F(52, "black"), fill="#FFFFFF", anchor="lm")
    d.text((PAD + 300, 166), x["created"].strftime("%H:%M"), font=F(32, "bold"), fill="#E3EDFF", anchor="lm")
    icon(img, "bell", W - PAD - 170, 30, 176)
    y = h + 36
    d.rounded_rectangle([PAD, y, W - PAD, y + 300], radius=28, fill=CARD)
    d.text((PAD + 36, y + 60), f"#{x['id']}  {x['hotel']}", font=F(28, "bold"), fill=MUTED, anchor="lm")
    d.text((PAD + 36, y + 130), x["name"], font=F(56, "black"), fill=INK, anchor="lm")
    d.text((PAD + 36, y + 200), f"{x['birth']}  ·  {x['phone']}", font=F(30, "regular"), fill=INK, anchor="lm")
    px = PAD + 36
    tags = []
    tags.append(("중복 번호", PILL["중복"]) if x["dup"] else ("신규", PILL["신규"]))
    if x["year"] >= 2000:
        tags.append(("00년생↑", PILL["00년생↑"]))
    for text, col in tags:
        px += pill(d, px, y + 236, text, col, size=24, h=46) + 10
    y += 300 + 20
    d.rounded_rectangle([PAD, y, W - PAD, y + 110], radius=24, fill=NAVY)
    d.text((PAD + 36, y + 55), "배분", font=F(28, "regular"), fill="#C9D4F2", anchor="lm")
    d.text((W - PAD - 36, y + 55), x["staff"] or "담당 없음", font=F(36, "black"), fill="#FFFFFF", anchor="rm")
    y += 110 + 12
    return finish(img, footer(d, y))
