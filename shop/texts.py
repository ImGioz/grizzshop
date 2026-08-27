"""Two-language copy. Every user-visible string lives here, keyed by language code."""

LANGUAGES = ("uk", "ru")
DEFAULT_LANGUAGE = "uk"

TEXTS = {
    "uk": {
        "choose_language": "Оберіть мову / Выберите язык",
        "language_set": "Готово, мову збережено ✅",

        "subscribe_required": "Щоб користуватися ботом, підпишіться на канал 👇",
        "subscribe_button": "📢 Відкрити канал",
        "check_subscription": "✅ Я підписався",
        "not_subscribed": "Підписки поки не видно. Підпишіться на канал і натисніть кнопку ще раз.",
        "subscription_ok": "Підписку зараховано, дякуємо! Бот у вашому розпорядженні 🎉",
        "subscription_check_failed": "Не вдалося перевірити підписку. Спробуйте за хвилину або напишіть у підтримку.",

        "menu_stars": "⭐ Купити зірки",
        "menu_premium": "💎 Купити Premium",
        "menu_gram": "💠 Купити Gram",
        "menu_more": "➕ Ще",
        "menu_profile": "👤 Мій профіль",
        "menu_calculator": "🧮 Калькулятор",
        "main_menu": "Головне меню",
        "menu_main": "🏠 Головне меню",

        "more_choose": "Оберіть розділ 👇",
        "menu_reviews": "⭐ Відгуки",
        "menu_support": "🆘 Підтримка",
        "menu_projects": "🧩 Інші проєкти",
        "menu_developer": "👨‍💻 Розробник бота",
        "support_ask": "Опишіть проблему одним повідомленням — воно одразу піде адміністраторам.\n\n"
                       "Відповідь надійде сюди, у цей чат.",
        "support_text_only": "Надішліть звернення текстом — інші формати не передаються.",
        "support_sent": "Звернення прийнято ✅\n\nВідповідь надійде в цей чат.",
        "support_failed": "Звернення не пішло. Спробуйте, будь ласка, трохи пізніше.",
        "support_answer": "💬 <b>Підтримка відповідає</b>\n\n{text}",
        "other_projects": "🧩 <b>Інші проєкти</b>\n\n"
                          "Оберіть категорію 👇\n\n",
        "projects_category": "{title}\n\n",
        "projects_back": "⬅️ До категорій",

        "product_nft": "NFT: {details}",

        "stars_for_whom": "Кому надсилаємо зірки?",
        "premium_for_whom": "Кому оформлюємо Telegram Premium?",
        "premium_already": "❌ У <b>@{recipient}</b> Premium уже активний.\n\n"
                            "Подарувати підписку поверх наявної не вийде — "
                            "дочекайтеся, поки поточна завершиться.\n\n"
                            "Вкажіть іншого отримувача або оберіть інший товар.",
        "premium_recipient_not_user": "❌ <b>@{recipient}</b> — це канал або бот, а не людина.\n\n"
                            "Premium оформлюється лише на акаунт користувача. "
                            "Надішліть інший username.",
        "premium_recipient_unknown": "❌ Акаунт <b>@{recipient}</b> не знайдено.\n\n"
                            "Перевірте написання username і спробуйте ще раз.",
        "gram_ask_wallet": "Надішліть адресу гаманця <b>в мережі TON</b> — на неї підуть монети.\n\nВиглядає так: <code>UQ...</code> або <code>EQ...</code>",
        "gram_bad_wallet": "На адресу TON це не схоже. Перевірте і надішліть ще раз.",
        "gram_ask_amount": "Гаманець: <code>{wallet}</code>\n\nСкільки TON берете? Надішліть число, мінімум {min_ton}.\nКурс: {rate} грн за 1 TON.",
        "gram_bad_amount": "Потрібне число від {min_ton}. Спробуйте ще раз.",
        "product_gram": "{amount} TON",
        "delivery_ok_gram": "Готово! <b>{amount} TON</b> пішли на\n<code>{wallet}</code>\nМонети з'являться після підтвердження транзакції.",
        "choose_months": "На який термін оформлюємо?",
        "months_label": "{months} міс. — {price} грн",
        "product_stars": "{quantity} зірок",
        "product_premium": "Telegram Premium, {quantity} міс.",
        "for_myself": "Собі",
        "for_friend": "Другу",
        "no_username": "У вашому Telegram не заданий username. Додайте його в налаштуваннях "
                       "(Settings → Username) і поверніться сюди.",
        "ask_friend_username": "Надішліть @username того, кому призначений подарунок.",
        "bad_username": "Це не схоже на username. Формат: @nickname — 5–32 символи, літери, цифри та _.",

        "choose_quantity": "Скільки зірок беремо?",
        "custom_quantity": "Своя кількість",
        "ask_custom_quantity": "Надішліть кількість зірок числом, мінімум {min_stars}.",
        "bad_quantity": "Потрібне ціле число від {min_stars}. Спробуйте ще раз.",

        "order_created": "<b>Замовлення оформлено</b>\n"
                         "Отримувач: {recipient}\n"
                         "Товар: {product}\n"
                         "До сплати: {price} грн\n"
                         "Спосіб оплати: —",
        "pay_transfer": "💳 Переказ",
        "pay_crypto": "🪙 Криптовалюта",
        "crypto_details": "<b>Оплата в TON</b>\n\n"
                          "Гаманець:\n<code>{wallet}</code>\n\n"
                          "Сума: <b>{amount} TON</b>\n"
                          "Курс: {rate} грн за TON\n"
                          "Коментар до переказу: <code>{comment}</code>\n\n"
                          "⚠️ <b>Коментар обов'язковий</b> — без нього платіж не знайдеться.\n"
                          "Товар: {product}\n"
                          "Час на оплату: {timeout} хв.",
        "crypto_checking": "Дивлюся блокчейн...",
        "crypto_not_found": "Платежу поки не видно. Якщо переказ щойно пішов — зачекайте хвилину "
                            "і натисніть ще раз. Перевірте коментар <code>{comment}</code>.",
        "crypto_check": "🔍 Перевірити оплату",

        "payment_details": "<b>Оплата переказом на картку</b>\n\n"
                           "Картка: <code>{card}</code>\n"
                           "Отримувач: {holder}\n"
                           "Сума: <b>{price} грн</b>\n"
                           "Товар: {product}\n"
                           "ID замовлення: <code>{order_id}</code>\n\n"
                           "Після оплати натисніть <b>Перевірити</b> і далі за підказками бота.\n"
                           "Час на оплату: {timeout} хв.",
        "check_payment": "🔍 Перевірити",
        "cancel_order": "✖️ Скасувати замовлення",
        "order_cancelled": "Замовлення #{order_id} скасовано. Гроші не списувались.",
        "ask_sender_name": "Надішліть ПІБ відправника платежу — точно як у квитанції.",
        "ask_receipt_link": "Тепер надішліть посилання на квитанцію Monobank.",
        "bad_receipt_link": "На посилання check.monobank.ua/p/... це не схоже. Спробуйте ще раз.",
        "checking_receipt": "Звіряю квитанцію, кілька секунд...",
        "ask_receipt_any": "Надішліть підтвердження оплати в будь-якому з форматів:\n\n"
                           "• посилання на квитанцію Monobank (check.monobank.ua/p/...)\n"
                           "• PDF-квитанція вашого банку",
        "pdf_no_text": "У цьому PDF немає тексту — схоже, це скан або знімок екрана. "
                       "Потрібен PDF, збережений із застосунку банку.",
        "pdf_too_big": "Файл завеликий, максимум {limit} МБ.",
        "pdf_error": "PDF не читається: {error}",
        "order_on_review": "Оплату знайдено ✅\n\nЗамовлення пішло на підтвердження адміністратору: "
                           "суми понад {limit} грн перевіряються вручну. Зазвичай це кілька хвилин.",
        "order_rejected": "Замовлення #{order_id} відхилив адміністратор. "
                          "Якщо це помилка — напишіть у підтримку.",

        "verify_failed_name": "ПІБ у квитанції не збігається з тим, що ви вказали.",
        "verify_failed_card": "Картка отримувача у квитанції не наша.",
        "verify_failed_amount": "Сума у квитанції — {actual} грн, а замовлення на {expected} грн.",
        "verify_failed_time": "Платіж не потрапляє у час замовлення (допуск {tolerance} хв).",
        "verify_failed_incomplete": "З квитанції зчиталися не всі дані. Перевірте посилання.",
        "verify_failed_status": "Платіж ще не завершено (статус: {status}). Дочекайтеся зарахування.",
        "verify_failed_currency": "Платіж пройшов не в гривні (код валюти {currency}).",
        "receipt_already_used": "Цю квитанцію вже зараховано іншому замовленню.",
        "receipt_error": "Квитанція не читається: {error}",
        "verify_retry": "🔁 Спробувати ще раз",

        "payment_ok": "Оплату підтверджено ✅\nНадсилаю зірки...",
        "payment_ok_premium": "Оплату підтверджено ✅\nОформлюю Premium...",
        "payment_ok_gram": "Оплату підтверджено ✅\nНадсилаю TON на гаманець...",
        "delivery_ok": "Готово! <b>{quantity}</b> ⭐ пішли до <b>{recipient}</b>.\n"
                       "Зірки з'являться після підтвердження транзакції — зазвичай менш ніж за хвилину.",
        "delivery_failed": "Оплату зараховано, але автоматична видача не спрацювала. "
                           "Адміністратор видасть вручну найближчим часом.",

        "review_required": "⭐️ <b>Лишився один крок</b>\n\n"
                           "Оцініть попереднє замовлення — і йдемо далі. "
                           "Коментар та фото за бажанням.",
        "review_ask_rating": "Як усе пройшло? Поставте оцінку 👇",
        "review_ask_comment": "Дякуємо! Напишіть кілька слів про замовлення — "
                              "відгук потрапить у канал.",
        "review_ask_photo": "І останнє: додайте скриншот отриманого (зірки або Premium).",
        "review_skip": "Пропустити",
        "review_need_photo": "Потрібне саме фото. Надішліть скриншот або натисніть «Пропустити».",
        "review_thanks": "<b>Дякуємо за відгук! 💚</b>",
        "review_not_published": "Дякуємо за відгук! 💚",
        "order_expired": "Час замовлення вийшов. Оформте нове.",
        "no_active_order": "Активного замовлення немає.",
        "cancelled": "Скасовано.",

        "menu_referral": "🤝 Реферальна програма",
        "referral_screen": "<b>🤝 Реферальна програма</b>\n\n"
                           "За кожні <b>{per_reward}</b> запрошених із замовленням "
                           "ви отримуєте <b>{stars_per_reward} ⭐</b>.\n\n"
                           "Ваше посилання:\n<code>{link}</code>\n\n"
                           "Запрошено: <b>{invited}</b>\n"
                           "Зробили замовлення: <b>{qualified}</b>\n"
                           "До наступних {stars_per_reward} ⭐: <b>{to_next}</b>\n\n"
                           "Нараховано: <b>{earned} ⭐</b>\n"
                           "Отримано: <b>{paid} ⭐</b>\n"
                           "Доступно зараз: <b>{available} ⭐</b>",
        "referral_joined_notice": "🤝 <b>Новий реферал</b>\n\n"
                           "За вашим посиланням прийшов <b>{who}</b>.\n"
                           "Зарахуємо його, щойно він зробить замовлення.",
        "referral_purchase": "🛒 <b>Ваш реферал купив</b>\n\n"
                           "<b>{who}</b> оформив: {product}\n\n"
                           "Зараховано запрошених: <b>{qualified}</b>\n"
                           "До наступних {stars} ⭐: <b>{to_next}</b>",
        "referral_copy": "📋 Скопіювати посилання",
        "referral_share": "📤 Поділитися",
        "referral_share_text": "Беру тут зірки, Premium і TON — заходь за моїм посиланням: {link}",
        "referral_claim": "🎁 Забрати {available} ⭐",
        "referral_nothing": "Забирати поки нічого. Запросіть ще друзів 🙂",
        "referral_no_username": "Щоб отримати зірки, задайте username у налаштуваннях Telegram — "
                                "інакше їх нікуди надіслати.",
        "referral_sending": "Надсилаю {stars} ⭐...",
        "referral_claimed": "Готово! <b>{stars} ⭐</b> уже на вашому акаунті 🎉",
        "referral_claim_failed": "Зірки не пішли: {error}\nМенеджер уже в курсі, нарахування не згоріло.",
        "referral_reward": "🎉 <b>Вітаємо!</b>\n\n"
                           "Ваших запрошених із замовленнями вже <b>{qualified}</b>, "
                           "тому вам нараховано <b>{stars} ⭐</b>.\n\n"
                           "Забрати можна в профілі → Реферальна програма.",
        "referral_joined": "Ви прийшли за запрошенням 🤝",
        "profile": "<b>Ваш профіль</b>\n"
                   "ID: <code>{user_id}</code>\n"
                   "Username: {username}\n"
                   "Мова: {language}\n"
                   "Оплачених замовлень: {paid_orders}\n"
                   "Куплено зірок: {total_stars}\n\n"
                   "👨‍💻 Розробник бота: @{developer}",
        "premium_soon": "Розділ Premium ще готується. Стежте за новинами в каналі.",
        "delivery_ok_premium": "Готово! <b>Telegram Premium на {quantity} міс.</b> оформлено для <b>{recipient}</b>.\nПідписка активується після підтвердження транзакції.",
        "gram_soon": "Купівля Gram ще готується. Стежте за новинами в каналі.",
        "calc_choose": "🧮 <b>Калькулятор</b>\n\nЩо рахуємо?",
        "calc_pick_stars": "⭐ Зірки",
        "calc_pick_ton": "💠 TON",
        "calc_stars_title": "⭐ <b>Калькулятор зірок</b>\n\nЩо рахуємо?",
        "calc_ton_title": "💠 <b>Калькулятор TON</b>\n\nЩо рахуємо?",
        "calc_back": "⬅️ Назад",
        "calc_to_uah": "⭐ → ₴  зірки в гривні",
        "calc_to_stars": "₴ → ⭐  гривні в зірки",
        "calc_ask_stars": "Надішліть кількість зірок числом.",
        "calc_ask_uah": "Надішліть суму в гривнях.",
        "calc_bad_number": "Потрібне додатне число. Спробуйте ще раз.",
        "calc_result_to_uah": "🧮 <b>{quantity} ⭐ = {price} грн</b>\n\nВиходить {rate} грн за зірку.",
        "calc_result_to_stars": "🧮 <b>{amount} грн = {quantity} ⭐</b>\n\n"
                                "Рівно {quantity} зірок коштують {price} грн.\nВиходить {rate} грн за зірку.",
        "calc_min_note": "\n\n⚠️ Мінімальне замовлення — {min_stars} ⭐.",
        "calc_ton_to_uah": "💠 → ₴  TON у гривні",
        "calc_to_ton": "₴ → 💠  гривні в TON",
        "calc_ask_ton": "Надішліть кількість TON числом.",
        "calc_result_ton_to_uah": "🧮 <b>{amount} 💠 = {price} грн</b>\n\nЗа курсом {rate} грн за 1 TON.",
        "calc_result_to_ton": "🧮 <b>{amount} грн = {quantity} 💠</b>\n\nЗа курсом {rate} грн за 1 TON.",
        "calc_min_note_ton": "\n\n⚠️ Мінімальне замовлення — {min_ton} TON.",
        "calc_again": "🔄 Порахувати ще",
        "calculator_soon": "Калькулятор ще готується.",
    },
    "ru": {
        "choose_language": "Оберіть мову / Выберите язык",
        "language_set": "Готово, язык сохранён ✅",

        "subscribe_required": "Чтобы пользоваться ботом, подпишитесь на канал 👇",
        "subscribe_button": "📢 Открыть канал",
        "check_subscription": "✅ Я подписался",
        "not_subscribed": "Подписки пока не видно. Подпишитесь на канал и нажмите кнопку ещё раз.",
        "subscription_ok": "Подписка засчитана, спасибо! Бот в вашем распоряжении 🎉",
        "subscription_check_failed": "Не удалось проверить подписку. Попробуйте через минуту или напишите в поддержку.",

        "menu_stars": "⭐ Купить звёзды",
        "menu_premium": "💎 Купить Premium",
        "menu_gram": "💠 Купить Gram",
        "menu_more": "➕ Ещё",
        "menu_profile": "👤 Мой профиль",
        "menu_calculator": "🧮 Калькулятор",
        "main_menu": "Главное меню",
        "menu_main": "🏠 Главное меню",

        "more_choose": "Выберите раздел 👇",
        "menu_reviews": "⭐ Отзывы",
        "menu_support": "🆘 Поддержка",
        "menu_projects": "🧩 Другие проекты",
        "menu_developer": "👨‍💻 Разработчик бота",
        "support_ask": "Опишите проблему одним сообщением — оно сразу уйдёт администраторам.\n\n"
                       "Ответ придёт сюда, в этот чат.",
        "support_text_only": "Пришлите обращение текстом — другие форматы не передаются.",
        "support_sent": "Обращение принято ✅\n\nОтвет придёт в этот чат.",
        "support_failed": "Обращение не ушло. Попробуйте, пожалуйста, чуть позже.",
        "support_answer": "💬 <b>Поддержка отвечает</b>\n\n{text}",
        "other_projects": "🧩 <b>Другие проекты</b>\n\n"
                          "Выберите категорию 👇\n\n",
        "projects_category": "{title}\n\n",
        "projects_back": "⬅️ К категориям",

        "product_nft": "NFT: {details}",

        "stars_for_whom": "Кому отправляем звёзды?",
        "premium_for_whom": "Кому оформляем Telegram Premium?",
        "premium_already": "❌ У <b>@{recipient}</b> Premium уже активен.\n\n"
                            "Подарить подписку поверх имеющейся не выйдет — "
                            "дождитесь, пока текущая закончится.\n\n"
                            "Укажите другого получателя или выберите другой товар.",
        "premium_recipient_not_user": "❌ <b>@{recipient}</b> — это канал или бот, а не человек.\n\n"
                            "Premium оформляется только на аккаунт пользователя. "
                            "Пришлите другой username.",
        "premium_recipient_unknown": "❌ Аккаунт <b>@{recipient}</b> не найден.\n\n"
                            "Проверьте написание username и попробуйте ещё раз.",
        "gram_ask_wallet": "Пришлите адрес кошелька <b>в сети TON</b> — на него уйдут монеты.\n\nВыглядит так: <code>UQ...</code> или <code>EQ...</code>",
        "gram_bad_wallet": "На адрес TON это не похоже. Проверьте и пришлите ещё раз.",
        "gram_ask_amount": "Кошелёк: <code>{wallet}</code>\n\nСколько TON берёте? Пришлите число, минимум {min_ton}.\nКурс: {rate} грн за 1 TON.",
        "gram_bad_amount": "Нужно число от {min_ton}. Попробуйте ещё раз.",
        "product_gram": "{amount} TON",
        "delivery_ok_gram": "Готово! <b>{amount} TON</b> ушли на\n<code>{wallet}</code>\nМонеты появятся после подтверждения транзакции.",
        "choose_months": "На какой срок оформляем?",
        "months_label": "{months} мес. — {price} грн",
        "product_stars": "{quantity} звёзд",
        "product_premium": "Telegram Premium, {quantity} мес.",
        "for_myself": "Себе",
        "for_friend": "Другу",
        "no_username": "В вашем Telegram не задан username. Добавьте его в настройках "
                       "(Settings → Username) и вернитесь сюда.",
        "ask_friend_username": "Пришлите @username того, кому предназначен подарок.",
        "bad_username": "Это не похоже на username. Формат: @nickname — 5–32 символа, буквы, цифры и _.",

        "choose_quantity": "Сколько звёзд берём?",
        "custom_quantity": "Своё количество",
        "ask_custom_quantity": "Пришлите количество звёзд числом, минимум {min_stars}.",
        "bad_quantity": "Нужно целое число от {min_stars}. Попробуйте ещё раз.",

        "order_created": "<b>Заказ оформлен</b>\n"
                         "Получатель: {recipient}\n"
                         "Товар: {product}\n"
                         "К оплате: {price} грн\n"
                         "Способ оплаты: —",
        "pay_transfer": "💳 Перевод",
        "pay_crypto": "🪙 Криптовалюта",
        "crypto_details": "<b>Оплата в TON</b>\n\n"
                          "Кошелёк:\n<code>{wallet}</code>\n\n"
                          "Сумма: <b>{amount} TON</b>\n"
                          "Курс: {rate} грн за TON\n"
                          "Комментарий к переводу: <code>{comment}</code>\n\n"
                          "⚠️ <b>Комментарий обязателен</b> — без него платёж не найдётся.\n"
                          "Товар: {product}\n"
                          "Время на оплату: {timeout} мин.",
        "crypto_checking": "Смотрю блокчейн...",
        "crypto_not_found": "Платежа пока не видно. Если перевод только что ушёл — подождите минуту "
                            "и нажмите ещё раз. Проверьте комментарий <code>{comment}</code>.",
        "crypto_check": "🔍 Проверить оплату",

        "payment_details": "<b>Оплата переводом на карту</b>\n\n"
                           "Карта: <code>{card}</code>\n"
                           "Получатель: {holder}\n"
                           "Сумма: <b>{price} грн</b>\n"
                           "Товар: {product}\n"
                           "ID заказа: <code>{order_id}</code>\n\n"
                           "После оплаты нажмите <b>Проверить</b> и дальше по подсказкам бота.\n"
                           "Время на оплату: {timeout} мин.",
        "check_payment": "🔍 Проверить",
        "cancel_order": "✖️ Отменить заказ",
        "order_cancelled": "Заказ #{order_id} отменён. Деньги не списывались.",
        "ask_sender_name": "Пришлите ФИО отправителя платежа — точно как в квитанции.",
        "ask_receipt_link": "Теперь пришлите ссылку на квитанцию Monobank.",
        "bad_receipt_link": "На ссылку check.monobank.ua/p/... это не похоже. Попробуйте ещё раз.",
        "checking_receipt": "Сверяю квитанцию, несколько секунд...",
        "ask_receipt_any": "Пришлите подтверждение оплаты в любом из форматов:\n\n"
                           "• ссылка на квитанцию Monobank (check.monobank.ua/p/...)\n"
                           "• PDF-квитанция вашего банка",
        "pdf_no_text": "В этом PDF нет текста — похоже, это скан или снимок экрана. "
                       "Нужен PDF, сохранённый из приложения банка.",
        "pdf_too_big": "Файл слишком большой, максимум {limit} МБ.",
        "pdf_error": "PDF не читается: {error}",
        "order_on_review": "Оплата найдена ✅\n\nЗаказ ушёл на подтверждение администратору: "
                           "суммы свыше {limit} грн проверяются вручную. Обычно это несколько минут.",
        "order_rejected": "Заказ #{order_id} отклонил администратор. "
                          "Если это ошибка — напишите в поддержку.",

        "verify_failed_name": "ФИО в квитанции не совпадает с тем, что вы указали.",
        "verify_failed_card": "Карта получателя в квитанции не наша.",
        "verify_failed_amount": "Сумма в квитанции — {actual} грн, а заказ на {expected} грн.",
        "verify_failed_time": "Платёж не попадает во время заказа (допуск {tolerance} мин).",
        "verify_failed_incomplete": "Из квитанции считались не все данные. Проверьте ссылку.",
        "verify_failed_status": "Платёж ещё не завершён (статус: {status}). Дождитесь зачисления.",
        "verify_failed_currency": "Платёж прошёл не в гривне (код валюты {currency}).",
        "receipt_already_used": "Эта квитанция уже засчитана другому заказу.",
        "receipt_error": "Квитанция не читается: {error}",
        "verify_retry": "🔁 Попробовать ещё раз",

        "payment_ok": "Оплата подтверждена ✅\nОтправляю звёзды...",
        "payment_ok_premium": "Оплата подтверждена ✅\nОформляю Premium...",
        "payment_ok_gram": "Оплата подтверждена ✅\nОтправляю TON на кошелёк...",
        "delivery_ok": "Готово! <b>{quantity}</b> ⭐ ушли к <b>{recipient}</b>.\n"
                       "Звёзды появятся после подтверждения транзакции — обычно меньше чем за минуту.",
        "delivery_failed": "Оплата зачислена, но автоматическая выдача не сработала. "
                           "Администратор выдаст вручную в ближайшее время.",

        "review_required": "⭐️ <b>Остался один шаг</b>\n\n"
                           "Оцените предыдущий заказ — и идём дальше. "
                           "Комментарий и фото по желанию.",
        "review_ask_rating": "Как всё прошло? Поставьте оценку 👇",
        "review_ask_comment": "Спасибо! Напишите пару слов о заказе — "
                              "отзыв попадёт в канал.",
        "review_ask_photo": "И последнее: добавьте скриншот полученного (звёзды или Premium).",
        "review_skip": "Пропустить",
        "review_need_photo": "Нужно именно фото. Пришлите скриншот или нажмите «Пропустить».",
        "review_thanks": "Спасибо за отзыв! 💚 Он уже в канале отзывов.",
        "review_not_published": "Спасибо за отзыв! 💚",
        "order_expired": "Время заказа вышло. Оформите новый.",
        "no_active_order": "Активного заказа нет.",
        "cancelled": "Отменено.",

        "menu_referral": "🤝 Реферальная программа",
        "referral_screen": "<b>🤝 Реферальная программа</b>\n\n"
                           "За каждые <b>{per_reward}</b> приглашённых с заказом "
                           "вы получаете <b>{stars_per_reward} ⭐</b>.\n\n"
                           "Ваша ссылка:\n<code>{link}</code>\n\n"
                           "Приглашено: <b>{invited}</b>\n"
                           "Сделали заказ: <b>{qualified}</b>\n"
                           "До следующих {stars_per_reward} ⭐: <b>{to_next}</b>\n\n"
                           "Начислено: <b>{earned} ⭐</b>\n"
                           "Получено: <b>{paid} ⭐</b>\n"
                           "Доступно сейчас: <b>{available} ⭐</b>",
        "referral_joined_notice": "🤝 <b>Новый реферал</b>\n\n"
                           "По вашей ссылке пришёл <b>{who}</b>.\n"
                           "Засчитаем его, как только он сделает заказ.",
        "referral_purchase": "🛒 <b>Ваш реферал купил</b>\n\n"
                           "<b>{who}</b> оформил: {product}\n\n"
                           "Засчитано приглашённых: <b>{qualified}</b>\n"
                           "До следующих {stars} ⭐: <b>{to_next}</b>",
        "referral_copy": "📋 Скопировать ссылку",
        "referral_share": "📤 Поделиться",
        "referral_share_text": "Беру тут звёзды, Premium и TON — заходи по моей ссылке: {link}",
        "referral_claim": "🎁 Забрать {available} ⭐",
        "referral_nothing": "Забирать пока нечего. Пригласите ещё друзей 🙂",
        "referral_no_username": "Чтобы получить звёзды, задайте username в настройках Telegram — "
                                "иначе их некуда отправить.",
        "referral_sending": "Отправляю {stars} ⭐...",
        "referral_claimed": "Готово! <b>{stars} ⭐</b> уже на вашем аккаунте 🎉",
        "referral_claim_failed": "Звёзды не ушли: {error}\nМенеджер уже в курсе, начисление не сгорело.",
        "referral_reward": "🎉 <b>Поздравляем!</b>\n\n"
                           "Ваших приглашённых с заказами уже <b>{qualified}</b>, "
                           "поэтому вам начислено <b>{stars} ⭐</b>.\n\n"
                           "Забрать можно в профиле → Реферальная программа.",
        "referral_joined": "Вы пришли по приглашению 🤝",
        "profile": "<b>Ваш профиль</b>\n"
                   "ID: <code>{user_id}</code>\n"
                   "Username: {username}\n"
                   "Язык: {language}\n"
                   "Оплаченных заказов: {paid_orders}\n"
                   "Куплено звёзд: {total_stars}\n\n"
                   "👨‍💻 Разработчик бота: @{developer}",
        "premium_soon": "Раздел Premium ещё готовится. Следите за новостями в канале.",
        "delivery_ok_premium": "Готово! <b>Telegram Premium на {quantity} мес.</b> оформлен для <b>{recipient}</b>.\nПодписка активируется после подтверждения транзакции.",
        "gram_soon": "Покупка Gram ещё готовится. Следите за новостями в канале.",
        "calc_choose": "🧮 <b>Калькулятор</b>\n\nЧто считаем?",
        "calc_pick_stars": "⭐ Звёзды",
        "calc_pick_ton": "💠 TON",
        "calc_stars_title": "⭐ <b>Калькулятор звёзд</b>\n\nЧто считаем?",
        "calc_ton_title": "💠 <b>Калькулятор TON</b>\n\nЧто считаем?",
        "calc_back": "⬅️ Назад",
        "calc_to_uah": "⭐ → ₴  звёзды в гривны",
        "calc_to_stars": "₴ → ⭐  гривны в звёзды",
        "calc_ask_stars": "Пришлите количество звёзд числом.",
        "calc_ask_uah": "Пришлите сумму в гривнах.",
        "calc_bad_number": "Нужно положительное число. Попробуйте ещё раз.",
        "calc_result_to_uah": "🧮 <b>{quantity} ⭐ = {price} грн</b>\n\nВыходит {rate} грн за звезду.",
        "calc_result_to_stars": "🧮 <b>{amount} грн = {quantity} ⭐</b>\n\n"
                                "Ровно {quantity} звёзд стоят {price} грн.\nВыходит {rate} грн за звезду.",
        "calc_min_note": "\n\n⚠️ Минимальный заказ — {min_stars} ⭐.",
        "calc_ton_to_uah": "💠 → ₴  TON в гривны",
        "calc_to_ton": "₴ → 💠  гривны в TON",
        "calc_ask_ton": "Пришлите количество TON числом.",
        "calc_result_ton_to_uah": "🧮 <b>{amount} 💠 = {price} грн</b>\n\nПо курсу {rate} грн за 1 TON.",
        "calc_result_to_ton": "🧮 <b>{amount} грн = {quantity} 💠</b>\n\nПо курсу {rate} грн за 1 TON.",
        "calc_min_note_ton": "\n\n⚠️ Минимальный заказ — {min_ton} TON.",
        "calc_again": "🔄 Посчитать ещё",
        "calculator_soon": "Калькулятор ещё готовится.",
    },
}


def t(language: str | None, key: str, /, **kwargs) -> str:
    """`language` and `key` are positional-only so a template placeholder may reuse those names,
    e.g. t(lang, "profile", language=lang)."""
    language = language if language in TEXTS else DEFAULT_LANGUAGE
    template = TEXTS[language].get(key) or TEXTS[DEFAULT_LANGUAGE][key]
    return template.format(**kwargs) if kwargs else template
