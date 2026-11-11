// Devuelve un access_token válido de MercadoLibre, renovándolo si está por vencer.
// Solo acepta la service_role key (la usan los scripts del gestor). El client secret nunca sale de Supabase.
import { createClient } from "jsr:@supabase/supabase-js@2";

const TOKEN_URL = "https://api.mercadolibre.com/oauth/token";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// Acepta la service_role legacy o una secret key nueva (sb_secret_...).
// Una secret key se valida leyendo ml_auth por la Data API: esa tabla tiene RLS sin políticas,
// así que solo una clave con privilegios de servicio obtiene la fila.
async function claveValida(key: string, url: string, serviceKey: string): Promise<boolean> {
  if (!key) return false;
  if (key === serviceKey) return true;
  if (!key.startsWith("sb_secret_")) return false;
  const r = await fetch(`${url}/rest/v1/ml_auth?select=id`, { headers: { apikey: key } });
  if (!r.ok) return false;
  const rows = await r.json();
  return Array.isArray(rows) && rows.length > 0;
}

Deno.serve(async (req) => {
  const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  const URL_SB = Deno.env.get("SUPABASE_URL")!;
  const bearer = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const key = req.headers.get("apikey") || bearer;
  if (!(await claveValida(key, URL_SB, SERVICE_KEY))) return json({ error: "unauthorized" }, 401);

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, SERVICE_KEY);
  const { data: row, error } = await sb.from("ml_auth").select("*").eq("id", 1).maybeSingle();
  if (error) return json({ error: error.message }, 500);
  if (!row?.access_token) return json({ error: "Cuenta de ML no vinculada todavía" }, 409);

  const force = new URL(req.url).searchParams.get("force") === "1";
  const margin = 10 * 60 * 1000; // renovar 10 min antes de vencer
  const vigente = new Date(row.expires_at).getTime() - Date.now() > margin;
  if (!row.refresh_token) {
    if (vigente) return json({ access_token: row.access_token, ml_user_id: row.ml_user_id, expires_at: row.expires_at,
      aviso: "Sin refresh_token: activá 'offline access' en la app de ML y volvé a vincular" });
    return json({ error: "Token vencido y sin refresh_token: activá 'offline access' en la app de ML y volvé a vincular" }, 409);
  }
  if (!force && vigente) {
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
