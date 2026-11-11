// Devuelve un access_token válido de MercadoLibre, renovándolo si está por vencer.
// Solo acepta la service_role key (la usan los scripts del gestor). El client secret nunca sale de Supabase.
import { createClient } from "jsr:@supabase/supabase-js@2";

const TOKEN_URL = "https://api.mercadolibre.com/oauth/token";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

Deno.serve(async (req) => {
  const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const auth = req.headers.get("authorization") ?? "";
  if (auth !== `Bearer ${SERVICE_KEY}`) return json({ error: "unauthorized" }, 401);

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, SERVICE_KEY);
  const { data: row, error } = await sb.from("ml_auth").select("*").eq("id", 1).maybeSingle();
  if (error) return json({ error: error.message }, 500);
  if (!row?.refresh_token) return json({ error: "Cuenta de ML no vinculada todavía" }, 409);

  const force = new URL(req.url).searchParams.get("force") === "1";
  const margin = 10 * 60 * 1000; // renovar 10 min antes de vencer
  if (!force && row.access_token && new Date(row.expires_at).getTime() - Date.now() > margin) {
    return json({ access_token: row.access_token, ml_user_id: row.ml_user_id, expires_at: row.expires_at });
  }

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
  if (!res.ok) return json({ error: "refresh_failed", detail: data }, 502);

  const expires_at = new Date(Date.now() + data.expires_in * 1000).toISOString();
  // El refresh_token de ML es de un solo uso: guardar el nuevo solo si nadie lo renovó en paralelo
  const { data: upd } = await sb.from("ml_auth")
    .update({ access_token: data.access_token, refresh_token: data.refresh_token, expires_at })
    .eq("id", 1).eq("refresh_token", row.refresh_token).select("id");
  if (!upd?.length) {
    const { data: fresh } = await sb.from("ml_auth").select("*").eq("id", 1).single();
    return json({ access_token: fresh.access_token, ml_user_id: fresh.ml_user_id, expires_at: fresh.expires_at });
  }
  return json({ access_token: data.access_token, ml_user_id: row.ml_user_id, expires_at });
});
