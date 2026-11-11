"""Cliente de la API de MercadoLibre para los agentes. Salida compacta en JSON.

Uso:
  python tools/ml.py yo                                   # verifica la cuenta vinculada
  python tools/ml.py categoria "<título tentativo>"       # predice categoría
  python tools/ml.py atributos <CATEGORY_ID> [--todos]    # atributos (por defecto solo obligatorios/importantes)
  python tools/ml.py validar <archivo.json>               # valida sin publicar
  python tools/ml.py publicar <archivo.json>              # publica (+ descripción si el JSON trae "_descripcion")
  python tools/ml.py item <MLA...>                        # estado actual de una publicación
  python tools/ml.py actualizar <MLA...> '<json>'         # PUT parcial (precio, stock, título, variaciones...)
  python tools/ml.py descripcion <MLA...> "<texto>"
  python tools/ml.py foto <archivo.jpg>                   # sube foto y devuelve su id
  python tools/ml.py estado <MLA...> active|paused|closed
  python tools/ml.py mis-items [--estado active]
  python tools/ml.py preguntas                            # preguntas sin responder
  python tools/ml.py responder <question_id> "<texto>"
"""
import json
import sys

from common import SITE, ml, ml_token, out


def need_ok(status, data, ok=(200, 201, 204)):
    if status not in ok:
        out({"error": status, "detalle": data})
        sys.exit(1)


def compact_item(d):
    return {
        "id": d.get("id"), "titulo": d.get("title"), "estado": d.get("status"), "sub_estado": d.get("sub_status"),
        "precio": d.get("price"), "stock": d.get("available_quantity"), "vendidos": d.get("sold_quantity"),
        "categoria": d.get("category_id"), "tipo": d.get("listing_type_id"), "link": d.get("permalink"),
        "sku": d.get("seller_custom_field"), "fotos": len(d.get("pictures") or []),
        "variaciones": [{"id": v["id"], "precio": v.get("price"), "stock": v.get("available_quantity"),
                         "sku": v.get("seller_custom_field"),
                         "combinacion": {a["id"]: a.get("value_name") for a in v.get("attribute_combinations", [])}}
                        for v in d.get("variations") or []],
    }


def main(a):
    cmd = a[0]
    if cmd == "yo":
        s, d = ml("GET", "/users/me")
        need_ok(s, d)
        out({"id": d["id"], "nickname": d["nickname"], "reputacion": d.get("seller_reputation", {}).get("level_id")})
    elif cmd == "categoria":
        s, d = ml("GET", f"/sites/{SITE}/domain_discovery/search", {"q": a[1], "limit": 3})
        need_ok(s, d)
        for c in d:
            out({"category_id": c["category_id"], "categoria": c["category_name"], "dominio": c.get("domain_name")})
    elif cmd == "atributos":
        s, d = ml("GET", f"/categories/{a[1]}/attributes")
        need_ok(s, d)
        todos = "--todos" in a
        for at in d:
            tags = at.get("tags", {})
            imp = tags.get("required") or tags.get("catalog_required") or at.get("relevance") == 1
            if tags.get("read_only") or (not todos and not imp):
                continue
            out({"id": at["id"], "nombre": at["name"], "tipo": at["value_type"],
                 "obligatorio": bool(tags.get("required") or tags.get("catalog_required")),
                 "variacion": bool(tags.get("allow_variations")),
                 "valores": [v["name"] for v in (at.get("values") or [])][:15]})
    elif cmd in ("validar", "publicar"):
        with open(a[1], encoding="utf-8") as fh:
            body = json.load(fh)
        desc = body.pop("_descripcion", None)
        body = {k: v for k, v in body.items() if not k.startswith("_")}
        if cmd == "validar":
            s, d = ml("POST", "/items/validate", body=body)
            if s == 204:
                out({"ok": True})
            else:
                out({"ok": False, "errores": [{"code": c.get("code"), "msg": c.get("message")}
                                              for c in d.get("cause", [])] or d})
            return
        s, d = ml("POST", "/items", body=body)
        need_ok(s, d)
        res = compact_item(d)
        if desc:
            s2, d2 = ml("POST", f"/items/{d['id']}/description", body={"plain_text": desc})
            res["descripcion_ok"] = s2 in (200, 201)
        out(res)
    elif cmd == "item":
        s, d = ml("GET", f"/items/{a[1]}")
        need_ok(s, d)
        out(compact_item(d))
    elif cmd == "actualizar":
        s, d = ml("PUT", f"/items/{a[1]}", body=json.loads(a[2]))
        need_ok(s, d)
        out(compact_item(d))
    elif cmd == "descripcion":
        s, d = ml("PUT", f"/items/{a[1]}/description", body={"plain_text": a[2]})
        need_ok(s, d)
        out({"ok": True})
    elif cmd == "foto":
        with open(a[1], "rb") as fh:
            s, d = ml("POST", "/pictures/items/upload", files={"file": fh})
        need_ok(s, d)
        out({"id": d["id"], "max_size": d.get("max_size")})
    elif cmd == "estado":
        s, d = ml("PUT", f"/items/{a[1]}", body={"status": a[2]})
        need_ok(s, d)
        out({"id": a[1], "estado": d.get("status")})
    elif cmd == "mis-items":
        uid = ml_token()["ml_user_id"]
        params = {"limit": 100}
        if "--estado" in a:
            params["status"] = a[a.index("--estado") + 1]
        s, d = ml("GET", f"/users/{uid}/items/search", params)
        need_ok(s, d)
        out({"total": d["paging"]["total"], "ids": d["results"]})
    elif cmd == "preguntas":
        uid = ml_token()["ml_user_id"]
        s, d = ml("GET", "/questions/search", {"seller_id": uid, "status": "UNANSWERED", "api_version": 4})
        need_ok(s, d)
        for q in d.get("questions", []):
            out({"id": q["id"], "item": q["item_id"], "texto": q["text"], "fecha": q["date_created"]})
    elif cmd == "responder":
        s, d = ml("POST", "/answers", body={"question_id": int(a[1]), "text": a[2]})
        need_ok(s, d)
        out({"ok": True})
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
