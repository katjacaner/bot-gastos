# Bot de gastos por Telegram

Bot de Telegram al que le escribís en lenguaje natural — *"gasté 39000 en bolt"* — y
lo registra solo: una IA (Google Gemini) interpreta el monto y la categoría, el gasto
se guarda en PostgreSQL, y todos los lunes llega un resumen semanal automático.

```
Vos (Telegram) ──► bot.py ──► ai_extract.py ──► Gemini
                      │          (valida la respuesta)
                      ▼
                  PostgreSQL (Neon)
                      ▲
GitHub Actions ──► weekly_summary.py ──► resumen de los lunes por Telegram
  (cron semanal)
```

## Qué hace

| Mensaje | Respuesta del bot |
|---|---|
| `gasté 39000 en bolt` | ¿Guardo este gasto? 💰 $39.000 · 🏷 transporte · [✅ Confirmar] [❌ Cancelar] |
| *(editás tu mensaje a "3900")* | Actualiza la misma propuesta a 💰 $3.900 |
| *(tocás ✅ Confirmar)* | ✅ Guardado: $3.900 en transporte (Bolt) |
| `hola` | 🤔 Eso no parece un gasto |
| `/resumen` | 📊 Total por categoría de los últimos 7 días |

Nada se guarda hasta confirmarlo: si la IA entendió mal o hubo un error de tipeo, se
corrige editando el mensaje original.

## Stack

- **Python** · [python-telegram-bot](https://python-telegram-bot.org/)
- **Google Gemini** (capa gratuita) vía `google-genai`
- **PostgreSQL** en [Neon](https://neon.tech) · `psycopg`
- **GitHub Actions** para la tarea programada

## Decisiones de diseño

- **Base relacional, no una tabla plana.** `gastos.categoria_id` es una clave foránea a
  `categorias`: la base misma rechaza categorías inexistentes, además del código.
  Restricciones como `CHECK (monto > 0)` viven en el schema.
- **No se confía en la IA a ciegas.** `validar()` revisa cada respuesta: JSON mal formado,
  montos negativos o no numéricos se rechazan; una categoría inventada se reasigna a "otros".
- **Tolerancia a fallos de la API gratuita.** La capa gratuita tiene cupo diario por modelo
  (20 consultas/día en algunos) y devuelve 503 cuando está saturada. El código prueba una
  lista de modelos en orden y pasa al siguiente ante 429/503/404, en lugar de reintentar
  sobre un cupo ya agotado.
- **Confirmación antes de guardar.** Los gastos quedan pendientes en memoria hasta que el
  usuario toca ✅; editar el mensaje original recalcula la propuesta. Un gasto se retira de
  pendientes en el mismo paso en que se confirma, así un doble toque no lo duplica.
- **Consultas parametrizadas** (`%s`) en todo el SQL, para evitar inyección SQL.
- **Credenciales fuera del código:** `.env` local (ignorado por Git) y *secrets* de GitHub
  para la automatización. Los logs de `httpx` se silencian porque sus URLs incluyen el token.
- **SQL en un solo módulo** (`db.py`), compartido por el bot y el resumen semanal.

## Estructura

```
schema.sql            tablas, restricciones y categorías iniciales
ai_extract.py         texto libre -> gasto estructurado (Gemini + validación)
db.py                 todas las consultas a la base
bot.py                el bot de Telegram (/start, /resumen, registrar gastos)
weekly_summary.py     envía el resumen semanal y termina
.github/workflows/    ejecución programada de weekly_summary.py
```

## Cómo levantarlo

1. Crear un bot con [@BotFather](https://t.me/BotFather) y guardar el token.
2. Conseguir una API key gratuita de Gemini en [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
3. Crear una base Postgres (por ejemplo en Neon) y ejecutar `schema.sql` en ella.
4. Copiar `.env.example` a `.env` y completar los tres valores.
5. Instalar y correr:
   ```
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe bot.py
   ```
6. Para el resumen automático: cargar `TELEGRAM_TOKEN` y `DATABASE_URL` como *secrets*
   del repositorio (Settings → Secrets and variables → Actions).

## Limitaciones conocidas

- `bot.py` responde solo mientras está corriendo en una computadora; el resumen semanal,
  en cambio, corre en GitHub aunque la PC esté apagada. El próximo paso natural es
  desplegar el bot en un servidor (Railway, Render, etc.).
- En la capa gratuita de Gemini, Google puede usar el contenido enviado para mejorar sus
  productos: apto para práctica, no para datos reales de clientes.
