from __future__ import annotations

import uuid
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.bot_manager.manager import BotManager
from app.core.config import get_settings
from app.core.enums import PaymentStatus, PlanType
from app.core.logging import get_logger
from app.db.models import PaymentRequest
from app.db.session import session_scope
from app.master_bot.keyboards import master_panel_keyboard
from app.master_bot.states import MasterStates
from app.services.bot_service import (
    ban_bot,
    create_client_bot,
    create_coupon,
    get_platform_stats,
    list_owner_bots,
    set_payment_status,
    set_subscription_plan,
    unban_bot,
    utcnow,
    validate_bot_token,
)

router = Router(name="master_admin")
logger = get_logger(__name__)


def _is_admin(user_id: int) -> bool:
    settings = get_settings()
    admins = settings.admin_id_set
    if not admins:
        # Bootstrap mode: prevent accidental lockout if MASTER_ADMIN_IDS was not configured.
        logger.warning("master_admin_ids_missing_allowing_access_temporarily")
        return True
    return user_id in admins


def _split(text: str) -> list[str]:
    return text.strip().split()


@router.message(CommandStart())
async def start_master(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await message.answer("لوحة إدارة المنصة.", reply_markup=master_panel_keyboard())


@router.message(Command("myid"))
async def myid_cmd(message: Message) -> None:
    if not message.from_user:
        return
    is_admin = _is_admin(message.from_user.id)
    await message.answer(
        f"Telegram ID: `{message.from_user.id}`\n"
        f"Admin access: {'YES' if is_admin else 'NO'}"
    )


@router.callback_query(F.data == "m:help")
async def help_cb(callback: CallbackQuery) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("غير مصرح", show_alert=True)
        return
    await callback.message.answer(
        "أوامر الإدارة:\n"
        "`/newbot TOKEN`\n"
        "`/mybots`\n"
        "`/startbot BOT_ID`\n"
        "`/stopbot BOT_ID`\n"
        "`/restartbot BOT_ID`\n"
        "`/setplan BOT_ID FREE|MONTHLY|SEMIANNUAL|YEARLY`\n"
        "`/stats`\n"
        "`/banbot BOT_ID reason`\n"
        "`/unbanbot BOT_ID`\n"
        "`/create_coupon CODE PERCENT MAX_USES DAYS`\n"
        "`/approve_payment PAYMENT_ID PLAN`\n"
        "`/reject_payment PAYMENT_ID reason`\n"
        "`/payments`"
    )
    await callback.answer()


@router.callback_query(F.data == "m:newbot")
async def newbot_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("غير مصرح", show_alert=True)
        return
    await state.set_state(MasterStates.waiting_bot_token)
    await callback.message.answer("أرسل توكن البوت الآن.")
    await callback.answer()


@router.callback_query(F.data == "m:mybots")
async def mybots_cb(callback: CallbackQuery) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("غير مصرح", show_alert=True)
        return
    async with session_scope() as session:
        bots = await list_owner_bots(session, callback.from_user.id)
    if not bots:
        await callback.message.answer("لا يوجد بوتات.")
    else:
        lines = [f"- `{item.id}` | @{item.username or '-'} | {item.status.value}" for item in bots]
        await callback.message.answer("بوتاتك:\n" + "\n".join(lines))
    await callback.answer()


@router.callback_query(F.data == "m:stats")
async def stats_cb(callback: CallbackQuery) -> None:
    if not callback.from_user or not _is_admin(callback.from_user.id):
        await callback.answer("غير مصرح", show_alert=True)
        return
    async with session_scope() as session:
        stats = await get_platform_stats(session)
    await callback.message.answer(
        "إحصائيات المنصة:\n"
        f"- إجمالي البوتات: {stats['total_bots']}\n"
        f"- البوتات العاملة: {stats['running_bots']}\n"
        f"- المستخدمون: {stats['users_total']}\n"
        f"- دفعات معلقة: {stats['pending_payments']}"
    )
    await callback.answer()


@router.message(Command("newbot"))
async def newbot_cmd(message: Message, state: FSMContext, bot_manager: BotManager) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 2:
        await state.set_state(MasterStates.waiting_bot_token)
        await message.answer("الاستخدام: `/newbot TOKEN`")
        return
    await _register_bot(message, parts[1], bot_manager)


@router.message(MasterStates.waiting_bot_token)
async def newbot_state(message: Message, state: FSMContext, bot_manager: BotManager) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    token = (message.text or "").strip()
    if not token:
        await message.answer("أرسل توكن صحيح.")
        return
    await _register_bot(message, token, bot_manager)
    await state.clear()


async def _register_bot(message: Message, token: str, bot_manager: BotManager) -> None:
    try:
        bot_name, bot_username = await validate_bot_token(token)
    except Exception as exc:
        await message.answer(f"التوكن غير صالح: {exc}")
        return
    async with session_scope() as session:
        bot = await create_client_bot(
            session=session,
            owner_telegram_id=message.from_user.id,
            token_plain=token,
            bot_name=bot_name,
            bot_username=bot_username,
        )
    started = True
    try:
        await bot_manager.start_bot(bot.id)
    except Exception:
        started = False
        logger.warning("auto_start_new_client_bot_failed", bot_id=str(bot.id), exc_info=True)

    await message.answer(
        "تم إنشاء البوت:\n"
        f"- الاسم: {bot_name}\n"
        f"- المعرف: @{bot_username or '-'}\n"
        f"- BOT_ID: `{bot.id}`\n"
        + (f"- الحالة: {'RUNNING ✅' if started else 'STOPPED ⚠️'}\n")
        + ("تم تشغيله تلقائيًا." if started else "شغله عبر `/startbot BOT_ID`")
    )


@router.message(Command("mybots"))
async def mybots_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        bots = await list_owner_bots(session, message.from_user.id)
    if not bots:
        await message.answer("لا يوجد بوتات.")
        return
    lines = [f"- `{item.id}` | @{item.username or '-'} | {item.status.value}" for item in bots]
    await message.answer("بوتاتك:\n" + "\n".join(lines))


@router.message(Command("startbot"))
async def startbot_cmd(message: Message, bot_manager: BotManager) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 2:
        await message.answer("الاستخدام: `/startbot BOT_ID`")
        return
    try:
        bot_id = uuid.UUID(parts[1])
        await bot_manager.start_bot(bot_id)
        await message.answer(f"تم تشغيل `{bot_id}`.")
    except Exception as exc:
        await message.answer(f"فشل التشغيل: {exc}")


@router.message(Command("stopbot"))
async def stopbot_cmd(message: Message, bot_manager: BotManager) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 2:
        await message.answer("الاستخدام: `/stopbot BOT_ID`")
        return
    try:
        bot_id = uuid.UUID(parts[1])
        await bot_manager.stop_bot(bot_id)
        await message.answer(f"تم إيقاف `{bot_id}`.")
    except Exception as exc:
        await message.answer(f"فشل الإيقاف: {exc}")


@router.message(Command("restartbot"))
async def restartbot_cmd(message: Message, bot_manager: BotManager) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 2:
        await message.answer("الاستخدام: `/restartbot BOT_ID`")
        return
    try:
        bot_id = uuid.UUID(parts[1])
        await bot_manager.restart_bot(bot_id)
        await message.answer(f"تمت إعادة تشغيل `{bot_id}`.")
    except Exception as exc:
        await message.answer(f"فشل إعادة التشغيل: {exc}")


@router.message(Command("setplan"))
async def setplan_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 3:
        await message.answer("الاستخدام: `/setplan BOT_ID FREE|MONTHLY|SEMIANNUAL|YEARLY`")
        return
    try:
        bot_id = uuid.UUID(parts[1])
        plan = PlanType[parts[2].upper()]
    except Exception:
        await message.answer("صيغة الخطة غير صحيحة.")
        return
    async with session_scope() as session:
        await set_subscription_plan(session, bot_id, plan)
    await message.answer(f"تم تحديث الخطة إلى {plan.value}.")


@router.message(Command("stats"))
async def stats_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        stats = await get_platform_stats(session)
    await message.answer(
        "إحصائيات المنصة:\n"
        f"- إجمالي البوتات: {stats['total_bots']}\n"
        f"- البوتات العاملة: {stats['running_bots']}\n"
        f"- المستخدمون: {stats['users_total']}\n"
        f"- دفعات معلقة: {stats['pending_payments']}"
    )


@router.message(Command("banbot"))
async def banbot_cmd(message: Message, bot_manager: BotManager) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("الاستخدام: `/banbot BOT_ID reason`")
        return
    try:
        bot_id = uuid.UUID(parts[1])
    except ValueError:
        await message.answer("BOT_ID غير صالح.")
        return
    reason = parts[2] if len(parts) > 2 else None
    async with session_scope() as session:
        bot = await ban_bot(session, bot_id, reason=reason)
    if not bot:
        await message.answer("البوت غير موجود.")
        return
    await bot_manager.stop_bot(bot_id)
    await message.answer(f"تم حظر `{bot_id}`.")


@router.message(Command("unbanbot"))
async def unbanbot_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 2:
        await message.answer("الاستخدام: `/unbanbot BOT_ID`")
        return
    try:
        bot_id = uuid.UUID(parts[1])
    except ValueError:
        await message.answer("BOT_ID غير صالح.")
        return
    async with session_scope() as session:
        bot = await unban_bot(session, bot_id)
    if not bot:
        await message.answer("البوت غير موجود.")
        return
    await message.answer(f"تم إلغاء حظر `{bot_id}`.")


@router.message(Command("create_coupon"))
async def create_coupon_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 5:
        await message.answer("الاستخدام: `/create_coupon CODE PERCENT MAX_USES DAYS`")
        return
    try:
        percent = int(parts[2])
        max_uses = int(parts[3])
        days = int(parts[4])
    except ValueError:
        await message.answer("القيم الرقمية غير صحيحة.")
        return
    expires_at = utcnow() + timedelta(days=days) if days > 0 else None
    async with session_scope() as session:
        coupon = await create_coupon(
            session,
            code=parts[1],
            discount_percent=percent,
            max_uses=max_uses,
            expires_at=expires_at,
            created_by=message.from_user.id,
        )
    await message.answer(f"تم إنشاء كوبون `{coupon.code}` بخصم {coupon.discount_percent}%.")


@router.message(Command("approve_payment"))
async def approve_payment_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = _split(message.text or "")
    if len(parts) < 3:
        await message.answer("الاستخدام: `/approve_payment PAYMENT_ID PLAN`")
        return
    try:
        payment_id = uuid.UUID(parts[1])
        plan = PlanType[parts[2].upper()]
    except Exception:
        await message.answer("صيغة غير صحيحة.")
        return
    async with session_scope() as session:
        payment = await set_payment_status(
            session=session,
            payment_id=payment_id,
            status=PaymentStatus.APPROVED,
            reviewed_by=message.from_user.id,
        )
        if not payment:
            await message.answer("طلب الدفع غير موجود.")
            return
        await set_subscription_plan(session, payment.bot_id, plan)
    await message.answer(f"تمت الموافقة على `{payment_id}` وتفعيل خطة {plan.value}.")


@router.message(Command("reject_payment"))
async def reject_payment_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("الاستخدام: `/reject_payment PAYMENT_ID reason`")
        return
    try:
        payment_id = uuid.UUID(parts[1])
    except ValueError:
        await message.answer("PAYMENT_ID غير صالح.")
        return
    reason = parts[2]
    async with session_scope() as session:
        payment = await set_payment_status(
            session=session,
            payment_id=payment_id,
            status=PaymentStatus.REJECTED,
            reviewed_by=message.from_user.id,
            note=reason,
        )
    if not payment:
        await message.answer("طلب الدفع غير موجود.")
        return
    await message.answer(f"تم رفض `{payment_id}`.")


@router.message(Command("payments"))
async def payments_cmd(message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        result = await session.execute(
            select(PaymentRequest)
            .where(PaymentRequest.status == PaymentStatus.PENDING)
            .order_by(PaymentRequest.created_at.asc())
            .limit(20)
        )
        items = list(result.scalars().all())
    if not items:
        await message.answer("لا يوجد طلبات دفع معلقة.")
        return
    lines = [f"- `{p.id}` | bot `{p.bot_id}` | {p.amount} {p.currency} | by `{p.submitted_by}`" for p in items]
    await message.answer("طلبات الدفع المعلقة:\n" + "\n".join(lines))

