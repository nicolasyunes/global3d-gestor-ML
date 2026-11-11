// Redirect URI de la app de MercadoLibre.
// 1) Abrí  .../functions/v1/ml-oauth?login=<ML_LOGIN_KEY>  -> te manda a autorizar en ML
// 2) ML vuelve acá con ?code=...  -> se guardan los tokens en public.ml_auth
import { createClient } from "jsr:@supabase/supabase-js@2";

const REDIRECT_URI = "https://bukjmleercxlxbexekos.supabase.co/functions/v1/ml-oauth";
const AUTH_URL = "https://auth.mercadolibre.com.ar/authorization";
const TOKEN_URL = "https://api.mercadolibre.com/oauth/token";

const text = (body: string, status = 200, headers: Record<string, string> = {}) =>
  new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8", ...headers } });

function getCookie(req: Request, name: string): string | null {
  const raw = req.headers.get("cookie") ?? "";
  for (const part of raw.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return null;
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const CLIENT_ID = Deno.env.get("ML_CLIENT_ID");
  const CLIENT_SECRET = Deno.env.get("ML_CLIENT_SECRET");
  const LOGIN_KEY = Deno.env.get("ML_LOGIN_KEY");
  if (!CLIENT_ID || !CLIENT_SECRET || !LOGIN_KEY) {
    return text("Faltan secretos ML_CLIENT_ID / ML_CLIENT_SECRET / ML_LOGIN_KEY en Supabase.", 500);
  }

  // Paso 1: iniciar login (protegido con ML_LOGIN_KEY para que nadie más vincule otra cuenta)
  const login = url.searchParams.get("login");
  if (login !== null) {
    if (login !== LOGIN_KEY) return text("Clave de login incorrecta.", 403);
    const state = crypto.randomUUID();
    const target = new URL(AUTH_URL);
    target.searchParams.set("response_type", "code");
    target.searchParams.set("client_id", CLIENT_ID);
    target.searchParams.set("redirect_uri", REDIRECT_URI);
    target.searchParams.set("state", state);
    return new Response(null, {
      status: 302,
      headers: {
        Location: target.toString(),
        "Set-Cookie": `ml_state=${state}; HttpOnly; Secure; SameSite=Lax; Path=/functions/v1/ml-oauth; Max-Age=600`,
      },
    });
  }

  // Paso 2: callback de ML
  const code = url.searchParams.get("code");
  if (!code) return text("Gestor ML Global3D: abrí esta URL con ?login=<clave> para vincular la cuenta.");
  const state = url.searchParams.get("state");
  if (!state || state !== getCookie(req, "ml_state")) return text("State inválido o vencido. Repetí el login.", 400);

  const res = await fetch(TOKEN_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      code,
      redirect_uri: REDIRECT_URI,
    }),
  });
  const data = await res.json();
  if (!res.ok) return text(`Error de MercadoLibre: ${JSON.stringify(data)}`, 502);

  const sb = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { error } = await sb.from("ml_auth").upsert({
    id: 1,
    ml_user_id: data.user_id,
    access_token: data.access_token,
    refresh_token: data.refresh_token,
    expires_at: new Date(Date.now() + data.expires_in * 1000).toISOString(),
  });
  if (error) return text(`Error guardando tokens: ${error.message}`, 500);

  return text(`Cuenta de MercadoLibre vinculada (user_id ${data.user_id}). Ya podés cerrar esta pestaña.`, 200, {
    "Set-Cookie": "ml_state=; Max-Age=0; Path=/functions/v1/ml-oauth",
  });
});
