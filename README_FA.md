# دیجی‌اسکوپ

دیجی‌اسکوپ یک داشبورد فارسی و راست‌به‌چپ برای **ثبت و تحلیل رتبه‌های
مشاهده‌شده** و قیمت محصولات دیجی‌کالاست. برنامه با FastAPI، Pydantic،
SQLAlchemy 2، SQLite، جاوااسکریپت ساده و Chart.js اجرا می‌شود.

> رتبه در دیجی‌اسکوپ یعنی جایگاه کالا در یک فهرست مشخص، در زمان دریافت موفق؛
> نه تعداد فروش و نه تخمین فروش. رتبه فعلی هرگز به گذشته کپی نمی‌شود، اجرای
> ناموفق غیبت کالا محسوب نمی‌شود و تاریخچه ناقص، کامل نمایش داده نمی‌شود.

[English README](README.md) · [فهرست مستندات](docs/README.md) ·
[معماری](docs/architecture.md) · [مرجع REST API](docs/api.md) ·
[یکپارچگی داده](docs/data-integrity.md) · [راهنمای عملیات](docs/operations.md) ·
[امنیت](SECURITY.md)

## امکانات

- نمایش رتبه مشاهده‌شده فعلی برای کل بازار یا یک دسته؛
- گزارش‌های چرخان ۷ و ۳۰ روزه با میانگین، بهترین و آخرین رتبه؛
- محاسبه بهبود رتبه، نرخ حضور و شاخص شفاف روند رتبه؛
- تاریخچه مستقل قیمت و رتبه برای هر محصول؛
- نمایش پوشش تاریخی، اجرای موفق/ناموفق و قدیمی بودن داده؛
- خروجی CSV فارسی با BOM برای Excel؛
- جمع‌آوری دستی امن و فرمان مستقل مناسب cron؛
- دیتابیس SQLite با migration، قفل هر محدوده و ثبت خطاهای عملیاتی؛
- رابط واکنش‌گرا برای موبایل، تبلت و دسکتاپ؛
- داده نمایشی قطعی که فقط با فرمان صریح ساخته و در رابط علامت‌گذاری می‌شود.

## پیش‌نیاز

- Python 3.11 یا جدیدتر؛
- فضای خصوصی و قابل نوشتن برای SQLite، قفل‌ها و پشتیبان‌ها؛
- دسترسی HTTPS خروجی به MCP برای جمع‌آوری زنده؛
- cron یا زمان‌بند خارجی قابل اتکا برای ثبت منظم تاریخچه.

## نصب و اجرای توسعه

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

داشبورد در `http://127.0.0.1:8000` و مستندات تعاملی API در `/docs` در دسترس
است. مسیر `/ready` تا پیش از اجرای migration پاسخ 503 می‌دهد؛ برنامه در شروع،
ساختار production را بی‌صدا تغییر نمی‌دهد.

برای ساخت توکن قوی مدیریت:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

مقدار را فقط در `.env` با کلید `ADMIN_TOKEN` قرار دهید. در محیط production
حداقل ۲۴ نویسه الزامی است.

## داده نمایشی

فقط در `APP_ENV=development` یا `test`:

```bash
python -m scripts.seed_demo_data
python -m scripts.seed_demo_data --reset
```

شناسه‌های نمایشی با `demo-`، منبع snapshot با `demo:` و run با
`source_metadata.demo=true` ثبت می‌شوند. داشبورد وجود این داده را هشدار می‌دهد.
از این داده‌ها به‌عنوان وضعیت واقعی بازار استفاده نکنید.

## بررسی MCP

مخزن بالادستی `mmdju/digikala-mcp` در commit
`927ab481bb2d1292410b1b3858c691a844102c6d` بررسی شده است. گزارش دقیق در
[`docs/MCP_INTEGRATION_REPORT.md`](docs/MCP_INTEGRATION_REPORT.md) و snapshot
ابزارها در [`docs/tools.md`](docs/tools.md) قرار دارد.

روی میزبان واقعی اجرا کنید:

```bash
python -m scripts.check_mcp
python -m scripts.check_mcp --call-data
```

در محیط محدود ساخت، اتصال پیش از دریافت HTTP با `MCP network request failed`
ناموفق بود؛ بنابراین اتصال زنده این محیط تأیید نشده است. موفقیت workflow پروژه
بالادستی جای آزمون روی میزبان deployment را نمی‌گیرد.

## جمع‌آوری داده

همه محدوده‌های فعال:

```bash
python -m scripts.collect
python -m scripts.collect --limit 20
```

یک یا چند دسته شناخته‌شده:

```bash
python -m scripts.collect --category-id 2 --limit 20
python -m scripts.collect --category-id 2 --category-id 3 --no-global
```

ورود محدود تاریخچه کوتاه قیمت:

```bash
# ابتدا PRICE_HISTORY_PRODUCTS_PER_RUN را عددی محافظه‌کارانه مثل 3 قرار دهید.
python -m scripts.collect --limit 20 --with-price-history
```

مدیریت محدوده‌های زمان‌بندی‌شده:

```bash
python -m scripts.manage_scopes list
python -m scripts.manage_scopes add-category 2 --interval 1440
python -m scripts.manage_scopes set-enabled 2 false
```

دیجی‌اسکوپ همه دسته‌ها را خودکار و بازگشتی فعال نمی‌کند، چون حجم درخواست باید
پیش از استفاده از سرویس عمومی محدودشده اندازه‌گیری شود.

نمونه cron روزانه:

```cron
17 2 * * * cd /srv/digiscope && /srv/digiscope/.venv/bin/python -m scripts.collect >> /srv/digiscope/data/collection.log 2>&1
```

فقط یک میزبان زمان‌بند داشته باشید. قفل فایل، پردازه‌های یک filesystem را هماهنگ
می‌کند و قفل توزیع‌شده بین چند سرور نیست. `COLLECTION_INTERVAL_MINUTES` فقط
فرصت‌های مورد انتظار analytics را تعیین می‌کند؛ timer داخلی نیست و هر اجرای
collector همه scopeهای فعال انتخاب‌شده را اجرا می‌کند.

در نسخه `0.1.x`، گزینه `COLLECTION_ENABLED` فقط اعتبارسنجی توکن هنگام شروع
production را کنترل می‌کند و kill switch اجرایی نیست. برای حالت فقط‌خواندنی آن را
`false` کنید، `ADMIN_TOKEN` را حذف و cron را غیرفعال کنید.

## جمع‌آوری دستی API

برای عملیات استثنایی و فقط روی HTTPS:

```bash
curl --fail-with-body -X POST https://your-host.example/api/collection/run \
  -H 'Content-Type: application/json' \
  -H "X-Admin-Token: $ADMIN_TOKEN" \
  -d '{"include_global":true,"category_ids":[],"limit":10,"include_price_history":false}'
```

توکن را هرگز در URL، مرورگر، log یا source control قرار ندهید. endpoint دارای
کنترل burst و همان قفل محدوده cron است. برای کار روزمره cron ارجح است.

## تعریف محاسبات

```text
rank_improvement = earliest_rank - latest_rank
presence_rate = observed_successful_runs / eligible_successful_runs × 100
```

بهبود مثبت است، چون رتبه ۱ بهتر است. مخرج نرخ حضور فقط runهای موفق یا partial
قابل استفاده در همان محدوده و روش را شامل می‌شود؛ run ناموفق غیبت نیست.

شاخص روند رتبه:

```text
100 × (
  0.55 × normalized_rank_improvement
+ 0.25 × presence
+ 0.10 × observation_confidence
+ 0.10 × recency
)
```

این شاخص **رشد فروش نیست**. API اجزا و فرمول را برمی‌گرداند و برای ادعای بهبود
حداقل دو مشاهده معتبر لازم است. تعریف کامل پوشش و missing data در
[`docs/data-integrity.md`](docs/data-integrity.md) آمده است.

## محدودیت‌های اصلی داده

- MCP بررسی‌شده تاریخچه رتبه یا تعداد فروش ارائه نمی‌کند؛ تاریخچه رتبه از اولین
  جمع‌آوری دیجی‌اسکوپ شروع می‌شود.
- ابزار global `best_selling` حداکثر ۳۰ نتیجه و هیچ پارامتر page ندارد. درخواست
  ۵۰تایی با روش دیگری پر نمی‌شود و ناقص علامت می‌خورد.
- دسته‌ها با `browse_category` و pagination بررسی‌شده می‌توانند تا ۵۰ مشاهده
  جمع کنند.
- `product_price_chart` حدود ۳۰ نقطه روزانه مستقل برای هر رنگ/مدل می‌دهد و ممکن
  است برای بعضی محصولات خالی باشد.
- نقطه قیمت هرگز رکورد رتبه نمی‌سازد.
- مقدار اختیاری ناموجود `null` باقی می‌ماند؛ موجودی حدس زده نمی‌شود.

## APIهای مهم

| روش | مسیر | کاربرد |
|---|---|---|
| GET | `/health`, `/ready` | سلامت پردازه و آمادگی دیتابیس |
| GET | `/api/dashboard` | شاخص‌ها، رتبه فعلی، بهبود و پوشش |
| GET | `/api/categories` | دسته‌های شناخته‌شده و ساختار والد/فرزند |
| GET | `/api/products` | جست‌وجو، فیلتر و صفحه‌بندی |
| GET | `/api/products/{id}` | تاریخچه مستقل قیمت و رتبه |
| GET | `/api/rankings` | گزارش فعلی، ۷ روزه یا ۳۰ روزه |
| GET | `/api/market/trends` | بهبودهای دارای تاریخچه کافی |
| GET | `/api/collection/status` | runها، خطاها و محدوده‌ها |
| POST | `/api/collection/run` | جمع‌آوری دستی احراز‌شده |
| GET | `/api/export.csv` | CSV فارسی سازگار با Excel |

جزئیات پارامترها و خطاها در [`docs/api.md`](docs/api.md) است.

## آزمون

```bash
pytest -q
python -m compileall -q app scripts tests
node --check app/static/js/api.js
node --check app/static/js/charts.js
node --check app/static/js/app.js
```

baseline ثبت‌شده: **۵۸ آزمون موفق و صفر شکست**. suite عادی به سرویس زنده وابسته
نیست. ماتریس کامل در [`docs/testing.md`](docs/testing.md) است.

## پشتیبان‌گیری و بازیابی

```bash
python -m scripts.backup_db ./data/backups
```

فرمان از online backup API خود SQLite استفاده، integrity check اجرا و فایل را با
mode `0600` می‌سازد. پیش از migration پشتیبان بگیرید.

برای بازیابی:

1. وب و collector را متوقف کنید؛
2. از فایل فعلی و WAL/SHM کپی جدا بگیرید؛
3. پشتیبان را روی مسیر دقیق `DATABASE_URL` قرار دهید؛
4. فقط در حالت توقف کامل، WAL/SHM قدیمی را حذف کنید؛
5. `alembic current`، `alembic upgrade head` و `/ready` را بررسی کنید؛
6. پس از صحت read path، cron را فعال کنید.

راهنمای کامل در [`docs/operations.md`](docs/operations.md) است.

## استقرار

هدف پیشنهادی یک VPS کوچک، یک Uvicorn worker، reverse proxy دارای TLS، SQLite
خصوصی و cron محلی است. برای cPanel ابتدا Python 3.11، ASGI، HTTPS خروجی، فضای
خصوصی پایدار، cron و تعداد workerها را بررسی کنید. اگر فقط WSGI، فایل موقت یا
بدون cron/شبکه خروجی ارائه می‌شود، از VPS استفاده کنید.

این repository ادعا نمی‌کند که برنامه روی میزبان عمومی deploy شده است. چک‌لیست
کامل در [`docs/deployment.md`](docs/deployment.md) است.

## امنیت و مجوز

دیتابیس، `.env`، log، قفل و backup باید بیرون web root باشند. برنامه اطلاعات
مشتری، سفارش یا آدرس جمع نمی‌کند. سیاست گزارش آسیب‌پذیری و threat model در
[`SECURITY.md`](SECURITY.md) است.

فایل `LICENSE` از مخزن نمایشی MCP به ارث رسیده و مجوز روشنی برای source جدید
دیجی‌اسکوپ اعلام نمی‌کند. تا زمانی که مالک repository مجوز صریح اضافه نکرده،
حقوقی فراتر از متن موجود فرض نکنید. noticeهای Chart.js و Vazirmatn بدون تغییر
کنار assetها نگهداری می‌شوند.

دیجی‌اسکوپ مستقل از دیجی‌کالا و مورد تأیید آن نیست. قیمت، موجودی و رتبه ممکن است
بعد از آخرین مشاهده تغییر کنند.
