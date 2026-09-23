"""Acceso a la base de datos: todas las consultas SQL del proyecto viven acá.

Lo usan tanto bot.py como weekly_summary.py, así no repetimos SQL en dos lugares.
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv()


def conectar():
    return psycopg.connect(os.environ["DATABASE_URL"])


def obtener_categorias():
    with conectar() as con:
        filas = con.execute("SELECT nombre FROM categorias ORDER BY id").fetchall()
    return [nombre for (nombre,) in filas]


def guardar_gasto(chat_id, monto, categoria, descripcion):
    """Inserta el gasto buscando el id de la categoría por su nombre. Devuelve el id del gasto."""
    with conectar() as con:
        # Los %s se completan con los valores de la tupla. NUNCA armar el SQL pegando
        # texto del usuario con f-strings: eso abre la puerta a inyección SQL.
        fila = con.execute(
            """
            INSERT INTO gastos (chat_id, monto, descripcion, categoria_id)
            SELECT %s, %s, %s, id FROM categorias WHERE nombre = %s
            RETURNING id
            """,
            (chat_id, monto, descripcion, categoria),
        ).fetchone()
    if fila is None:
        raise ValueError(f"La categoría {categoria!r} no existe en la base")
    return fila[0]


def resumen_semanal(chat_id):
    """Total por categoría de los últimos 7 días, de mayor a menor: [(nombre, total), ...]."""
    with conectar() as con:
        return con.execute(
            """
            SELECT c.nombre, SUM(g.monto) AS total
            FROM gastos g
            JOIN categorias c ON c.id = g.categoria_id
            WHERE g.chat_id = %s
              AND g.creado_en >= now() - interval '7 days'
            GROUP BY c.nombre
            ORDER BY total DESC
            """,
            (chat_id,),
        ).fetchall()


def chats_activos():
    """Chats que cargaron al menos un gasto en los últimos 7 días (a quién mandarle el resumen)."""
    with conectar() as con:
        filas = con.execute(
            "SELECT DISTINCT chat_id FROM gastos WHERE creado_en >= now() - interval '7 days'"
        ).fetchall()
    return [chat_id for (chat_id,) in filas]


def formato_pesos(monto):
    """Decimal('30000.00') -> '$30.000'  |  Decimal('1500.50') -> '$1.500,50'"""
    texto = f"{monto:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return "$" + texto.removesuffix(",00")


def armar_resumen(chat_id):
    """Texto listo para mandar por Telegram con los gastos de la semana."""
    filas = resumen_semanal(chat_id)
    if not filas:
        return "No registraste gastos en los últimos 7 días."
    total = sum(monto for _, monto in filas)
    lineas = [f"• {nombre}: {formato_pesos(monto)}" for nombre, monto in filas]
    return (
        "📊 Tus gastos de los últimos 7 días:\n\n"
        + "\n".join(lineas)
        + f"\n\nTotal: {formato_pesos(total)}"
    )
