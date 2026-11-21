CREATE TABLE IF NOT EXISTS omega_digital_offers (
  connection_id text NOT NULL,
  offer_key text NOT NULL,
  definition bytea NOT NULL,
  archive bytea NOT NULL,
  PRIMARY KEY (connection_id, offer_key)
);
CREATE TABLE IF NOT EXISTS omega_digital_orders (
  connection_id text NOT NULL,
  id uuid NOT NULL,
  buyer_hash bytea NOT NULL,
  offer_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  session_id text,
  checkout_url text NOT NULL DEFAULT '',
  payment_id text NOT NULL DEFAULT '',
  charge_id text NOT NULL DEFAULT '',
  payment integer NOT NULL DEFAULT 1,
  refunded bigint NOT NULL DEFAULT 0,
  dispute text NOT NULL DEFAULT '',
  entitled_at timestamptz,
  verified_at timestamptz,
  next_check timestamptz NOT NULL DEFAULT now(),
  downloads integer NOT NULL DEFAULT 0,
  PRIMARY KEY (connection_id, id),
  FOREIGN KEY (connection_id, offer_key) REFERENCES omega_digital_offers(connection_id, offer_key),
  UNIQUE (connection_id, session_id)
);
-- Existing orders are checked with Stripe before the UI offers a retry.
ALTER TABLE omega_digital_orders ADD COLUMN IF NOT EXISTS checkout_open boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS omega_digital_by_payment ON omega_digital_orders(connection_id, payment_id) WHERE payment_id <> '';
CREATE INDEX IF NOT EXISTS omega_digital_by_charge ON omega_digital_orders(connection_id, charge_id) WHERE charge_id <> '';
CREATE TABLE IF NOT EXISTS omega_digital_inbox (
  connection_id text NOT NULL,
  id text NOT NULL,
  event_type text NOT NULL,
  subject_kind text NOT NULL,
  subject_id text NOT NULL,
  observed_at bigint NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'queued',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt timestamptz NOT NULL DEFAULT now(),
  order_id uuid,
  PRIMARY KEY (connection_id,id),
  FOREIGN KEY (connection_id,order_id) REFERENCES omega_digital_orders(connection_id,id)
);
CREATE INDEX IF NOT EXISTS omega_digital_ready ON omega_digital_inbox(connection_id, status, next_attempt);
CREATE INDEX IF NOT EXISTS omega_digital_subject ON omega_digital_inbox(connection_id, subject_kind, subject_id);
