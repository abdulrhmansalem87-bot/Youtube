# WealthRadar Shorts

مسار مستقل لإنتاج YouTube Shorts لقناة WealthRadar. لا يغيّر هذا المسار NewsFlow القديم.

## مواصفات الإنتاج

- فيديو رأسي 9:16 بدقة 1080×1920 و30 FPS.
- مدة إجمالية من 30 إلى 45 ثانية.
- مشاهد فيديو B-roll من Pexels، بمشهد جديد كل 1.5–2.5 ثانية.
- تسجيل صوتي أصلي بصوت مقدم القناة؛ يمنع TTS أو استنساخ الصوت أو أي صوت آلي بديل.
- كلمتان أو ثلاث كلمات مفتاحية بارزة لكل مشهد.
- جمل صوتية لا تتجاوز 8 كلمات.
- عنوان لا يتجاوز 50 حرفاً ويتضمن #shorts.
- Loop phrase مشتركة بين أول جملة وآخر جملة.
- يمنع ظهور كلمات تحريرية مثل Draft أو NewsFlow أو AI-generated.

## ملف الإنتاج

انسخ ملف wealthradar/production.example.json إلى ملف JSON جديد، ثم اكتب:
- title: عنوان الفيديو.
- loop_phrase: العبارة المشتركة بين أول وآخر جملة.\n- voiceover_path: مسار تسجيلك الأصلي WAV أو MP3 أو M4A داخل المستودع (مثلاً assets/voice/wealthradar-short.wav).
- narration: جمل التعليق الصوتي القصيرة.
- scenes: مشاهد B-roll، ولكل مشهد مدة 1.5–2.5 ثانية، ووصف بحث إنجليزي، وكلمتان أو ثلاث للظهور على الشاشة.

إجمالي مدد المشاهد يجب أن يكون 30–45 ثانية، ويجب أن يطابق مدة الصوت بهامش ثانيتين.

## التشغيل المحلي

    pip install -r requirements.txt
    sudo apt-get install ffmpeg
    python -m wealthradar_shorts --plan wealthradar/production.example.json --validate-only
    PEXELS_API_KEY=YOUR_KEY python -m wealthradar_shorts --plan wealthradar/production.example.json

يلزم تسجيلك الصوتي الأصلي في المسار المحدد داخل الخطة، مع مفتاح Pexels API في GitHub Secret باسم PEXELS_API_KEY لتنزيل المقاطع. لا تضع المفتاح داخل ملفات المشروع أو Git. لا يستخدم مسار Shorts أي خدمة لتوليد الصوت أو استنساخه.

## GitHub Actions

من Actions اختر WealthRadar Shorts:
- validate_only=true: فحص الخطة فقط، ولا يحتاج إلى مفتاح API.
- validate_only=false: إنتاج الفيديو، ويتطلب GitHub Secret باسم PEXELS_API_KEY.

النظام الحالي لا يرفع إلى YouTube ولا ينشر تلقائياً. يرفع ملف MP4 كـ Artifact للمراجعة فقط. لم تُفعّل جدولة Unlisted/Public بعد؛ يجب اختبار جودة الفيديو وحقوق المقاطع أولاً، ثم تنفيذ مرحلة النشر المجدول بموافقة مالك القناة.

## حقوق الوسائط

تُسترجع مقاطع B-roll من Pexels API. راجع ترخيص كل مادة وسياسة المنصة قبل الاستخدام التجاري أو النشر. نجاح التنزيل لا يعني تلقائياً أن كل استخدام أو سياق تحريري مسموح.
