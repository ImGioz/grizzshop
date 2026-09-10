require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const TelegramBot = require('node-telegram-bot-api');
const { initializeApp } = require('firebase/app');
const { getDatabase, ref, update, get, set } = require('firebase/database');

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
const ADMIN_ID = Number(process.env.ADMIN_ID);

// --- CryptoBot (Crypto Pay API) ---
// Токен додатку з @CryptoBot → Crypto Pay → Create App.
// Якщо не заданий — кнопка оплати криптою просто не показується.
const CRYPTOBOT_TOKEN = process.env.CRYPTOBOT_TOKEN || '';
const CRYPTOBOT_API_BASE = process.env.CRYPTOBOT_TESTNET
  ? 'https://testnet-pay.crypt.bot/api'
  : 'https://pay.crypt.bot/api';
const CRYPTO_ENABLED = Boolean(CRYPTOBOT_TOKEN);

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
    return new Date(Date.UTC(2099, 11, 31, 23, 59, 59)).toISOString();
  }
  const now = Date.now();
  const currentEnd = currentEndIso ? new Date(currentEndIso).getTime() : 0;
  const base = currentEnd && currentEnd > now ? currentEnd : now;
  const newEnd = new Date(base + plan.days * 24 * 60 * 60 * 1000);
  return newEnd.toISOString();
}

// ============================================================
// СПІЛЬНЕ НАРАХУВАННЯ ПІДПИСКИ (і для Stars, і для крипти)
// ------------------------------------------------------------
// meta.method — 'stars' | 'crypto', решта полів — деталі платежу.
// ============================================================
async function grantSubscription(chatId, plan, meta) {
  const user = await getUser(chatId);
  const newEndIso = calcNewEndDate(plan, user && user.subscriptionEndDate);

  // update() створить вузол, якщо користувача ще нема (Telegram ID спільний)
  await update(ref(db, `users/${chatId}`), {
    subscriptionStatus: plan.days === null ? 'lifetime' : true,
    subscriptionEndDate: newEndIso,
    lastPayment: { planId: plan.id, ...meta, paidAt: new Date().toISOString() },
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

  const methodLabel = meta.method === 'crypto' ? '🪙 Crypto' : '⭐ Stars';
  const amountLabel = meta.method === 'crypto'
    ? `$${plan.usd}${meta.paidAsset ? ` (${meta.paidAmount} ${meta.paidAsset})` : ''}`
    : `${plan.stars} ⭐`;
  await logToChannel(
    `💰 ОПЛАТА (${methodLabel})\n🤖 Користувач ID: ${chatId}\n💎 Тариф: ${plan.label} (${amountLabel})\n❤️ Активна ${untilText}\n⏰ ${new Date().toLocaleString('uk-UA', { timeZone: KYIV_TZ })}`
  );

  return newEndIso;
}

// ============================================================
// TELEGRAM STARS
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

async function sendStarsInvoice(chatId, plan) {
  const title = `Преміум підписка — ${plan.label}`;
  const description = plan.days === null
    ? 'Довічний доступ до преміум-функцій.'
    : `Доступ до преміум-функцій на ${plan.label}.`;
  const payload = `sub:${plan.id}`;
  try {
    const prices = [{ label: plan.label, amount: plan.stars }];
    await bot.sendInvoice(...buildInvoiceArgs(chatId, title, description, payload, prices));
  } catch (err) {
    console.error('Помилка sendInvoice:', err.message);
    await bot.sendMessage(chatId, '❌ Не вдалося сформувати рахунок Stars. Спробуйте пізніше або оберіть інший спосіб.');
  }
}

// ============================================================
// CRYPTOBOT (Crypto Pay API)
// ============================================================
async function cryptoBotCall(method, params) {
  const resp = await fetch(`${CRYPTOBOT_API_BASE}/${method}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Crypto-Pay-API-Token': CRYPTOBOT_TOKEN
    },
    body: JSON.stringify(params || {})
  });
  const data = await resp.json();
  if (!data.ok) {
    throw new Error(data.error ? JSON.stringify(data.error) : 'CryptoBot API помилка');
  }
  return data.result;
}

// Активні крипто-рахунки в пам'яті: invoiceId -> { chatId, planId, createdAt }
// Фоновий поллер періодично перевіряє їхній статус.
const pendingCrypto = new Map();

async function sendCryptoInvoice(chatId, plan) {
  try {
    const invoice = await cryptoBotCall('createInvoice', {
      currency_type: 'fiat',
      fiat: 'USD',
      amount: String(plan.usd),
      description: `Преміум підписка — ${plan.label}`,
      payload: JSON.stringify({ chatId, planId: plan.id }),
      expires_in: 3600 // 1 година
    });

    const invoiceId = invoice.invoice_id;
    const payUrl = invoice.bot_invoice_url || invoice.mini_app_invoice_url || invoice.pay_url || invoice.web_app_invoice_url;

    pendingCrypto.set(String(invoiceId), { chatId, planId: plan.id, createdAt: Date.now() });

    await bot.sendMessage(
      chatId,
      `🪙 *Оплата криптою (CryptoBot)*\n\n💎 Тариф: ${plan.label}\n💵 Сума: $${plan.usd}\n\n1️⃣ Натисніть «Сплатити» і оберіть будь-яку монету (USDT, TON, BTC…)\n2️⃣ Після оплати натисніть «Перевірити оплату»`,
      {
        parse_mode: 'Markdown',
        reply_markup: {
          inline_keyboard: [
            [{ text: `💳 Сплатити $${plan.usd}`, url: payUrl }],
            [{ text: '🔄 Перевірити оплату', callback_data: `chk:${invoiceId}:${plan.id}` }]
          ]
        }
      }
    );
  } catch (err) {
    console.error('Помилка createInvoice (CryptoBot):', err.message);
    await bot.sendMessage(chatId, '❌ Не вдалося створити крипто-рахунок. Спробуйте пізніше або оберіть Telegram Stars.');
  }
}

// Перевіряє статус крипто-рахунку і, якщо оплачено, нараховує підписку.
// Ідемпотентно: кожен invoiceId обробляється лише раз (позначка в Firebase).
// Повертає true, якщо саме зараз була зарахована оплата.
async function processCryptoInvoice(invoiceId, planIdHint) {
  const res = await cryptoBotCall('getInvoices', { invoice_ids: String(invoiceId) });
  const inv = res && res.items && res.items[0];
  if (!inv || inv.status !== 'paid') return { paid: false };

  // Дістаємо chatId та planId з payload рахунку (надійніше за підказку)
  let chatId, planId = planIdHint;
  try {
    const p = JSON.parse(inv.payload || '{}');
    chatId = p.chatId;
    if (p.planId) planId = p.planId;
  } catch (_) { /* ignore */ }
  if (!chatId) return { paid: false };

  const plan = PLAN_BY_ID[planId];
  if (!plan) return { paid: false };

  // Захист від подвійного нарахування (поллер + кнопка + рестарти)
  const guardRef = ref(db, `cryptoPayments/${invoiceId}`);
  const existing = await get(guardRef);
  if (existing.exists()) {
    pendingCrypto.delete(String(invoiceId));
    return { paid: true, already: true, chatId };
  }
  await set(guardRef, { chatId, planId, paidAt: new Date().toISOString() });

  await grantSubscription(chatId, plan, {
    method: 'crypto',
    usd: plan.usd,
    invoiceId,
    paidAsset: inv.paid_asset || inv.asset || null,
    paidAmount: inv.paid_amount || inv.amount || null
  });

  pendingCrypto.delete(String(invoiceId));
  return { paid: true, chatId };
}

// Фоновий поллер: раз на 12 сек перевіряє всі активні крипто-рахунки.
if (CRYPTO_ENABLED) {
  setInterval(async () => {
    if (pendingCrypto.size === 0) return;
    const entries = [...pendingCrypto.entries()];
    for (const [invoiceId, info] of entries) {
      // Прибираємо протухлі (понад 1 год) — рахунок все одно вже expired
      if (Date.now() - info.createdAt > 60 * 60 * 1000) {
        pendingCrypto.delete(invoiceId);
        continue;
      }
      try {
        await processCryptoInvoice(invoiceId, info.planId);
      } catch (err) {
        console.error('Поллер CryptoBot:', err.message);
      }
    }
  }, 12000);
}

// ============================================================
// МЕНЮ ВИБОРУ ТАРИФУ / СПОСОБУ ОПЛАТИ
// ============================================================
function sendPlansMenu(chatId) {
  const text =
    '💎 *Преміум підписка*\n\n' +
    '✨ Що ви отримаєте:\n' +
    '🎯 Ідеальний настрій\n\n' +
    '🎁 Оберіть зручний для вас термін:';
  const planButtons = PLANS.map((p) => ([
    { text: `${p.button} — ${p.stars} ⭐ / $${p.usd}`, callback_data: `pay:${p.id}` }
  ]));
  return bot.sendMessage(chatId, text, {
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: planButtons }
  });
}

// Вибір способу оплати для конкретного тарифу
function sendPaymentMethods(chatId, plan) {
  const text =
    `💎 *${plan.label}*\n\n` +
    '💳 Оберіть спосіб оплати:\n' +
    `⭐ Telegram Stars — ${plan.stars} ⭐\n` +
    (CRYPTO_ENABLED ? `🪙 Крипта (CryptoBot) — $${plan.usd}\n` : '') +
    '\n💡 Купівля зірок через Chrome/Safari — економія до 30%!';

  const rows = [
    [{ text: `⭐ Telegram Stars · ${plan.stars} ⭐`, callback_data: `stars:${plan.id}` }]
  ];
  if (CRYPTO_ENABLED) {
    rows.push([{ text: `🪙 Крипта · $${plan.usd}`, callback_data: `crypto:${plan.id}` }]);
  }
  rows.push([{ text: '⬅️ Інші тарифи', callback_data: 'plans' }]);

  return bot.sendMessage(chatId, text, {
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: rows }
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
      return sendPaymentMethods(chatId, PLAN_BY_ID[planId]);
    }
    return sendPlansMenu(chatId);
  } catch (err) {
    console.error('Помилка /start (payment bot):', err.message);
  }
});

// ============================================================
// Обробка inline-кнопок
// ============================================================
bot.on('callback_query', async (query) => {
  const chatId = query.message?.chat?.id;
  const data = query.data || '';

  try {
    if (data === 'plans') {
      await sendPlansMenu(chatId);
    } else if (data.startsWith('pay:')) {
      const plan = PLAN_BY_ID[data.slice(4)];
      if (plan) await sendPaymentMethods(chatId, plan);
    } else if (data.startsWith('stars:')) {
      const plan = PLAN_BY_ID[data.slice(6)];
      if (plan) await sendStarsInvoice(chatId, plan);
    } else if (data.startsWith('crypto:')) {
      const plan = PLAN_BY_ID[data.slice(7)];
      if (!CRYPTO_ENABLED) {
        await bot.answerCallbackQuery(query.id, { text: 'Оплата криптою тимчасово недоступна.', show_alert: true });
        return;
      }
      if (plan) await sendCryptoInvoice(chatId, plan);
    } else if (data.startsWith('chk:')) {
      // Ручна перевірка крипто-оплати: chk:<invoiceId>:<planId>
      const [, invoiceId, planId] = data.split(':');
      const result = await processCryptoInvoice(invoiceId, planId);
      if (result.paid) {
        await bot.answerCallbackQuery(query.id, { text: result.already ? '✅ Уже зараховано' : '✅ Оплату підтверджено!' });
      } else {
        await bot.answerCallbackQuery(query.id, { text: '⏳ Оплата ще не надійшла. Спробуйте за хвилину.', show_alert: true });
        return;
      }
    }
    return bot.answerCallbackQuery(query.id);
  } catch (err) {
    console.error('Помилка callback_query (payment bot):', err.message);
    return bot.answerCallbackQuery(query.id, { text: '❌ Сталася помилка', show_alert: true }).catch(() => {});
  }
});

// ============================================================
// STARS: pre-checkout (підтвердити ПЕРЕД списанням, ≤10 сек)
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
// STARS: успішна оплата
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
    await grantSubscription(chatId, plan, {
      method: 'stars',
      stars: plan.stars,
      chargeId: sp.telegram_payment_charge_id,
      providerChargeId: sp.provider_payment_charge_id
    });
  } catch (err) {
    console.error('Помилка нарахування підписки (Stars):', err.message);
    await bot.sendMessage(chatId, '⚠️ Оплату отримано, але сталася помилка при активації. Зверніться до підтримки, якщо підписка не з’явилась.');
  }
});

// ============================================================
// (Опційно) повернення зірок: /refund <user_id> <charge_id> — лише адмін
// ------------------------------------------------------------
// Метод refundStarPayment є в самому Bot API, але helper у бібліотеці
// з'явився лише у нових версіях node-telegram-bot-api. Тому викликаємо
// напряму через HTTP API — працює на будь-якій версії.
// ============================================================
async function refundStarPayment(userId, chargeId) {
  if (typeof bot.refundStarPayment === 'function') {
    return bot.refundStarPayment(Number(userId), chargeId);
  }
  const resp = await fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/refundStarPayment`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: Number(userId), telegram_payment_charge_id: chargeId })
  });
  const data = await resp.json();
  if (!data.ok) throw new Error(data.description || 'Telegram API повернув помилку');
  return data.result;
}

bot.onText(/^\/refund\s+(\S+)\s+(\S+)/, async (msg, match) => {
  if (!msg.from || msg.from.id !== ADMIN_ID) return;
  try {
    await refundStarPayment(match[1], match[2]);
    await bot.sendMessage(msg.chat.id, `✅ Повернено зірки за платіж ${match[2]}`);
  } catch (err) {
    await bot.sendMessage(msg.chat.id, `❌ Не вдалося повернути: ${err.message}`);
  }
});

console.log(`💳 Payment bot запущено. Stars: ✅  Crypto (CryptoBot): ${CRYPTO_ENABLED ? '✅' : '⛔ (немає CRYPTOBOT_TOKEN)'}`);
