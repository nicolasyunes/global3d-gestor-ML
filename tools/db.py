"""Acceso a la base de Global3D (Supabase) para los agentes.

Uso:
  python tools/db.py pendientes                 # familias publicadas en la web y sin publicación en ML
  python tools/db.py familia <id|slug>          # todo lo necesario para publicar una familia
  python tools/db.py listings [--revisar]       # publicaciones de ML registradas
  python tools/db.py listing-guardar '<json>'   # alta/actualización en ml_listings (upsert por ml_item_id+ml_variation_id)
  python tools/db.py memoria                    # memoria del director
  python tools/db.py recordar <clave> "<texto>" # guarda/actualiza un recuerdo
  python tools/db.py olvidar <clave>
  python tools/db.py reglas-precio
"""
import json
import re
import sys

from common import out, sb

UUID = re.compile(r"^[0-9a-f-]{36}$")


def pendientes():
    fams = sb("GET", "shop_families", {"select": "id,slug,name,category,sale_mode,published,shop_family_products(product_id)",
                                       "published": "eq.true", "order": "position"})
    ya = {l["family_id"] for l in sb("GET", "ml_listings", {"select": "family_id"}) if l["family_id"]}
    for f in fams:
        if f["id"] not in ya:
            out({"id": f["id"], "slug": f["slug"], "nombre": f["name"], "cat": f["category"],
                 "modo": f["sale_mode"], "variantes": len(f["shop_family_products"])})


def familia(ref):
    flt = {"id": f"eq.{ref}"} if UUID.match(ref) else {"slug": f"eq.{ref}"}
    sel = ("id,slug,name,category,description,sale_mode,lead_days,min_qty,option_axes,ship_box,images,"
           "shop_family_products(option_values,position,products(id,name,description,stock_quantity,active,ship_box,"
           "product_images(url,position)))")
    rows = sb("GET", "shop_families", {"select": sel, **flt})
    if not rows:
        sys.exit("Familia no encontrada")
    f = rows[0]
    pids = [x["products"]["id"] for x in f["shop_family_products"]]
    precios = {}
    if pids:
        for p in sb("GET", "v_product_prices", {"product_id": f"in.({','.join(pids)})"}):
            precios[p["product_id"]] = p
    variantes = []
    for x in sorted(f["shop_family_products"], key=lambda v: v["position"] or 0):
        p = x["products"]
        pr = precios.get(p["id"], {})
        variantes.append({
            "product_id": p["id"], "nombre": p["name"], "opciones": x["option_values"],
            "stock": p["stock_quantity"], "activo": p["active"],
            "precio_ml": pr.get("price_ml"), "precio_web": pr.get("price_web"),
            "fotos": [i["url"] for i in sorted(p["product_images"], key=lambda i: i["position"] or 0)],
        })
    listings = sb("GET", "ml_listings", {"family_id": f"eq.{f['id']}",
                                         "select": "ml_item_id,ml_variation_id,status,product_id"})
    out({"id": f["id"], "slug": f["slug"], "nombre": f["name"], "categoria_web": f["category"],
         "descripcion": f["description"], "modo_venta": f["sale_mode"], "dias_fabricacion": f["lead_days"],
         "ejes_opciones": f["option_axes"], "caja_envio": f["ship_box"], "fotos_familia": f["images"] or [],
         "variantes": variantes, "publicaciones_ml": listings})


def listings(revisar=False):
    params = {"select": "ml_item_id,ml_variation_id,status,title,ml_price,ml_stock,family_id,product_id,needs_review,last_synced_at",
              "order": "updated_at.desc"}
    if revisar:
        params["needs_review"] = "eq.true"
    for l in sb("GET", "ml_listings", params):
        out(l)


def listing_guardar(raw):
    data = json.loads(raw)
    data.setdefault("ml_variation_id", None)
    # upsert manual (ml_variation_id puede ser null y el unique no lo cubre)
    flt = {"ml_item_id": f"eq.{data['ml_item_id']}",
           "ml_variation_id": f"eq.{data['ml_variation_id']}" if data["ml_variation_id"] else "is.null"}
    existing = sb("GET", "ml_listings", {"select": "id", **flt})
    if existing:
        res = sb("PATCH", "ml_listings", {"id": f"eq.{existing[0]['id']}"}, data, prefer="return=representation")
    else:
        res = sb("POST", "ml_listings", body=data, prefer="return=representation")
    out({"ok": True, "id": res[0]["id"]})


def memoria():
    for m in sb("GET", "agent_memory", {"scope": "eq.director", "order": "updated_at.desc", "select": "key,content,updated_at"}):
        out(m)


def recordar(key, content):
    sb("POST", "agent_memory", {"on_conflict": "scope,key"}, {"scope": "director", "key": key, "content": content},
       prefer="resolution=merge-duplicates")
    out({"ok": True})


def olvidar(key):
    sb("DELETE", "agent_memory", {"scope": "eq.director", "key": f"eq.{key}"})
    out({"ok": True})


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "pendientes":
        pendientes()
    elif cmd == "familia":
        familia(a[1])
    elif cmd == "listings":
        listings("--revisar" in a)
    elif cmd == "listing-guardar":
        listing_guardar(a[1])
    elif cmd == "memoria":
        memoria()
    elif cmd == "recordar":
        recordar(a[1], a[2])
    elif cmd == "olvidar":
        olvidar(a[1])
    elif cmd == "reglas-precio":
        for r in sb("GET", "price_rules", {"select": "channel,markup_pct,fixed_add,round_to"}):
            out(r)
    else:
        sys.exit(__doc__)
