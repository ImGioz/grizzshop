"""Two-language copy. Every user-visible string lives here, keyed by language code."""

LANGUAGES = ("uk", "ru")
DEFAULT_LANGUAGE = "uk"

TEXTS = {
    "uk": {
        "choose_language": "Оберіть мову / Выберите язык",
        "language_set": "Мову успішно встановлено ✅",

        "subscribe_required": "Для використання бота підпишіться на канал 👇",
        "subscribe_button": "📢 Перейти до каналу",
        "check_subscription": "✅ Перевірити підписку",
        "not_subscribed": "Ви ще не підписані на канал. Підпишіться і натисніть кнопку ще раз.",
        "subscription_ok": "Дякуємо за підписку! Можете користуватися ботом 🎉",
        "subscription_check_failed": "Не вдалося перевірити підписку. Спробуйте пізніше або зверніться до підтримки.",

        "menu_stars": "⭐ Купити зірки",
        "menu_premium": "💎 Купити Premium",
        "menu_gram": "💠 Купити Gram",
        "menu_nft": "🖼 Список NFT",
        "nft_choose_type": "Оберіть тип покупки",
        "nft_market": "🛒 Маркет",
        "nft_from_list": "📋 Обрати зі списку",
        "nft_stock_empty": "Зараз у наявності немає подарунків, доступних до передачі.\n"
                           "Скористайтеся Маркетом — там можна замовити будь-який NFT.",
        "nft_stock_title": "📋 <b>Наявні NFT</b>\n\nОберіть подарунок:",
        "nft_stock_error": "Склад тимчасово недоступний: {error}",
        "nft_stock_gone": "Цей подарунок уже недоступний. Оберіть інший.",
        "nft_stock_card": "🎁 Колекція: <b>{collection}</b>\n"
                          "🧩 Модель: {model}\n"
                          "✨ Символ: {symbol}\n"
                          "🎨 Фон: {backdrop}\n\n"
                          "🔗 <a href=\"{link}\">Переглянути подарунок</a>\n\n"
                          "💰 <b>Ціна: {price} грн</b>",
        "nft_buy": "✅ Придбати",
        "nft_decline": "✖️ Відмовитись",
        "nft_declined": "Гаразд, повертаємось до меню.",
        "delivery_ok_nft_stock": "Готово! Подарунок <b>{details}</b> надіслано вам.\n"
                                 "Перевірте профіль — він уже там.",
        "nft_market_hello": "Вітаю в Маркеті!\n\nТут ви можете розмістити замовлення на будь-який NFT.\n"
                            "Щоб це зробити, надішліть пряме посилання на подарунок, який хочете купити, "
                            "або надішліть дані як у прикладі.\n\n"
                            "<code>1. Model Name\n2. Symbol\n3. Backdrop</code>",
        "nft_searching": "Шукаю на маркеті...",
        "nft_not_found": "За таким описом нічого не знайдено. Перевірте назви та спробуйте ще раз.",
        "nft_bad_input": "Не зрозумів запит. Надішліть посилання або три рядки: модель, символ, фон.",
        "nft_market_error": "Маркет тимчасово недоступний: {error}",
        "nft_header_exact": "✅ <b>NFT знайдено</b>\n\n",
        "nft_header_similar": "⚠️ <b>Точно такий самий не знайдено</b>\n\n"
                              "🔎 Ви шукали:\n"
                              "🧩 Модель: {model}\n"
                              "✨ Символ: {symbol}\n"
                              "🎨 Фон: {backdrop}\n\n"
                              "💡 <b>Але є схожий:</b>\n\n",
        "nft_card": "🎁 Колекція: <b>{collection}</b>\n"
                    "🧩 Модель: {model}\n"
                    "✨ Символ: {symbol}\n"
                    "🎨 Фон: {backdrop}\n\n"
                    "💰 <b>До сплати: {price} грн</b>",
        "nft_order_placed": "Замовлення створено. Оберіть спосіб оплати.",
        "nft_make_order": "✅ Зробити замовлення",
        "nft_cancel_order": "✖️ Скасувати замовлення",
        "nft_cancelled": "Замовлення скасовано.",
        "product_nft": "NFT: {details}",
        "delivery_ok_nft": "Оплату отримано ✅\n\nЗамовлення на NFT передано менеджеру — "
                           "подарунок буде надіслано вручну найближчим часом.",
        "menu_profile": "👤 Мій профіль",
        "menu_calculator": "🧮 Калькулятор",
        "main_menu": "Головне меню",

        "stars_for_whom": "Кому купуємо зірки?",
        "premium_for_whom": "Кому купуємо Telegram Premium?",
        "premium_already": "❌ У <b>@{recipient}</b> вже активний Telegram Premium.\n\n"
                            "Бот не дозволяє подарувати підписку тому, хто вже її має — "
                            "спочатку дочекайтесь її завершення.\n\n"
                            "Можете вказати іншого отримувача або обрати інший товар.",
        "premium_recipient_not_user": "❌ <b>@{recipient}</b> — це username каналу або бота, "
                            "а не користувача.\n\nПідписку можна подарувати лише людині. "
                            "Надішліть username отримувача.",
        "premium_recipient_unknown": "❌ Бот не знайшов акаунт <b>@{recipient}</b>.\n\n"
                            "Перевірте username і спробуйте ще раз.",
        "gram_ask_wallet": "Надішліть адресу гаманця <b>у мережі TON</b>, на яку надіслати монети.\n\nНаприклад: <code>UQ...</code> або <code>EQ...</code>",
        "gram_bad_wallet": "Це не схоже на адресу TON. Перевірте та надішліть ще раз.",
        "gram_ask_amount": "Гаманець: <code>{wallet}</code>\n\nСкільки TON купуєте? Введіть число, мінімум {min_ton}.\nКурс: {rate} грн за 1 TON.",
        "gram_bad_amount": "Потрібне число не менше {min_ton}. Спробуйте ще раз.",
        "product_gram": "{amount} TON",
        "delivery_ok_gram": "Готово! <b>{amount} TON</b> надіслано на\n<code>{wallet}</code>\nМонети надійдуть після підтвердження транзакції.",
        "choose_months": "Оберіть термін підписки",
        "months_label": "{months} міс. — {price} грн",
        "product_stars": "{quantity} зірок",
        "product_premium": "Telegram Premium, {quantity} міс.",
        "for_myself": "Собі",
        "for_friend": "Другу",
        "no_username": "У вас не встановлений username у Telegram. Додайте його в налаштуваннях "
                       "(Settings → Username) і поверніться до бота.",
        "ask_friend_username": "Надішліть @username отримувача.",
        "bad_username": "Схоже, це не username. Формат: @nickname (5–32 символи, літери, цифри та _).",

        "choose_quantity": "Оберіть кількість зірок",
        "custom_quantity": "Своя кількість",
        "ask_custom_quantity": "Введіть кількість зірок числом (мінімум {min_stars}).",
        "bad_quantity": "Потрібне ціле число не менше {min_stars}. Спробуйте ще раз.",

        "order_created": "<b>Замовлення створено</b>\n"
                         "Отримувач: {recipient}\n"
                         "Товар: {product}\n"
                         "Вартість: {price} грн\n"
                         "Спосіб оплати: —",
        "pay_transfer": "💳 Переказ",
        "pay_crypto": "🪙 Криптовалюта",
        "crypto_details": "<b>Спосіб оплати: TON</b>\n\n"
                          "Гаманець:\n<code>{wallet}</code>\n\n"
                          "Сума: <b>{amount} TON</b>\n"
                          "Курс: {rate} грн за TON\n"
                          "Коментар до переказу: <code>{comment}</code>\n\n"
                          "⚠️ <b>Обов'язково вкажіть коментар</b> — без нього платіж не знайдеться.\n"
                          "Товар: {product}\n"
                          "Оплатіть протягом {timeout} хв.",
        "crypto_checking": "Перевіряю блокчейн...",
        "crypto_not_found": "Платіж не знайдено. Якщо ви щойно надіслали — зачекайте хвилину "
                            "і натисніть ще раз. Перевірте коментар <code>{comment}</code>.",
        "crypto_check": "🔍 Перевірити оплату",

        "payment_details": "<b>Спосіб оплати: переказ на картку</b>\n\n"
                           "Номер картки: <code>{card}</code>\n"
                           "Отримувач: {holder}\n"
                           "Сума: <b>{price} грн</b>\n"
                           "Товар: {product}\n"
                           "ID замовлення: <code>{order_id}</code>\n\n"
                           "Після оплати натисніть на кнопку <b>Перевірити</b> та дотримуйтесь подальших інструкцій.\n"
                           "Оплатіть протягом {timeout} хв.",
        "check_payment": "🔍 Перевірити",
        "cancel_order": "✖️ Скасувати замовлення",
        "order_cancelled": "Замовлення #{order_id} скасовано. Кошти не списувались.",
        "ask_sender_name": "Надішліть ПІБ відправника платежу — так, як він вказаний у квитанції.",
        "ask_receipt_link": "Тепер надішліть посилання на квитанцію Monobank.",
        "bad_receipt_link": "Це не схоже на посилання check.monobank.ua/p/... Спробуйте ще раз.",
        "checking_receipt": "Перевіряю квитанцію, це займе кілька секунд...",
        "ask_receipt_any": "Надішліть підтвердження оплати одним із способів:\n\n"
                           "• посилання на квитанцію Monobank (check.monobank.ua/p/...)\n"
                           "• PDF-файл квитанції вашого банку",
        "pdf_no_text": "У цьому PDF немає тексту — схоже, це скан або картинка. "
                       "Надішліть квитанцію у форматі PDF, збереженому з додатку банку.",
        "pdf_too_big": "Файл завеликий. Максимум {limit} МБ.",
        "pdf_error": "Не вдалося прочитати PDF: {error}",
        "order_on_review": "Оплату знайдено ✅\n\nЗамовлення передано на перевірку адміністратору — "
                           "суми понад {limit} грн підтверджуються вручну. Зазвичай це займає кілька хвилин.",
        "order_rejected": "Замовлення #{order_id} відхилено адміністратором. "
                          "Якщо це помилка — зверніться до підтримки.",

        "verify_failed_name": "ПІБ у квитанції не збігається з тим, що ви вказали.",
        "verify_failed_card": "Картка отримувача у квитанції не збігається з нашою.",
        "verify_failed_amount": "Сума у квитанції ({actual} грн) не збігається з сумою замовлення ({expected} грн).",
        "verify_failed_time": "Платіж не потрапляє у часове вікно замовлення (допуск {tolerance} хв).",
        "verify_failed_incomplete": "Не вдалося прочитати всі дані з квитанції. Перевірте посилання.",
        "verify_failed_status": "Платіж не завершено (статус: {status}). Дочекайтеся зарахування.",
        "verify_failed_currency": "Платіж виконано не в гривні (код валюти {currency}).",
        "receipt_already_used": "Ця квитанція вже використана для іншого замовлення.",
        "receipt_error": "Помилка читання квитанції: {error}",
        "verify_retry": "🔁 Спробувати ще раз",

        "payment_ok": "Оплату підтверджено ✅\nВидаю зірки...",
        "payment_ok_premium": "Оплату підтверджено ✅\nОформлюю підписку Telegram Premium...",
        "payment_ok_gram": "Оплату підтверджено ✅\nНадсилаю TON на ваш гаманець...",
        "payment_ok_nft": "Оплату підтверджено ✅\nОформлюю передачу подарунка...",
        "payment_ok_nft_stock": "Оплату підтверджено ✅\nПередаю подарунок...",
        "delivery_ok": "Готово! <b>{quantity}</b> ⭐ надіслано до <b>{recipient}</b>.\n"
                       "Зірки надійдуть після підтвердження транзакції, зазвичай менше хвилини.",
        "delivery_failed": "Оплата зарахована, але автоматична видача не вдалася. "
                           "Адміністратор видасть зірки вручну найближчим часом.",

        "review_ask_rating": "Як усе пройшло? Оцініть замовлення 👇",
        "review_ask_comment": "Дякуємо! Напишіть кілька слів про замовлення — "
                              "відгук буде опубліковано в каналі.",
        "review_ask_photo": "Останнє: надішліть скриншот отриманої послуги (зірки або Premium).",
        "review_skip": "Пропустити",
        "review_need_photo": "Це має бути фото. Надішліть скриншот або натисніть «Пропустити».",
        "review_thanks": "<b>Дякуємо за відгук! 💚</b>",
        "review_not_published": "Дякуємо за відгук! 💚",
        "order_expired": "Термін замовлення минув. Створіть нове.",
        "no_active_order": "Немає активного замовлення.",
        "cancelled": "Скасовано.",

        "profile": "<b>Ваш профіль</b>\n"
                   "ID: <code>{user_id}</code>\n"
                   "Username: {username}\n"
                   "Мова: {language}\n"
                   "Замовлень оплачено: {paid_orders}\n"
                   "Зірок куплено: {total_stars}",
        "premium_soon": "Розділ Premium у розробці. Слідкуйте за оновленнями в каналі.",
        "delivery_ok_premium": "Готово! <b>Telegram Premium на {quantity} міс.</b> надіслано до <b>{recipient}</b>.\nПідписка активується після підтвердження транзакції.",
        "gram_soon": "Купівля Gram у розробці. Слідкуйте за оновленнями в каналі.",
        "calc_choose": "🧮 <b>Калькулятор</b>\n\nЩо переводимо?",
        "calc_to_uah": "⭐ → ₴  зірки в гривні",
        "calc_to_stars": "₴ → ⭐  гривні в зірки",
        "calc_ask_stars": "Введіть кількість зірок числом.",
        "calc_ask_uah": "Введіть суму в гривнях.",
        "calc_bad_number": "Потрібне додатне число. Спробуйте ще раз.",
        "calc_result_to_uah": "🧮 <b>{quantity} ⭐ = {price} грн</b>\n\nКурс: {rate} грн за зірку.",
        "calc_result_to_stars": "🧮 <b>{amount} грн = {quantity} ⭐</b>\n\n"
                                "Точна вартість {quantity} зірок — {price} грн.\nКурс: {rate} грн за зірку.",
        "calc_min_note": "\n\n⚠️ Мінімальне замовлення — {min_stars} ⭐.",
        "calc_again": "🔄 Порахувати ще",
        "calculator_soon": "Калькулятор у розробці.",
    },
    "ru": {
        "choose_language": "Оберіть мову / Выберите язык",
        "language_set": "Язык успешно установлен ✅",

        "subscribe_required": "Для использования бота подпишитесь на канал 👇",
        "subscribe_button": "📢 Перейти в канал",
        "check_subscription": "✅ Проверить подписку",
        "not_subscribed": "Вы ещё не подписаны на канал. Подпишитесь и нажмите кнопку ещё раз.",
        "subscription_ok": "Спасибо за подписку! Можете пользоваться ботом 🎉",
        "subscription_check_failed": "Не удалось проверить подписку. Попробуйте позже или обратитесь в поддержку.",

        "menu_stars": "⭐ Купить звёзды",
        "menu_premium": "💎 Купить Premium",
        "menu_gram": "💠 Купить Gram",
        "menu_nft": "🖼 Список NFT",
        "nft_choose_type": "Выберите тип покупки",
        "nft_market": "🛒 Маркет",
        "nft_from_list": "📋 Выбрать из списка",
        "nft_stock_empty": "Сейчас в наличии нет подарков, доступных к передаче.\n"
                           "Воспользуйтесь Маркетом — там можно заказать любой NFT.",
        "nft_stock_title": "📋 <b>NFT в наличии</b>\n\nВыберите подарок:",
        "nft_stock_error": "Склад временно недоступен: {error}",
        "nft_stock_gone": "Этот подарок уже недоступен. Выберите другой.",
        "nft_stock_card": "🎁 Коллекция: <b>{collection}</b>\n"
                          "🧩 Модель: {model}\n"
                          "✨ Символ: {symbol}\n"
                          "🎨 Фон: {backdrop}\n\n"
                          "🔗 <a href=\"{link}\">Посмотреть подарок</a>\n\n"
                          "💰 <b>Цена: {price} грн</b>",
        "nft_buy": "✅ Приобрести",
        "nft_decline": "✖️ Отказаться",
        "nft_declined": "Хорошо, возвращаемся в меню.",
        "delivery_ok_nft_stock": "Готово! Подарок <b>{details}</b> отправлен вам.\n"
                                 "Проверьте профиль — он уже там.",
        "nft_market_hello": "Приветствую в Маркете!\n\nТут вы можете разместить заказ на любой NFT.\n"
                            "Чтобы это сделать, отправьте прямую ссылку на подарок, который хотите купить, "
                            "или отправьте данные как в примере.\n\n"
                            "<code>1. Model Name\n2. Symbol\n3. Backdrop</code>",
        "nft_searching": "Ищу на маркете...",
        "nft_not_found": "По такому описанию ничего не найдено. Проверьте названия и попробуйте ещё раз.",
        "nft_bad_input": "Не понял запрос. Пришлите ссылку или три строки: модель, символ, фон.",
        "nft_market_error": "Маркет временно недоступен: {error}",
        "nft_header_exact": "✅ <b>NFT найден</b>\n\n",
        "nft_header_similar": "⚠️ <b>Точно такой же не найден</b>\n\n"
                              "🔎 Вы искали:\n"
                              "🧩 Модель: {model}\n"
                              "✨ Символ: {symbol}\n"
                              "🎨 Фон: {backdrop}\n\n"
                              "💡 <b>Но есть похожий:</b>\n\n",
        "nft_card": "🎁 Коллекция: <b>{collection}</b>\n"
                    "🧩 Модель: {model}\n"
                    "✨ Символ: {symbol}\n"
                    "🎨 Фон: {backdrop}\n\n"
                    "💰 <b>К оплате: {price} грн</b>",
        "nft_order_placed": "Заказ создан. Выберите способ оплаты.",
        "nft_make_order": "✅ Сделать заказ",
        "nft_cancel_order": "✖️ Отменить заказ",
        "nft_cancelled": "Заказ отменён.",
        "product_nft": "NFT: {details}",
        "delivery_ok_nft": "Оплата получена ✅\n\nЗаказ на NFT передан менеджеру — "
                           "подарок будет отправлен вручную в ближайшее время.",
        "menu_profile": "👤 Мой профиль",
        "menu_calculator": "🧮 Калькулятор",
        "main_menu": "Главное меню",

        "stars_for_whom": "Кому покупаем звёзды?",
        "premium_for_whom": "Кому покупаем Telegram Premium?",
        "premium_already": "❌ У <b>@{recipient}</b> уже активен Telegram Premium.\n\n"
                            "Бот не даёт возможность подарить подписку тому, у кого она уже есть — "
                            "сначала дождитесь её окончания.\n\n"
                            "Можете указать другого получателя или выбрать другой товар.",
        "premium_recipient_not_user": "❌ <b>@{recipient}</b> — это username канала или бота, "
                            "а не пользователя.\n\nПодписку можно подарить только человеку. "
                            "Пришлите username получателя.",
        "premium_recipient_unknown": "❌ Бот не нашёл аккаунт <b>@{recipient}</b>.\n\n"
                            "Проверьте username и попробуйте ещё раз.",
        "gram_ask_wallet": "Пришлите адрес кошелька <b>в сети TON</b>, на который отправить монеты.\n\nНапример: <code>UQ...</code> или <code>EQ...</code>",
        "gram_bad_wallet": "Это не похоже на адрес TON. Проверьте и пришлите ещё раз.",
        "gram_ask_amount": "Кошелёк: <code>{wallet}</code>\n\nСколько TON покупаете? Введите число, минимум {min_ton}.\nКурс: {rate} грн за 1 TON.",
        "gram_bad_amount": "Нужно число не меньше {min_ton}. Попробуйте ещё раз.",
        "product_gram": "{amount} TON",
        "delivery_ok_gram": "Готово! <b>{amount} TON</b> отправлено на\n<code>{wallet}</code>\nМонеты придут после подтверждения транзакции.",
        "choose_months": "Выберите срок подписки",
        "months_label": "{months} мес. — {price} грн",
        "product_stars": "{quantity} звёзд",
        "product_premium": "Telegram Premium, {quantity} мес.",
        "for_myself": "Себе",
        "for_friend": "Другу",
        "no_username": "У вас не установлен username в Telegram. Добавьте его в настройках "
                       "(Settings → Username) и вернитесь в бота.",
        "ask_friend_username": "Пришлите @username получателя.",
        "bad_username": "Похоже, это не username. Формат: @nickname (5–32 символа, буквы, цифры и _).",

        "choose_quantity": "Выберите количество звёзд",
        "custom_quantity": "Своё количество",
        "ask_custom_quantity": "Введите количество звёзд числом (минимум {min_stars}).",
        "bad_quantity": "Нужно целое число не меньше {min_stars}. Попробуйте ещё раз.",

        "order_created": "<b>Заказ создан</b>\n"
                         "Получатель: {recipient}\n"
                         "Товар: {product}\n"
                         "Стоимость: {price} грн\n"
                         "Способ оплаты: —",
        "pay_transfer": "💳 Перевод",
        "pay_crypto": "🪙 Криптовалюта",
        "crypto_details": "<b>Способ оплаты: TON</b>\n\n"
                          "Кошелёк:\n<code>{wallet}</code>\n\n"
                          "Сумма: <b>{amount} TON</b>\n"
                          "Курс: {rate} грн за TON\n"
                          "Комментарий к переводу: <code>{comment}</code>\n\n"
                          "⚠️ <b>Обязательно укажите комментарий</b> — без него платёж не найдётся.\n"
                          "Товар: {product}\n"
                          "Оплатите в течение {timeout} мин.",
        "crypto_checking": "Проверяю блокчейн...",
        "crypto_not_found": "Платёж не найден. Если вы только что отправили — подождите минуту "
                            "и нажмите ещё раз. Проверьте комментарий <code>{comment}</code>.",
        "crypto_check": "🔍 Проверить оплату",

        "payment_details": "<b>Метод оплаты: перевод на карту</b>\n\n"
                           "Номер карты: <code>{card}</code>\n"
                           "Получатель: {holder}\n"
                           "Сумма: <b>{price} грн</b>\n"
                           "Товар: {product}\n"
                           "ID заказа: <code>{order_id}</code>\n\n"
                           "После оплаты нажмите на кнопку <b>Проверить</b> и придерживайтесь дальнейших инструкций.\n"
                           "Оплатите в течение {timeout} мин.",
        "check_payment": "🔍 Проверить",
        "cancel_order": "✖️ Отменить заказ",
        "order_cancelled": "Заказ #{order_id} отменён. Средства не списывались.",
        "ask_sender_name": "Пришлите ФИО отправителя платежа — так, как оно указано в квитанции.",
        "ask_receipt_link": "Теперь пришлите ссылку на квитанцию Monobank.",
        "bad_receipt_link": "Это не похоже на ссылку check.monobank.ua/p/... Попробуйте ещё раз.",
        "checking_receipt": "Проверяю квитанцию, это займёт несколько секунд...",
        "ask_receipt_any": "Пришлите подтверждение оплаты одним из способов:\n\n"
                           "• ссылку на квитанцию Monobank (check.monobank.ua/p/...)\n"
                           "• PDF-файл квитанции вашего банка",
        "pdf_no_text": "В этом PDF нет текста — похоже, это скан или картинка. "
                       "Пришлите квитанцию в формате PDF, сохранённом из приложения банка.",
        "pdf_too_big": "Файл слишком большой. Максимум {limit} МБ.",
        "pdf_error": "Не удалось прочитать PDF: {error}",
        "order_on_review": "Оплата найдена ✅\n\nЗаказ передан на проверку администратору — "
                           "суммы свыше {limit} грн подтверждаются вручную. Обычно это занимает несколько минут.",
        "order_rejected": "Заказ #{order_id} отклонён администратором. "
                          "Если это ошибка — обратитесь в поддержку.",

        "verify_failed_name": "ФИО в квитанции не совпадает с тем, что вы указали.",
        "verify_failed_card": "Карта получателя в квитанции не совпадает с нашей.",
        "verify_failed_amount": "Сумма в квитанции ({actual} грн) не совпадает с суммой заказа ({expected} грн).",
        "verify_failed_time": "Платёж не попадает во временное окно заказа (допуск {tolerance} мин).",
        "verify_failed_incomplete": "Не удалось прочитать все данные из квитанции. Проверьте ссылку.",
        "verify_failed_status": "Платёж не завершён (статус: {status}). Дождитесь зачисления.",
        "verify_failed_currency": "Платёж выполнен не в гривне (код валюты {currency}).",
        "receipt_already_used": "Эта квитанция уже использована для другого заказа.",
        "receipt_error": "Ошибка чтения квитанции: {error}",
        "verify_retry": "🔁 Попробовать ещё раз",

        "payment_ok": "Оплата подтверждена ✅\nВыдаю звёзды...",
        "payment_ok_premium": "Оплата подтверждена ✅\nОформляю подписку Telegram Premium...",
        "payment_ok_gram": "Оплата подтверждена ✅\nОтправляю TON на ваш кошелёк...",
        "payment_ok_nft": "Оплата подтверждена ✅\nОформляю передачу подарка...",
        "payment_ok_nft_stock": "Оплата подтверждена ✅\nПередаю подарок...",
        "delivery_ok": "Готово! <b>{quantity}</b> ⭐ отправлено на <b>{recipient}</b>.\n"
                       "Звёзды придут после подтверждения транзакции, обычно меньше минуты.",
        "delivery_failed": "Оплата зачтена, но автоматическая выдача не удалась. "
                           "Администратор выдаст звёзды вручную в ближайшее время.",

        "review_ask_rating": "Как всё прошло? Оцените заказ 👇",
        "review_ask_comment": "Спасибо! Напишите пару слов о заказе — "
                              "отзыв будет опубликован в канале.",
        "review_ask_photo": "Последнее: пришлите скриншот полученной услуги (звёзды или Premium).",
        "review_skip": "Пропустить",
        "review_need_photo": "Нужно фото. Пришлите скриншот или нажмите «Пропустить».",
        "review_thanks": "Спасибо за отзыв! 💚 Он опубликован в канале отзывов.",
        "review_not_published": "Спасибо за отзыв! 💚",
        "order_expired": "Срок заказа истёк. Создайте новый.",
        "no_active_order": "Нет активного заказа.",
        "cancelled": "Отменено.",

        "profile": "<b>Ваш профиль</b>\n"
                   "ID: <code>{user_id}</code>\n"
                   "Username: {username}\n"
                   "Язык: {language}\n"
                   "Заказов оплачено: {paid_orders}\n"
                   "Звёзд куплено: {total_stars}",
        "premium_soon": "Раздел Premium в разработке. Следите за обновлениями в канале.",
        "delivery_ok_premium": "Готово! <b>Telegram Premium на {quantity} мес.</b> отправлен на <b>{recipient}</b>.\nПодписка активируется после подтверждения транзакции.",
        "gram_soon": "Покупка Gram в разработке. Следите за обновлениями в канале.",
        "calc_choose": "🧮 <b>Калькулятор</b>\n\nЧто переводим?",
        "calc_to_uah": "⭐ → ₴  звёзды в гривны",
        "calc_to_stars": "₴ → ⭐  гривны в звёзды",
        "calc_ask_stars": "Введите количество звёзд числом.",
        "calc_ask_uah": "Введите сумму в гривнах.",
        "calc_bad_number": "Нужно положительное число. Попробуйте ещё раз.",
        "calc_result_to_uah": "🧮 <b>{quantity} ⭐ = {price} грн</b>\n\nКурс: {rate} грн за звезду.",
        "calc_result_to_stars": "🧮 <b>{amount} грн = {quantity} ⭐</b>\n\n"
                                "Точная стоимость {quantity} звёзд — {price} грн.\nКурс: {rate} грн за звезду.",
        "calc_min_note": "\n\n⚠️ Минимальный заказ — {min_stars} ⭐.",
        "calc_again": "🔄 Посчитать ещё",
        "calculator_soon": "Калькулятор в разработке.",
    },
}


def t(language: str | None, key: str, /, **kwargs) -> str:
    """`language` and `key` are positional-only so a template placeholder may reuse those names,
    e.g. t(lang, "profile", language=lang)."""
    language = language if language in TEXTS else DEFAULT_LANGUAGE
    template = TEXTS[language].get(key) or TEXTS[DEFAULT_LANGUAGE][key]
    return template.format(**kwargs) if kwargs else template
