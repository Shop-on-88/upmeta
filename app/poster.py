"""UP META 채널 글쓰기 (팀장님 전용)

봇 개인채팅에 글/사진/영상을 보내면, 저장해 둔 버튼을 붙여 미리보기 → [채널에 올리기] 한 번으로 채널에 게시.
- 쓸 수 있는 사람: 사장님(OWNER_IDS)이 승인한 사람만 (팀장님)
- 버튼: 색 없는 기본 버튼(반투명) + UP META 움직이는 이모지 아이콘
- 데모봇 기능과 데이터는 따로 (data/poster.json)
"""
import asyncio
import json
import os
import re
import logging

from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as M, ReplyParameters
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

log = logging.getLogger("upmeta-poster")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "poster.json")
OWNER_IDS = {int(x) for x in os.environ.get("OWNER_IDS", "2103748907").split(",") if x.strip().isdigit()}
DEFAULT_BUTTONS = ("💬 상담 문의하기 - @upmeta9\n"
                   "🗂 DB봇 체험 - @metaupdemo_bot | 🏠 홈페이지 - upmeta.online")
EMOJI_CODE = {}  # 표준 이모지 -> 움직이는 이모지 번호 (bot.py에서 채움)
_emoji_ids = {}  # 번호 -> custom_emoji_id (bot.py와 공유)

HELP = ("✍️ <b>UP META 채널 글쓰기</b>\n\n"
        "1. 여기에 올릴 글이나 사진·영상(설명 포함)을 보내세요\n"
        "2. 미리보기가 오면 버튼 색(⚪기본 🔵파랑 🟢초록 🔴빨강)을 누르면 바로 올라가요\n"
        "   버튼이 필요 없으면 <b>[버튼 없이 올리기]</b>\n"
        "3. 예전 채널 글에 버튼을 붙이려면 그 글을 여기로 <b>전달</b> → 색 고르기\n"
        "※ 사진 여러 장 앨범은 버튼을 못 붙여서 바로 아래 버튼 글로 달려요\n\n"
        "/버튼 — 붙일 버튼 보기·바꾸기\n"
        "/채널 — 올릴 채널 바꾸기 (지금: {ch})")


def load():
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("allowed", [])
    d.setdefault("buttons", DEFAULT_BUTTONS)
    d.setdefault("channel", "@UPMETA99")
    return d


def save(d):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)


def allowed(uid):
    return uid in OWNER_IDS or uid in load()["allowed"]


def norm_url(u):
    u = u.strip()
    if u.startswith("@"):
        return "https://t.me/" + u[1:]
    if not re.match(r"^[a-z]+://", u, re.I) and not u.startswith("tg:"):
        return "https://" + u
    return u


def parse_buttons(text):
    """'이모지 이름 - 링크' 한 줄 = 한 줄, '|' = 같은 줄 옆 버튼"""
    rows, errs = [], []
    for line in text.strip().splitlines():
        row = []
        for part in line.split("|"):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(.+?)\s+-\s+(\S+)$", part)
            if not m:
                errs.append(part)
                continue
            row.append((m.group(1).strip(), norm_url(m.group(2))))
        if row:
            rows.append(row)
    return rows, errs


ALBUM_BTN_TEXT = "📌 문의·상담은 아래 버튼을 눌러주세요"
COLORS = {"d": ("⚪", "기본", None), "b": ("🔵", "파랑", "primary"), "g": ("🟢", "초록", "success"), "r": ("🔴", "빨강", "danger")}


def keyboard(text, color="d", icons=True):
    """color: d 기본(반투명) / b 파랑 / g 초록 / r 빨강"""
    style = COLORS.get(color, COLORS["d"])[2]
    rows, _ = parse_buttons(text)
    out = []
    for row in rows:
        r = []
        for label, url in row:
            extra = {}
            if icons:
                for emo, code in EMOJI_CODE.items():
                    if label.startswith(emo) and code in _emoji_ids:
                        label = label[len(emo):].strip()
                        extra["icon_custom_emoji_id"] = _emoji_ids[code]
                        break
            if style:
                extra["style"] = style
            r.append(B(label, url=url, api_kwargs=extra or None))
        out.append(r)
    return M(out) if out else None


def plain_kb(text, color="d"):
    return keyboard(text, color, icons=False)


async def with_fallback(fn, text, color):
    """아이콘+색 -> 색만 -> 그냥 버튼 순서로 시도"""
    last = None
    for kb in (keyboard(text, color), plain_kb(text, color), plain_kb(text, "d")):
        try:
            return await fn(kb)
        except Exception as e:
            if "not modified" in str(e).lower():
                raise
            log.warning("버튼 거부됨, 다음 방식으로 재시도: %s", e)
            last = e
    raise last


def color_rows(prefix):
    c = COLORS
    return [[B(f"{c[k][0]} {c[k][1]}", callback_data=f"{prefix}:{k}") for k in ("d", "b")],
            [B(f"{c[k][0]} {c[k][1]}", callback_data=f"{prefix}:{k}") for k in ("g", "r")]]


async def cmd_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if update.effective_chat.type != "private":
        return
    if allowed(u.id):
        await update.message.reply_html(HELP.format(ch=load()["channel"]))
        return
    name = (u.full_name or "") + (f" (@{u.username})" if u.username else "")
    for oid in OWNER_IDS:
        try:
            await ctx.bot.send_message(oid, f"✍️ 채널 글쓰기 사용 요청\n{name}\nID: {u.id}",
                                       reply_markup=M([[B("✅ 승인", callback_data=f"pa:{u.id}"),
                                                        B("❌ 거절", callback_data=f"pr:{u.id}")]]))
        except Exception as e:
            log.warning("승인 요청 실패: %s", e)
    await update.message.reply_text("사용 요청을 보냈어요. 승인되면 알려드릴게요.")


async def cmd_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not allowed(update.effective_user.id):
        return
    d = load()
    ctx.user_data["poster_wait"] = "buttons"
    await update.message.reply_text(
        "지금 붙는 버튼이에요 👇\n\n" + d["buttons"] +
        "\n\n바꾸려면 아래 형식으로 보내주세요 (취소: /취소)\n"
        "• 한 줄 = 버튼 한 줄\n• 같은 줄에 2개: | 로 구분\n• 형식: 이모지 이름 - 링크\n\n"
        "예)\n💬 이도문의하기 - @upmeta9\n📢 공지채널 - @UPMETA99 | 🏠 홈페이지 - upmeta.online",
        reply_markup=keyboard(d["buttons"]) or None)


async def cmd_channel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or not allowed(update.effective_user.id):
        return
    ctx.user_data["poster_wait"] = "channel"
    await update.message.reply_text(f"지금 올리는 채널: {load()['channel']}\n바꿀 채널 주소를 보내주세요 (예: @UPMETA99, 취소: /취소)\n"
                                    "※ 봇이 그 채널의 관리자(글 올리기 권한)여야 해요")


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not allowed(update.effective_user.id):
        return
    ctx.user_data.pop("poster_wait", None)
    ctx.user_data.pop("poster_draft", None)
    await update.message.reply_text("취소했어요.")


async def on_private(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """승인된 사람이 개인채팅에 보낸 글/사진 -> 버튼 붙인 미리보기"""
    msg = update.message
    if not msg or not allowed(update.effective_user.id):
        return
    wait = ctx.user_data.pop("poster_wait", None)
    d = load()
    if wait == "buttons" and msg.text:
        rows, errs = parse_buttons(msg.text)
        if not rows or errs:
            ctx.user_data["poster_wait"] = "buttons"
            await msg.reply_text("형식이 맞지 않는 줄이 있어요:\n" + "\n".join(errs or [msg.text]) +
                                 "\n\n형식: 이모지 이름 - 링크  (다시 보내주세요, 취소: /취소)")
            return
        d["buttons"] = msg.text.strip()
        save(d)
        await msg.reply_text("✅ 버튼을 바꿨어요. 이제 올리는 글에 이 버튼이 붙어요.", reply_markup=keyboard(d["buttons"]))
        return
    if wait == "channel" and msg.text:
        ch = msg.text.strip()
        ch = "@" + ch.split("t.me/")[-1] if "t.me/" in ch else ch
        try:
            chat = await ctx.bot.get_chat(ch)
            me = await ctx.bot.get_chat_member(chat.id, ctx.bot.id)
            if me.status not in ("administrator", "creator"):
                raise ValueError("봇이 관리자가 아니에요")
        except Exception as e:
            await msg.reply_text(f"❌ 그 채널에 올릴 수 없어요: {e}\n봇을 채널 관리자로 먼저 추가해주세요.")
            return
        d["channel"] = ch
        save(d)
        await msg.reply_text(f"✅ 이제 {ch} 채널에 올려요.")
        return
    gid = msg.media_group_id
    origin = getattr(msg, "forward_origin", None)
    if origin is not None and getattr(origin, "type", "") == "channel":
        och = origin.chat
        target = d["channel"]
        same = (target.startswith("@") and (och.username or "").lower() == target[1:].lower()) or str(och.id) == str(target)
        if same:
            if gid:
                # 앨범(사진 여러 장 묶음): 텔레그램이 앨범에는 버튼을 허용하지 않음 -> 바로 아래 버튼 글로
                cur = ctx.user_data.get("poster_edit")
                if cur and cur[2] == gid:
                    cur[1] = min(cur[1], origin.message_id)
                    return
                ctx.user_data["poster_edit"] = [och.id, origin.message_id, gid]
                await msg.reply_text("📌 이 글은 사진 여러 장을 묶은 <b>앨범</b>이라 텔레그램이 버튼을 붙이지 못하게 막아요.\n"
                                     f"대신 이 글 <b>바로 아래에 버튼 글</b>(\"{ALBUM_BTN_TEXT}\")을 답장으로 달아드릴게요.\n"
                                     "버튼 색을 고르세요 👇", parse_mode="HTML",
                                     reply_markup=M(color_rows("pe") + [[B("❌ 취소", callback_data="pe:no")]]))
                return
            ctx.user_data["poster_edit"] = [och.id, origin.message_id, None]
            await msg.reply_text("📌 채널에 있는 이 글에 버튼을 붙일까요?\n붙일 버튼 색을 고르세요 👇",
                                 reply_markup=M(color_rows("pe") + [[B("🧹 버튼 없애기", callback_data="pe:del"),
                                                                     B("❌ 취소", callback_data="pe:no")]]))
            return
    if gid:
        # 새 앨범 글: 묶음이 다 들어올 때까지 모았다가 미리보기 한 번만
        alb = ctx.user_data.get("poster_album")
        if alb and alb["gid"] == gid:
            alb["ids"].append(msg.message_id)
            return
        ctx.user_data["poster_album"] = {"gid": gid, "ids": [msg.message_id]}
        asyncio.create_task(album_preview(ctx, msg.chat_id, gid))
        return
    kb = keyboard(d["buttons"])
    try:
        prev = await msg.copy(msg.chat_id, reply_markup=kb)
    except Exception:
        kb = plain_kb(d["buttons"])
        prev = await msg.copy(msg.chat_id, reply_markup=kb)
    ctx.user_data["poster_draft"] = msg.message_id
    await ctx.bot.send_message(msg.chat_id, f"👆 미리보기예요. {d['channel']} 채널에 올릴까요?\n버튼 색을 고르면 바로 올라가요 👇",
                               reply_to_message_id=prev.message_id,
                               reply_markup=M(color_rows("pp") + [[B("📝 버튼 없이 올리기", callback_data="pp:nob"),
                                                                    B("❌ 취소", callback_data="pp:no")]]))


async def album_preview(ctx, chat_id, gid):
    await asyncio.sleep(2.5)
    alb = ctx.user_data.get("poster_album")
    if not alb or alb["gid"] != gid:
        return
    ids = sorted(alb["ids"])
    d = load()
    try:
        prev = await ctx.bot.copy_messages(chat_id, chat_id, ids)
        await ctx.bot.send_message(chat_id, ALBUM_BTN_TEXT, reply_markup=keyboard(d["buttons"]) or plain_kb(d["buttons"]),
                                   reply_parameters=ReplyParameters(prev[0].message_id))
    except Exception as e:
        log.warning("앨범 미리보기 실패: %s", e)
    ctx.user_data["poster_draft"] = {"album": ids}
    await ctx.bot.send_message(chat_id, f"👆 미리보기예요 (사진 {len(ids)}장 앨범). {d['channel']} 채널에 올릴까요?\n"
                                        "앨범에는 버튼을 바로 못 붙여서, 앨범 바로 아래에 버튼 글이 따라 올라가요.\n버튼 색을 고르세요 👇",
                               reply_markup=M(color_rows("pp") + [[B("📝 버튼 없이 올리기", callback_data="pp:nob"),
                                                                    B("❌ 취소", callback_data="pp:no")]]))


async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    kind, arg = q.data.split(":", 1)
    uid = q.from_user.id
    if kind in ("pa", "pr"):
        if uid not in OWNER_IDS:
            await q.answer("사장님만 승인할 수 있어요", show_alert=True)
            return
        target = int(arg)
        d = load()
        if kind == "pa":
            if target not in d["allowed"]:
                d["allowed"].append(target)
                save(d)
            await q.edit_message_text(q.message.text + "\n\n✅ 승인했어요")
            try:
                await ctx.bot.send_message(target, "✅ 채널 글쓰기가 승인됐어요!\n\n" + HELP.format(ch=d["channel"]).replace("<b>", "").replace("</b>", ""))
            except Exception:
                pass
        else:
            await q.edit_message_text(q.message.text + "\n\n❌ 거절했어요")
        await q.answer()
        return
    if not allowed(uid):
        await q.answer()
        return
    if kind == "pe":
        tgt = ctx.user_data.pop("poster_edit", None)
        if arg == "no" or not tgt:
            await q.edit_message_text("취소했어요." if arg == "no" else "시간이 지나서 만료됐어요. 글을 다시 전달해주세요.")
            await q.answer()
            return
        d = load()
        chat_id, mid = tgt[0], tgt[1]
        if len(tgt) > 2 and tgt[2] and arg in COLORS:
            try:
                await with_fallback(lambda kb: ctx.bot.send_message(chat_id, ALBUM_BTN_TEXT, reply_markup=kb,
                                                                    reply_parameters=ReplyParameters(mid)), d["buttons"], arg)
            except Exception as e:
                await q.edit_message_text(f"❌ 버튼 글을 올리지 못했어요: {e}")
                await q.answer()
                return
            await q.edit_message_text(f"✅ 앨범 바로 아래에 {COLORS[arg][1]} 버튼 글을 달았어요!")
            await q.answer()
            return
        try:
            if arg in COLORS:
                await with_fallback(lambda kb: ctx.bot.edit_message_reply_markup(chat_id, mid, reply_markup=kb), d["buttons"], arg)
            else:
                await ctx.bot.edit_message_reply_markup(chat_id, mid, reply_markup=None)
        except Exception as e:
            err = str(e)
            if "not modified" in err.lower():
                await q.edit_message_text("이미 같은 색 버튼이 붙어 있어요." if arg in COLORS else "이미 버튼이 없어요.")
            elif "can't be edited" in err.lower() or "not enough rights" in err.lower() or "message_author_required" in err.lower():
                await q.edit_message_text("❌ 텔레그램이 이 글은 봇이 수정하지 못하게 막았어요.\n"
                                          "(다른 관리자가 쓴 글은 막힐 수 있어요 → 이 글은 봇으로 다시 올려주세요)")
            else:
                await q.edit_message_text(f"❌ 수정하지 못했어요: {err}\n봇에게 채널 '메시지 수정' 권한이 있는지 확인해주세요.")
            await q.answer()
            return
        link = f"https://t.me/{d['channel'].lstrip('@')}/{mid}" if d["channel"].startswith("@") else ""
        await q.edit_message_text((f"✅ {COLORS[arg][1]} 버튼을 붙였어요!" if arg in COLORS else "✅ 버튼을 없앴어요!") + (f"\n{link}" if link else ""))
        await q.answer()
        return
    draft = ctx.user_data.get("poster_draft")
    if arg == "no" or not draft:
        ctx.user_data.pop("poster_draft", None)
        await q.edit_message_text("취소했어요." if arg == "no" else "미리보기가 만료됐어요. 글을 다시 보내주세요.")
        await q.answer()
        return
    d = load()
    try:
        if isinstance(draft, dict):
            ids = await ctx.bot.copy_messages(d["channel"], q.message.chat_id, draft["album"])
            sent = ids[0]
            if arg != "nob":
                color = arg if arg in COLORS else "d"
                await with_fallback(lambda kb: ctx.bot.send_message(d["channel"], ALBUM_BTN_TEXT, reply_markup=kb,
                                                                    reply_parameters=ReplyParameters(sent.message_id)),
                                    d["buttons"], color)
        elif arg == "nob":
            sent = await ctx.bot.copy_message(d["channel"], q.message.chat_id, draft)
        else:
            color = arg if arg in COLORS else "d"
            sent = await with_fallback(lambda kb: ctx.bot.copy_message(d["channel"], q.message.chat_id, draft, reply_markup=kb),
                                       d["buttons"], color)
    except Exception as e:
        await q.answer("올리기 실패", show_alert=True)
        await q.message.reply_text(f"❌ 채널에 못 올렸어요: {e}\n봇이 {d['channel']} 채널 관리자(글 올리기 권한)인지 확인해주세요.")
        return
    ctx.user_data.pop("poster_draft", None)
    link = f"https://t.me/{d['channel'].lstrip('@')}/{sent.message_id}" if d["channel"].startswith("@") else ""
    await q.edit_message_text("✅ 채널에 올렸어요!" + (f"\n{link}" if link else ""))
    await q.answer("올렸어요")


def setup(app, emoji_ids, set_emoji):
    """bot.py에서 호출: 핸들러 등록 + 움직이는 이모지 연결"""
    global _emoji_ids
    _emoji_ids = emoji_ids
    EMOJI_CODE.update({v: k for k, v in set_emoji.items()})
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler(["post", "write"], cmd_post, filters=private))
    app.add_handler(MessageHandler(private & filters.Regex(r"^/(글쓰기)(@\w+)?$"), cmd_post))
    app.add_handler(MessageHandler(private & filters.Regex(r"^/(버튼)(@\w+)?$"), cmd_buttons))
    app.add_handler(MessageHandler(private & filters.Regex(r"^/(채널)(@\w+)?$"), cmd_channel))
    app.add_handler(MessageHandler(private & filters.Regex(r"^/(취소)(@\w+)?$"), cmd_cancel))
    app.add_handler(CallbackQueryHandler(on_cb, pattern=r"^(pa|pr|pp|pe):"))
    app.add_handler(MessageHandler(private & ~filters.COMMAND & ~filters.Regex(r"^/"), on_private))
