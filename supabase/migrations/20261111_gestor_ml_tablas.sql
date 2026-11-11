-- Ya aplicada en el proyecto Global-3D-Corrientes (bukjmleercxlxbexekos). Se guarda como registro.
-- Tablas: ml_listings, ml_auth (solo service_role), agent_memory, price_rules, product_prices; vista v_product_prices.
-- Reglas iniciales: ml +20%, efectivo -10% (igual a shop_settings.descuento_efectivo), redondeo a $100 hacia arriba.
create or replace function public.ml_touch_updated_at() returns trigger
language plpgsql set search_path = '' as $$ begin new.updated_at = now(); return new; end; $$;
-- (ver definición completa en el historial de migraciones de Supabase: gestor_ml_tablas)
