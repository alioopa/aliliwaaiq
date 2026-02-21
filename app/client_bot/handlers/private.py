from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from celery import Celery

from app.client_bot.keyboards import (
    client_main_keyboard,
    owner_panel_keyboard,
    templates_keyboard,
    verify_channels_keyboard,
)
from app.client_bot.templates import BOT_TEMPLATES
from app.core.config import get_settings
from app.core.enums import UserRole
from app.db.session import session_scope
from app.services.bot_service import (
    add_ad,
    add_forced_channel,
    build_backup_payload,
    create_payment_request,
    dumps_backup,
    get_client_bot,
    get_due_ad,
    get_user_role,
    is_platform_banned,
    list_forced_channels,
    redeem_coupon,
    remove_forced_channel,
    restore_backup_payload,
    set_bot_setting,
    upsert_member,
)
from app.services.broadcast_service import create_broadcast_job, parse_segment

router = Router(name="client_private")


def _manager_roles() -> set[UserRole]:
    return {UserRole.OWNER, UserRole.ADMIN}


async def _check_force_sub(bot_api, user_id: int, channels) -> tuple[bool, list]:
    missing = []
    for ch in channels:
        try:
            member = await bot_api.get_chat_member(ch.channel_id, user_id)
            if member.status in {"left", "kicked"}:
                missing.append(ch)
        except Exception:
            missing.append(ch)
    return len(missing) == 0, missing


async def _load_bot_and_role(tenant_bot_id: uuid.UUID, user_id: int):
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return None, None
        role = await get_user_role(session, bot, user_id)
        return bot, role


@router.message(CommandStart())
async def start_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        if bot.is_banned:
            await message.answer("هذا البوت موقوف من قبل المنصة.")
            return
        if await is_platform_banned(session, message.from_user.id):
            await message.answer("حسابك محظور على مستوى المنصة.")
            return

        await upsert_member(
            session,
            bot,
            message.from_user.id,
            increment_interaction=True,
            mark_started=True,
        )
        channels = await list_forced_channels(session, bot.id)

    if channels:
        ok, missing = await _check_force_sub(message.bot, message.from_user.id, channels)
        if not ok:
            await message.answer(
                "يجب الاشتراك بالقنوات المطلوبة أولاً.",
                reply_markup=verify_channels_keyboard(missing),
            )
            return

    text = "أهلاً بك 👋"
    if bot.branding_enabled:
        text += f"\n\nPowered by {get_settings().platform_brand_handle}"
    await message.answer(text, reply_markup=client_main_keyboard())


@router.callback_query(F.data == "c:verify_sub")
async def verify_sub_cb(callback: CallbackQuery, tenant_bot_id: uuid.UUID) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            await callback.answer("البوت غير موجود", show_alert=True)
            return
        channels = await list_forced_channels(session, bot.id)
    if not channels:
        await callback.answer("لا يوجد اشتراك إجباري.", show_alert=True)
        return
    ok, missing = await _check_force_sub(callback.bot, callback.from_user.id, channels)
    if ok:
        await callback.message.answer("تم التحقق بنجاح ✅")
    else:
        await callback.message.answer(
            "لا تزال هناك قنوات غير مشترك بها.",
            reply_markup=verify_channels_keyboard(missing),
        )
    await callback.answer()


@router.message(Command("panel"))
async def panel_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    bot, role = await _load_bot_and_role(tenant_bot_id, message.from_user.id)
    if not bot or role not in _manager_roles() | {UserRole.MOD, UserRole.OWNER}:
        return
    await message.answer("لوحة التحكم:", reply_markup=owner_panel_keyboard())


@router.callback_query(F.data == "c:panel")
async def panel_cb(callback: CallbackQuery, tenant_bot_id: uuid.UUID) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    bot, role = await _load_bot_and_role(tenant_bot_id, callback.from_user.id)
    if not bot or role not in _manager_roles() | {UserRole.MOD, UserRole.OWNER}:
        await callback.answer("غير مصرح", show_alert=True)
        return
    await callback.message.answer("لوحة التحكم:", reply_markup=owner_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "c:broadcast_help")
async def broadcast_help_cb(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "الأوامر:\n"
        "`/broadcast SEGMENT الرسالة`\n"
        "Segments: ALL | ACTIVE_24H | ACTIVE_7D | VIP_ONLY\n\n"
        "`/broadcast_schedule 2026-02-21T20:30:00+00:00 SEGMENT الرسالة`"
    )
    await callback.answer()


@router.callback_query(F.data == "c:security_help")
async def security_help_cb(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "أوامر الحماية:\n"
        "`/set_guard anti_link on|off`\n"
        "`/set_guard anti_spam on|off`\n"
        "`/set_guard forbidden_words word1,word2`\n"
        "`/set_guard max_warns 3`"
    )
    await callback.answer()


@router.callback_query(F.data == "c:backup")
async def backup_cb(callback: CallbackQuery, tenant_bot_id: uuid.UUID) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            await callback.answer("غير موجود", show_alert=True)
            return
        role = await get_user_role(session, bot, callback.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            await callback.answer("غير مصرح", show_alert=True)
            return
        payload = await build_backup_payload(session, bot)
    content = dumps_backup(payload).encode("utf-8")
    await callback.message.answer_document(
        BufferedInputFile(content, filename=f"backup_{tenant_bot_id}.json"),
        caption="تم إنشاء النسخة الاحتياطية.",
    )
    await callback.answer()


@router.callback_query(F.data == "c:templates")
async def templates_cb(callback: CallbackQuery) -> None:
    await callback.message.answer("اختر القالب:", reply_markup=templates_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("c:template:"))
async def apply_template_cb(callback: CallbackQuery, tenant_bot_id: uuid.UUID) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    template_name = callback.data.split(":")[-1].upper()
    template = BOT_TEMPLATES.get(template_name)
    if not template:
        await callback.answer("Template غير معروف", show_alert=True)
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            await callback.answer("غير موجود", show_alert=True)
            return
        role = await get_user_role(session, bot, callback.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            await callback.answer("غير مصرح", show_alert=True)
            return
        bot.settings = template
        bot.template_name = template_name
    await callback.message.answer(f"تم تطبيق قالب {template_name}.")
    await callback.answer()


@router.message(Command("set_guard"))
async def set_guard_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("الاستخدام: `/set_guard key value`")
        return
    key, raw = parts[1], parts[2]
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER, UserRole.MOD}:
            return
        if raw.lower() in {"on", "true"}:
            value = True
        elif raw.lower() in {"off", "false"}:
            value = False
        elif key == "forbidden_words":
            value = [x.strip().lower() for x in raw.split(",") if x.strip()]
        elif key == "max_warns":
            value = int(raw)
        else:
            value = raw
        await set_bot_setting(session, bot, key, value)
    await message.answer(f"تم حفظ `{key}`.")


@router.message(Command("add_channel"))
async def add_channel_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/add_channel CHANNEL_ID [@username]`")
        return
    channel_id = int(parts[1])
    username = parts[2] if len(parts) > 2 else None
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        channel = await add_forced_channel(session, bot.id, channel_id, username)
    await message.answer(f"تمت إضافة القناة: {channel.channel_id}")


@router.message(Command("remove_channel"))
async def remove_channel_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/remove_channel CHANNEL_ID`")
        return
    channel_id = int(parts[1])
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        ok = await remove_forced_channel(session, bot.id, channel_id)
    await message.answer("تم الحذف." if ok else "القناة غير موجودة.")


@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, tenant_bot_id: uuid.UUID, celery_app: Celery) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("الاستخدام: `/broadcast SEGMENT الرسالة`")
        return
    try:
        segment = parse_segment(parts[1])
    except Exception as exc:
        await message.answer(str(exc))
        return
    text = parts[2]
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        job = await create_broadcast_job(
            session=session,
            bot_id=bot.id,
            created_by=message.from_user.id,
            text=text,
            segment=segment,
        )
    celery_app.send_task("app.tasks.broadcast.process_broadcast_job", args=[str(job.id)])
    await message.answer(f"تم إنشاء مهمة البث `{job.id}`.")


@router.message(Command("broadcast_schedule"))
async def broadcast_schedule_cmd(message: Message, tenant_bot_id: uuid.UUID, celery_app: Celery) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 4:
        await message.answer("الاستخدام: `/broadcast_schedule ISO_DATETIME SEGMENT الرسالة`")
        return
    try:
        scheduled_at = datetime.fromisoformat(parts[1])
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
        segment = parse_segment(parts[2])
    except Exception:
        await message.answer("صيغة التاريخ أو segment غير صحيحة.")
        return
    text = parts[3]
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        job = await create_broadcast_job(
            session=session,
            bot_id=bot.id,
            created_by=message.from_user.id,
            text=text,
            segment=segment,
            scheduled_at=scheduled_at,
        )
    celery_app.send_task("app.tasks.broadcast.process_broadcast_job", args=[str(job.id)], eta=scheduled_at)
    await message.answer(f"تمت جدولة مهمة `{job.id}` عند {scheduled_at.isoformat()}.")


@router.message(Command("backup_settings"))
async def backup_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        payload = await build_backup_payload(session, bot)
    content = dumps_backup(payload).encode("utf-8")
    await message.answer_document(BufferedInputFile(content, filename=f"backup_{tenant_bot_id}.json"))


@router.message(Command("restore_settings"))
async def restore_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/restore_settings {json}`")
        return
    try:
        payload = json.loads(parts[1])
    except json.JSONDecodeError:
        await message.answer("JSON غير صالح.")
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        await restore_backup_payload(session, bot, payload)
    await message.answer("تمت الاستعادة بنجاح.")


@router.message(Command("apply_template"))
async def apply_template_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/apply_template BASIC|COMMUNITY|STORE`")
        return
    template_name = parts[1].strip().upper()
    template = BOT_TEMPLATES.get(template_name)
    if not template:
        await message.answer("القالب غير موجود.")
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        bot.settings = template
        bot.template_name = template_name
    await message.answer(f"تم تطبيق القالب {template_name}.")


@router.message(Command("set_ad_frequency"))
async def ad_frequency_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/set_ad_frequency NUMBER`")
        return
    try:
        frequency = max(0, int(parts[1]))
    except ValueError:
        await message.answer("NUMBER غير صالح.")
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        bot.ad_frequency = frequency
    await message.answer(f"تم ضبط تكرار الإعلانات: {frequency}")


@router.message(Command("add_ad"))
async def add_ad_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/add_ad نص الإعلان`")
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        every_n = bot.ad_frequency if bot.ad_frequency > 0 else 5
        ad = await add_ad(session, bot.id, parts[1], every_n)
    await message.answer(f"تمت إضافة الإعلان `{ad.id}`.")


@router.message(Command("payment_request"))
async def payment_request_cmd(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    parts = (message.text or "").split(maxsplit=4)
    if len(parts) < 3:
        await message.answer("الاستخدام: `/payment_request amount currency [receipt_url] [note]`")
        return
    try:
        amount = Decimal(parts[1])
    except Exception:
        await message.answer("amount غير صالح.")
        return
    currency = parts[2]
    receipt_url = parts[3] if len(parts) > 3 else None
    note = parts[4] if len(parts) > 4 else None
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        role = await get_user_role(session, bot, message.from_user.id)
        if role not in _manager_roles() | {UserRole.OWNER}:
            return
        payment = await create_payment_request(
            session=session,
            bot_id=bot.id,
            submitted_by=message.from_user.id,
            amount=amount,
            currency=currency,
            receipt_url=receipt_url,
            note=note,
        )
    await message.answer(f"تم إرسال طلب الدفع `{payment.id}` للمراجعة.")


@router.message(Command("redeem"))
async def redeem_cmd(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/redeem CODE`")
        return
    code = parts[1].strip().upper()
    async with session_scope() as session:
        coupon = await redeem_coupon(session, code)
    if not coupon:
        await message.answer("الكوبون غير صالح أو منتهي.")
        return
    await message.answer(f"تم تطبيق كوبون `{coupon.code}` بخصم {coupon.discount_percent}%.")


@router.message(F.chat.type == "private")
async def private_activity(message: Message, tenant_bot_id: uuid.UUID) -> None:
    if not message.from_user:
        return
    text = message.text or ""
    if text.startswith("/"):
        return
    async with session_scope() as session:
        bot = await get_client_bot(session, tenant_bot_id)
        if not bot:
            return
        member = await upsert_member(session, bot, message.from_user.id, increment_interaction=True)
        ad = await get_due_ad(session, bot.id, member.interactions_count)
    if ad:
        await message.answer(ad.text)
