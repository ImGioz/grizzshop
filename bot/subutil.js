// ============================================================
// Спільний надійний розбір дати завершення підписки
// ------------------------------------------------------------
// Підписки могли створюватись різними частинами системи, тому
// subscriptionEndDate трапляється в різних форматах:
//   • ISO рядок:            "2026-08-16T12:00:00.000Z"
//   • ISO лише дата:        "2026-08-16"
//   • мілісекунди (number): 1755300000000
//   • локалізований рядок:  "16.08.2026" або "16.08.2026 23:59"
// new Date("16.08.2026") у Node = Invalid Date → саме через це
// раніше губилося продовження (стекінг) підписки.
//
// parseEndMs() повертає час у мілісекундах (0 — якщо розпізнати не вдалось).
// ============================================================
function parseEndMs(val) {
  if (val === null || val === undefined || val === '') return 0;
  if (typeof val === 'number') return Number.isFinite(val) ? val : 0;
  if (val instanceof Date) {
    const t = val.getTime();
    return Number.isNaN(t) ? 0 : t;
  }

  const s = String(val).trim();

  // 1) Все, що вміє розпарсити стандартний Date (ISO тощо)
  const iso = Date.parse(s);
  if (!Number.isNaN(iso)) return iso;

  // 2) Локалізований формат ДД.ММ.РРРР [ГГ:ХХ] (крапка, слеш або дефіс)
  const m = s.match(/^(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{4})(?:[ T](\d{1,2}):(\d{2}))?/);
  if (m) {
    const day = +m[1], month = +m[2] - 1, year = +m[3];
    const hh = m[4] !== undefined ? +m[4] : 23;
    const mm = m[5] !== undefined ? +m[5] : 59;
    const t = Date.UTC(year, month, day, hh, mm, 59);
    return Number.isNaN(t) ? 0 : t;
  }

  return 0;
}

module.exports = { parseEndMs };
