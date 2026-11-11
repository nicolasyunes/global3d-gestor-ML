"""Ventas y postventa de MercadoLibre. Fuente: API de ML -> libro de ventas de Supabase.

Uso:
  python tools/ventas.py nuevas [--dias 7]      # órdenes pagadas que todavía no están registradas
  python tools/ventas.py registrar [--dias 7]   # registra las nuevas (venta + descuento de stock) y anula las canceladas
  python tools/ventas.py despachos              # ventas sin entregar: estado del envío y fecha límite de despacho
  python tools/ventas.py orden <ml_order_id>    # detalle de una orden

'registrar' no toca nada en MercadoLibre: solo escribe en Supabase. Se puede programar (cron / Programador de tareas).
"""
import datetime
import sys

from common import ml, ml_token, out, sb


def dias_arg(a, default=7):
    return int(a[a.index("--dias") + 1]) if "--dias" in a else default


def ordenes_ml(dias):
    uid = ml_token()["ml_user_id"]
    desde = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S.000-00:00")
    res, offset = [], 0
    while True:
        s, d = ml("GET", "/orders/search", {"seller": uid, "sort": "date_desc", "order.date_created.from": desde,
                                            "limit": 50, "offset": offset})
        if s != 200:
            out({"error": s, "detalle": d})
            sys.exit(1)
        res += d.get("results", [])
        offset += 50
        if offset >= d.get("paging", {}).get("total", 0):
            return res


def mapa_listings():
    m = {}
    for l in sb("GET", "ml_listings", {"select": "ml_item_id,ml_variation_id,product_id,family_id"}):
        m[(l["ml_item_id"], str(l["ml_variation_id"]) if l["ml_variation_id"] else None)] = l
    fams = {f["id"]: f["sale_mode"] for f in sb("GET", "shop_families", {"select": "id,sale_mode"})}
    return m, fams


def armar_payload(o, mapa, fams):
    items = []
    for it in o.get("order_items", []):
        item = it.get("item", {})
        var = str(item["variation_id"]) if item.get("variation_id") else None
        l = mapa.get((item.get("id"), var)) or mapa.get((item.get("id"), None))
        pid = l["product_id"] if l else None
        a_pedido = l and fams.get(l["family_id"]) == "a_pedido"
        items.append({"product_id": pid, "description": item.get("title", "")[:200], "quantity": it.get("quantity", 1),
                      "unit_price": it.get("unit_price"), "descontar_stock": not a_pedido,
                      "ml_item_id": item.get("id"), "ml_variation_id": var})
    return {"ml_order_id": o["id"], "pack_id": o.get("pack_id") or o["id"], "sold_at": o.get("date_closed") or o.get("date_created"),
            "total": o.get("total_amount"), "status": o.get("status"), "buyer_id": (o.get("buyer") or {}).get("id"),
            "buyer_nickname": (o.get("buyer") or {}).get("nickname"), "shipping_id": (o.get("shipping") or {}).get("id"),
            "items": items}


def ya_registradas():
    return {r["ml_order_id"]: r for r in sb("GET", "ml_orders", {"select": "ml_order_id,voided"})}


def nuevas(dias, registrar=False):
    ords = ordenes_ml(dias)
    reg = ya_registradas()
    mapa, fams = mapa_listings()
    resumen = {"nuevas": 0, "registradas": 0, "anuladas": 0, "sin_vincular": 0}
    for o in ords:
        st = o.get("status")
        if st == "cancelled" and o["id"] in reg and not reg[o["id"]]["voided"]:
            if registrar:
                sb("POST", "rpc/ml_void_sale", body={"p_order": o["id"], "p_reason": "Cancelada en MercadoLibre"})
                resumen["anuladas"] += 1
            out({"orden": o["id"], "accion": "anular" if not registrar else "anulada"})
            continue
        if st != "paid" or o["id"] in reg:
            continue
        p = armar_payload(o, mapa, fams)
        resumen["nuevas"] += 1
        sin = [i["description"] for i in p["items"] if not i["product_id"]]
        if sin:
            resumen["sin_vincular"] += 1
        if registrar:
            sb("POST", "rpc/ml_register_sale", body={"p": p})
            resumen["registradas"] += 1
        out({"orden": o["id"], "fecha": p["sold_at"], "comprador": p["buyer_nickname"], "total": p["total"],
             "items": [f'{i["quantity"]}x {i["description"]}' for i in p["items"]],
             "sin_vincular": sin or None})
    out(resumen)


def despachos():
    rows = sb("GET", "ml_orders", {"select": "ml_order_id,pack_id,buyer_nickname,shipping_id,shipping_status,items",
                                   "voided": "eq.false", "shipping_id": "not.is.null",
                                   "or": "(shipping_status.is.null,shipping_status.not.in.(delivered,not_delivered,cancelled))"})
    for r in rows:
        s, d = ml("GET", f"/shipments/{r['shipping_id']}")
        if s != 200:
            out({"orden": r["ml_order_id"], "error_envio": s})
            continue
        limite = (((d.get("shipping_option") or {}).get("estimated_handling_limit") or {}).get("date")
                  or ((d.get("lead_time") or {}).get("estimated_handling_limit") or {}).get("date"))
        sb("PATCH", "ml_orders", {"ml_order_id": f"eq.{r['ml_order_id']}"},
           {"shipping_status": d.get("status"), "handling_limit": limite})
        if d.get("status") in ("delivered", "not_delivered", "cancelled"):
            continue
        out({"orden": r["ml_order_id"], "comprador": r["buyer_nickname"], "envio": d.get("status"),
             "subestado": d.get("substatus"), "despachar_antes_de": limite,
             "items": [f'{i["quantity"]}x {i["description"]}' for i in r["items"] or []]})


def orden(oid):
    s, o = ml("GET", f"/orders/{oid}")
    if s != 200:
        out({"error": s, "detalle": o})
        sys.exit(1)
    mapa, fams = mapa_listings()
    p = armar_payload(o, mapa, fams)
    p["pagos"] = [{"estado": x.get("status"), "monto": x.get("total_paid_amount")} for x in o.get("payments", [])]
    out(p)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "nuevas":
        nuevas(dias_arg(a))
    elif a[0] == "registrar":
        nuevas(dias_arg(a), registrar=True)
    elif a[0] == "despachos":
        despachos()
    elif a[0] == "orden":
        orden(a[1])
    else:
        sys.exit(__doc__)
