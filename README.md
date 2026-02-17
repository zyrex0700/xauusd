# XAUUSD M5 MetaTrader5 Trading Bot (Python)

این پروژه یک ربات ترید **M5 برای XAUUSD** است که به متاتریدر 5 وصل می‌شود و بر اساس چارچوبی که گفتید عمل می‌کند:

- تشخیص رژیم بازار با `ADX` و `Bollinger BandWidth`
- انتخاب پویا بین چند خانواده استراتژی (trend pullback, momentum, breakout, mean reversion)
- مدیریت ریسک درصدی ثابت به‌همراه حد ضرر روزانه
- اجرای سفارش با API رسمی `MetaTrader5`

> ⚠️ این ربات «سود تضمینی» ندارد. دقت بالا فقط با داده/اجرای مناسب، بک‌تست واقعی، فوروارد تست و کنترل ریسک ممکن می‌شود.

## 1) نصب

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) تنظیمات

یک فایل `.env` بسازید:

```env
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=YourBroker-Server
MT5_PATH=/path/to/terminal64.exe
SYMBOL=XAUUSD
TIMEFRAME=M5
RISK_PER_TRADE=0.005
DAILY_MAX_LOSS_R=3
MAX_POSITIONS=1
DRY_RUN=true
MAGIC=550051
POLL_SECONDS=5
SLIPPAGE_POINTS=30
```

## 3) اجرا

```bash
python bot.py
```

## 4) نکات مهم

- قبل از حساب واقعی، روی دمو اجرا کنید.
- مشخصات قرارداد (contract size, tick value, volume step) را از همان بروکر بگیرید.
- در زمان اخبار شدید ممکن است اسلیپیج زیاد شود.
- اگر `DRY_RUN=true` باشد، سفارش واقعی ارسال نمی‌شود و فقط لاگ سیگنال می‌بینید.
