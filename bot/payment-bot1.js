require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const TelegramBot = require('node-telegram-bot-api');
const { initializeApp } = require('firebase/app');
const { getDatabase, ref, update, get, set, push } = require('firebase/database');

const { PLANS, PLAN_BY_ID } = require('./plans');
const { parseEndMs } = require('./subutil');

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
// Кілька адмінів через кому: ADMIN_IDS=111,222,333 (ADMIN_ID теж враховується)
const ADMIN_IDS = new Set(
  [ADMIN_ID, ...String(process.env.ADMIN_IDS || '')
    .split(',')
    .map((s) => Number(s.trim()))]
    .filter((n) => Number.isFinite(n) && n > 0)
);
function isAdmin(userId) {
  return ADMIN_IDS.has(Number(userId));
}

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
// від неї (стекінг), інакше — від поточного моменту. "Назавжди" → далека дата.
function calcNewEndDate(plan, currentEndVal) {
  if (plan.days === null) {
    return new Date(Date.UTC(2099, 11, 31, 23, 59, 59)).toISOString();
  }
  const now = Date.now();
  const currentEnd = parseEndMs(currentEndVal); // надійний розбір будь-якого формату
  const base = currentEnd > now ? currentEnd : now; // продовжуємо від пізнішої з дат
  const newEnd = new Date(base + plan.days * 24 * 60 * 60 * 1000);

  console.log(
    `[sub] plan=${plan.id} +${plan.days}d | prevEnd=${currentEnd ? new Date(currentEnd).toISOString() : 'none/unparsed'} ` +
    `| base=${new Date(base).toISOString()} | newEnd=${newEnd.toISOString()}`
  );
  return newEnd.toISOString();
}

// ============================================================
// СПІЛЬНЕ НАРАХУВАННЯ ПІДПИСКИ (і для Stars, і для крипти)
// ------------------------------------------------------------
// meta.method — 'stars' | 'crypto', решта полів — деталі платежу.
// ============================================================
async function grantSubscription(chatId, plan, meta) {
  const user = await getUser(chatId);
  const prevEndMs = parseEndMs(user && user.subscriptionEndDate);
  const wasExtension = Boolean(user && user.subscriptionStatus) && prevEndMs > Date.now();

  const newEndIso = calcNewEndDate(plan, user && user.subscriptionEndDate);

  // Чи нагадувати за добу до кінця: тільки якщо підписка довша за ~1 день.
  // Свіжий тариф «1 день» дає ~24 год → нагадування не має сенсу.
  const expiryReminder = plan.days !== null &&
    (new Date(newEndIso).getTime() - Date.now()) > (25 * 60 * 60 * 1000);

  // update() створить вузол, якщо користувача ще нема (Telegram ID спільний)
  await update(ref(db, `users/${chatId}`), {
    subscriptionStatus: plan.days === null ? 'lifetime' : true,
    subscriptionEndDate: newEndIso,
    expiryReminder,
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

  // Записуємо платіж в історію (для адмін-панелі та повернень)
  try {
    const listRef = ref(db, 'payments');
    const newRef = push(listRef);
    await set(newRef, {
      id: newRef.key,
      chatId,
      planId: plan.id,
      planLabel: plan.label,
      method: meta.method,                 // 'stars' | 'crypto'
      status: 'paid',
      // сума
      stars: meta.method === 'stars' ? plan.stars : null,
      usd: meta.method === 'crypto' ? plan.usd : null,
      // деталі для повернення
      chargeId: meta.chargeId || null,             // Stars: telegram_payment_charge_id
      invoiceId: meta.invoiceId || null,           // Crypto: CryptoBot invoice_id
      paidAsset: meta.paidAsset || null,           // Crypto: фактична монета
      paidAmount: meta.paidAmount || null,         // Crypto: фактична сума
      // стан підписки на момент оплати (для відкату)
      subscriptionEndDate: newEndIso,
      paidAt: new Date().toISOString()
    });
  } catch (err) {
    console.error('Не вдалося записати платіж в історію:', err.message);
  }

  // Кладемо сповіщення в чергу — головний бот доставить його користувачу
  // (успішна покупка / продовження, і на скільки).
  try {
    await set(push(ref(db, 'notifications')), {
      chatId,
      kind: 'purchased',
      planLabel: plan.label,
      planId: plan.id,
      days: plan.days,
      lifetime: plan.days === null,
      wasExtension,
      endDate: newEndIso,
      createdAt: new Date().toISOString()
    });
  } catch (err) {
    console.error('Не вдалося поставити сповіщення в чергу:', err.message);
  }

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

// Чи діє підписка користувача зараз (для заборони повторної «1 день»)
function isSubActive(user) {
  if (!user) return false;
  if (user.subscriptionStatus === 'lifetime') return true;
  const endMs = parseEndMs(user.subscriptionEndDate);
  return Boolean(user.subscriptionStatus) && endMs > Date.now();
}

// Вибір способу оплати для конкретного тарифу
async function sendPaymentMethods(chatId, plan) {
  // Поки підписка активна, тариф «1 день» купувати не можна — тільки довший.
  if (plan.days === 1) {
    const user = await getUser(chatId);
    if (isSubActive(user)) {
      return bot.sendMessage(
        chatId,
        '⛔ У вас уже є активна підписка, тому тариф «1 день» недоступний.\nОберіть довший термін — він додасться до поточної дати.',
        {
          parse_mode: 'Markdown',
          reply_markup: {
            inline_keyboard: PLANS.filter((p) => p.days !== 1).map((p) => ([
              { text: `${p.button} — ${p.stars} ⭐ / $${p.usd}`, callback_data: `pay:${p.id}` }
            ]))
          }
        }
      );
    }
  }

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
    } else if (data.startsWith('adm:')) {
      // Адмін-панель — доступ лише адмінам
      if (!isAdmin(query.from && query.from.id)) {
        await bot.answerCallbackQuery(query.id, { text: '⛔ Немає доступу', show_alert: true });
        return;
      }
      await handleAdminCallback(query, data);
      return bot.answerCallbackQuery(query.id).catch(() => {});
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
// ПОВЕРНЕННЯ ПЛАТЕЖІВ
// ============================================================
// Stars: refundStarPayment є в самому Bot API, але helper у бібліотеці
// з'явився лише у нових версіях node-telegram-bot-api. Тому за потреби
// викликаємо напряму через HTTP API — працює на будь-якій версії.
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

// Крипто-повернення через CryptoBot transfer (з балансу застосунку користувачу).
async function refundCryptoPayment(payment) {
  if (!payment.paidAsset || !payment.paidAmount) {
    throw new Error('немає даних про монету/суму — поверніть вручну в @CryptoBot');
  }
  return cryptoBotCall('transfer', {
    user_id: Number(payment.chatId),
    asset: payment.paidAsset,
    amount: String(payment.paidAmount),
    spend_id: `refund_${payment.id}`, // ідемпотентність — повторний виклик не задублює
    comment: 'Повернення за підписку'
  });
}

// Відкат підписки при поверненні: віднімаємо дні цього тарифу.
async function revokeSubscription(payment) {
  const user = await getUser(payment.chatId);
  const plan = PLAN_BY_ID[payment.planId];
  if (!user || !plan) return;

  let status = false;
  let endIso = new Date().toISOString();
  if (plan.days !== null) {
    const cur = user.subscriptionEndDate ? new Date(user.subscriptionEndDate).getTime() : 0;
    const reduced = cur - plan.days * 24 * 60 * 60 * 1000;
    if (reduced > Date.now()) {
      status = true;
      endIso = new Date(reduced).toISOString();
    }
  }
  await update(ref(db, `users/${payment.chatId}`), {
    subscriptionStatus: status,
    subscriptionEndDate: endIso,
    updatedAt: new Date().toISOString()
  });
}

// Головна операція повернення для конкретного платежу з історії.
async function doRefund(paymentId) {
  const snap = await get(ref(db, `payments/${paymentId}`));
  const payment = snap.val();
  if (!payment) return { ok: false, msg: 'Платіж не знайдено' };
  if (payment.status === 'refunded') return { ok: false, msg: 'Платіж уже повернено' };

  if (payment.method === 'stars') {
    await refundStarPayment(payment.chatId, payment.chargeId);
  } else if (payment.method === 'crypto') {
    await refundCryptoPayment(payment);
  } else {
    return { ok: false, msg: 'Невідомий метод оплати' };
  }

  await revokeSubscription(payment);
  await update(ref(db, `payments/${paymentId}`), {
    status: 'refunded',
    refundedAt: new Date().toISOString()
  });

  // Сповіщаємо користувача
  try {
    await bot.sendMessage(
      payment.chatId,
      '↩️ Ваш платіж за підписку повернено. Якщо є питання — зверніться до підтримки.'
    );
  } catch (_) { /* користувач міг заблокувати бота */ }

  await logToChannel(`↩️ ПОВЕРНЕННЯ\n🆔 ${paymentId}\n🤖 Користувач: ${payment.chatId}\n💎 ${payment.planLabel} (${payment.method})`);
  return { ok: true, msg: 'Платіж повернено' };
}

// ============================================================
// АДМІН-ПАНЕЛЬ
// ============================================================
async function getAllPayments() {
  const snap = await get(ref(db, 'payments'));
  const val = snap.val() || {};
  return Object.values(val).sort((a, b) => String(b.paidAt).localeCompare(String(a.paidAt)));
}

function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('uk-UA', { timeZone: KYIV_TZ });
}

function paymentAmountLabel(p) {
  if (p.method === 'crypto') {
    return `$${p.usd}${p.paidAsset ? ` (${p.paidAmount} ${p.paidAsset})` : ''}`;
  }
  return `${p.stars} ⭐`;
}

// Головний екран панелі: статистика
async function buildAdminHome() {
  const payments = await getAllPayments();
  const paid = payments.filter((p) => p.status === 'paid');
  const refunded = payments.filter((p) => p.status === 'refunded');
  const starsSum = paid.filter((p) => p.method === 'stars').reduce((s, p) => s + (p.stars || 0), 0);
  const usdSum = paid.filter((p) => p.method === 'crypto').reduce((s, p) => s + (p.usd || 0), 0);
  const starsCount = paid.filter((p) => p.method === 'stars').length;
  const cryptoCount = paid.filter((p) => p.method === 'crypto').length;

  const text =
    '🛠 *Адмін-панель*\n\n' +
    `📊 Усього платежів: ${payments.length}\n` +
    `✅ Активних: ${paid.length}  ·  ↩️ Повернень: ${refunded.length}\n\n` +
    `⭐ Stars: ${starsCount} шт · ${starsSum} ⭐\n` +
    `🪙 Crypto: ${cryptoCount} шт · $${usdSum.toFixed(2)}\n`;

  const keyboard = [
    [{ text: '📋 Останні платежі', callback_data: 'adm:list:0' }],
    [{ text: '🔄 Оновити', callback_data: 'adm:home' }]
  ];
  return { text, keyboard };
}

// Список платежів (по 8 на сторінку)
const PAGE = 8;
async function buildAdminList(offset) {
  const payments = await getAllPayments();
  const slice = payments.slice(offset, offset + PAGE);

  let text = '📋 *Платежі*';
  if (payments.length === 0) text += '\n\n_Поки що платежів немає._';

  const keyboard = slice.map((p) => {
    const icon = p.status === 'refunded' ? '↩️' : (p.method === 'crypto' ? '🪙' : '⭐');
    const label = `${icon} ${p.planLabel} · ${paymentAmountLabel(p)} · id${p.chatId}`;
    return [{ text: label, callback_data: `adm:view:${p.id}` }];
  });

  // Пагінація
  const nav = [];
  if (offset > 0) nav.push({ text: '⬅️ Назад', callback_data: `adm:list:${Math.max(0, offset - PAGE)}` });
  if (offset + PAGE < payments.length) nav.push({ text: 'Далі ➡️', callback_data: `adm:list:${offset + PAGE}` });
  if (nav.length) keyboard.push(nav);
  keyboard.push([{ text: '🏠 На головну', callback_data: 'adm:home' }]);

  return { text, keyboard };
}

// Картка платежу
async function buildAdminView(paymentId) {
  const snap = await get(ref(db, `payments/${paymentId}`));
  const p = snap.val();
  if (!p) return { text: 'Платіж не знайдено.', keyboard: [[{ text: '🏠 На головну', callback_data: 'adm:home' }]] };

  const statusLabel = p.status === 'refunded' ? '↩️ Повернено' : '✅ Оплачено';
  const methodLabel = p.method === 'crypto' ? '🪙 Crypto (CryptoBot)' : '⭐ Telegram Stars';

  let text =
    '🧾 *Платіж*\n\n' +
    `Статус: ${statusLabel}\n` +
    `Спосіб: ${methodLabel}\n` +
    `Тариф: ${p.planLabel}\n` +
    `Сума: ${paymentAmountLabel(p)}\n` +
    `Користувач ID: \`${p.chatId}\`\n` +
    `Оплачено: ${fmtDate(p.paidAt)}\n`;
  if (p.method === 'stars' && p.chargeId) text += `Charge ID: \`${p.chargeId}\`\n`;
  if (p.method === 'crypto' && p.invoiceId) text += `Invoice ID: \`${p.invoiceId}\`\n`;
  if (p.status === 'refunded') text += `Повернено: ${fmtDate(p.refundedAt)}\n`;

  const keyboard = [];
  if (p.status !== 'refunded') {
    keyboard.push([{ text: '↩️ Повернути платіж', callback_data: `adm:rfask:${p.id}` }]);
  }
  keyboard.push([{ text: '⬅️ До списку', callback_data: 'adm:list:0' }, { text: '🏠 На головну', callback_data: 'adm:home' }]);
  return { text, keyboard };
}

// Редагуємо повідомлення панелі (плавна навігація)
async function editPanel(query, view) {
  try {
    await bot.editMessageText(view.text, {
      chat_id: query.message.chat.id,
      message_id: query.message.message_id,
      parse_mode: 'Markdown',
      reply_markup: { inline_keyboard: view.keyboard }
    });
  } catch (_) {
    // Якщо редагувати не вдалось (напр. текст не змінився) — надсилаємо нове
    await bot.sendMessage(query.message.chat.id, view.text, {
      parse_mode: 'Markdown',
      reply_markup: { inline_keyboard: view.keyboard }
    });
  }
}

async function handleAdminCallback(query, data) {
  // adm:home | adm:list:<offset> | adm:view:<id> | adm:rfask:<id> | adm:rfyes:<id>
  const parts = data.split(':');
  const action = parts[1];

  if (action === 'home') {
    return editPanel(query, await buildAdminHome());
  }
  if (action === 'list') {
    const offset = Number(parts[2]) || 0;
    return editPanel(query, await buildAdminList(offset));
  }
  if (action === 'view') {
    return editPanel(query, await buildAdminView(parts[2]));
  }
  if (action === 'rfask') {
    const id = parts[2];
    return editPanel(query, {
      text: '⚠️ *Підтвердіть повернення*\n\nКошти повернуться користувачу, а підписку буде відкликано. Дію не можна скасувати.',
      keyboard: [
        [{ text: '✅ Так, повернути', callback_data: `adm:rfyes:${id}` }],
        [{ text: '⬅️ Скасувати', callback_data: `adm:view:${id}` }]
      ]
    });
  }
  if (action === 'rfyes') {
    const id = parts[2];
    let resultMsg;
    try {
      const r = await doRefund(id);
      resultMsg = r.ok ? `✅ ${r.msg}` : `⚠️ ${r.msg}`;
    } catch (err) {
      console.error('Помилка повернення:', err.message);
      resultMsg = `❌ Не вдалося повернути: ${err.message}`;
    }
    const view = await buildAdminView(id);
    view.text = `${resultMsg}\n\n${view.text}`;
    return editPanel(query, view);
  }
}

// Вхід у панель
bot.onText(/^\/admin\b/, async (msg) => {
  if (!isAdmin(msg.from && msg.from.id)) return;
  const view = await buildAdminHome();
  await bot.sendMessage(msg.chat.id, view.text, {
    parse_mode: 'Markdown',
    reply_markup: { inline_keyboard: view.keyboard }
  });
});

// Ручне продовження підписки (адмін): /addsub <userId> <днів>
// Додає дні поверх поточної дати (стекінг). Зручно, щоб виправити запис,
// у якого продовження раніше не зарахувалось.
bot.onText(/^\/addsub\s+(\d+)\s+(\d+)/, async (msg, match) => {
  if (!isAdmin(msg.from && msg.from.id)) return;
  const uid = match[1];
  const days = Number(match[2]);
  try {
    const user = await getUser(uid);
    const base = Math.max(Date.now(), parseEndMs(user && user.subscriptionEndDate));
    const newEnd = new Date(base + days * 24 * 60 * 60 * 1000).toISOString();
    await update(ref(db, `users/${uid}`), {
      subscriptionStatus: true,
      subscriptionEndDate: newEnd,
      expiryReminder: days > 1,
      updatedAt: new Date().toISOString()
    });
    await bot.sendMessage(
      msg.chat.id,
      `✅ Користувачу ${uid} додано ${days} дн.\nТепер підписка діє до ${new Date(newEnd).toLocaleString('uk-UA', { timeZone: KYIV_TZ })}`
    );
  } catch (err) {
    await bot.sendMessage(msg.chat.id, `❌ Помилка: ${err.message}`);
  }
});

console.log(`💳 Payment bot запущено. Stars: ✅  Crypto (CryptoBot): ${CRYPTO_ENABLED ? '✅' : '⛔ (немає CRYPTOBOT_TOKEN)'}  Адмінів: ${ADMIN_IDS.size}`);
