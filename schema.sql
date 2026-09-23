-- Esquema de la base de datos del bot de gastos.
-- Dos tablas relacionadas: cada gasto pertenece a UNA categoría.

-- 1) Catálogo de categorías válidas.
--    Si la IA inventa una categoría que no está acá, el bot la rechaza.
CREATE TABLE IF NOT EXISTS categorias (
    id     SERIAL PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);

-- 2) Los gastos en sí.
CREATE TABLE IF NOT EXISTS gastos (
    id           SERIAL PRIMARY KEY,
    chat_id      BIGINT NOT NULL,                 -- quién lo cargó (id del chat de Telegram)
    monto        NUMERIC(12, 2) NOT NULL CHECK (monto > 0),
    descripcion  TEXT,
    categoria_id INTEGER NOT NULL REFERENCES categorias (id),  -- clave foránea
    creado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Acelera la consulta típica: "gastos de este chat en los últimos 7 días".
CREATE INDEX IF NOT EXISTS idx_gastos_chat_fecha ON gastos (chat_id, creado_en);

-- Categorías iniciales. ON CONFLICT hace que se pueda correr este archivo
-- varias veces sin duplicar nada.
INSERT INTO categorias (nombre) VALUES
    ('supermercado'),
    ('comida'),
    ('transporte'),
    ('servicios'),
    ('salud'),
    ('entretenimiento'),
    ('otros')
ON CONFLICT (nombre) DO NOTHING;
