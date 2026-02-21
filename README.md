# منصة Telegram Bot Maker متعددة المستأجرين (Python + Railway)

منصة جاهزة للإنتاج لبناء وإدارة عدة بوتات تيليجرام من مشروع واحد:
- `Master Bot` لإدارة المنصة.
- `Client Bots` متعددة (كل عميل بتوكن مختلف من BotFather).
- Webhooks عبر `FastAPI`.
- PostgreSQL + Redis + Celery + Alembic.

## المزايا الأساسية

### Master Bot
- إنشاء بوت عميل من التوكن (مع تحقق `getMe`).
- تشغيل/إيقاف/إعادة تشغيل البوتات ديناميكياً من قاعدة البيانات.
- خطط اشتراك: `FREE / MONTHLY / SEMIANNUAL / YEARLY`.
- Branding تلقائي:
  - FREE: يظهر `Powered by @PlatformBot`.
  - المدفوع: بدون Branding.
- كوبونات، موافقات دفع يدوية، وإحصائيات المنصة.
- نظام حظر للبوتات.

### Client Bot
- أدوار: `OWNER / ADMIN / MOD / USER`.
- اشتراك إجباري بالقنوات + زر Verify.
- حماية مجموعات: anti-link / anti-spam / forbidden words مع تسلسل `warn -> mute -> kick`.
- Broadcast:
  - `ALL / ACTIVE_24H / ACTIVE_7D / VIP_ONLY`
  - دعم الجدولة + تقرير إرسال.
- إدارة إعلانات كل X تفاعل.
- Backup/Restore بصيغة JSON.
- تطبيق Templates جاهزة.

## هيكل المشروع

```text
app/
  api/
  bot_manager/
  client_bot/
  core/
  db/
  master_bot/
  services/
  tasks/
alembic/
```

## التشغيل المحلي

1) إنشاء ملف `.env` من `.env.example`.

2) توليد مفتاح تشفير التوكنات (Fernet):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

3) تثبيت المتطلبات:

```bash
pip install -r requirements.txt
```

4) تنفيذ المايغريشن:

```bash
alembic upgrade head
```

5) تشغيل خدمات المنصة:

```bash
uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
celery -A app.tasks.celery_app.celery_app worker -l info
celery -A app.tasks.celery_app.celery_app beat -l info
```

## متطلبات Railway (منفذة)

1. التطبيق يستمع على `0.0.0.0` وبورت `PORT`.
2. نقطة `GET /health` ترجع `200 OK`.
3. Start command للويب:
   - `uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}`
4. ملفات النشر متوفرة:
   - `Dockerfile`
   - `Procfile`
   - `requirements.txt`
   - `.env.example`
5. كل الأسرار عبر Environment Variables (لا توجد أسرار hardcoded).

## نشر Railway (خطوة بخطوة)

1. ارفع المشروع على GitHub.
2. في Railway:
   - أنشئ مشروع جديد من GitHub Repo.
3. أضف خدمات Managed:
   - PostgreSQL
   - Redis
4. أنشئ 3 Services من نفس الريبو:
   - `web`
   - `worker`
   - `beat`
5. إعداد أوامر التشغيل:
   - Web:
     - `uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT}`
   - Worker:
     - `celery -A app.tasks.celery_app.celery_app worker -l info --concurrency=2`
   - Beat:
     - `celery -A app.tasks.celery_app.celery_app beat -l info`
6. أضف المتغيرات البيئية لكل Service:
   - `DATABASE_URL`
   - `REDIS_URL`
   - `CELERY_BROKER_URL`
   - `CELERY_RESULT_BACKEND`
   - `MASTER_BOT_TOKEN`
   - `MASTER_BOT_WEBHOOK_SECRET`
   - `BOT_TOKEN_ENCRYPTION_KEY`
   - `MASTER_ADMIN_IDS`
   - `WEBHOOK_BASE_URL` = رابط Railway Public Domain الخاص بخدمة web.
7. نفّذ migration مرة واحدة:
   - `alembic upgrade head`
8. اختبر:
   - `GET /health` يجب أن يرجع `{"status":"ok"}`.

## أوامر مهمة

### أوامر Master Bot
- `/newbot TOKEN`
- `/mybots`
- `/startbot BOT_ID`
- `/stopbot BOT_ID`
- `/restartbot BOT_ID`
- `/setplan BOT_ID FREE|MONTHLY|SEMIANNUAL|YEARLY`
- `/stats`
- `/create_coupon CODE PERCENT MAX_USES DAYS`
- `/approve_payment PAYMENT_ID PLAN`
- `/reject_payment PAYMENT_ID reason`

### أوامر Client Bot
- `/start`
- `/panel`
- `/add_channel CHANNEL_ID [@username]`
- `/remove_channel CHANNEL_ID`
- `/set_guard key value`
- `/broadcast SEGMENT الرسالة`
- `/broadcast_schedule ISO_DATETIME SEGMENT الرسالة`
- `/backup_settings`
- `/restore_settings {json}`
- `/apply_template BASIC|COMMUNITY|STORE`
- `/set_ad_frequency NUMBER`
- `/add_ad نص الإعلان`
- `/payment_request amount currency [receipt_url] [note]`

