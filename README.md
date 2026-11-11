# Gestor MercadoLibre — Global3D

Director + subagentes (Claude Code) que publican y controlan las publicaciones de MercadoLibre
usando la base de Supabase del admin como fuente de verdad.

```
Vos ──▶ Director (CLAUDE.md) ──▶ catalogador · imagenes · publicador · auditor · atencion · ventas · mensajeria
                     │
                     └── memoria en Supabase (agent_memory) — no depende del historial del chat
```

## Puesta en marcha (una sola vez)

1. **App de MercadoLibre** (developers.mercadolibre.com.ar → Crear aplicación)
   - Redirect URI: `https://bukjmleercxlxbexekos.supabase.co/functions/v1/ml-oauth`
   - Permisos: lectura, escritura y offline access.
2. **Secretos en Supabase** (Dashboard → Edge Functions → Secrets):
   - `ML_CLIENT_ID` = App ID
   - `ML_CLIENT_SECRET` = Client Secret
   - `ML_LOGIN_KEY` = una clave inventada por vos (ej. 20 caracteres al azar)
3. **Vincular la cuenta**: abrí en el navegador, logueado con la cuenta vendedora:
   `https://bukjmleercxlxbexekos.supabase.co/functions/v1/ml-oauth?login=<ML_LOGIN_KEY>`
4. **En tu compu**:
   ```bash
   git clone https://github.com/nicolasyunes/global3d-gestor-ML.git && cd global3d-gestor-ML
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env    # pegá la Secret key (sb_secret_...) de Supabase
   python tools/ml.py yo   # debe mostrar tu usuario de ML
   claude                  # abre el director
   ```

## Uso
Hablale al director normalmente:
- "¿Qué familias me faltan publicar en ML?"
- "Armá los borradores de los mates y las macetas"
- "Publicá los que aprobé"
- "Auditá ML" / "Corregí las diferencias"
- "¿Tengo preguntas sin responder?"

Cada vez que vuelvas, abrí una conversación nueva (`claude`): el director lee su memoria de Supabase y sigue.

## Precios
| Canal | Cálculo |
|---|---|
| Web | `products.base_price` |
| Efectivo / transferencia | regla `price_rules.efectivo` (−10%) |
| MercadoLibre | regla `price_rules.ml` (+20%) |

Un precio puntual distinto para un producto se carga en `product_prices` y tiene prioridad.
Todo se ve junto en la vista `v_product_prices`.

## Tareas automáticas (sin IA, sin tokens)
Estos comandos no usan Claude; conviene programarlos cada 15-60 min (Programador de tareas de Windows):
```bash
python tools/ventas.py registrar   # registra ventas de ML en Supabase y descuenta stock
python tools/sync.py --aplicar     # lleva precio/stock de Supabase a ML
```

## Sincronización (detalle)
`python tools/sync.py` informa diferencias; `python tools/sync.py --aplicar` corrige precio/stock en ML.
Se puede programar (cron / Programador de tareas de Windows) cada hora.

## Estructura
- `CLAUDE.md` — instrucciones del director
- `.claude/agents/` — subagentes
- `tools/` — `db.py` (Supabase), `ml.py` (API ML), `imagenes.py`, `sync.py`
- `supabase/functions/` — `ml-oauth` (login/redirect) y `ml-token` (entrega y renueva el token). Ya desplegadas.
