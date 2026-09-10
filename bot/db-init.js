#!/usr/bin/env node
require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const { initDB, close } = require('./db');

console.log('🔧 Ініціалізація SQLite БД для бота...\n');

initDB()
  .then(() => {
    console.log('\n✅ БД успішно ініціалізована!');
    console.log('📁 Файл: bot.db\n');
    close();
    process.exit(0);
  })
  .catch((err) => {
    console.error('❌ Помилка ініціалізації:', err);
    close();
    process.exit(1);
  });
