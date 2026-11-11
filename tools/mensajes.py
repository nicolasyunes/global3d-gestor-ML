"""Mensajería postventa con compradores de MercadoLibre.

Uso:
  python tools/mensajes.py pendientes          # conversaciones con mensajes sin leer
  python tools/mensajes.py ver <pack_id>       # últimos mensajes de una venta (no los marca como leídos)
  python tools/mensajes.py enviar <pack_id> "<texto>"   # SOLO con OK del dueño

pack_id: el de la venta (si la orden no tiene pack, es el mismo número de orden).
"""
import sys

from common import ml, ml_token, out, sb


def seller():
    return ml_token()["ml_user_id"]


def comprador(pack_id):
    r = sb("GET", "ml_orders", {"pack_id": f"eq.{pack_id}", "select": "buyer_id,buyer_nickname,items", "limit": 1})
    if r and r[0]["buyer_id"]:
        return r[0]
    s, o = ml("GET", f"/orders/{pack_id}")
    if s != 200:
        s, pk = ml("GET", f"/packs/{pack_id}")
        if s != 200 or not pk.get("orders"):
            sys.exit(f"No encuentro la venta {pack_id}")
        s, o = ml("GET", f"/orders/{pk['orders'][0]['id']}")
    b = o.get("buyer") or {}
    return {"buyer_id": b.get("id"), "buyer_nickname": b.get("nickname"),
            "items": [{"description": i["item"]["title"], "quantity": i["quantity"]} for i in o.get("order_items", [])]}


def ver(pack_id, n=10):
    uid = seller()
    s, d = ml("GET", f"/messages/packs/{pack_id}/sellers/{uid}", {"tag": "post_sale", "mark_as_read": "false"})
    if s != 200:
        out({"error": s, "detalle": d})
        sys.exit(1)
    estado = (d.get("conversation_status") or {})
    msgs = d.get("messages", [])[-n:]
    out({"pack_id": pack_id, "estado": estado.get("status"), "bloqueo": estado.get("substatus")})
    for m in msgs:
        quien = "yo" if (m.get("from") or {}).get("user_id") == uid else "comprador"
        out({"de": quien, "fecha": (m.get("message_date") or {}).get("created"), "texto": m.get("text")})


def pendientes():
    s, d = ml("GET", "/messages/unread", {"role": "seller", "tag": "post_sale"})
    if s != 200:
        out({"error": s, "detalle": d})
        sys.exit(1)
    res = d.get("results", d if isinstance(d, list) else [])
    if not res:
        out({"pendientes": 0})
    for r in res:
        recurso = r.get("resource", "")
        partes = recurso.strip("/").split("/")
        pack = partes[1] if len(partes) > 1 and partes[0] == "packs" else recurso
        c = comprador(pack)
        out({"pack_id": pack, "sin_leer": r.get("count"), "comprador": c.get("buyer_nickname"),
             "compro": [f'{i["quantity"]}x {i["description"]}' for i in c.get("items") or []]})


def enviar(pack_id, texto):
    if len(texto) > 350:
        sys.exit("Máximo 350 caracteres por mensaje")
    uid = seller()
    c = comprador(pack_id)
    s, d = ml("POST", f"/messages/packs/{pack_id}/sellers/{uid}", {"tag": "post_sale"},
              body={"from": {"user_id": uid}, "to": {"user_id": c["buyer_id"]}, "text": texto})
    if s not in (200, 201):
        out({"error": s, "detalle": d})
        sys.exit(1)
    out({"ok": True, "pack_id": pack_id})


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "pendientes":
        pendientes()
    elif a[0] == "ver":
        ver(a[1])
    elif a[0] == "enviar":
        enviar(a[1], a[2])
    else:
        sys.exit(__doc__)
