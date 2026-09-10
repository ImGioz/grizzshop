require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const TelegramBot = require('node-telegram-bot-api');
const { initializeApp } = require('firebase/app');
const { getDatabase, ref, update, get } = require('firebase/database');

const { PLANS, PLAN_BY_ID } = require('./plans');

// ============================================================
// 🔐 Конфіг з .env
// ------------------------------------------------------------
// Це ДРУГИЙ, ОКРЕМИЙ бот зі СВОЇМ токеном (PAYMENT_TELEGRAM_TOKEN).
// Firebase — той самий, що й у головного бота, бо ID користувача в
// Telegram однаковий у всіх ботів, тож підписка пишеться в той самий
// вузол users/<chatId> і одразу видно в профілі головного бота.
// ============================================================
const TELEGRAM_TOKEN = process.env.PAYMENT_TELEGRAM_TOKEN;

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

const LOG_CHANNEL_ID = process.env.LOG_CHANNEL_ID; // необов'язково
// Username головного бота — БЕЗ @. Щоб після оплати повернути користувача назад.
const MAIN_BOT_USERNAME = (process.env.MAIN_BOT_USERNAME || 'your_main_bot').replace('@', '');

const KYIV_TZ = 'Europe/Kyiv';

// ✅ Firebase init
const app = initializeApp(firebaseConfig);
const db = getDatabase(app);

// ✅ Telegram bot init
const bot = new TelegramBot(TELEGRAM_TOKEN, { polling: true });

// ============================================================
// Хелпери
// ============================================================
async function getUser(chatId) {
  const snapshot = await get(ref(db, `users/${chatId}`));
  return snapshot.val();
}

async function logToChannel(text) {
  if (!LOG_CHANNEL_ID) return;
  try {
    await bot.sendMessage(LOG_CHANNEL_ID, text);
  } catch (err) {
    console.error('Не вдалося надіслати повідомлення в лог-канал:', err.message);
  }
}

// Обчислює нову дату завершення підписки.
// Якщо в користувача вже є активна підписка в майбутньому — продовжуємо
// від неї, інакше — від поточного моменту. Для "назавжди" ставимо далеку дату.
function calcNewEndDate(plan, currentEndIso) {
  if (plan.days === null) {
    // Назавжди — фіксуємо далеку дату
    return new Date(Date.UTC(2099, 11, 31, 23, 59, 59)).toISOString();
  }

  const now = Date.now();
  const currentEnd = currentEndIso ? new Date(currentEndIso).getTime() : 0;
  const base = currentEnd && currentEnd > now ? currentEnd : now;
  const newEnd = new Date(base + plan.days * 24 * 60 * 60 * 1000);
  return newEnd.toISOString();
}

// ============================================================
// Виставлення рахунку в Telegram Stars
// ============================================================
// Різні версії node-telegram-bot-api мають різний позиційний підпис
// sendInvoice: історично між providerToken і currency стоїть startParameter.
// Визначаємо за арністю функції, щоб працювало на будь-якій версії.
function buildInvoiceArgs(chatId, title, description, payload, prices) {
  const providerToken = ''; // для Stars — порожній
  const currency = 'XTR';   // зірки Telegram
  if (bot.sendInvoice.length >= 8) {
    const startParameter = ''; // для Stars не потрібен
    return [chatId, title, description, payload, providerToken, startParameter, currency, prices, {}];
  }
  return [chatId, title, description, payload, providerToken, currency, prices, {}];
}

async function sendPlanInvoice(chatId, plan) {
  // Для Telegram Stars: currency = 'XTR', provider_token = '' (порожній),
  // а amount у prices дорівнює кількості зірок (без множення на 100).
  const title = `Преміум підписка — ${plan.label}`;
  const description =
    plan.days === null
      ? 'Довічний доступ до преміум-функцій.'
      : `Доступ до преміум-функцій на ${plan.label}.`;

  // payload несе id тарифу — знадобиться на етапі підтвердження оплати
  const payload = `sub:${plan.id}`;

  try {
    const prices = [{ label: plan.label, amount: plan.stars }];
    await bot.sendInvoice(...buildInvoiceArgs(chatId, title, description, payload, prices));
  } catch (err) {
    console.error('Помилка sendInvoice:', err.message);
    await bot.sendMessage(
      chatId,
      '❌ Не вдалося сформувати рахунок. Спробуйте пізніше або оберіть інший тариф командою /start.'
    );
  }
}

// Меню вибору тарифу (коли зайшли без deep-link параметра)
function sendPlansMenu(chatId) {
  const text =
    '💎 *Преміум підписка*\n\n' +
    '✨ Що ви отримаєте:\n' +
    '🎯 Ідеальний настрій\n\n' +
    '💳 Оплата через Telegram Stars.\n' +
    '💡 Купівля зірок через Chrome/Safari — економія до 30%!\n\n' +
    '🎁 Оберіть зручний для вас термін:';

  const planButtons = PLANS.map((p) => ([
    { text: `${p.button} — ${p.stars} ⭐`, callback_data: `pay:${p.id}` }
  ]));

  return bot.sendMessage(chatId, text, {
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: planButtons }
  });
}

// ============================================================
// /start [planId]  — вхід через deep-link з головного бота
// ============================================================
bot.onText(/^\/start(?:\s+(\S+))?/, async (msg, match) => {
  const chatId = msg.chat.id;
  const planId = match && match[1];

  try {
    if (planId && PLAN_BY_ID[planId]) {
      // Прийшли з головного бота з конкретним тарифом — одразу рахунок
      return sendPlanInvoice(chatId, PLAN_BY_ID[planId]);
    }
    // Без параметра (або невідомий) — показуємо вибір тарифів
    return sendPlansMenu(chatId);
  } catch (err) {
    console.error('Помилка /start (payment bot):', err.message);
  }
});

// ============================================================
// Вибір тарифу кнопкою (коли меню показане в цьому ж боті)
// ============================================================
bot.on('callback_query', async (query) => {
  const chatId = query.message?.chat?.id;
  const data = query.data || '';

  try {
    if (data.startsWith('pay:')) {
      const planId = data.slice('pay:'.length);
      const plan = PLAN_BY_ID[planId];
      if (plan) await sendPlanInvoice(chatId, plan);
    }
    return bot.answerCallbackQuery(query.id);
  } catch (err) {
    console.error('Помилка callback_query (payment bot):', err.message);
    return bot.answerCallbackQuery(query.id, { text: '❌ Сталася помилка', show_alert: true }).catch(() => {});
  }
});

// ============================================================
// Pre-checkout: Telegram питає підтвердження ПЕРЕД списанням зірок.
// Треба відповісти протягом 10 секунд, інакше оплата скасується.
// ============================================================
bot.on('pre_checkout_query', async (query) => {
  try {
    const planId = (query.invoice_payload || '').replace('sub:', '');
    const ok = Boolean(PLAN_BY_ID[planId]);
    await bot.answerPreCheckoutQuery(query.id, ok, ok ? undefined : { error_message: 'Тариф недоступний.' });
  } catch (err) {
    console.error('Помилка pre_checkout_query:', err.message);
    try { await bot.answerPreCheckoutQuery(query.id, false, { error_message: 'Технічна помилка.' }); } catch (_) {}
  }
});

// ============================================================
// Успішна оплата: нараховуємо підписку в той самий Firebase-вузол,
// що читає головний бот (users/<chatId>).
// ============================================================
bot.on('successful_payment', async (msg) => {
  const chatId = msg.chat.id;
  const sp = msg.successful_payment;
  const planId = (sp.invoice_payload || '').replace('sub:', '');
  const plan = PLAN_BY_ID[planId];

  if (!plan) {
    console.error('successful_payment: невідомий тариф', sp.invoice_payload);
    return bot.sendMessage(chatId, '⚠️ Оплата отримана, але тариф не розпізнано. Зверніться до підтримки.');
  }

  try {
    const user = await getUser(chatId);
    const newEndIso = calcNewEndDate(plan, user && user.subscriptionEndDate);

    // update() створить вузол, якщо користувача ще нема (Telegram ID спільний)
    await update(ref(db, `users/${chatId}`), {
      subscriptionStatus: plan.days === null ? 'lifetime' : true,
      subscriptionEndDate: newEndIso,
      lastPayment: {
        planId: plan.id,
        stars: plan.stars,
        chargeId: sp.telegram_payment_charge_id,
        providerChargeId: sp.provider_payment_charge_id,
        paidAt: new Date().toISOString()
      },
      updatedAt: new Date().toISOString()
    });

    const untilText =
      plan.days === null
        ? 'назавжди 👑'
        : `до ${new Date(newEndIso).toLocaleDateString('uk-UA', { timeZone: KYIV_TZ })}`;

    await bot.sendMessage(
      chatId,
      `✅ *Оплату отримано!*\n\n💎 Тариф: ${plan.label}\n❤️ Підписка активна ${untilText}\n\nДякуємо за підтримку! 🎉`,
      {
        parse_mode: 'Markdown',
        reply_markup: {
          inline_keyboard: [[{ text: '⬅️ Повернутися в бот', url: `https://t.me/${MAIN_BOT_USERNAME}` }]]
        }
      }
    );

    await logToChannel(
      `💰 ОПЛАТА (Stars)\n🤖 Користувач ID: ${chatId}\n💎 Тариф: ${plan.label} (${plan.stars} ⭐)\n❤️ Активна ${untilText}\n🧾 charge: ${sp.telegram_payment_charge_id}\n⏰ ${new Date().toLocaleString('uk-UA', { timeZone: KYIV_TZ })}`
    );
  } catch (err) {
    console.error('Помилка нарахування підписки:', err.message);
    await bot.sendMessage(
      chatId,
      '⚠️ Оплату отримано, але сталася помилка при активації. Ми вже розбираємось — зверніться до підтримки, якщо підписка не з’явилась.'
    );
  }
});

// ============================================================
// (Опційно) повернення зірок: /refund <charge_id> лише для адміна
// ============================================================
const ADMIN_ID = Number(process.env.ADMIN_ID);
bot.onText(/^\/refund\s+(\S+)\s+(\S+)/, async (msg, match) => {
  if (!msg.from || msg.from.id !== ADMIN_ID) return;
  const targetUserId = match[1];
  const chargeId = match[2];
  try {
    await bot.refundStarPayment(Number(targetUserId), chargeId);
    await bot.sendMessage(msg.chat.id, `✅ Повернено зірки за платіж ${chargeId}`);
  } catch (err) {
    await bot.sendMessage(msg.chat.id, `❌ Не вдалося повернути: ${err.message}`);
  }
});

console.log('💳 Payment bot запущено (Telegram Stars).');
