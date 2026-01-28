-- ==========================================
-- SCHEMA DATABASE PER IL BOT DI RESELLING
-- ==========================================

-- 1. Tabella delle Ricerche (Sostituisce searches.tracked)
-- Qui salviamo cosa deve cercare il bot
CREATE TABLE IF NOT EXISTS ricerche (
    nome TEXT PRIMARY KEY,               -- Nome univoco della ricerca (es: 'iPhone 11')
    url TEXT NOT NULL,                   -- URL di Subito/Marketplace
    prezzo_min REAL DEFAULT 0,
    prezzo_max REAL DEFAULT 99999,
    attiva INTEGER DEFAULT 1,            -- 1 = Attiva, 0 = Pausa
    ultima_esecuzione DATETIME
);

-- 2. Tabella degli Annunci (La memoria storica)
CREATE TABLE IF NOT EXISTS annunci (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link TEXT NOT NULL UNIQUE,           -- UNIQUE garantisce niente duplicati
    titolo TEXT NOT NULL,
    prezzo REAL,
    categoria TEXT,                      -- Collegata al 'nome' della ricerca
    localita TEXT,
    data_scoperta DATETIME DEFAULT CURRENT_TIMESTAMP,
    ultimo_aggiornamento DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (categoria) REFERENCES ricerche (nome) ON DELETE CASCADE
);

-- 3. Indici per la velocità (Performance)
-- Fondamentale per calcolare la media mobile in millisecondi
CREATE INDEX IF NOT EXISTS idx_stats_prezzo ON annunci (categoria, prezzo);

-- 4. Trigger per l'aggiornamento automatico dei timestamp
CREATE TRIGGER IF NOT EXISTS trg_update_timestamp
AFTER UPDATE ON annunci
FOR EACH ROW
BEGIN
    UPDATE annunci SET ultimo_aggiornamento = CURRENT_TIMESTAMP WHERE id = OLD.id;
END;
