"""UP META 데모 DB관리봇 (@metaupdemo_bot)

체험 전용 봇. 모든 데이터는 가짜 예시이며, 사용자(채팅)마다 따로 메모리에 보관됩니다.
실제 고객 DB나 다른 사업(B2, 베스트여행사 등)의 파일과 연결되지 않습니다.
"""
import os
import random
import logging
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("upmeta-demo")
logging.getLogger("httpx").setLevel(logging.WARNING)  # 로그에 토큰이 찍히지 않게

KST = timezone(timedelta(hours=9))
CONTACT_URL = "https://t.me/upmeta9"
CHANNEL_URL = "https://t.me/UPMETA99"
STAFF = ["담당 A", "담당 B"]
STATUSES = ["선톡", "리딩", "뽑장", "블랙"]

LAST = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신"]
HOTELS = ["서울 시그니처", "부산 오션뷰", "제주 리조트"]

FILTERS = {
    "all": "전체", "dup": "중복", "y2k": "00년생↑", "black": "블랙",
    "talk": "선톡", "lead": "리딩", "win": "뽑장", "none": "담당 없음",
    "s0": STAFF[0], "s1": STAFF[1],
}
PERIODS = {"today": "오늘", "week": "최근 7일", "month": "이번 달", "all": "전체 기간"}


# ---------- 가짜 데이터 ----------

def now():
    return datetime.now(KST)


def fake_lead(lid, when, staff_rr):
    year = random.choice([1985, 1988, 1990, 1992, 1994, 1996, 1998, 2000, 2001, 2003])
    return {
        "id": lid,
        "name": random.choice(LAST) + "○○",
        "phone": f"010-****-{random.randint(1000, 9999)}",
        "birth": f"{year}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
        "year": year,
        "hotel": random.choice(HOTELS),
        "created": when,
        "dup": random.random() < 0.12,
        "status": None,
        "staff": staff_rr,
    }


def seed(chat_data):
    random.seed()
    leads = []
    t = now()
    for i in range(14):
        when = t - timedelta(days=random.choice([0, 0, 0, 0, 1, 2, 3, 5, 9, 15]), hours=random.randint(0, 10))
        lead = fake_lead(i + 1, when, None)
        leads.append(lead)
    leads.sort(key=lambda x: x["created"])
    for i, lead in enumerate(leads):
        lead["id"] = i + 1
        lead["staff"] = None if lead["dup"] or i % 7 == 6 else STAFF[i % 2]
        r = random.random()
        if not lead["dup"]:
            lead["status"] = "선톡" if r < 0.3 else "리딩" if r < 0.45 else "뽑장" if r < 0.55 else "블랙" if r < 0.6 else None
    chat_data.clear()
    chat_data.update({"leads": leads, "next_id": len(leads) + 1, "period": "all", "auto": True, "rr": 0})


def data(ctx):
    if "leads" not in ctx.chat_data:
        seed(ctx.chat_data)
    return ctx.chat_data


def in_period(lead, period):
    t = now()
    c = lead["created"]
    if period == "today":
        return c.date() == t.date()
    if period == "week":
        return c >= t - timedelta(days=7)
    if period == "month":
        return c.year == t.year and c.month == t.month
    return True


def match(lead, key):
    return {
        "all": True,
        "dup": lead["dup"],
        "y2k": lead["year"] >= 2000,
        "black": lead["status"] == "블랙",
        "talk": lead["status"] == "선톡",
        "lead": lead["status"] == "리딩",
        "win": lead["status"] == "뽑장",
        "none": lead["staff"] is None,
        "s0": lead["staff"] == STAFF[0],
        "s1": lead["staff"] == STAFF[1],
    }[key]


def scoped(d):
    return [x for x in d["leads"] if in_period(x, d["period"])]


# ---------- 카드 화면 (사진 + 버튼) ----------
import cards
from telegram import InputMediaPhoto, InputSticker

HERE = os.path.dirname(os.path.abspath(__file__))
STICKER_DIR = os.path.join(HERE, "assets", "sticker")
EMOJI_DIR = os.path.join(HERE, "assets", "emoji")
SETUP_CODE = os.environ.get("SETUP_CODE", "")
BOT_USERNAME = "metaupdemo_bot"
EMOJI_SET = f"metaup_emoji_by_{BOT_USERNAME}"
STICKER_SET = f"metaup_sticker_by_{BOT_USERNAME}"
SET_EMOJI = {
    "20": "📈", "00": "🗂", "01": "❗", "02": "🎂", "03": "🚫", "04": "💬", "05": "📞", "06": "🏆",
    "07": "👤", "08": "📅", "09": "🗓", "10": "📆", "11": "⏳", "12": "⚙️", "13": "🔄", "14": "👥",
    "15": "✏️", "16": "💭", "17": "📢", "18": "🔔", "19": "🏠",
}
_sticker_ids = {}


def sticker_path(code):
    for f in sorted(os.listdir(STICKER_DIR)) if os.path.isdir(STICKER_DIR) else []:
        if f.startswith(code + "_"):
            return os.path.join(STICKER_DIR, f)
    return None


async def load_sticker_ids(app):
    """등록된 UP META 스티커 세트에서 file_id를 받아 둔다 (업로드 없이 바로 전송)."""
    try:
        st = await app.bot.get_sticker_set(STICKER_SET)
        files = sorted(f for f in os.listdir(STICKER_DIR) if f.endswith(".webm"))
        files.sort(key=lambda f: (0 if f.startswith("20_") else 1, f))
        for f, s in zip(files, st.stickers):
            _sticker_ids[f[:2]] = s.file_id
        log.info("스티커 %d개 준비됨", len(_sticker_ids))
    except Exception as e:
        log.warning("스티커 세트 불러오기 실패: %s", e)


async def send_sticker(chat, code):
    try:
        if code in _sticker_ids:
            return await chat.send_sticker(_sticker_ids[code])
        p = sticker_path(code)
        if not p:
            return None
        with open(p, "rb") as fh:
            m = await chat.send_sticker(fh)
        if m and m.sticker:
            _sticker_ids[code] = m.sticker.file_id
        return m
    except Exception as e:  # 스티커는 없어도 봇은 계속 동작
        log.warning("스티커 실패 %s: %s", code, e)
        return None


_emoji_ids = {}

# 버튼 아이콘(움직이는 UP META 이모지 번호)과 색
F_ICON = {"all": "00", "dup": "01", "y2k": "02", "black": "03", "talk": "04", "lead": "05", "win": "06",
          "none": "07", "s0": "07", "s1": "07"}
F_STYLE = {"all": "primary", "dup": "danger", "y2k": "danger", "black": "danger", "talk": "primary", "lead": "primary", "win": "primary"}
P_ICON = {"today": "08", "week": "09", "month": "10", "all": "11"}
S_ICON = {"선톡": "04", "리딩": "05", "뽑장": "06", "블랙": "03"}
S_STYLE = {"선톡": "primary", "리딩": "primary", "뽑장": "primary", "블랙": "danger"}


def btn(text, icon=None, style=None, **kw):
    """UP META 움직이는 이모지 + 색 버튼. 이모지가 아직 없으면 글자만."""
    extra = {}
    if icon and icon in _emoji_ids:
        extra["icon_custom_emoji_id"] = _emoji_ids[icon]
    if style:
        extra["style"] = style
    return B(text, api_kwargs=extra or None, **kw)


def plain(markup):
    """텔레그램이 아이콘/색을 거부할 때 쓰는 일반 버튼판."""
    return M([[B(x.text, callback_data=x.callback_data, url=x.url) for x in row] for row in markup.inline_keyboard])


async def load_emoji_ids(app):
    try:
        st = await app.bot.get_sticker_set(EMOJI_SET)
        files = sorted(f for f in os.listdir(EMOJI_DIR) if f.endswith(".webm"))
        files.sort(key=lambda f: (0 if f.startswith("20_") else 1, f))
        for f, s in zip(files, st.stickers):
            if s.custom_emoji_id:
                _emoji_ids[f[:2]] = s.custom_emoji_id
        log.info("버튼 이모지 %d개 준비됨", len(_emoji_ids))
    except Exception as e:
        log.warning("이모지 세트 불러오기 실패: %s", e)


async def on_startup(app):
    await load_sticker_ids(app)
    await load_emoji_ids(app)


def counts_of(d):
    leads = scoped(d)
    return {k: sum(1 for x in leads if match(x, k)) for k in FILTERS}


def home_view(d):
    c = counts_of(d)
    photo = cards.home_card(c, PERIODS[d["period"]], d["auto"], [(STAFF[0], c["s0"]), (STAFF[1], c["s1"])])

    def fb(k):
        return btn(f"{FILTERS[k]} {c[k]}", F_ICON[k], F_STYLE.get(k), callback_data=f"f:{k}:0")

    def pb(k):
        return btn(PERIODS[k], P_ICON[k], "primary" if d["period"] == k else None, callback_data=f"p:{k}")
    kb = [
        [fb("all"), fb("dup"), fb("y2k"), fb("black")],
        [fb("talk"), fb("lead"), fb("win")],
        [fb("s0"), fb("s1")],
        [pb("today"), pb("week"), pb("month"), pb("all")],
        [btn(f"자동 배분 {'ON' if d['auto'] else 'OFF'}", "12", "primary" if d["auto"] else "danger", callback_data="auto")],
        [btn("새로고침", "13", callback_data="home"), btn("직원 관리", "14", callback_data="staff"),
         btn("테스트 DB", "15", callback_data="test")],
        [btn("UP META 상담하기", "16", "primary", url=CONTACT_URL)],
    ]
    return photo, "<b>UP META · DB 관리봇</b>  체험판", M(kb)


PAGE = 6


def lead_icon(x):
    return "01" if x["dup"] else S_ICON.get(x["status"], "00")


def list_view(d, key, page):
    rows = [x for x in scoped(d) if match(x, key)]
    rows.sort(key=lambda x: x["created"], reverse=True)
    total = len(rows)
    pages = max(1, (total + PAGE - 1) // PAGE)
    page = max(0, min(page, pages - 1))
    chunk = rows[page * PAGE:(page + 1) * PAGE]
    photo = cards.list_card(FILTERS[key], PERIODS[d["period"]], total, chunk, page, pages)
    kb = []
    for i in range(0, len(chunk), 2):
        kb.append([btn(f"#{x['id']} {x['name']}", lead_icon(x), callback_data=f"c:{x['id']}:{key}") for x in chunk[i:i + 2]])
    nav = []
    if page > 0:
        nav.append(btn("◀ 이전", callback_data=f"f:{key}:{page - 1}"))
    if page + 1 < pages:
        nav.append(btn("다음 ▶", callback_data=f"f:{key}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([btn("메뉴로", "19", "primary", callback_data="home")])
    return photo, f"<b>{FILTERS[key]}</b> · {total}건 · 이름을 누르면 카드가 열려요", M(kb)


def card_view(d, lid, back):
    x = next((l for l in d["leads"] if l["id"] == lid), None)
    if not x:
        return home_view(d)
    st = [btn(s, S_ICON[s], S_STYLE[s] if x["status"] == s else None, callback_data=f"s:{x['id']}:{s}:{back}")
          for s in STATUSES]
    sf = [btn(s, "07", "primary" if x["staff"] == s else None, callback_data=f"a:{x['id']}:{i}:{back}")
          for i, s in enumerate(STAFF)]
    kb = [st, sf, [btn("명단으로", "00", callback_data=f"f:{back}:0"), btn("메뉴로", "19", "primary", callback_data="home")]]
    return cards.lead_card(x), f"<b>DB #{x['id']}</b> · 버튼으로 상태·담당을 바꿔 보세요 (색이 들어온 버튼 = 현재 상태)", M(kb)


def staff_view(d):
    stats = []
    for s in STAFF:
        mine = [x for x in d["leads"] if x["staff"] == s]
        stats.append((s, len(mine), sum(x["status"] == "선톡" for x in mine),
                      sum(x["status"] == "리딩" for x in mine), sum(x["status"] == "뽑장" for x in mine)))
    kb = [[btn("체험 데이터 초기화", "13", "danger", callback_data="reset")],
          [btn("메뉴로", "19", "primary", callback_data="home")]]
    return cards.staff_card(stats), "<b>직원 관리</b>", M(kb)


# ---------- 핸들러 ----------

async def show(update: Update, view):
    photo, caption, kb = view
    q = update.callback_query
    if q and q.message and q.message.photo:
        try:
            await q.edit_message_media(InputMediaPhoto(photo, caption=caption, parse_mode=ParseMode.HTML), reply_markup=kb)
            return
        except BadRequest as e:
            if "not modified" in str(e):
                return
            log.warning("수정 실패, 새로 보냄: %s", e)
            photo.seek(0)
    try:
        await update.effective_chat.send_photo(photo, caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
    except BadRequest as e:
        log.warning("꾸민 버튼 거부됨, 일반 버튼으로: %s", e)
        photo.seek(0)
        await update.effective_chat.send_photo(photo, caption=caption, parse_mode=ParseMode.HTML, reply_markup=plain(kb))


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    d = data(ctx)
    await send_sticker(update.effective_chat, "20")
    await update.effective_chat.send_message(
        "안녕하세요, <b>UP META</b> DB관리봇 체험판입니다.\n\n"
        "페이스북·인스타그램·틱톡 광고로 들어온 DB를 엑셀 없이 텔레그램에서 바로 "
        "정리·배분·통계까지 하는 봇이에요. 아래 카드의 버튼을 마음껏 눌러 보세요.\n\n"
        "<i>체험용 가짜 데이터만 들어 있어요. 눌러서 바뀐 내용은 본인 화면에만 보입니다.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=M([[btn("상담하기", "16", "primary", url=CONTACT_URL), btn("공지 채널", "17", url=CHANNEL_URL)]]),
    )
    await show(update, home_view(d))


async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.effective_chat.send_message(f"내 텔레그램 ID: <code>{u.id}</code>", parse_mode=ParseMode.HTML)


async def setup_sets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """비밀 명령: 보낸 사람 계정으로 UP META 이모지·스티커 세트를 만든다."""
    if not SETUP_CODE or not ctx.args or ctx.args[0] != SETUP_CODE:
        return
    uid = update.effective_user.id
    chat = update.effective_chat
    await chat.send_message("UP META 이모지·스티커 세트를 만드는 중이에요… (1분 정도)")
    results = []
    for set_name, title, folder, stype in [
        (EMOJI_SET, "UP META 이모지", EMOJI_DIR, "custom_emoji"),
        (STICKER_SET, "UP META 스티커", STICKER_DIR, "regular"),
    ]:
        files = sorted(f for f in os.listdir(folder) if f.endswith(".webm"))
        files.sort(key=lambda f: (0 if f.startswith("20_") else 1, f))
        handles, stickers = [], []
        for f in files:
            fh = open(os.path.join(folder, f), "rb")
            handles.append(fh)
            stickers.append(InputSticker(sticker=fh, emoji_list=[SET_EMOJI.get(f[:2], "📈")], format="video"))
        try:
            await ctx.bot.create_new_sticker_set(user_id=uid, name=set_name, title=title,
                                                 stickers=stickers, sticker_type=stype,
                                                 read_timeout=120, write_timeout=120)
            results.append(f"✅ {title} {len(stickers)}개")
        except BadRequest as e:
            if "occupied" in str(e).lower() or "already" in str(e).lower():
                results.append(f"ℹ️ {title}: 이미 만들어져 있어요")
            else:
                results.append(f"❌ {title}: {e}")
        finally:
            for fh in handles:
                fh.close()
    await on_startup(ctx.application)
    await chat.send_message(
        "\n".join(results) + "\n\n아래 버튼으로 추가하세요.",
        reply_markup=M([[btn("이모지 추가", "20", "primary", url=f"https://t.me/addemoji/{EMOJI_SET}")],
                        [btn("스티커 추가", "20", "success", url=f"https://t.me/addstickers/{STICKER_SET}")]]),
    )


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = data(ctx)
    parts = (q.data or "").split(":")
    kind = parts[0]
    note = None

    if kind == "f" and parts[1] in FILTERS:
        view = list_view(d, parts[1], int(parts[2]))
    elif kind == "p" and parts[1] in PERIODS:
        d["period"] = parts[1]
        view = home_view(d)
    elif kind == "auto":
        d["auto"] = not d["auto"]
        note = f"자동 배분 {'ON' if d['auto'] else 'OFF'}"
        view = home_view(d)
    elif kind == "staff":
        view = staff_view(d)
    elif kind == "reset":
        seed(d)
        note = "체험 데이터를 처음 상태로 돌렸어요"
        view = home_view(d)
    elif kind == "c":
        view = card_view(d, int(parts[1]), parts[2])
    elif kind == "s":
        x = next((l for l in d["leads"] if l["id"] == int(parts[1])), None)
        if x:
            x["status"] = None if x["status"] == parts[2] else parts[2]
        view = card_view(d, int(parts[1]), parts[3])
    elif kind == "a":
        x = next((l for l in d["leads"] if l["id"] == int(parts[1])), None)
        if x:
            s = STAFF[int(parts[2])]
            x["staff"] = None if x["staff"] == s else s
        view = card_view(d, int(parts[1]), parts[3])
    elif kind == "test":
        if len(d["leads"]) >= 60:
            await q.answer("체험 DB는 60건까지예요. 직원 관리 > 초기화를 눌러 주세요.", show_alert=True)
            return
        staff = None
        if d["auto"]:
            staff = STAFF[d["rr"] % len(STAFF)]
            d["rr"] += 1
        x = fake_lead(d["next_id"], now(), staff)
        if x["dup"]:
            x["staff"] = None
        d["next_id"] += 1
        d["leads"].append(x)
        await q.answer("테스트 DB가 들어왔어요")
        await send_sticker(q.message.chat, "18")
        await q.message.chat.send_photo(
            cards.new_lead_card(x), caption=f"🔔 <b>새 DB 도착</b> · #{x['id']}", parse_mode=ParseMode.HTML,
            reply_markup=M([[btn("카드 열기", lead_icon(x), "success", callback_data=f"c:{x['id']}:all"), btn("메뉴", "19", "primary", callback_data="home")]]),
        )
        return
    else:
        view = home_view(d)

    await q.answer(note or "")
    await show(update, view)


async def on_error(update, ctx: ContextTypes.DEFAULT_TYPE):
    log.warning("오류: %s", ctx.error)


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN 환경변수가 없습니다 (.env 확인)")
    app = (Application.builder().token(token)
           .connect_timeout(20).read_timeout(60).write_timeout(60).media_write_timeout(120).pool_timeout(30)
           .post_init(on_startup).build())
    app.add_handler(CommandHandler(["start", "menu"], start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("setup", setup_sets))
    import poster  # 팀장님 전용 채널 글쓰기 (데모 기능과 별개)
    poster.setup(app, _emoji_ids, SET_EMOJI)
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    log.info("UP META 데모봇 시작")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
