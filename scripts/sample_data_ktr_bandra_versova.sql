-- Sample data: two outlets — KTR Bandra and KTR Versova.
--
-- Usage:
--   psql "$POSTGRES_DB_URL" -f scripts/sample_data_ktr_bandra_versova.sql
--   (Strip +asyncpg query params or use a sync URL; or paste into any Postgres client.)
--
-- Before running: replace all __PLACEHOLDER__ strings with values from `.env.local`
-- (Petpooja, PhonePe, PineLabs). Use a distinct Petpooja `petpooja_restaurant_id` per
-- outlet — `petpooja_restaurant_id` / menu JSON `restaurantid` for webhook routing.
-- `menu_sharing_code` = Petpooja menu sharing code (same value as restID in APIs; often matches menu JSON).
--
-- Note: `salt_key_index` is VARCHAR(16) — use your real `SALT_KEY_INDEX` from env (often "1").
--
-- After running: call POST /admin/cache/invalidate with the appropriate X-Store-Id header
-- for each store id, or restart the app so Redis credential caches refresh.

DO $$
DECLARE
  bandra_id   INTEGER;
  versova_id  INTEGER;
BEGIN
  INSERT INTO stores (store_code, store_name, is_active)
  VALUES ('KTR-BANDRA', 'KTR Bandra', true)
  ON CONFLICT (store_code) DO UPDATE
    SET store_name = EXCLUDED.store_name,
        is_active = EXCLUDED.is_active;
  SELECT id INTO bandra_id FROM stores WHERE store_code = 'KTR-BANDRA';

  INSERT INTO stores (store_code, store_name, is_active)
  VALUES ('KTR-VERSOVA', 'KTR Versova', true)
  ON CONFLICT (store_code) DO UPDATE
    SET store_name = EXCLUDED.store_name,
        is_active = EXCLUDED.is_active;
  SELECT id INTO versova_id FROM stores WHERE store_code = 'KTR-VERSOVA';

  -- Petpooja (replace placeholders; menu_sharing_code = menu sharing code from Petpooja, used as restID)
  INSERT INTO store_petpooja_credentials (
    store_id, app_key, app_secret, access_token,
    petpooja_restaurant_id, menu_sharing_code,
    fetch_menu_url, create_order_url, callback_url
  ) VALUES
    (
      bandra_id,
      '__PETPOOJA_API_KEY__',
      '__PETPOOJA_API_SECRET__',
      '__PETPOOJA_ACCESS_TOKEN__',
      '__PP_REST_BANDRA__',
      '__PP_MENU_SHARING_BANDRA__',
      '__PETPOOJA_FETCH_MENU_URL__',
      '__PETPOOJA_CREATE_ORDER_URL__',
      '__PETPOOJA_CALLBACK_URL__'
    ),
    (
      versova_id,
      '__PETPOOJA_API_KEY__',
      '__PETPOOJA_API_SECRET__',
      '__PETPOOJA_ACCESS_TOKEN__',
      '__PP_REST_VERSOVA__',
      '__PP_MENU_SHARING_VERSOVA__',
      '__PETPOOJA_FETCH_MENU_URL__',
      '__PETPOOJA_CREATE_ORDER_URL__',
      '__PETPOOJA_CALLBACK_URL__'
    )
  ON CONFLICT (store_id) DO UPDATE SET
    app_key = EXCLUDED.app_key,
    app_secret = EXCLUDED.app_secret,
    access_token = EXCLUDED.access_token,
    petpooja_restaurant_id = EXCLUDED.petpooja_restaurant_id,
    menu_sharing_code = EXCLUDED.menu_sharing_code,
    fetch_menu_url = EXCLUDED.fetch_menu_url,
    create_order_url = EXCLUDED.create_order_url,
    callback_url = EXCLUDED.callback_url;

  -- PhonePe (replace per-outlet store/terminal ids from PhonePe dashboard)
  -- salt_key_index must fit VARCHAR(16) — copy SALT_KEY_INDEX from .env (typically one digit).
  INSERT INTO store_phonepe_credentials (
    store_id, merchant_id, salt_key, salt_key_index,
    phonepe_store_id, terminal_id, x_provider_id
  ) VALUES
    (
      bandra_id,
      '__PHONEPE_MERCHANT_ID__',
      '__PHONEPE_SALT_KEY__',
      '1',
      '__PHONEPE_STORE_ID_BANDRA__',
      '__PHONEPE_TERMINAL_ID_BANDRA__',
      '__PHONEPE_X_PROVIDER_ID__'
    ),
    (
      versova_id,
      '__PHONEPE_MERCHANT_ID__',
      '__PHONEPE_SALT_KEY__',
      '1',
      '__PHONEPE_STORE_ID_VERSOVA__',
      '__PHONEPE_TERMINAL_ID_VERSOVA__',
      '__PHONEPE_X_PROVIDER_ID__'
    )
  ON CONFLICT (store_id) DO UPDATE SET
    merchant_id = EXCLUDED.merchant_id,
    salt_key = EXCLUDED.salt_key,
    salt_key_index = EXCLUDED.salt_key_index,
    phonepe_store_id = EXCLUDED.phonepe_store_id,
    terminal_id = EXCLUDED.terminal_id,
    x_provider_id = EXCLUDED.x_provider_id;

  -- PineLabs Cloud EDC API (often shared merchant across outlets; one row per store)
  INSERT INTO store_pinelabs_credentials (
    store_id, base_url, merchant_id, user_id, security_token
  ) VALUES
    (
      bandra_id,
      '__PINELABS_EDC_BASE_URL__',
      '__PINELABS_EDC_MERCHANT_ID__',
      '__PINELABS_EDC_USER_ID__',
      '__PINELABS_EDC_SECURITY_TOKEN__'
    ),
    (
      versova_id,
      '__PINELABS_EDC_BASE_URL__',
      '__PINELABS_EDC_MERCHANT_ID__',
      '__PINELABS_EDC_USER_ID__',
      '__PINELABS_EDC_SECURITY_TOKEN__'
    )
  ON CONFLICT (store_id) DO UPDATE SET
    base_url = EXCLUDED.base_url,
    merchant_id = EXCLUDED.merchant_id,
    user_id = EXCLUDED.user_id,
    security_token = EXCLUDED.security_token;

  -- Kiosk terminals: PineLabs ClientID (terminal_id) + PineLabs Store ID per device
  DELETE FROM kiosk_terminals WHERE store_id IN (bandra_id, versova_id);

  INSERT INTO kiosk_terminals (store_id, terminal_id, pinelabs_store_id, mid_on_device, label, is_active)
  VALUES
    (bandra_id, '4724310', '1570451', '741921', 'KTR Bandra — terminal 1', true),
    (bandra_id, '4724309', '1570451', '741921', 'KTR Bandra — terminal 2', true),
    (versova_id, '2605783', '1223733', '741921', 'KTR Versova — terminal 1', true),
    (versova_id, '2605784', '1223733', '741921', 'KTR Versova — terminal 2', true);

  -- Staff PINs (unique per store_id + pin)
  DELETE FROM cash_pin WHERE store_id IN (bandra_id, versova_id);

  INSERT INTO cash_pin (store_id, pin, staff_name) VALUES
    (bandra_id, '9580', 'Devesh'),
    (bandra_id, '9581', 'Soham'),
    (bandra_id, '9582', 'Kyra'),
    (bandra_id, '9583', 'Shruti'),
    (bandra_id, '9584', 'Test'),
    (versova_id, '9580', 'Devesh'),
    (versova_id, '9581', 'Soham'),
    (versova_id, '9582', 'Kyra'),
    (versova_id, '9583', 'Shruti'),
    (versova_id, '9584', 'Test');

  -- Minimal Petpooja-shaped menus (empty catalog until webhook or API fills real data).
  -- `restaurantid` should match webhook routing: `petpooja_restaurant_id` or `menu_sharing_code` in DB.
  DELETE FROM menus WHERE store_id IN (bandra_id, versova_id) AND provider = 'petpooja';

  INSERT INTO menus (store_id, provider, data) VALUES
    (
      bandra_id,
      'petpooja',
      '{"success":"1","restaurantid":"__PP_REST_BANDRA__","categories":[],"items":[],"addongroups":[],"taxes":[]}'::jsonb
    ),
    (
      versova_id,
      'petpooja',
      '{"success":"1","restaurantid":"__PP_REST_VERSOVA__","categories":[],"items":[],"addongroups":[],"taxes":[]}'::jsonb
    );

  RAISE NOTICE 'KTR Bandra store_id=%, KTR Versova store_id=%', bandra_id, versova_id;
END $$;
