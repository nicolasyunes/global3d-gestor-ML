"""Compara Supabase (fuente de verdad) con MercadoLibre y opcionalmente corrige precio, stock y plazo.
No usa IA: se puede correr a mano o programado.

Uso:
  python tools/sync.py             # solo informa diferencias (no toca nada)
  python tools/sync.py --aplicar   # corrige ML para que coincida con Supabase

Reglas (ver regla_stock):
  - precio = v_product_prices.price_ml (base_price +20% o precio manual de product_prices)
  - con stock real                         -> stock real, sin plazo de fabricación (envío inmediato)
  - sin stock y la familia tiene lead_days -> STOCK_FABRICABLE unidades + MANUFACTURING_TIME = lead_days
  - familia 'a_pedido'                     -> STOCK_FABRICABLE + MANUFACTURING_TIME siempre
  - sin stock y sin lead_days, o inactivo  -> 0 (ML pausa la publicación)
  Se publica un producto por publicación, así que el plazo de cada publicación depende solo de ese producto.
  (Si hubiera publicaciones viejas con variaciones, el plazo es por publicación y se usa el mayor.)
"""
import datetime
import sys
from collections import defaultdict

from common import ml, out, sb

STOCK_FABRICABLE = 3


def regla_stock(stock_real, activo, sale_mode, lead_days):
    """Devuelve (stock_a_publicar, dias_fabricacion o None)."""
    stock_real = max(stock_real or 0, 0)
    lead = lead_days or 0
    if not activo:
        return 0, None
    if sale_mode == "a_pedido":
        return STOCK_FABRICABLE, (lead or 5)
    if stock_real > 0:
        return stock_real, None
    if lead > 0:
        return STOCK_FABRICABLE, lead
    return 0, None


def plazo_actual(item):
    for t in item.get("sale_terms") or []:
        if t.get("id") == "MANUFACTURING_TIME":
            num = (t.get("value_struct") or {}).get("number")
            if num is None and t.get("value_name"):
                try:
                    num = int(str(t["value_name"]).split()[0])
                except ValueError:
                    num = None
            return num
    return None


def main(aplicar):
    rows = sb("GET", "ml_listings", {"select": "id,ml_item_id,ml_variation_id,product_id,family_id,status",
                                     "product_id": "not.is.null", "status": "neq.closed"})
    if not rows:
        out({"info": "No hay publicaciones vinculadas en ml_listings"})
        return
    pids = sorted({r["product_id"] for r in rows})
    precios = {p["product_id"]: p for p in sb("GET", "v_product_prices", {"product_id": f"in.({','.join(pids)})"})}
    prods = {p["id"]: p for p in sb("GET", "products", {"id": f"in.({','.join(pids)})",
                                                         "select": "id,name,stock_quantity,active"})}
    fam_ids = sorted({r["family_id"] for r in rows if r["family_id"]})
    fams = {}
    if fam_ids:
        fams = {f["id"]: f for f in sb("GET", "shop_families",
                                       {"id": f"in.({','.join(fam_ids)})", "select": "id,sale_mode,lead_days"})}
    por_item = defaultdict(list)
    for r in rows:
        por_item[r["ml_item_id"]].append(r)

    resumen = {"revisados": 0, "con_diferencias": 0, "corregidos": 0}
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for item_id, filas in por_item.items():
        s, item = ml("GET", f"/items/{item_id}")
        if s != 200:
            out({"item": item_id, "error": s})
            continue
        resumen["revisados"] += 1
        vars_ml = {str(v["id"]): v for v in item.get("variations") or []}
        cambios_vars, cambio_simple, difs = [], {}, []
        plazos = []
        for f in filas:
            p, pr = prods.get(f["product_id"]), precios.get(f["product_id"])
            if not p or not pr:
                continue
            fam = fams.get(f["family_id"]) or {}
            want_price = float(pr["price_ml"])
            want_stock, plazo = regla_stock(p["stock_quantity"], p["active"], fam.get("sale_mode"), fam.get("lead_days"))
            if plazo:
                plazos.append(plazo)
            src = vars_ml.get(str(f["ml_variation_id"])) if f["ml_variation_id"] else item
            if src is None:
                difs.append({"producto": p["name"], "problema": "variación no existe en ML"})
                continue
            d = {}
            if abs(float(src.get("price") or 0) - want_price) > 0.5:
                d["precio"] = [src.get("price"), want_price]
            if int(src.get("available_quantity") or 0) != want_stock:
                d["stock"] = [src.get("available_quantity"), want_stock]
            sb("PATCH", "ml_listings", {"id": f"eq.{f['id']}"},
               {"last_audit": {"fecha": ahora, "diferencias": d}, "needs_review": bool(d),
                "ml_price": src.get("price"), "ml_stock": src.get("available_quantity"),
                "status": item.get("status"), "last_synced_at": ahora})
            if d:
                difs.append({"producto": p["name"], **d})
            if f["ml_variation_id"]:
                cambios_vars.append({"id": int(f["ml_variation_id"]), "price": want_price, "available_quantity": want_stock})
            else:
                cambio_simple = {"price": want_price, "available_quantity": want_stock}

        want_plazo = max(plazos) if plazos else None
        tiene_plazo = plazo_actual(item)
        cambio_plazo = None
        if want_plazo != tiene_plazo:
            difs.append({"plazo_fabricacion_dias": [tiene_plazo, want_plazo]})
            cambio_plazo = [{"id": "MANUFACTURING_TIME",
                             "value_name": f"{want_plazo} días" if want_plazo else None}]

        if difs:
            resumen["con_diferencias"] += 1
            out({"item": item_id, "titulo": item.get("title"), "diferencias": difs})
            if aplicar:
                body = {"variations": cambios_vars} if cambios_vars else dict(cambio_simple)
                if cambio_plazo:
                    body["sale_terms"] = cambio_plazo
                s2, d2 = ml("PUT", f"/items/{item_id}", body=body)
                if s2 == 200:
                    resumen["corregidos"] += 1
                    for f in filas:
                        sb("PATCH", "ml_listings", {"id": f"eq.{f['id']}"}, {"needs_review": False})
                else:
                    out({"item": item_id, "error_al_corregir": d2})
    out(resumen)


if __name__ == "__main__":
    main("--aplicar" in sys.argv)
