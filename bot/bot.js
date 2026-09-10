require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const TelegramBot = require('node-telegram-bot-api');
const { initializeApp } = require('firebase/app');
const { getDatabase, ref, set, update, push, get, onChildAdded, remove } = require('firebase/database');
const { imageSize } = require('image-size');
const crypto = require('crypto');
const path = require('path');
const fs = require('fs');

// 🔐 Telegram bot token from .env
const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN;

// 🔐 Firebase config from .env
const firebaseConfig = {
  apiKey: process.env.FIREBASE_API_KEY,
  authDomain: process.env.FIREBASE_AUTH_DOMAIN,
  databaseURL: process.env.FIREBASE_DATABASE_URL,
  projectId: process.env.FIREBASE_PROJECT_ID,
  storageBucket: process.env.FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.FIREBASE_APP_ID,
  measurementId: process.env.FIREBASE_MEASUREMENT_ID
};

// 🔐 Onboarding / moderation config from .env
const ADMIN_ID = Number(process.env.ADMIN_ID);
const LOG_CHANNEL_ID = process.env.LOG_CHANNEL_ID;
const REQUIRED_CHANNEL = process.env.REQUIRED_CHANNEL || '@monomo_news';
const CHANNEL_URL = `https://t.me/${REQUIRED_CHANNEL.replace('@', '')}`;
const APP_DOWNLOAD_URL = process.env.APP_DOWNLOAD_URL || 'https://monotest-d5389.web.app/';

// 🤖 Username другого (платіжного) бота — БЕЗ символу @.
// Саме на нього перенаправляємо користувача при виборі тарифу.
const PAYMENT_BOT_USERNAME = (process.env.PAYMENT_BOT_USERNAME || 'your_payment_bot').replace('@', '');

// Спільна конфігурація тарифів (той самий файл підключає й payment-bot.js)
const { PLANS, PLAN_BY_ID } = require('./plans');
const { parseEndMs } = require('./subutil');

// Весь інтерфейс орієнтований на київський час, а сервер бота може працювати
// в будь-якому системному часовому поясі — тому дати завжди трактуємо/показуємо
// саме як Europe/Kyiv, а не покладаємось на локальний TZ процесу.
const KYIV_TZ = 'Europe/Kyiv';

function getTimeZoneOffsetMs(date, timeZone) {
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false
  });
  const parts = {};
  dtf.formatToParts(date).forEach(({ type, value }) => { parts[type] = value; });
  const asUTC = Date.UTC(
    Number(parts.year), Number(parts.month) - 1, Number(parts.day),
    Number(parts.hour) === 24 ? 0 : Number(parts.hour), Number(parts.minute), Number(parts.second)
  );
  return asUTC - date.getTime();
}

// Перетворює "стінний" час (рік, місяць, день, година, хвилина) у Києві на
// коректний UTC Date — з урахуванням літнього/зимового часу.
function kyivWallTimeToUTC(year, monthIndex, day, hour = 0, minute = 0) {
  const naiveUTC = new Date(Date.UTC(year, monthIndex, day, hour, minute));
  const offsetMs = getTimeZoneOffsetMs(naiveUTC, KYIV_TZ);
  return new Date(naiveUTC.getTime() - offsetMs);
}

// ✅ Firebase init
const app = initializeApp(firebaseConfig);
const db = getDatabase(app);

// ✅ Telegram bot init
const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });
const userState = {}; // ефемерні багатокрокові діалоги (фінанси, редагування профілю)

const mainMenu = {
  reply_markup: {
    keyboard: [
      [{ text: '💰 Ввести баланс' }],
      [{ text: '➕ Додати транзакцію' }]
    ],
    resize_keyboard: true,
    one_time_keyboard: false
  }
};

const skipKeyboard = {
  reply_markup: {
    keyboard: [[{ text: '⏭ Пропустити дату' }]],
    resize_keyboard: true,
    one_time_keyboard: true
  }
};

// 🔑 Ключ доступа для привязки застосунку до конкретного користувача
function generateAccessKey() {
  return crypto.randomBytes(8).toString('hex').toUpperCase().match(/.{1,4}/g).join('-');
}

async function getOrCreateAccessKey(chatId) {
  const userKeyRef = ref(db, `users/${chatId}/accessKey`);
  const snapshot = await get(userKeyRef);
  if (snapshot.exists()) {
    return { key: snapshot.val(), isNew: false };
  }

  const key = generateAccessKey();
  await Promise.all([
    set(userKeyRef, key),
    set(ref(db, `accessKeys/${key}`), String(chatId))
  ]);
  return { key, isNew: true };
}

// 💳 Номер картки для відображення в застосунку (тільки для вигляду, не справжня картка)
function generateCardNumber() {
  let digits = '';
  for (let i = 0; i < 12; i++) {
    digits += crypto.randomInt(0, 10);
  }
  return `4441${digits}`;
}

async function getOrCreateCardNumber(chatId) {
  const cardRef = ref(db, `users/${chatId}/cardNumber`);
  const snapshot = await get(cardRef);
  if (snapshot.exists()) {
    return snapshot.val();
  }

  const cardNumber = generateCardNumber();
  await set(cardRef, cardNumber);
  return cardNumber;
}

// 🏦 IBAN відправника для квитанції (тільки для вигляду).
// Детермінований від chatId — той самий алгоритм, що й у застосунку
// (src/receiptUtils.js → generateIban), тож значення завжди збігаються.
function ibanHashSeed(str) {
  let h = 2166136261;
  const s = String(str);
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function ibanMulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function generateIban(chatId) {
  const rand = ibanMulberry32(ibanHashSeed(`iban:${chatId}`));
  const check = String(10 + Math.floor(rand() * 90));
  let account = '00000';
  for (let i = 0; i < 14; i++) {
    account += Math.floor(rand() * 10);
  }
  return `UA${check}322001${account}`;
}

async function getOrCreateIban(chatId) {
  const ibanRef = ref(db, `users/${chatId}/iban`);
  const snapshot = await get(ibanRef);
  if (snapshot.exists()) {
    return snapshot.val();
  }

  const iban = generateIban(chatId);
  await set(ibanRef, iban);
  return iban;
}

// ============================================================
// ОНБОРДИНГ: тексти повідомлень
// ============================================================

const TERMS_MESSAGE = `👋 Привіт! Раді вітати вас у нашому боті!

📝 Для початку роботи потрібно всього лише заповнити дані

🤝 Використовуючи наш сервіс, ви автоматично погоджуєтесь з нашою [Угодою користувача](https://monotest-d5389.web.app/user_agreement.html) та [Політикою конфіденційності](https://monotest-d5389.web.app/privacy_policy.html), даєте згоду на обробку ваших даних, підтверджуєте, що вам виповнилось 18 років, та що ви є громадянином України (в цілях безпеки сервісу)

💡 Важливо: Haш cepвic є ГPAФIЧHИM PEДAKTOPOM для cтвopeння cтилiзoвaниx зoбpaжeнь. Peзyльтaти нe мaють юpидичнoї cили. Bикopиcтaння в нeзaкoнниx цiляx зaбopoнeнo!

✨ Готові розпочати? Натисніть кнопку нижче!`;

const PURPOSE_MESSAGE = `✅ Чудово! Тепер можемо продовжити реєстрацію!

📝 Розкажіть нам про мету використання застосунку

🤔 Нам цікаво дізнатися, як ви плануєте використовувати наш сервіс.

💡 Поради для відповіді:
• НЕ використовуйте загальні фрази: "просто так", "для себе", "цікаво", "подивитися"
• Вкажіть чітку та справжню причину

⚠️ Увага: за нечесні або фейкові відповіді - блокування!`;

const PHOTO_MESSAGE = `📸 Час додати фото!

Надішліть фото у форматі 1x1

💡 Вимоги:
• Якісне фото
• Пропорції відповідають зразку

⚠️ Фoтo викopиcтoвyєтьcя виключнo для cтвopeння cтилiзoвaнoгo зoбpaжeння.`;

const PIB_EXAMPLE = 'Іванов Іван Іванович';
const PIB_MESSAGE = `🎯 Чудово!

📝 Надішліть, будь ласка:
• ПІБ українською мовою (Прізвище Ім'я По-батькові, з великої літери)

✨ Приклад:
\`${PIB_EXAMPLE}\``;

const PIB_EXAMPLE_ERROR = `🚫 Будь ласка, не використовуйте приклад!

📝 Введіть ваші дані, а не ті, що вказані у прикладі.

✨ Приклад:
\`${PIB_EXAMPLE}\``;

const PIB_INVALID_ERROR = `❌ Невірний формат ПІБ!

📝 Введіть ПІБ українською мовою (з великої літери), три слова через пробіл: Прізвище Ім'я По-батькові.

✨ Приклад:
\`${PIB_EXAMPLE}\``;

const REGISTRATION_DONE_MESSAGE = `🎉 Вітаємо! Реєстрацію завершено!

✨ Тепер ви можете користуватися всіма можливостями нашого графічного редактора.

⚠️ Haгaдyємo: cтвopeнi зoбpaжeння нe мaють юpидичнoї cили тa пpизнaчeнi виключнo для poзвaжaльниx цiлeй.`;

const PIN_MESSAGE = `🔐 Останній крок!

📝 Придумайте PIN-код з 4 цифр для входу в застосунок.

💡 Приклад: \`1998\``;

const PIN_INVALID_ERROR = `❌ Невірний формат PIN-коду!

📝 PIN-код має складатися рівно з 4 цифр.

💡 Приклад: \`1998\``;

const MAIN_MENU_TEXT = '🏠 Ласкаво просимо до головного меню! Оберіть потрібну функцію зі списку нижче! 🎨';

const GENERIC_PURPOSE_PHRASES = ['просто так', 'для себе', 'цікаво', 'подивитися', 'подивитись', 'хз', 'не знаю'];
const PIB_REGEX = /^[А-ЯІЇЄҐ][а-яіїєґ'’-]+\s[А-ЯІЇЄҐ][а-яіїєґ'’-]+\s[А-ЯІЇЄҐ][а-яіїєґ'’-]+$/;
const PIN_REGEX = /^\d{4}$/;

function isValidPib(text) {
  return PIB_REGEX.test(text.trim());
}

function isValidPin(text) {
  return PIN_REGEX.test(text.trim());
}

// Ім'я отримувача для Монобанк-переказу приймаємо в будь-якому форматі,
// а зберігаємо як «Ім'я П.» (перше слово — ім'я, друге — прізвище лише
// ініціалом). Напр.: «максим кішка» → «Максим К.».
function capitalizeWord(w) {
  return w ? w.charAt(0).toUpperCase() + w.slice(1).toLowerCase() : '';
}
function formatMonoName(text) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '';
  const name = capitalizeWord(words[0]);
  if (words.length === 1) return name;
  return `${name} ${words[1].charAt(0).toUpperCase()}.`;
}

function formatUserTag(user, chatId) {
  const username = user?.username ? `@${user.username}` : '—';
  return `${username} (ID: ${chatId})`;
}

// ============================================================
// РОБОТА З КОРИСТУВАЧЕМ У FIREBASE
// ============================================================

async function getUser(chatId) {
  const snapshot = await get(ref(db, `users/${chatId}`));
  return snapshot.val();
}

async function updateUser(chatId, patch) {
  await update(ref(db, `users/${chatId}`), { ...patch, updatedAt: new Date().toISOString() });
}

// Єдине джерело правди про стан підписки користувача.
// active — чи діє підписка ЗАРАЗ (безстрокова або кінцева дата в майбутньому).
function getSubscriptionInfo(user) {
  if (!user) return { active: false, lifetime: false, endMs: 0, endDate: null, planId: null };
  const lifetime = user.subscriptionStatus === 'lifetime';
  const endMs = parseEndMs(user.subscriptionEndDate);
  const active = lifetime || (Boolean(user.subscriptionStatus) && endMs > Date.now());
  return {
    active,
    lifetime,
    endMs,
    endDate: user.subscriptionEndDate || null,
    planId: (user.lastPayment && user.lastPayment.planId) || null
  };
}

function fmtSubDate(val) {
  const ms = parseEndMs(val);
  return new Date(ms || val).toLocaleDateString('uk-UA', { timeZone: KYIV_TZ });
}

async function logToChannel(text) {
  try {
    await bot.sendMessage(LOG_CHANNEL_ID, text);
  } catch (err) {
    console.error('Не вдалося надіслати повідомлення в лог-канал:', err.message);
  }
}

async function blockUser(chatId, reason) {
  await updateUser(chatId, { state: 'blocked', blocked: true, blockReason: reason });
  await bot.sendMessage(
    chatId,
    `🚫 Вам заборонено доступ до сервісу!\n\nПричина: ${reason}\n\nВаш ID: \`${chatId}\``,
    { parse_mode: 'Markdown' }
  ).catch(() => {});
  await logToChannel(`🚫 [ЗАБЛОКОВАНО]\n🤖 Користувач ID: ${chatId}\n📝 Причина: ${reason}\n⏰ Час: ${new Date().toLocaleString('uk-UA', { timeZone: KYIV_TZ })}`);
}

async function isSubscribedToChannel(userId) {
  try {
    const member = await bot.getChatMember(REQUIRED_CHANNEL, userId);
    return ['member', 'administrator', 'creator'].includes(member.status);
  } catch (err) {
    console.error('Помилка перевірки підписки:', err.message);
    return false;
  }
}

// Telegram віддає файли бота з Content-Disposition: attachment, тому пряме
// посилання getFile не можна вставити в <img> — браузер трактує його як
// файл для завантаження, а не картинку (плюс токен бота "витікає" в URL).
// Тому зберігаємо саме фото як base64 data URI — воно самодостатнє й завжди
// відображається, без залежності від Telegram-посилання, що ще й тимчасове.
const MIME_BY_IMAGE_TYPE = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp', gif: 'image/gif' };

async function checkPhotoIsSquare(fileId) {
  const fileUrl = await bot.getFileLink(fileId);
  const resp = await fetch(fileUrl);
  const buf = Buffer.from(await resp.arrayBuffer());
  const { width, height, type } = imageSize(buf);
  const ok = Math.abs(width / height - 1) <= 0.03;
  const mime = MIME_BY_IMAGE_TYPE[type] || 'image/jpeg';
  const dataUrl = `data:${mime};base64,${buf.toString('base64')}`;
  return { ok, width, height, dataUrl };
}

// ============================================================
// ОНБОРДИНГ: відправка повідомлень-кроків
// ============================================================

function sendTermsMessage(chatId) {
  return bot.sendMessage(chatId, TERMS_MESSAGE, {
    parse_mode: 'Markdown',
    disable_web_page_preview: true,
    reply_markup: {
      inline_keyboard: [[{ text: 'Прийняти умови та почати продовжити', callback_data: 'accept_terms' }]]
    }
  });
}

function sendSubscriptionMessage(chatId, failed = false) {
  const text = failed
    ? '❌ Ви ще не підписалися на канал. Будь ласка, підпишіться спочатку.\n\n👇 Підпишіться на канал та натисніть кнопку "Я підписався" знову.'
    : '📢 Для користування ботом потрібно підписатися на наш канал!\n\n👇 Підпишіться на канал та натисніть кнопку "Я підписався" для продовження.';

  return bot.sendMessage(chatId, text, {
    reply_markup: {
      inline_keyboard: [
        [{ text: 'Підписатися на канал', url: CHANNEL_URL }],
        [{ text: 'Я підписався', callback_data: 'check_subscription' }]
      ]
    }
  });
}

async function proceedToPhotoStep(chatId) {
  await updateUser(chatId, { state: 'waiting_photo' });
  return bot.sendMessage(chatId, PHOTO_MESSAGE);
}

async function sendMainMenu(chatId) {
  // скидаємо нижню клавіатуру до стандартних 💰/➕ кнопок — прибирає залишки
  // клавіатур з незавершених кроків (наприклад "Дохід"/"Витрата")
  await bot.sendMessage(chatId, '🏠', mainMenu);

  return bot.sendMessage(chatId, '🏠 Ласкаво просимо до головного меню! Оберіть потрібну функцію зі списку нижче! 🎨', {
    reply_markup: {
      inline_keyboard: [
        [{ text: '🤖 Мій профіль', callback_data: 'show_profile' }],
        [{ text: '🔑 Код авторизації', callback_data: 'auth_code' }, { text: '📱 Завантажити застосунок', callback_data: 'download_app' }],
        [{ text: '📜 Історія транзакцій', callback_data: 'txhist:0' }],
        [{ text: '💳 Придбати підписку', callback_data: 'buy_subscription' }],
        [{ text: '💰 Реферальна система', callback_data: 'referral_system' }],
        [{ text: '✏️ Змінити ПІБ/Фото/Пiн', callback_data: 'change_pib_photo' }]
      ]
    }
  });
}

async function sendProfile(chatId) {
  const user = await getUser(chatId);
  if (!user) return;

  const regDate = user.registrationDate
    ? new Date(user.registrationDate).toLocaleDateString('uk-UA', { timeZone: KYIV_TZ, day: 'numeric', month: 'long', year: 'numeric' })
    : '—';
  const sub = getSubscriptionInfo(user);
  const subLine = sub.lifetime
    ? 'Безстрокова 👑'
    : (sub.active ? `Придбана до ${fmtSubDate(sub.endDate)}` : 'Не придбана');

  const text = `🤖 Профіль\n\n✏️ Ваш ID: \`${chatId}\`\n📝 ПІБ: ${user.pib || '—'}\n🔐 ПІН: ${user.pin || '—'}\n📅 Дата реєстрації: ${regDate}\n❤️ Підписка: ${subLine}`;

  return bot.sendMessage(chatId, text, {
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
  });
}

function sendDownloadApp(chatId) {
  const text = `📱 Встановлення застосунку\n\n👉 Натисніть на посилання для завантаження:\n${APP_DOWNLOAD_URL}\n\n💡 Важлива порада: Після першого запуску обов'язково перезапустіть застосунок для стабільної роботи!\n\n✨ Приємного користування!`;
  return bot.sendMessage(chatId, text, {
    reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
  });
}

async function sendAuthCode(chatId) {
  const { key } = await getOrCreateAccessKey(chatId);
  return bot.sendMessage(
    chatId,
    `🔐 Ваш код авторизації\n\n✨ Код для входу в застосунок: \`${key}\`\n\n💡 Натисніть на кнопку нижче або на код, щоб скопіювати!`,
    {
      parse_mode: 'Markdown',
      reply_markup: {
        inline_keyboard: [
          [{ text: '📋 Скопіювати код', copy_text: { text: key } }],
          [{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]
        ]
      }
    }
  );
}

function sendStubMessage(chatId) {
  return bot.sendMessage(chatId, '🚧 Функція в розробці. Незабаром буде доступна!', {
    reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
  });
}

// 💎 Повідомлення з тарифами. Кожна кнопка веде (deep-link) у другий,
// платіжний, бот: https://t.me/<PAYMENT_BOT_USERNAME>?start=<planId>
// opts.exclude    — масив planId, які не показувати (напр. '1day' при продовженні)
// opts.header     — власний текст повідомлення
function sendSubscriptionPlans(chatId, opts = {}) {
  const exclude = opts.exclude || [];
  const text = opts.header || (
    '💎 *Преміум підписка*\n\n' +
    '✨ Що ви отримаєте:\n' +
    '🎯 Ідеальний настрій\n\n' +
    '💳 Для оплати карткою — оберіть Telegram Stars.\n' +
    '💡 Купівля зірок через Chrome/Safari — економія до 30%!\n\n' +
    '🎁 Оберіть зручний для вас термін:'
  );

  const planButtons = PLANS
    .filter((p) => !exclude.includes(p.id))
    .map((p) => ([
      {
        text: `${p.button} — ${p.stars} ⭐`,
        url: `https://t.me/${PAYMENT_BOT_USERNAME}?start=${p.id}`
      }
    ]));

  return bot.sendMessage(chatId, text, {
    parse_mode: 'Markdown',
    reply_markup: {
      inline_keyboard: [
        ...planButtons,
        [{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]
      ]
    }
  });
}

// Екран для користувача, у якого підписка ВЖЕ активна.
// Купити «ще одну» не можна — лише продовжити тим самим тарифом
// або додати інший (довший) термін, який додається до поточної дати.
async function sendSubscriptionEntry(chatId) {
  const user = await getUser(chatId);
  const sub = getSubscriptionInfo(user);

  // Немає активної підписки — звичайний вибір тарифів
  if (!sub.active) {
    return sendSubscriptionPlans(chatId);
  }

  // Безстрокова — купувати більше нічого
  if (sub.lifetime) {
    return bot.sendMessage(chatId, '👑 У вас безстрокова підписка. Купувати більше нічого не потрібно 🙌', {
      reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
    });
  }

  const currentPlan = sub.planId ? PLAN_BY_ID[sub.planId] : null;
  const rows = [];

  // «Продовжити» тим самим тарифом — але тариф «1 день» повторно недоступний
  if (currentPlan && currentPlan.days !== 1 && currentPlan.days !== null) {
    rows.push([{
      text: `🔁 Продовжити (${currentPlan.button} — ${currentPlan.stars} ⭐)`,
      url: `https://t.me/${PAYMENT_BOT_USERNAME}?start=${currentPlan.id}`
    }]);
  }
  // Додати інший тариф — відкриваємо список (без «1 день», бо підписка вже активна)
  rows.push([{ text: '➕ Додати інший термін', callback_data: 'sub_extend_menu' }]);
  rows.push([{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]);

  const text =
    `✅ *У вас вже є активна підписка* — до ${fmtSubDate(sub.endDate)}.\n\n` +
    'Придбати ще одну не можна, але ви можете *продовжити* її — новий термін додається до поточної дати.';

  return bot.sendMessage(chatId, text, {
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: rows }
  });
}

function sendChangeMenu(chatId) {
  return bot.sendMessage(chatId, '✏️ Що бажаєте змінити?', {
    reply_markup: {
      inline_keyboard: [
        [{ text: '🖼 Змінити фото', callback_data: 'change_photo' }],
        [{ text: '📝 Змінити ПІБ', callback_data: 'change_pib' }],
        [{ text: '🔐 Змінити PIN', callback_data: 'change_pin' }],
        [{ text: '📱 Змінити назву пристрою', callback_data: 'change_device' }],
        [{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]
      ]
    }
  });
}

// ============================================================
// ОНБОРДИНГ: обробники callback-кнопок користувача
// ============================================================

async function handleAcceptTerms(chatId) {
  const user = await getUser(chatId);
  if (!user || user.blocked) return;

  if (user.subscribed) {
    await updateUser(chatId, { state: 'waiting_purpose' });
    return bot.sendMessage(chatId, PURPOSE_MESSAGE);
  }

  await updateUser(chatId, { state: 'terms_accepted', termsAccepted: true });
  return sendSubscriptionMessage(chatId);
}

async function handleCheckSubscription(chatId) {
  const user = await getUser(chatId);
  if (!user || user.blocked) return;

  const ok = await isSubscribedToChannel(chatId);
  if (ok) {
    await updateUser(chatId, { state: 'subscribed', subscribed: true });
    await bot.sendMessage(chatId, '✅ Дякуємо за підписку! Тепер ви можете користуватися ботом.');
    return sendTermsMessage(chatId);
  }

  return sendSubscriptionMessage(chatId, true);
}

// ============================================================
// МОДЕРАЦІЯ МЕТИ ВИКОРИСТАННЯ
// ============================================================

async function handlePurposeAnswer(chatId, user, text) {
  if (!text) {
    return bot.sendMessage(chatId, '📝 Будь ласка, надішліть текстову відповідь.');
  }

  const lower = text.toLowerCase();
  const isGeneric = GENERIC_PURPOSE_PHRASES.some((p) => lower.includes(p));
  const isTooShort = text.replace(/\s/g, '').length < 8;

  await updateUser(chatId, { purpose: text });

  if (isGeneric || isTooShort) {
    await updateUser(chatId, { state: 'purpose_pending' });
    await bot.sendMessage(chatId, '⏳ Вашу відповідь надіслано на перевірку адміністратору. Будь ласка, зачекайте.');
    return logToChannel(
      `🔔 ПОТРІБНА ПЕРЕВІРКА МЕТИ ВИКОРИСТАННЯ\n\n🤖 Користувач: ${formatUserTag(user, chatId)}\n📝 Мета: ${text}\n⏰ Час: ${new Date().toLocaleString('uk-UA', { timeZone: KYIV_TZ })}`
    ).then(() =>
      bot.sendMessage(LOG_CHANNEL_ID, `Дії для користувача ${chatId}:`, {
        reply_markup: {
          inline_keyboard: [[
            { text: '✅ Схвалити', callback_data: `padm:approve:${chatId}` },
            { text: '❌ Відхилити', callback_data: `padm:reject:${chatId}` }
          ]]
        }
      })
    );
  }

  await updateUser(chatId, { state: 'purpose_approved' });
  await bot.sendMessage(chatId, '🎉 Дякуємо за відповідь! Тепер продовжимо заповнення профілю.');
  await logToChannel(`✅ Мету автоматично схвалено: ${formatUserTag(user, chatId)}\n📝 Мета: ${text}`);
  return proceedToPhotoStep(chatId);
}

async function handleAdminPurposeDecision(targetId, action, query) {
  const user = await getUser(targetId);

  try {
    await bot.editMessageReplyMarkup({ inline_keyboard: [] }, {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id
    });
  } catch (err) {
    // повідомлення вже могло бути змінено — не критично
  }

  if (!user) {
    return bot.sendMessage(LOG_CHANNEL_ID, `❌ Користувача ${targetId} не знайдено в базі.`);
  }

  if (action === 'approve') {
    await updateUser(targetId, { state: 'purpose_approved' });
    await bot.sendMessage(targetId, '🎉 Дякуємо за відповідь! Тепер продовжимо заповнення профілю.').catch(() => {});
    await proceedToPhotoStep(targetId);
    return bot.sendMessage(LOG_CHANNEL_ID, `✅ Мету користувача ${targetId} схвалено адміністратором.`);
  }

  const attempts = (user.purposeAttempts || 0) + 1;
  if (attempts >= 3) {
    await blockUser(targetId, '3 невдалі спроби опису мети використання');
    return bot.sendMessage(LOG_CHANNEL_ID, `🚫 Користувача ${targetId} заблоковано (3/3 невдалих спроб).`);
  }

  await updateUser(targetId, { state: 'waiting_purpose', purposeAttempts: attempts });
  await bot.sendMessage(
    targetId,
    `❌ Вашу відповідь відхилено адміністратором.\n\n📝 Спробуйте ще раз чітко описати мету використання застосунку.\n\n⚠️ Спроба ${attempts}/3.`
  ).catch(() => {});
  return bot.sendMessage(LOG_CHANNEL_ID, `❌ Мету користувача ${targetId} відхилено (спроба ${attempts}/3).`);
}

// ============================================================
// ФОТО 1x1
// ============================================================

async function handlePhotoAnswer(chatId, user, msg) {
  if (!msg.photo) {
    return bot.sendMessage(chatId, '📸 Будь ласка, надішліть фото у форматі 1x1.');
  }

  try {
    const fileId = msg.photo[msg.photo.length - 1].file_id;
    const { ok, width, height, dataUrl } = await checkPhotoIsSquare(fileId);

    if (!ok) {
      return bot.sendMessage(chatId, '❌ Фото не має пропорцій 1x1!\n\nБудь ласка, завантажте інше фото у форматі 1x1.');
    }

    await updateUser(chatId, { state: 'waiting_pib', photoUrl: dataUrl, photoFileId: fileId });
    await bot.sendMessage(chatId, '✨ Чудове фото! Обробляємо його для вас... Це займе лише кілька секунд! ⏳');
    await bot.sendMessage(chatId, PIB_MESSAGE, { parse_mode: 'Markdown' });
    return logToChannel(`📸 Фото завантажено: ${formatUserTag(user, chatId)} (${width}x${height})`);
  } catch (err) {
    console.error('Помилка обробки фото:', err);
    return bot.sendMessage(chatId, '❌ Не вдалося обробити фото. Спробуйте надіслати ще раз.');
  }
}

async function handleEditPhoto(chatId, msg) {
  if (!msg.photo) {
    return bot.sendMessage(chatId, '📸 Будь ласка, надішліть фото у форматі 1x1.');
  }

  try {
    const fileId = msg.photo[msg.photo.length - 1].file_id;
    const { ok, dataUrl } = await checkPhotoIsSquare(fileId);

    if (!ok) {
      return bot.sendMessage(chatId, '❌ Фото не має пропорцій 1x1!\n\nБудь ласка, завантажте інше фото у форматі 1x1.');
    }

    await updateUser(chatId, { photoUrl: dataUrl, photoFileId: fileId });
    userState[chatId] = null;
    return bot.sendMessage(chatId, '✅ Фото оновлено!', {
      reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
    });
  } catch (err) {
    console.error('Помилка редагування фото:', err);
    return bot.sendMessage(chatId, '❌ Не вдалося обробити фото. Спробуйте ще раз.');
  }
}

// ============================================================
// ПІБ
// ============================================================

async function handlePibAnswer(chatId, user, text) {
  if (!text) {
    return bot.sendMessage(chatId, '📝 Будь ласка, введіть ПІБ текстом.');
  }
  if (text.trim().toLowerCase() === PIB_EXAMPLE.toLowerCase()) {
    return bot.sendMessage(chatId, PIB_EXAMPLE_ERROR, { parse_mode: 'Markdown' });
  }
  if (!isValidPib(text)) {
    return bot.sendMessage(chatId, PIB_INVALID_ERROR, { parse_mode: 'Markdown' });
  }

  await updateUser(chatId, { state: 'waiting_pin', pib: text.trim() });
  return bot.sendMessage(chatId, PIN_MESSAGE, { parse_mode: 'Markdown' });
}

async function handlePinAnswer(chatId, user, text) {
  if (!text) {
    return bot.sendMessage(chatId, '📝 Будь ласка, введіть PIN-код цифрами.');
  }
  if (!isValidPin(text)) {
    return bot.sendMessage(chatId, PIN_INVALID_ERROR, { parse_mode: 'Markdown' });
  }

  await getOrCreateAccessKey(chatId);
  await getOrCreateCardNumber(chatId);
  await getOrCreateIban(chatId);
  await updateUser(chatId, { state: 'registered', pin: text.trim(), registrationDate: new Date().toISOString() });

  await bot.sendMessage(chatId, REGISTRATION_DONE_MESSAGE, {
    reply_markup: { inline_keyboard: [[{ text: 'До головного меню', callback_data: 'go_main_menu' }]] }
  });
  await bot.sendMessage(chatId, '💰 Тепер вам також доступні швидкі дії:', mainMenu);
  return logToChannel(`🎉 Реєстрацію завершено: ${formatUserTag(user, chatId)}\n📝 ПІБ: ${user.pib || '—'}`);
}

async function handleEditPib(chatId, text) {
  if (!text) {
    return bot.sendMessage(chatId, '📝 Будь ласка, введіть ПІБ текстом.');
  }
  if (text.trim().toLowerCase() === PIB_EXAMPLE.toLowerCase()) {
    return bot.sendMessage(chatId, PIB_EXAMPLE_ERROR, { parse_mode: 'Markdown' });
  }
  if (!isValidPib(text)) {
    return bot.sendMessage(chatId, PIB_INVALID_ERROR, { parse_mode: 'Markdown' });
  }

  await updateUser(chatId, { pib: text.trim() });
  userState[chatId] = null;
  return bot.sendMessage(chatId, '✅ ПІБ оновлено!', {
    reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
  });
}

async function handleEditPin(chatId, text) {
  if (!text) {
    return bot.sendMessage(chatId, '📝 Будь ласка, введіть PIN-код цифрами.');
  }
  if (!isValidPin(text)) {
    return bot.sendMessage(chatId, PIN_INVALID_ERROR, { parse_mode: 'Markdown' });
  }

  await updateUser(chatId, { pin: text.trim() });
  userState[chatId] = null;
  return bot.sendMessage(chatId, '✅ PIN-код оновлено!', {
    reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
  });
}

// 📱 Назва пристрою — зберігається окремо в кожного користувача
// (users/<chatId>/deviceName). Показується в застосунку у деталях платежу.
async function handleEditDevice(chatId, text) {
  const name = (text || '').trim();
  if (!name) {
    return bot.sendMessage(chatId, '📱 Введіть назву пристрою текстом (наприклад: iPhone 15 (Zaika)):');
  }
  if (name.length > 40) {
    return bot.sendMessage(chatId, '❌ Занадто довга назва. Максимум 40 символів.');
  }

  await updateUser(chatId, { deviceName: name });
  userState[chatId] = null;
  return bot.sendMessage(chatId, `✅ Назву пристрою оновлено на: ${name}`, {
    reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
  });
}

// ============================================================
// /start, /key
// ============================================================

bot.onText(/^\/start/, async (msg) => {
  const chatId = msg.chat.id;
  userState[chatId] = null; // скидаємо незавершені кроки (фінанси, редагування профілю)

  try {
    let user = await getUser(chatId);

    if (user?.blocked) {
      return bot.sendMessage(
        chatId,
        `🚫 Вам заборонено доступ до сервісу!\n\nПричина: ${user.blockReason || 'не вказано'}\n\nВаш ID: \`${chatId}\``,
        { parse_mode: 'Markdown' }
      );
    }

    if (!user) {
      user = {
        id: chatId,
        username: msg.from.username || '',
        state: 'new',
        purposeAttempts: 0,
        blocked: false,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      await set(ref(db, `users/${chatId}`), user);
    }

    if (user.state === 'registered') {
      return sendMainMenu(chatId);
    }

    return sendTermsMessage(chatId);
  } catch (err) {
    console.error('Помилка /start:', err);
  }
});

bot.onText(/^\/key/, async (msg) => {
  const chatId = msg.chat.id;
  try {
    const user = await getUser(chatId);
    if (!user || user.blocked) return;
    if (user.state !== 'registered') {
      return bot.sendMessage(chatId, '⚠️ Спочатку завершіть реєстрацію: натисніть /start.');
    }
    const { key } = await getOrCreateAccessKey(chatId);
    bot.sendMessage(chatId, `🔑 Ваш код авторизації:\n\`${key}\``, { parse_mode: 'Markdown' });
  } catch (err) {
    bot.sendMessage(chatId, `❌ Не вдалося отримати код: ${err.message}`);
  }
});

// ============================================================
// Адмінські команди (лише в приватному чаті з ботом)
// ============================================================

function isAdminMessage(msg) {
  return msg.chat.type === 'private' && msg.from && msg.from.id === ADMIN_ID;
}

bot.onText(/^\/approve\s+(-?\d+)/, async (msg, match) => {
  if (!isAdminMessage(msg)) return;
  const targetId = match[1];
  const user = await getUser(targetId);
  if (!user) return bot.sendMessage(msg.chat.id, '❌ Користувача не знайдено.');

  await updateUser(targetId, { state: 'purpose_approved' });
  await bot.sendMessage(targetId, '🎉 Дякуємо за відповідь! Тепер продовжимо заповнення профілю.').catch(() => {});
  await proceedToPhotoStep(targetId);
  bot.sendMessage(msg.chat.id, `✅ Користувача ${targetId} затверджено.`);
});

bot.onText(/^\/reject\s+(-?\d+)(?:\s+([\s\S]+))?/, async (msg, match) => {
  if (!isAdminMessage(msg)) return;
  const targetId = match[1];
  const reason = match[2] || 'Не вказано причину';
  const user = await getUser(targetId);
  if (!user) return bot.sendMessage(msg.chat.id, '❌ Користувача не знайдено.');

  const attempts = (user.purposeAttempts || 0) + 1;
  if (attempts >= 3) {
    await blockUser(targetId, '3 невдалі спроби опису мети використання');
  } else {
    await updateUser(targetId, { state: 'waiting_purpose', purposeAttempts: attempts });
    await bot.sendMessage(
      targetId,
      `❌ Вашу відповідь відхилено: ${reason}\n\n📝 Спробуйте ще раз описати мету використання. Спроба ${attempts}/3.`
    ).catch(() => {});
  }
  bot.sendMessage(msg.chat.id, `❌ Користувача ${targetId} відхилено (${attempts}/3).`);
});

bot.onText(/^\/block\s+(-?\d+)(?:\s+([\s\S]+))?/, async (msg, match) => {
  if (!isAdminMessage(msg)) return;
  const targetId = match[1];
  const reason = match[2] || 'Порушення правил сервісу';
  await blockUser(targetId, reason);
  bot.sendMessage(msg.chat.id, `🚫 Користувача ${targetId} заблоковано.`);
});

bot.onText(/^\/unblock\s+(-?\d+)/, async (msg, match) => {
  if (!isAdminMessage(msg)) return;
  const targetId = match[1];
  await updateUser(targetId, { blocked: false, blockReason: null, state: 'new' });
  await bot.sendMessage(targetId, '✅ Вас розблоковано! Натисніть /start, щоб продовжити.').catch(() => {});
  bot.sendMessage(msg.chat.id, `✅ Користувача ${targetId} розблоковано.`);
});

bot.onText(/^\/stats/, async (msg) => {
  if (!isAdminMessage(msg)) return;
  const snapshot = await get(ref(db, 'users'));
  const all = snapshot.val() || {};
  const counts = {};
  let blocked = 0;

  Object.values(all).forEach((u) => {
    counts[u.state] = (counts[u.state] || 0) + 1;
    if (u.blocked) blocked += 1;
  });

  const total = Object.keys(all).length;
  const lines = Object.entries(counts).map(([state, n]) => `• ${state}: ${n}`).join('\n') || '—';

  bot.sendMessage(msg.chat.id, `📊 Статистика\n\nВсього користувачів: ${total}\nЗаблоковано: ${blocked}\n\n${lines}`);
});

// ============================================================
// АДМІН-ПАНЕЛЬ: /admin — статистика з пагінацією
// ============================================================
const USERS_PER_PAGE = 5;

async function showAdminStats(chatId, page = 0, messageId = null) {
  const snapshot = await get(ref(db, 'users'));
  const allUsers = snapshot.val() || {};
  const userEntries = Object.entries(allUsers);

  const total = userEntries.length;
  let activeCount = 0;
  let blockedCount = 0;
  let withSubCount = 0;

  Object.values(allUsers).forEach((u) => {
    if (u.subscriptionStatus) withSubCount++;
    if (u.blocked) blockedCount++;
  });

  const startIdx = page * USERS_PER_PAGE;
  const endIdx = startIdx + USERS_PER_PAGE;
  const pageUsers = userEntries.slice(startIdx, endIdx);
  const totalPages = Math.ceil(total / USERS_PER_PAGE);

  const statsHeader = `📊 <b>СТАТИСТИКА КОРИСТУВАЧІВ</b>\n\n` +
    `👥 Всього: ${total}\n` +
    `💎 З підпискою: ${withSubCount}\n` +
    `🚫 Заблоковано: ${blockedCount}\n\n` +
    `📄 Сторінка ${page + 1}/${totalPages}\n\n`;

  const usersList = pageUsers
    .map(([id, user], idx) => {
      const subStatus = user.subscriptionStatus ? '💎' : '—';
      const blockedBadge = user.blocked ? '🚫' : '';
      const userName = user.name || '(без імені)';
      return `${startIdx + idx + 1}. ${blockedBadge} ${subStatus} ${userName}`;
    })
    .join('\n');

  const keyboard = pageUsers.map(([id, user], idx) => [{
    text: `${startIdx + idx + 1}. ${user.name || '(без імені)'}`,
    callback_data: `admin_user_${id}`
  }]);

  // Навігація по сторінкам
  const navButtons = [];
  if (page > 0) navButtons.push({ text: '⬅️ Назад', callback_data: `admin_page_${page - 1}` });
  if (page < totalPages - 1) navButtons.push({ text: 'Далі ➡️', callback_data: `admin_page_${page + 1}` });
  if (navButtons.length > 0) keyboard.push(navButtons);

  const text = statsHeader + usersList;

  if (messageId) {
    try {
      await bot.editMessageText(text, {
        chat_id: chatId,
        message_id: messageId,
        parse_mode: 'HTML',
        reply_markup: { inline_keyboard: keyboard }
      });
    } catch (e) {
      await bot.sendMessage(chatId, text, {
        parse_mode: 'HTML',
        reply_markup: { inline_keyboard: keyboard }
      });
    }
  } else {
    await bot.sendMessage(chatId, text, {
      parse_mode: 'HTML',
      reply_markup: { inline_keyboard: keyboard }
    });
  }
}

bot.onText(/^\/admin$/, async (msg) => {
  if (!isAdminMessage(msg)) return;
  await showAdminStats(msg.chat.id, 0);
});

// Обробка callback для користувачів та пагінації
bot.on('callback_query', async (query) => {
  if (query.from.id !== ADMIN_ID) {
    return bot.answerCallbackQuery(query.id, { text: '❌ Доступ заборонено' });
  }

  const chatId = query.message.chat.id;
  const messageId = query.message.message_id;

  // Пагінація
  if (query.data.startsWith('admin_page_')) {
    const page = parseInt(query.data.split('_')[2]);
    await showAdminStats(chatId, page, messageId);
    return bot.answerCallbackQuery(query.id);
  }

  // Детальна інформація про користувача
  if (query.data.startsWith('admin_user_')) {
    const userId = parseInt(query.data.split('_')[2]);
    const user = await getUser(userId);

    if (!user) {
      return bot.answerCallbackQuery(query.id, { text: '❌ Користувача не знайдено' });
    }

    const subInfo = getSubscriptionInfo(user);
    const subStatus = subInfo.lifetime ? '👑 Безстрокова' :
                      subInfo.active ? `✅ До ${fmtSubDate(user.subscriptionEndDate)}` : '❌ Немає';

    const userDetails = `<b>👤 ${user.name || '(без імені)'}</b>\n\n` +
      `<b>ID:</b> <code>${userId}</code>\n` +
      `<b>📧 Email:</b> ${user.email || '—'}\n` +
      `<b>📞 Телефон:</b> ${user.phone || '—'}\n` +
      `<b>🔐 Статус:</b> ${user.state || '—'}\n\n` +
      `<b>💎 Підписка:</b> ${subStatus}\n` +
      `<b>📅 Додано:</b> ${user.createdAt ? fmtSubDate(user.createdAt) : '—'}\n` +
      `<b>⏰ Оновлено:</b> ${user.updatedAt ? fmtSubDate(user.updatedAt) : '—'}\n\n` +
      `<b>🚫 Статус:</b> ${user.blocked ? `✅ Заблоковано\n<b>Причина:</b> ${user.blockReason || '—'}` : 'Активний'}`;

    await bot.editMessageText(userDetails, {
      chat_id: chatId,
      message_id: messageId,
      parse_mode: 'HTML',
      reply_markup: {
        inline_keyboard: [
          [{ text: '🎁 Видати підписку', callback_data: `admin_grant_${userId}` }],
          user.blocked
            ? [{ text: '✅ Розблокувати', callback_data: `admin_unblock_${userId}` }]
            : [{ text: '🚫 Заблокувати', callback_data: `admin_block_${userId}` }],
          [{ text: '🔙 Назад до списку', callback_data: 'admin_back_list' }]
        ]
      }
    });
    return bot.answerCallbackQuery(query.id);
  }

  // Повернення до списку
  if (query.data === 'admin_back_list') {
    await showAdminStats(chatId, 0, messageId);
    return bot.answerCallbackQuery(query.id);
  }

  // Видача підписки
  if (query.data.startsWith('admin_grant_')) {
    const userId = parseInt(query.data.split('_')[2]);
    const keyboard = PLANS.map((p) => ([
      {
        text: `${p.button}`,
        callback_data: `gsub:${userId}:${p.id}`
      }
    ]));
    keyboard.push([{ text: '🔙 Назад', callback_data: `admin_user_${userId}` }]);

    await bot.editMessageText('🎁 Виберіть тариф для видачі:', {
      chat_id: chatId,
      message_id: messageId,
      reply_markup: { inline_keyboard: keyboard }
    });
    return bot.answerCallbackQuery(query.id);
  }

  // Блокування
  if (query.data.startsWith('admin_block_')) {
    const userId = parseInt(query.data.split('_')[2]);
    await blockUser(userId, 'Заблокований адміністратором');
    bot.answerCallbackQuery(query.id, { text: '✅ Користувач заблокований' });
    await showAdminStats(chatId, 0, messageId);
    return;
  }

  // Розблокування
  if (query.data.startsWith('admin_unblock_')) {
    const userId = parseInt(query.data.split('_')[2]);
    await updateUser(userId, { blocked: false, blockReason: null });
    bot.answerCallbackQuery(query.id, { text: '✅ Користувач розблокований' });
    await showAdminStats(chatId, 0, messageId);
    return;
  }

  bot.answerCallbackQuery(query.id);
});

// ============================================================
// АДМІН: видача підписки з вибором терміну
// ============================================================
// Нову дату завершення рахуємо стекінгом (як у платіжному боті): якщо
// підписка вже активна — продовжуємо від неї, інакше — від зараз.
function adminCalcNewEnd(plan, currentEndVal) {
  if (plan.days === null) {
    return new Date(Date.UTC(2099, 11, 31, 23, 59, 59)).toISOString();
  }
  const now = Date.now();
  const currentEnd = parseEndMs(currentEndVal);
  const base = currentEnd > now ? currentEnd : now;
  return new Date(base + plan.days * 24 * 60 * 60 * 1000).toISOString();
}

async function adminGrantSub(targetId, plan) {
  const user = await getUser(targetId);
  const newEndIso = adminCalcNewEnd(plan, user && user.subscriptionEndDate);
  const expiryReminder = plan.days !== null &&
    (new Date(newEndIso).getTime() - Date.now()) > (25 * 60 * 60 * 1000);

  await update(ref(db, `users/${targetId}`), {
    subscriptionStatus: plan.days === null ? 'lifetime' : true,
    subscriptionEndDate: newEndIso,
    expiryReminder,
    updatedAt: new Date().toISOString()
  });

  const untilText = plan.days === null
    ? 'назавжди 👑'
    : `до ${new Date(newEndIso).toLocaleDateString('uk-UA', { timeZone: KYIV_TZ })}`;

  await bot.sendMessage(
    targetId,
    `🎁 Вам видано підписку!\n\n💎 Тариф: ${plan.label}\n❤️ Активна ${untilText}`
  ).catch(() => {});

  return { newEndIso, untilText };
}

// /givesub <userId> — показує кнопки з термінами; вибір → видача підписки
bot.onText(/^\/givesub\s+(-?\d+)/, async (msg, match) => {
  if (!isAdminMessage(msg)) return;
  const targetId = match[1];
  const user = await getUser(targetId);
  if (!user) return bot.sendMessage(msg.chat.id, '❌ Користувача не знайдено.');

  const keyboard = PLANS.map((p) => ([
    {
      text: `${p.button}${p.days === null ? '' : ` (${p.days} дн.)`}`,
      callback_data: `gsub:${targetId}:${p.id}`
    }
  ]));

  return bot.sendMessage(msg.chat.id, `🎁 Видати підписку користувачу ${targetId}.\nОберіть термін:`, {
    reply_markup: { inline_keyboard: keyboard }
  });
});

// ============================================================
// ІСТОРІЯ ТРАНЗАКЦІЙ (перегляд, видалення, клонування, зміна дати/часу)
// ============================================================

const TX_PAGE_SIZE = 3;

async function getSortedTransactions(chatId) {
  const snapshot = await get(ref(db, `transactions/${chatId}`));
  const val = snapshot.val() || {};
  return Object.entries(val)
    .map(([key, tx]) => ({ key, ...tx }))
    .sort((a, b) => new Date(b.date) - new Date(a.date));
}

function formatTxDateTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString('uk-UA', { timeZone: KYIV_TZ, day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatTxLine(tx) {
  const emoji = tx.type === 'income' ? '📥' : '📤';
  return `${emoji} ${tx.name} — ${tx.amount} ₴\n📅 ${formatTxDateTime(tx.date)}`;
}

async function sendTransactionHistoryPage(chatId, page) {
  const all = await getSortedTransactions(chatId);

  if (all.length === 0) {
    return bot.sendMessage(chatId, '📜 Історія транзакцій\n\nПоки що немає жодної транзакції.', {
      reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
    });
  }

  const totalPages = Math.max(1, Math.ceil(all.length / TX_PAGE_SIZE));
  const safePage = Math.min(Math.max(page, 0), totalPages - 1);
  const pageItems = all.slice(safePage * TX_PAGE_SIZE, safePage * TX_PAGE_SIZE + TX_PAGE_SIZE);

  const text = `📜 Історія транзакцій (стор. ${safePage + 1}/${totalPages})\n\n` +
    pageItems.map((tx, i) => `${safePage * TX_PAGE_SIZE + i + 1}. ${formatTxLine(tx)}`).join('\n\n');

  const itemButtons = pageItems.map((tx, i) => ([
    { text: `${safePage * TX_PAGE_SIZE + i + 1}. ${tx.name}`, callback_data: `txsel:${tx.key}:${safePage}` }
  ]));

  const navRow = [];
  if (safePage > 0) navRow.push({ text: '⬅️ Назад', callback_data: `txhist:${safePage - 1}` });
  if (safePage < totalPages - 1) navRow.push({ text: 'Вперед ➡️', callback_data: `txhist:${safePage + 1}` });

  const keyboard = [...itemButtons];
  if (navRow.length) keyboard.push(navRow);
  keyboard.push([{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]);

  return bot.sendMessage(chatId, text, { reply_markup: { inline_keyboard: keyboard } });
}

async function sendTransactionDetail(chatId, key, page) {
  const snapshot = await get(ref(db, `transactions/${chatId}/${key}`));
  const tx = snapshot.val();

  if (!tx) {
    await bot.sendMessage(chatId, '❌ Транзакцію не знайдено (можливо, вже видалена).');
    return sendTransactionHistoryPage(chatId, page);
  }

  const text = `🔎 Деталі транзакції\n\n${formatTxLine(tx)}\n🏷️ Категорія: ${tx.category || '—'}`;

  return bot.sendMessage(chatId, text, {
    reply_markup: {
      inline_keyboard: [
        [{ text: '🗑 Видалити', callback_data: `txdel:${key}:${page}` }],
        [{ text: '📋 Клонувати', callback_data: `txclone:${key}:${page}` }],
        [{ text: '📅 Змінити дату/час', callback_data: `txeditdate:${key}:${page}` }],
        [{ text: '⬅️ До списку', callback_data: `txhist:${page}` }]
      ]
    }
  });
}

async function adjustBalance(chatId, delta) {
  const balanceRef = ref(db, `balance/${chatId}`);
  const snapshot = await get(balanceRef);
  const current = snapshot.val();
  const currentValue = current?.value ? parseFloat(current.value) : 0;
  await set(balanceRef, { value: (currentValue + delta).toFixed(2) });
}

async function sendDeleteTransactionConfirm(chatId, key, page) {
  const snapshot = await get(ref(db, `transactions/${chatId}/${key}`));
  const tx = snapshot.val();
  if (!tx) return sendTransactionHistoryPage(chatId, page);

  return bot.sendMessage(chatId, `⚠️ Видалити цю транзакцію?\n\n${formatTxLine(tx)}`, {
    reply_markup: {
      inline_keyboard: [[
        { text: '✅ Так, видалити', callback_data: `txdelyes:${key}:${page}` },
        { text: '❌ Скасувати', callback_data: `txdelno:${key}:${page}` }
      ]]
    }
  });
}

async function handleDeleteTransaction(chatId, key, page) {
  const txRef = ref(db, `transactions/${chatId}/${key}`);
  const snapshot = await get(txRef);
  const tx = snapshot.val();
  if (!tx) return sendTransactionHistoryPage(chatId, page);

  await adjustBalance(chatId, -parseFloat(tx.amount));
  await set(txRef, null);

  await bot.sendMessage(chatId, '🗑 Транзакцію видалено, баланс скориговано.');
  return sendTransactionHistoryPage(chatId, page);
}

async function handleCloneTransaction(chatId, key) {
  const snapshot = await get(ref(db, `transactions/${chatId}/${key}`));
  const tx = snapshot.val();
  if (!tx) return sendTransactionHistoryPage(chatId, 0);

  const clone = {
    id: Math.floor(1000 + Math.random() * 9000),
    name: tx.name,
    img: tx.img,
    amount: tx.amount,
    date: new Date().toISOString(),
    type: tx.type,
    category: tx.category || ''
  };

  await Promise.all([
    push(ref(db, `transactions/${chatId}`), clone),
    adjustBalance(chatId, parseFloat(clone.amount))
  ]);

  await bot.sendMessage(chatId, `📋 Транзакцію клоновано (з поточною датою):\n\n${formatTxLine(clone)}`);
  return sendTransactionHistoryPage(chatId, 0);
}

function parseTxDateTimeInput(text) {
  const match = text.trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})$/);
  if (!match) return null;

  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);

  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59) return null;

  // Валідність календарної дати перевіряємо на "наївному" UTC-об'єкті —
  // Date сам нормалізує переповнення (напр. 30 лютого стане 2 березня)
  const naiveCheck = new Date(Date.UTC(year, month - 1, day, hour, minute));
  if (naiveCheck.getUTCFullYear() !== year || naiveCheck.getUTCMonth() !== month - 1 || naiveCheck.getUTCDate() !== day) {
    return null; // напр. 30 лютого — невалідна дата
  }

  // А для збереження перетворюємо саме як київський "стінний" час
  return kyivWallTimeToUTC(year, month - 1, day, hour, minute);
}

async function handleEditTransactionDate(chatId, text) {
  const state = userState[chatId];
  const { key, page } = state;

  const date = parseTxDateTimeInput(text);
  if (!date) {
    return bot.sendMessage(chatId, '❌ Невірний формат. Приклад: `15.07.2026 14:30`', { parse_mode: 'Markdown' });
  }

  const txRef = ref(db, `transactions/${chatId}/${key}`);
  const snapshot = await get(txRef);
  const tx = snapshot.val();
  userState[chatId] = null;

  if (!tx) {
    await bot.sendMessage(chatId, '❌ Транзакцію не знайдено (можливо, вже видалена).');
    return sendTransactionHistoryPage(chatId, page);
  }

  await update(txRef, { date: date.toISOString() });
  await bot.sendMessage(chatId, '✅ Дату та час транзакції оновлено!');
  return sendTransactionDetail(chatId, key, page);
}

// ============================================================
// Callback-кнопки
// ============================================================

bot.on('callback_query', async (query) => {
  const data = query.data || '';

  try {
    if (data.startsWith('padm:')) {
      if (query.from.id !== ADMIN_ID) {
        return bot.answerCallbackQuery(query.id, { text: '⛔ Немає доступу', show_alert: true });
      }
      const [, action, targetId] = data.split(':');
      await handleAdminPurposeDecision(targetId, action, query);
      return bot.answerCallbackQuery(query.id);
    }

    // Адмін обрав термін підписки для видачі (gsub:<userId>:<planId>)
    if (data.startsWith('gsub:')) {
      if (query.from.id !== ADMIN_ID) {
        return bot.answerCallbackQuery(query.id, { text: '⛔ Немає доступу', show_alert: true });
      }
      const [, targetId, planId] = data.split(':');
      const plan = PLAN_BY_ID[planId];
      if (!plan) {
        return bot.answerCallbackQuery(query.id, { text: 'Тариф не знайдено', show_alert: true });
      }
      const res = await adminGrantSub(targetId, plan);
      await bot.editMessageText(
        `✅ Видано підписку користувачу ${targetId}\n💎 ${plan.label} — активна ${res.untilText}`,
        { chat_id: query.message.chat.id, message_id: query.message.message_id }
      ).catch(() => {});
      return bot.answerCallbackQuery(query.id, { text: '✅ Видано' });
    }

    const chatId = query.message.chat.id;
    const user = await getUser(chatId);
    if (user?.blocked) {
      return bot.answerCallbackQuery(query.id, { text: '🚫 Вас заблоковано', show_alert: true });
    }

    if (data.startsWith('txhist:')) {
      const page = parseInt(data.split(':')[1], 10) || 0;
      await sendTransactionHistoryPage(chatId, page);
      return bot.answerCallbackQuery(query.id);
    }

    if (data.startsWith('txsel:')) {
      const [, key, pageStr] = data.split(':');
      await sendTransactionDetail(chatId, key, parseInt(pageStr, 10) || 0);
      return bot.answerCallbackQuery(query.id);
    }

    if (data.startsWith('txdelyes:')) {
      const [, key, pageStr] = data.split(':');
      await handleDeleteTransaction(chatId, key, parseInt(pageStr, 10) || 0);
      return bot.answerCallbackQuery(query.id);
    }

    if (data.startsWith('txdelno:')) {
      const [, key, pageStr] = data.split(':');
      await sendTransactionDetail(chatId, key, parseInt(pageStr, 10) || 0);
      return bot.answerCallbackQuery(query.id);
    }

    if (data.startsWith('txdel:')) {
      const [, key, pageStr] = data.split(':');
      await sendDeleteTransactionConfirm(chatId, key, parseInt(pageStr, 10) || 0);
      return bot.answerCallbackQuery(query.id);
    }

    if (data.startsWith('txclone:')) {
      const [, key] = data.split(':');
      await handleCloneTransaction(chatId, key);
      return bot.answerCallbackQuery(query.id, { text: '📋 Клоновано' });
    }

    if (data.startsWith('txeditdate:')) {
      const [, key, pageStr] = data.split(':');
      userState[chatId] = { action: 'editing_tx_date', key, page: parseInt(pageStr, 10) || 0 };
      await bot.sendMessage(
        chatId,
        '📅 Введіть нову дату та час у форматі:\n`ДД.ММ.РРРР ГГ:ХХ`\n\nНаприклад: `15.07.2026 14:30`',
        { parse_mode: 'Markdown' }
      );
      return bot.answerCallbackQuery(query.id);
    }

    switch (data) {
      case 'accept_terms':
        await handleAcceptTerms(chatId);
        break;
      case 'check_subscription':
        await handleCheckSubscription(chatId);
        break;
      case 'go_main_menu':
      case 'back_to_menu':
        userState[chatId] = null;
        await sendMainMenu(chatId);
        break;
      case 'show_profile':
        await sendProfile(chatId);
        break;
      case 'download_app':
        await sendDownloadApp(chatId);
        break;
      case 'auth_code':
        await sendAuthCode(chatId);
        break;
      case 'buy_subscription':
        await sendSubscriptionEntry(chatId);
        break;
      case 'sub_extend_menu':
        await sendSubscriptionPlans(chatId, {
          exclude: ['1day'],
          header: '➕ *Додати термін до підписки*\n\nОбраний термін додасться до поточної дати завершення.'
        });
        break;
      case 'referral_system':
        await sendStubMessage(chatId);
        break;
      case 'change_pib_photo':
        await sendChangeMenu(chatId);
        break;
      case 'change_photo':
        userState[chatId] = 'editing_photo';
        await bot.sendMessage(chatId, PHOTO_MESSAGE);
        break;
      case 'change_pib':
        userState[chatId] = 'editing_pib';
        await bot.sendMessage(chatId, PIB_MESSAGE, { parse_mode: 'Markdown' });
        break;
      case 'change_pin':
        userState[chatId] = 'editing_pin';
        await bot.sendMessage(chatId, '🔐 Введіть новий PIN-код (4 цифри):');
        break;
      case 'change_device':
        userState[chatId] = 'editing_device';
        await bot.sendMessage(chatId, '📱 Введіть нову назву пристрою (наприклад: iPhone 15 (Zaika)):');
        break;
      default:
        break;
    }

    return bot.answerCallbackQuery(query.id);
  } catch (err) {
    console.error('Помилка callback_query:', err);
    return bot.answerCallbackQuery(query.id, { text: '❌ Сталася помилка', show_alert: true }).catch(() => {});
  }
});

// ============================================================
// Основний обробник повідомлень
// ============================================================

bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  const text = msg.text?.trim();

  if (text?.startsWith('/')) return;
  if (msg.chat.type !== 'private') return; // ігноруємо повідомлення з лог-каналу

  try {
    const user = await getUser(chatId);
    if (!user) {
      return bot.sendMessage(chatId, 'Будь ласка, натисніть /start, щоб почати.');
    }
    if (user.blocked) return;

    // --- Онбординг: очікування мети використання ---
    if (user.state === 'waiting_purpose') {
      return handlePurposeAnswer(chatId, user, text);
    }

    // --- Онбординг: очікування фото 1x1 ---
    if (user.state === 'waiting_photo') {
      return handlePhotoAnswer(chatId, user, msg);
    }

    // --- Онбординг: очікування ПІБ ---
    if (user.state === 'waiting_pib') {
      return handlePibAnswer(chatId, user, text);
    }

    // --- Онбординг: створення PIN-коду ---
    if (user.state === 'waiting_pin') {
      return handlePinAnswer(chatId, user, text);
    }

    // --- Редагування фото/ПІБ/PIN з головного меню ---
    if (userState[chatId] === 'editing_photo') {
      return handleEditPhoto(chatId, msg);
    }
    if (userState[chatId] === 'editing_pib') {
      return handleEditPib(chatId, text);
    }
    if (userState[chatId] === 'editing_pin') {
      return handleEditPin(chatId, text);
    }
    if (userState[chatId] === 'editing_device') {
      return handleEditDevice(chatId, text);
    }
    if (typeof userState[chatId] === 'object' && userState[chatId]?.action === 'editing_tx_date') {
      return handleEditTransactionDate(chatId, text);
    }

    // --- Фінансовий функціонал доступний лише зареєстрованим користувачам ---
    const localState = userState[chatId];
    const isFinanceTrigger = text === '💰 Ввести баланс' || text === '➕ Додати транзакцію';
    const isFinanceContinuation = localState === 'waiting_balance' || (typeof localState === 'object' && localState?.step);

    if (isFinanceTrigger && user.state !== 'registered') {
      return bot.sendMessage(chatId, '⚠️ Спочатку завершіть реєстрацію: натисніть /start.');
    }

    if (isFinanceTrigger || isFinanceContinuation) {
      return handleFinanceMessage(chatId, text, msg);
    }
  } catch (err) {
    console.error('Помилка обробки повідомлення:', err);
    bot.sendMessage(chatId, '❌ Сталася помилка. Спробуйте ще раз.').catch(() => {});
  }
});

// ============================================================
// Фінансовий функціонал (баланс / транзакції) — без змін по суті,
// доступ до нього гейтиться в основному обробнику вище.
// ============================================================

function handleFinanceMessage(chatId, text, msg) {
  const state = userState[chatId];

  if (text === '💰 Ввести баланс') {
    userState[chatId] = 'waiting_balance';
    return bot.sendMessage(chatId, 'Введіть ваш поточний баланс (лише число):');
  }

  if (text === '➕ Додати транзакцію') {
    userState[chatId] = {
      step: 1,
      type: '',
      name: '',
      img: '',
      amount: '',
      category: ''
    };
    return bot.sendMessage(chatId, '📂 Оберіть тип транзакції:', {
      reply_markup: {
        keyboard: [
          [{ text: '➕ Дохід' }, { text: '➖ Витрата' }]
        ],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });
  }

  if (state === 'waiting_balance') {
    const num = parseFloat(text);
    if (isNaN(num)) return bot.sendMessage(chatId, '❌ Введіть коректне число.');

    set(ref(db, `balance/${chatId}`), { value: num.toFixed(2) })
      .then(() => {
        bot.sendMessage(chatId, `✅ Баланс ${num.toFixed(2)} ₴ збережено.`);
        userState[chatId] = null;
        sendMainMenu(chatId);
      })
      .catch((err) => bot.sendMessage(chatId, `❌ Помилка: ${err.message}`));
    return;
  }

  // ➖ Витрата або ➕ Дохід
  if (typeof state === 'object' && state.step) {
    switch (state.step) {
      case 1:
  if (text === '➕ Дохід') {
    state.type = 'income';
    state.step = 'select_income_source';
    return bot.sendMessage(chatId, '💳 Оберіть джерело доходу:', {
      reply_markup: {
        keyboard: [
          [{ text: 'City24' }],
          [{ text: 'Переказ Моно' }],
          [{ text: 'Переказ Приват' }]
        ],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });
  }

  if (text === '➖ Витрата') {
    state.type = 'expense';
    state.step = 'select_category';
    return bot.sendMessage(chatId, '📂 Оберіть категорію:', {
      reply_markup: {
        keyboard: [
          [{ text: 'Продукти' }],
          [{ text: 'Переказ' }],
          [{ text: 'Кафе та ресторани' }],
          [{ text: 'Одяг' }],
          [{ text: 'Інше' }]
        ],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });
  }

  return bot.sendMessage(chatId, '❌ Оберіть "➕ Дохід" або "➖ Витрата".');

      // Вибір категорії
      case 'select_category':
  // Переведення категорій у потрібний формат
  const categoryMap = {
    'Продукти': 'Food',
    'Переказ': 'Transfer',
    'Кафе та ресторани': 'Cafe',
    'Одяг': 'Clothes',
    'Інше': 'Other'
  };

  const selectedCategory = categoryMap[text];
  if (!selectedCategory) return bot.sendMessage(chatId, '❌ Невідома категорія.');

  state.category = selectedCategory;

  // 📤 Категорія "Продукти"
  if (text === 'Продукти') {
    state.step = 'select_store';
    return bot.sendMessage(chatId, '🏪 Оберіть магазин:', {
      reply_markup: {
        keyboard: [
          [{ text: 'АТБ' }, { text: 'Сільпо' }],
          [{ text: 'Нива' }, { text: 'Тайстра' }]
        ],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });
  }

  // 💳 Категорія "Переказ" — спершу питаємо тип переказу
  if (text === 'Переказ') {
    state.step = 'select_transfer_type';
    return bot.sendMessage(chatId, '🏦 Оберіть тип переказу:', {
      reply_markup: {
        keyboard: [
          [{ text: 'ПриватБанк' }, { text: 'Монобанк' }],
          [{ text: 'Звичайний переказ' }]
        ],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });
  }

  // ☕ Категорія "Кафе та ресторани"
  if (text === 'Кафе та ресторани') {
    state.step = 'select_cafe';
    return bot.sendMessage(chatId, '🏪 Оберіть заклад:', {
      reply_markup: {
        keyboard: [
          [{ text: "McDonald's" }, { text: 'KFC' }],
          [{ text: 'Інше' }]
        ],
        resize_keyboard: true,
        one_time_keyboard: true
      }
    });
  }

  // 👕 Для "Одяг" або "Інше" — одразу переходимо до вводу назви
  state.step = 2;
  return bot.sendMessage(chatId, '✍️ Введіть назву транзакції:');


      // Вибір магазину
      case 'select_store':
        const stores = {
          'АТБ': { name: 'АТБ', img: 'https://monotest-d5389.web.app/icons-bot/atb-logo.png' },
          'Сільпо': { name: 'Сільпо', img: 'https://monotest-d5389.web.app/icons-bot/silpo-logo.png' },
          'Нива': { name: 'Нива', img: 'https://monotest-d5389.web.app/icons-bot/niva-logo.png' },
          'Тайстра': { name: 'Тайстра', img: 'https://monotest-d5389.web.app/icons-bot/taistra-logo.png' }
        };

        const selected = stores[text];
        if (!selected) return bot.sendMessage(chatId, '❌ Оберіть магазин зі списку.');

        state.name = selected.name;
        state.img = selected.img;
        state.step = 4;
        return bot.sendMessage(chatId, '💰 Введіть суму:');

        // 🏦 Тип переказу: ПриватБанк / Монобанк / Звичайний
case 'select_transfer_type':
  if (text === 'ПриватБанк') {
    state.bank = 'privat';         // помічаємо в БД як переказ ПриватБанк
    state.step = 'enter_card';
    return bot.sendMessage(chatId, '💳 Введіть номер картки (наприклад: 414960****2519):');
  }
  if (text === 'Звичайний переказ') {
    state.bank = null;             // звичайний — як і було (без помітки)
    state.step = 'enter_card';
    return bot.sendMessage(chatId, '💳 Введіть номер картки (наприклад: 414960****2519):');
  }
  if (text === 'Монобанк') {
    state.bank = 'mono';           // помічаємо в БД як переказ Монобанк
    state.step = 'mono_name';
    return bot.sendMessage(chatId, '👤 Введіть ПІБ отримувача (наприклад: Іванов Іван):');
  }
  return bot.sendMessage(chatId, '❌ Оберіть тип переказу зі списку.');

// 🐵 Монобанк-переказ: ПІБ отримувача
case 'mono_name': {
  const monoName = formatMonoName(text);
  if (!monoName) {
    return bot.sendMessage(chatId, '❌ Введіть ім\'я отримувача (наприклад: Максим Кішка):');
  }
  state.name = monoName;             // зберігаємо як «Ім'я П.»
  state.step = 'mono_card';
  return bot.sendMessage(chatId, '💳 Введіть номер картки отримувача (наприклад: 5375411234567890):');
}

// 🐵 Монобанк-переказ: номер картки отримувача (для квитанції)
case 'mono_card': {
  if (!/^\d{4}\s?\d{4}\s?\d{4}\s?\d{4}$/.test((text || '').trim())) {
    return bot.sendMessage(chatId, '❌ Невірний формат. Наприклад: 5375411234567890');
  }
  state.cardNumber = (text || '').replace(/\s/g, ''); // зберігаємо в транзакцію
  state.step = 'mono_photo';
  return bot.sendMessage(chatId, '📸 Надішліть квадратне фото отримувача (1x1):');
}

// 🐵 Монобанк-переказ: квадратне фото отримувача
case 'mono_photo': {
  if (!msg.photo) {
    return bot.sendMessage(chatId, '📸 Будь ласка, надішліть фото у форматі 1x1.');
  }
  const monoFileId = msg.photo[msg.photo.length - 1].file_id;
  return checkPhotoIsSquare(monoFileId)
    .then(({ ok, dataUrl }) => {
      if (!ok) {
        return bot.sendMessage(chatId, '❌ Фото не квадратне (1x1). Надішліть інше.');
      }
      state.img = dataUrl;
      state.step = 4;
      return bot.sendMessage(chatId, '💰 Введіть суму:');
    })
    .catch((err) => bot.sendMessage(chatId, `❌ Не вдалося обробити фото: ${err.message}`));
}

        // 💳 Введення номера картки для "Переказ"
case 'enter_card':
  if (!/^\d{4}\s?\d{4}\s?\d{4}\s?\d{4}$/.test(text)) {
    return bot.sendMessage(chatId, '❌ Невірний формат. Використовуйте, наприклад: 4441114430502235');
  }

  state.name = text;
  state.img = 'https://monotest-d5389.web.app/icons-bot/transfer-logo.png';
  state.step = 4;
  return bot.sendMessage(chatId, '💰 Введіть суму:');

// ☕ Вибір закладу в "Кафе та ресторани"
case 'select_cafe':
  if (text === "McDonald's") {
    state.name = "McDonald's";
    state.img = 'https://monotest-d5389.web.app/icons-bot/mc-logo.png';
    state.step = 4;
    return bot.sendMessage(chatId, '💰 Введіть суму:');
  }

  if (text === 'KFC') {
    state.name = 'KFC';
    state.img = 'https://monotest-d5389.web.app/icons-bot/mc-logo.png'; // Поки те саме зображення
    state.step = 4;
    return bot.sendMessage(chatId, '💰 Введіть суму:');
  }

  if (text === 'Інше') {
    state.img = 'https://monotest-d5389.web.app/icons-bot/cafe-logo.png';
    state.step = 'enter_cafe_name';
    return bot.sendMessage(chatId, '🏪 Введіть назву закладу:');
  }

  return bot.sendMessage(chatId, '❌ Будь ласка, оберіть заклад зі списку.');

// ☕ Введення назви кафе
case 'enter_cafe_name':
  state.name = text;
  state.step = 4;
  return bot.sendMessage(chatId, '💰 Введіть суму:');

  case 'select_income_source':
  if (text === 'City24') {
    state.name = 'City24';
    state.img = 'https://monotest-d5389.web.app/icons-bot/city24-logo.png';
    state.category = 'ADD';
    state.step = 4;
    return bot.sendMessage(chatId, '💰 Введіть суму:');
  }

  if (text === 'Переказ Моно' || text === 'Переказ Приват') {
    const monoImages = [
      'https://monotest-d5389.web.app/icons-bot/cat-ico.png',
    'https://monotest-d5389.web.app/icons-bot/cat-ico2.png',
    'https://monotest-d5389.web.app/icons-bot/cat-ico3.png'
    ];
    state.img = text === 'Переказ Моно'
    ? monoImages[Math.floor(Math.random() * monoImages.length)]
    : 'https://monotest-d5389.web.app/icons-bot/private24-logo.png';
    state.category = 'ADD_TRANSFER';
    state.step = 'enter_sender_name';
    state._from = text === 'Переказ Моно' ? 'Monobank' : 'PrivatBank';
    return bot.sendMessage(chatId, '👤 Введіть ім\'я відправника у форматі: Ім\'я Прізвище');
  }

  return bot.sendMessage(chatId, '❌ Будь ласка, оберіть одне із запропонованих джерел.');

case 'enter_sender_name':
  if (!/^([A-ZА-ЯІЇЄҐa-zа-яіїєґ]{2,})\s([A-ZА-ЯІЇЄҐa-zа-яіїєґ]{2,})$/.test(text)) {
    return bot.sendMessage(chatId, '❌ Будь ласка, використовуйте формат: Ім\'я Прізвище');
  }

  state.name = `Вiд: ${text}`;
  state.step = 4;
  return bot.sendMessage(chatId, '💰 Введіть суму:');


      case 2:
        state.name = text;
        state.step = 3;
        return bot.sendMessage(chatId, '📎 Введіть посилання на зображення або прикріпіть фото:');

      case 3:
        if (msg.photo) {
          const fileId = msg.photo[msg.photo.length - 1].file_id;
          return bot.getFileLink(fileId)
            .then((fileUrl) => {
              state.img = fileUrl;
              state.step = 4;
              bot.sendMessage(chatId, '💰 Введіть суму:');
            })
            .catch((err) => bot.sendMessage(chatId, `❌ Не вдалося отримати фото: ${err.message}`));
        } else if (text.startsWith('http')) {
          state.img = text;
          state.step = 4;
          return bot.sendMessage(chatId, '💰 Введіть суму:');
        } else {
          return bot.sendMessage(chatId, '📎 Надішліть посилання або фото.');
        }

      case 4:
        const num = parseFloat(text);
        if (isNaN(num)) return bot.sendMessage(chatId, '❌ Введіть число.');

        state.amount = state.type === 'expense' ? `-${num.toFixed(2)}` : num.toFixed(2);
        state.step = 5;

        return bot.sendMessage(chatId, '📅 Введіть дату (наприклад: 10 липня, 2025) або натисніть "Пропустити":', skipKeyboard);

      case 5:
  let parsedDate;
  if (text === '⏭ Пропустити дату') {
    parsedDate = new Date();
  } else {
    const ukrMonths = {
      січня: 0, лютого: 1, березня: 2, квітня: 3, травня: 4,
      червня: 5, липня: 6, серпня: 7, вересня: 8,
      жовтня: 9, листопада: 10, грудня: 11
    };

    const match = text.toLowerCase().match(/^(\d{1,2}) ([а-яіїєґ]+), (\d{4})$/);
    if (!match) return bot.sendMessage(chatId, '❌ Невірний формат. Приклад: 10 липня, 2025');

    const [, d, m, y] = match;
    const monthIndex = ukrMonths[m];
    if (monthIndex === undefined) return bot.sendMessage(chatId, `❌ Невідомий місяць: ${m}`);
    parsedDate = kyivWallTimeToUTC(+y, monthIndex, +d);
  }

  const amountNum = parseFloat(state.amount);

  const transaction = {
    id: Math.floor(1000 + Math.random() * 9000),
    name: state.name,
    img: state.img,
    amount: state.amount,
    date: parsedDate.toISOString(),
    type: state.type,
    category: state.category || ''
  };
  // Помітка типу переказу: 'privat' | 'mono'; звичайний — без поля (як було)
  if (state.bank) transaction.bank = state.bank;
  // Номер картки отримувача (mono-переказ) — для відображення у квитанції
  if (state.cardNumber) transaction.cardNumber = state.cardNumber;

  const balanceRef = ref(db, `balance/${chatId}`);

  // Отримуємо поточний баланс
  get(balanceRef).then(snapshot => {
    const current = snapshot.val();
    let newBalance = current?.value ? parseFloat(current.value) : 0;

    // Якщо це витрата — зменшуємо
    if (state.type === 'expense') {
      newBalance -= Math.abs(amountNum);
    } else {
      newBalance += Math.abs(amountNum);
    }

    // Зберігаємо транзакцію та оновлюємо баланс
    return Promise.all([
      push(ref(db, `transactions/${chatId}`), transaction),
      set(balanceRef, { value: newBalance.toFixed(2) })
    ]);
  }).then(() => {
    const formatted = parsedDate.toLocaleDateString('uk-UA', { timeZone: KYIV_TZ, day: 'numeric', month: 'long', year: 'numeric' });
    const label = transaction.type === 'income' ? '📥 Дохід' : '📤 Витрата';

    bot.sendMessage(chatId,
      `✅ Транзакцію додано:\n${label}\n${transaction.name} — ${transaction.amount} ₴\n📅 ${formatted}`
    );
    userState[chatId] = null;
    sendMainMenu(chatId);
  }).catch(err => {
    bot.sendMessage(chatId, `❌ Помилка при збереженні або оновленні балансу: ${err.message}`);
  });

  return;
    }
  }
}

// ============================================================
// СПОВІЩЕННЯ ПРО ОПЛАТУ (черга від платіжного бота)
// ------------------------------------------------------------
// Платіжний бот кладе у вузол `notifications` запис про успішну оплату.
// Тут ми доставляємо його користувачу саме в цьому (головному) боті
// і прибираємо з черги. Якщо бот був вимкнений — доставимо після старту.
// ============================================================
onChildAdded(ref(db, 'notifications'), async (snap) => {
  const key = snap.key;
  const n = snap.val();
  if (!n || !n.chatId) {
    try { await remove(ref(db, `notifications/${key}`)); } catch (_) {}
    return;
  }
  try {
    let text;
    if (n.lifetime) {
      text = `🎉 Дякуємо за покупку!\n\n💎 Тариф: ${n.planLabel}\n👑 Підписку активовано безстроково.`;
    } else if (n.wasExtension) {
      text = `🎉 Підписку продовжено!\n\n💎 Тариф: ${n.planLabel}\n❤️ Тепер діє до ${fmtSubDate(n.endDate)}.`;
    } else {
      text = `🎉 Дякуємо за покупку!\n\n💎 Тариф: ${n.planLabel}\n❤️ Підписка активна до ${fmtSubDate(n.endDate)}.`;
    }
    await bot.sendMessage(n.chatId, text, {
      reply_markup: { inline_keyboard: [[{ text: '🏠 Головне меню', callback_data: 'back_to_menu' }]] }
    });
  } catch (err) {
    console.error('Помилка доставки сповіщення про оплату:', err.message);
  } finally {
    try { await remove(ref(db, `notifications/${key}`)); } catch (_) {}
  }
});

// ============================================================
// НАГАДУВАННЯ ПРО ЗАВЕРШЕННЯ ПІДПИСКИ (за добу до кінця)
// ------------------------------------------------------------
// Раз на годину перевіряємо активні НЕ безстрокові підписки.
// Нагадуємо лише тим, у кого підписка довша за 1 день (позначка
// expiryReminder ставиться платіжним ботом), і не частіше одного
// разу на кожну кінцеву дату.
// ============================================================
const ONE_DAY_MS = 24 * 60 * 60 * 1000;

async function checkExpiringSubscriptions() {
  try {
    const snap = await get(ref(db, 'users'));
    const users = snap.val() || {};
    const now = Date.now();

    for (const [chatId, user] of Object.entries(users)) {
      if (!user) continue;
      if (user.subscriptionStatus === 'lifetime') continue;
      if (!user.subscriptionStatus || !user.subscriptionEndDate) continue;
      if (!user.expiryReminder) continue; // 1-денні підписки не нагадуємо

      const endMs = parseEndMs(user.subscriptionEndDate);
      const left = endMs - now;
      if (left <= 0 || left > ONE_DAY_MS) continue; // тільки остання доба
      if (user.notified && user.notified.expiryFor === user.subscriptionEndDate) continue; // вже нагадали

      const currentPlan = user.lastPayment && user.lastPayment.planId
        ? PLAN_BY_ID[user.lastPayment.planId]
        : null;

      const rows = [];
      if (currentPlan && currentPlan.days) {
        rows.push([{
          text: `🔁 Продовжити (${currentPlan.button})`,
          url: `https://t.me/${PAYMENT_BOT_USERNAME}?start=${currentPlan.id}`
        }]);
      }
      rows.push([{ text: '💳 Обрати інший тариф', callback_data: 'sub_extend_menu' }]);

      await bot.sendMessage(
        chatId,
        `⏳ Ваша підписка закінчується завтра — ${fmtSubDate(user.subscriptionEndDate)}.\n\nПродовжте, щоб не втратити доступ 👇`,
        { reply_markup: { inline_keyboard: rows } }
      ).catch(() => {});

      await update(ref(db, `users/${chatId}/notified`), { expiryFor: user.subscriptionEndDate });
    }
  } catch (err) {
    console.error('Помилка перевірки підписок, що завершуються:', err.message);
  }
}

setTimeout(checkExpiringSubscriptions, 30 * 1000);        // перша перевірка через 30с після старту
setInterval(checkExpiringSubscriptions, 60 * 60 * 1000);  // далі — щогодини
