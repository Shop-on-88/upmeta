"""UP META 업무 현황판 카드 이미지 (Pillow). UP META 카드 스타일과 같은 색·글꼴.

단독 실행: 표준입력으로 JSON을 받아 표준출력으로 JPEG를 내보냄.
"""
import io
import json
import os
import sys

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

# 상태별 (진한 색, 연한 배경, 글자색)
TONE = {
    "new": ("#D92D20", "#FDE7E2", "#B42318"),
    "ack": ("#6D28D9", "#EDE9FE", "#5B21B6"),
    "doing": ("#2F6BFF", "#E3EDFF", "#1A56DB"),
    "hold": ("#E8590C", "#FEF0E1", "#B54708"),
    "stop": ("#64748B", "#F1F5F9", "#475569"),
    "done": ("#15803D", "#DCFCE7", "#166534"),
}
LABEL = {"new": "미확인", "ack": "확인", "doing": "진행 중", "hold": "보류", "stop": "중지", "done": "오늘 완료"}

_FONTS = {
    "bold": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1), ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", 1),
             ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0), ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0)],
    "black": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 1), ("/usr/share/fonts/noto-cjk/NotoSansCJK-Black.ttc", 1),
              ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1), ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0)],
    "regular": [("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc", 1), ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 1),
                ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc", 1), ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", 0)],
}
_cache = {}
LOGO_PNG = "/root/upmeta/demo-bot/assets/icons/logo.png"  # UP META 로고 (없으면 직접 그림)


def F(size, weight="bold"):
    key = (size, weight)
    if key not in _cache:
        for path, idx in _FONTS[weight]:
            if os.path.exists(path):
                _cache[key] = ImageFont.truetype(path, size, index=idx)
                break
        else:
            _cache[key] = ImageFont.load_default(size)
    return _cache[key]


def fit(d, text, font, width):
    """폭에 맞게 자르고 … 붙이기"""
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def pill(d, x, y, text, bg, fg, size=24, padx=16, h=44, right=False):
    f = F(size, "bold")
    w = d.textlength(text, font=f) + padx * 2
    if right:
        x -= w
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    d.text((x + padx, y + h / 2), text, font=f, fill=fg, anchor="lm")
    return w


def logo(img, d, x, y, s=64):
    if os.path.exists(LOGO_PNG):
        try:
            im = Image.open(LOGO_PNG).convert("RGBA").resize((80, 80), Image.LANCZOS)
            img.paste(im, (x - 6, y - 10), im)
            return
        except Exception:
            pass
    d.rounded_rectangle([x, y, x + s, y + s], radius=int(s * 0.26), fill="#FFFFFF")
    k = s / 220
    d.line([(x + a * k, y + b * k) for a, b in [(46, 150), (104, 92), (130, 116), (170, 66)]],
           fill=NAVY, width=max(4, int(20 * k)), joint="curve")
    d.line([(x + 140 * k, y + 64 * k), (x + 174 * k, y + 62 * k), (x + 172 * k, y + 96 * k)],
           fill=NAVY, width=max(4, int(20 * k)), joint="curve")


def render(data):
    img = Image.new("RGB", (W, 4200), BG)
    d = ImageDraw.Draw(img)

    # 머리띠
    d.rectangle([0, 0, W, 210], fill=NAVY2)
    logo(img, d, PAD, 52)
    d.text((PAD + 86, 84), "UP META", font=F(34, "black"), fill="#FFFFFF", anchor="lm")
    pill(d, W - PAD, 60, "실시간", BLUE, "#FFFFFF", size=24, h=46, padx=18, right=True)
    d.text((PAD, 150), "업무 현황판", font=F(44, "black"), fill="#FFFFFF", anchor="lm")
    d.text((W - PAD, 152), data["now"] + " 기준", font=F(26, "regular"), fill="#C9D4F2", anchor="rm")
    y = 250

    # 숫자 타일 3 x 2
    gap = 20
    cw = (W - PAD * 2 - gap * 2) / 3
    ch = 168
    for i, k in enumerate(["new", "ack", "doing", "hold", "stop", "done"]):
        cx = PAD + (i % 3) * (cw + gap)
        cy = y + (i // 3) * (ch + gap)
        col = TONE[k][0]
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=28, fill=col)
        d.rounded_rectangle([cx, cy, cx + cw, cy + ch - 9], radius=28, fill=CARD)
        d.text((cx + 30, cy + 52), LABEL[k], font=F(28, "bold"), fill=INK, anchor="lm")
        d.ellipse([cx + cw - 44, cy + 40, cx + cw - 22, cy + 62], fill=col)
        d.text((cx + 30, cy + 112), str(data["counts"].get(k, 0)), font=F(64, "black"), fill=col, anchor="lm")
        d.text((cx + 34 + d.textlength(str(data["counts"].get(k, 0)), font=F(64, "black")), cy + 122), "건",
               font=F(26, "bold"), fill=MUTED, anchor="lm")
    y += ch * 2 + gap + 44

    # 상태별 목록
    any_rows = False
    for sec in data["sections"]:
        items = sec["items"]
        if not items:
            continue
        any_rows = True
        col, soft, ink = TONE[sec["key"]]
        d.rounded_rectangle([PAD, y + 6, PAD + 10, y + 46], radius=5, fill=col)
        d.text((PAD + 28, y + 26), LABEL[sec["key"]], font=F(34, "black"), fill=INK, anchor="lm")
        d.text((PAD + 40 + d.textlength(LABEL[sec["key"]], font=F(34, "black")), y + 28), "%d건" % sec["total"],
               font=F(28, "bold"), fill=col, anchor="lm")
        y += 68
        for it in items:
            rh = 178 if it.get("note") else 132
            d.rounded_rectangle([PAD, y, W - PAD, y + rh], radius=24, fill=CARD)
            x = PAD + 28
            x += pill(d, x, y + 22, it["cat"], "#EEF2FF", NAVY, size=22, h=40, padx=14) + 10
            right = W - PAD - 28
            if it.get("late"):
                right -= pill(d, right, y + 22, "기한 지남", "#FDE7E2", "#B42318", size=22, h=40, padx=14, right=True) + 10
            if it.get("hot"):
                right -= pill(d, right, y + 22, "긴급", "#D92D20", "#FFFFFF", size=22, h=40, padx=14, right=True) + 10
            meta = it["who"] + (("  ·  ~" + it["due"]) if it.get("due") else "")
            d.text((right, y + 42), fit(d, meta, F(25, "regular"), right - x - 10), font=F(25, "regular"), fill=MUTED, anchor="rm")
            d.text((PAD + 28, y + 96), fit(d, it["title"], F(34, "bold"), W - PAD * 2 - 56), font=F(34, "bold"), fill=INK, anchor="lm")
            if it.get("note"):
                d.rounded_rectangle([PAD + 28, y + 126, W - PAD - 28, y + 164], radius=10, fill=soft)
                d.text((PAD + 44, y + 145), fit(d, sec.get("note_label", "사유") + "  " + it["note"], F(23, "bold"), W - PAD * 2 - 90),
                       font=F(23, "bold"), fill=ink, anchor="lm")
            y += rh + 14
        if sec["total"] > len(items):
            d.text((W - PAD - 8, y + 12), "외 %d건은 업무 보드에서 확인" % (sec["total"] - len(items)),
                   font=F(24, "regular"), fill=MUTED, anchor="rm")
            y += 40
        y += 26
    if not any_rows:
        d.rounded_rectangle([PAD, y, W - PAD, y + 150], radius=24, fill=CARD)
        d.text((W / 2, y + 75), "진행 중인 업무가 없습니다", font=F(32, "bold"), fill=MUTED, anchor="mm")
        y += 176

    # 바닥
    d.rounded_rectangle([PAD, y, W - PAD, y + 88], radius=22, fill=NAVY)
    d.text((PAD + 32, y + 44), "업무 등록 · 상태 변경", font=F(26, "bold"), fill="#C9D4F2", anchor="lm")
    d.text((W - PAD - 32, y + 44), data.get("url", "").replace("https://", ""), font=F(28, "black"), fill="#FFFFFF", anchor="rm")
    y += 88 + 44

    buf = io.BytesIO()
    img.crop((0, 0, W, y)).save(buf, "JPEG", quality=92, subsampling=0, optimize=True)
    return buf.getvalue()


if __name__ == "__main__":
    sys.stdout.buffer.write(render(json.loads(sys.stdin.buffer.read().decode("utf-8"))))
