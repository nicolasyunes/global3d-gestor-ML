// Sincroniza en el momento precio, stock y plazo de fabricación de las publicaciones de ML de un producto.
// La llama un trigger de la base (pg_net) cuando cambia el stock, el precio o el estado de un producto.
// Misma regla que tools/sync.py. Se autentica con un secreto guardado en ml_auth.hook_secret.
import { createClient } from "jsr:@supabase/supabase-js@2";

const ML_API = "https://api.mercadolibre.com";
const TOKEN_URL = `${ML_API}/oauth/token`;
const STOCK_FABRICABLE = 3;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// deno-lint-ignore no-explicit-any
type Sb = any;

async function accessToken(sb: Sb): Promise<string | null> {
  const { data: row } = await sb.from("ml_auth").select("*").eq("id", 1).maybeSingle();
  if (!row?.access_token) return null;
  const vigente = new Date(row.expires_at).getTime() - Date.now() > 10 * 60 * 1000;
  if (vigente || !row.refresh_token) return vigente ? row.access_token : null;
  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      client_id: Deno.env.get("ML_CLIENT_ID")!,
      client_secret: Deno.env.get("ML_CLIENT_SECRET")!,
      refresh_token: row.refresh_token,
    }),
  });
  const data = await res.json();
  if (!res.ok) return null;
  const expires_at = new Date(Date.now() + data.expires_in * 1000).toISOString();
  // refresh_token de un solo uso: guardar solo si nadie lo renovó en paralelo
  const { data: upd } = await sb.from("ml_auth")
    .update({ access_token: data.access_token, refresh_token: data.refresh_token, expires_at })
    .eq("id", 1).eq("refresh_token", row.refresh_token).select("id");
  if (!upd?.length) {
    const { data: fresh } = await sb.from("ml_auth").select("access_token").eq("id", 1).single();
    return fresh.access_token;
  }
  return data.access_token;
}

function reglaStock(stock: number | null, activo: boolean, saleMode: string | null, leadDays: number | null) {
  const real = Math.max(stock ?? 0, 0);
  const lead = leadDays ?? 0;
  if (!activo) return { stock: 0, plazo: null as number | null };
  if (saleMode === "a_pedido") return { stock: STOCK_FABRICABLE, plazo: lead || 5 };
  if (real > 0) return { stock: real, plazo: null };
  if (lead > 0) return { stock: STOCK_FABRICABLE, plazo: lead };
  return { stock: 0, plazo: null };
}

// deno-lint-ignore no-explicit-any
function plazoActual(item: any): number | null {
  // deno-lint-ignore no-explicit-any
  const t = (item.sale_terms ?? []).find((x: any) => x.id === "MANUFACTURING_TIME");
  if (!t) return null;
  const n = t.value_struct?.number ?? parseInt(String(t.value_name ?? ""), 10);
  return Number.isFinite(n) ? n : null;
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "method" }, 405);
  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

  const { data: auth } = await sb.from("ml_auth").select("hook_secret").eq("id", 1).maybeSingle();
  const secret = req.headers.get("x-hook-secret") ?? "";
  if (!auth?.hook_secret || secret !== auth.hook_secret) return json({ error: "unauthorized" }, 401);

  const body = await req.json().catch(() => ({}));
  const productId: string | undefined = body.product_id;
  if (!productId) return json({ error: "product_id requerido" }, 400);

  const { data: listings } = await sb.from("ml_listings")
    .select("id, ml_item_id, ml_variation_id, family_id")
    .eq("product_id", productId).neq("status", "closed");
  if (!listings?.length) return json({ ok: true, publicaciones: 0 });

  const [{ data: prod }, { data: precio }] = await Promise.all([
    sb.from("products").select("stock_quantity, active").eq("id", productId).single(),
    sb.from("v_product_prices").select("price_ml").eq("product_id", productId).single(),
  ]);
  if (!prod || !precio) return json({ error: "producto no encontrado" }, 404);

  const token = await accessToken(sb);
  if (!token) return json({ error: "sin token de ML" }, 409);
  const H = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
  const ahora = new Date().toISOString();
  const res: unknown[] = [];

  for (const l of listings) {
    let fam: { sale_mode: string | null; lead_days: number | null } | null = null;
    if (l.family_id) {
      const { data } = await sb.from("shop_families").select("sale_mode, lead_days").eq("id", l.family_id).maybeSingle();
      fam = data;
    }
    const want = reglaStock(prod.stock_quantity, prod.active, fam?.sale_mode ?? null, fam?.lead_days ?? null);
    // Sin precio cargado en Supabase no se toca el precio de ML (nunca publicar $0).
    const wantPrice = precio.price_ml == null || !(Number(precio.price_ml) > 0) ? null : Number(precio.price_ml);

    const r = await fetch(`${ML_API}/items/${l.ml_item_id}`, { headers: H });
    if (!r.ok) { res.push({ item: l.ml_item_id, error: r.status }); continue; }
    const item = await r.json();
    // deno-lint-ignore no-explicit-any
    const src = l.ml_variation_id ? (item.variations ?? []).find((v: any) => String(v.id) === String(l.ml_variation_id)) : item;
    if (!src) { res.push({ item: l.ml_item_id, error: "variación inexistente" }); continue; }

    // deno-lint-ignore no-explicit-any
    const put: Record<string, any> = {};
    const difPrecio = wantPrice !== null && Math.abs(Number(src.price ?? 0) - wantPrice) > 0.5;
    const difStock = Number(src.available_quantity ?? 0) !== want.stock;
    if (difPrecio || difStock) {
      if (l.ml_variation_id) {
        // deno-lint-ignore no-explicit-any
        const v: Record<string, any> = { id: Number(l.ml_variation_id), available_quantity: want.stock };
        if (wantPrice !== null) v.price = wantPrice;
        put.variations = [v];
      } else {
        if (difStock) put.available_quantity = want.stock;
        if (difPrecio) put.price = wantPrice;
      }
    }
    // El plazo es por publicación: solo se toca en publicaciones de un solo producto.
    if (!l.ml_variation_id && plazoActual(item) !== want.plazo) {
      put.sale_terms = [{ id: "MANUFACTURING_TIME", value_name: want.plazo ? `${want.plazo} días` : null }];
    }
    if (want.stock > 0 && item.status === "paused" && (item.sub_status ?? []).includes("out_of_stock")) put.status = "active";

    let ok = true;
    let detalle: unknown = null;
    if (Object.keys(put).length) {
      const u = await fetch(`${ML_API}/items/${l.ml_item_id}`, { method: "PUT", headers: H, body: JSON.stringify(put) });
      ok = u.ok;
      if (!ok) detalle = await u.json().catch(() => null);
    }
    await sb.from("ml_listings").update({
      ml_price: ok && wantPrice !== null ? wantPrice : src.price, ml_stock: ok ? want.stock : src.available_quantity,
      needs_review: !ok, last_synced_at: ahora,
      last_audit: { fecha: ahora, origen: "tiempo_real", cambios: Object.keys(put), error: detalle },
    }).eq("id", l.id);
    res.push({ item: l.ml_item_id, cambios: Object.keys(put), ok });
  }
  return json({ ok: true, resultados: res });
});
