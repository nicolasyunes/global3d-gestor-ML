"""Compara Supabase (fuente de verdad) con MercadoLibre y opcionalmente corrige precio y stock.
No usa IA: se puede correr a mano o programado (cron).

Uso:
  python tools/sync.py             # solo informa diferencias (no toca nada)
  python tools/sync.py --aplicar   # corrige precio/stock en ML para que coincida con Supabase

Reglas:
  - precio  = v_product_prices.price_ml (base_price +20% o precio manual de product_prices)
  - stock   = products.stock_quantity; si la familia es 'a_pedido' se publica STOCK_A_PEDIDO
"""
import datetime
import sys
from collections import defaultdict

from common import ml, out, sb

STOCK_A_PEDIDO = 5


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
    modos = {}
    if fam_ids:
        modos = {f["id"]: f["sale_mode"] for f in sb("GET", "shop_families",
                                                    {"id": f"in.({','.join(fam_ids)})", "select": "id,sale_mode"})}
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
        for f in filas:
            p, pr = prods.get(f["product_id"]), precios.get(f["product_id"])
            if not p or not pr:
                continue
            want_price = float(pr["price_ml"])
            want_stock = STOCK_A_PEDIDO if modos.get(f["family_id"]) == "a_pedido" else max(p["stock_quantity"] or 0, 0)
            if not p["active"]:
                want_stock = 0
            src = vars_ml.get(str(f["ml_variation_id"])) if f["ml_variation_id"] else item
            if src is None:
                difs.append({"producto": p["name"], "problema": "variación no existe en ML"})
                continue
            d = {}
            if abs(float(src.get("price") or 0) - want_price) > 0.5:
                d["precio"] = [src.get("price"), want_price]
            if int(src.get("available_quantity") or 0) != want_stock:
                d["stock"] = [src.get("available_quantity"), want_stock]
            audit = {"fecha": ahora, "diferencias": d}
            sb("PATCH", "ml_listings", {"id": f"eq.{f['id']}"},
               {"last_audit": audit, "needs_review": bool(d), "ml_price": src.get("price"),
                "ml_stock": src.get("available_quantity"), "status": item.get("status"), "last_synced_at": ahora})
            if d:
                difs.append({"producto": p["name"], **d})
                if f["ml_variation_id"]:
                    cambios_vars.append({"id": int(f["ml_variation_id"]), "price": want_price, "available_quantity": want_stock})
                else:
                    cambio_simple = {"price": want_price, "available_quantity": want_stock}
        if difs:
            resumen["con_diferencias"] += 1
            out({"item": item_id, "titulo": item.get("title"), "diferencias": difs})
            if aplicar:
                body = {"variations": cambios_vars} if cambios_vars else cambio_simple
                if body:
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
