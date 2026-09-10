const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const DB_PATH = path.join(__dirname, '../bot.db');

let db = null;

function getDB() {
  if (!db) {
    db = new sqlite3.Database(DB_PATH, (err) => {
      if (err) console.error('Database connection error:', err);
      else console.log('✅ SQLite БД підключена:', DB_PATH);
    });
    db.configure('busyTimeout', 5000);
  }
  return db;
}

function initDB() {
  return new Promise((resolve, reject) => {
    const database = getDB();

    database.serialize(() => {
      // Таблиця користувачів
      database.run(`
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY,
          name TEXT,
          email TEXT,
          phone TEXT,
          state TEXT DEFAULT 'new',
          subscriptionStatus TEXT,
          subscriptionEndDate TEXT,
          blocked INTEGER DEFAULT 0,
          blockReason TEXT,
          lastPaymentAmount TEXT,
          lastPaymentPlanId TEXT,
          createdAt TEXT NOT NULL,
          updatedAt TEXT NOT NULL
        )
      `, (err) => {
        if (err) console.error('Error creating users table:', err);
        else console.log('✅ Таблиця users готова');
      });

      // Таблиця платежей
      database.run(`
        CREATE TABLE IF NOT EXISTS payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          userId INTEGER NOT NULL,
          amount TEXT NOT NULL,
          planId TEXT,
          source TEXT,
          receiptId TEXT UNIQUE,
          status TEXT DEFAULT 'completed',
          paymentDate TEXT NOT NULL,
          createdAt TEXT NOT NULL,
          FOREIGN KEY (userId) REFERENCES users(id)
        )
      `, (err) => {
        if (err) console.error('Error creating payments table:', err);
        else console.log('✅ Таблиця payments готова');
      });

      // Таблиця підписок
      database.run(`
        CREATE TABLE IF NOT EXISTS subscriptions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          userId INTEGER NOT NULL,
          planId TEXT NOT NULL,
          starsPrice TEXT,
          cryptoPrice TEXT,
          startDate TEXT NOT NULL,
          endDate TEXT,
          status TEXT DEFAULT 'active',
          createdAt TEXT NOT NULL,
          updatedAt TEXT NOT NULL,
          FOREIGN KEY (userId) REFERENCES users(id)
        )
      `, (err) => {
        if (err) console.error('Error creating subscriptions table:', err);
        else console.log('✅ Таблиця subscriptions готова');
      });

      // Таблиця тарифів
      database.run(`
        CREATE TABLE IF NOT EXISTS plans (
          id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          starsPrice TEXT,
          cryptoPrice TEXT,
          days INTEGER,
          button TEXT,
          createdAt TEXT NOT NULL
        )
      `, (err) => {
        if (err) console.error('Error creating plans table:', err);
        else console.log('✅ Таблиця plans готова');
      });

      // Таблиця промокодів
      database.run(`
        CREATE TABLE IF NOT EXISTS promos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          code TEXT UNIQUE NOT NULL,
          discount INTEGER,
          planId TEXT,
          maxUses INTEGER,
          usedCount INTEGER DEFAULT 0,
          expiresAt TEXT,
          active INTEGER DEFAULT 1,
          createdAt TEXT NOT NULL,
          FOREIGN KEY (planId) REFERENCES plans(id)
        )
      `, (err) => {
        if (err) console.error('Error creating promos table:', err);
        else console.log('✅ Таблиця promos готова');
      });

      // Таблиця рассилок
      database.run(`
        CREATE TABLE IF NOT EXISTS broadcasts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          adminId INTEGER NOT NULL,
          message TEXT NOT NULL,
          targetUserIds TEXT,
          status TEXT DEFAULT 'pending',
          sentCount INTEGER DEFAULT 0,
          createdAt TEXT NOT NULL,
          sentAt TEXT
        )
      `, (err) => {
        if (err) console.error('Error creating broadcasts table:', err);
        else console.log('✅ Таблиця broadcasts готова');
      });

      database.run(`
        CREATE TABLE IF NOT EXISTS logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          userId INTEGER,
          action TEXT NOT NULL,
          details TEXT,
          createdAt TEXT NOT NULL
        )
      `, (err) => {
        if (err) console.error('Error creating logs table:', err);
        else console.log('✅ Таблиця logs готова');
      });

      resolve();
    });
  });
}

function run(sql, params = []) {
  return new Promise((resolve, reject) => {
    getDB().run(sql, params, function(err) {
      if (err) reject(err);
      else resolve({ lastID: this.lastID, changes: this.changes });
    });
  });
}

function get(sql, params = []) {
  return new Promise((resolve, reject) => {
    getDB().get(sql, params, (err, row) => {
      if (err) reject(err);
      else resolve(row);
    });
  });
}

function all(sql, params = []) {
  return new Promise((resolve, reject) => {
    getDB().all(sql, params, (err, rows) => {
      if (err) reject(err);
      else resolve(rows || []);
    });
  });
}

function close() {
  return new Promise((resolve, reject) => {
    if (db) {
      db.close((err) => {
        if (err) reject(err);
        else resolve();
      });
    } else resolve();
  });
}

module.exports = {
  initDB,
  getDB,
  run,
  get,
  all,
  close,
  DB_PATH
};
