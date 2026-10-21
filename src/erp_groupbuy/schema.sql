PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, display_name TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('admin','buyer')),
 address TEXT NOT NULL DEFAULT '', department TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 category TEXT NOT NULL, unit TEXT NOT NULL, description TEXT NOT NULL,
 price INTEGER NOT NULL CHECK(price>0), tiers TEXT NOT NULL,
 visual TEXT NOT NULL DEFAULT 'box', color TEXT NOT NULL DEFAULT 'teal',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS cart_items (
 user_id INTEGER NOT NULL REFERENCES users(id), product_id INTEGER NOT NULL REFERENCES products(id),
 quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 9999), quoted_price INTEGER NOT NULL,
 PRIMARY KEY(user_id,product_id)
);
CREATE TABLE IF NOT EXISTS batches (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 supplier TEXT NOT NULL, created_at TEXT NOT NULL, expected_date TEXT NOT NULL,
 note TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 0,
 baseline_cost INTEGER NOT NULL, merged_cost INTEGER NOT NULL,
 original_lines INTEGER NOT NULL, order_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL REFERENCES users(id),
 address TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
 cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)),
 batch_id INTEGER REFERENCES batches(id), total INTEGER NOT NULL CHECK(total>0)
);
CREATE TABLE IF NOT EXISTS order_items (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id), sku TEXT NOT NULL,
 name TEXT NOT NULL, unit TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>0),
 quantity INTEGER NOT NULL CHECK(quantity>0), UNIQUE(order_id,product_id)
);
CREATE TABLE IF NOT EXISTS batch_items (
 id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches(id),
 product_id INTEGER NOT NULL REFERENCES products(id), sku TEXT NOT NULL,
 name TEXT NOT NULL, unit TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_cost INTEGER NOT NULL CHECK(unit_cost>0), tiers TEXT NOT NULL,
 UNIQUE(batch_id,product_id)
);
CREATE TABLE IF NOT EXISTS receipts (
 id INTEGER PRIMARY KEY, batch_item_id INTEGER NOT NULL REFERENCES batch_items(id),
 quantity INTEGER NOT NULL CHECK(quantity>0), reference TEXT NOT NULL,
 created_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', UNIQUE(batch_item_id,reference)
);
CREATE TABLE IF NOT EXISTS allocations (
 id INTEGER PRIMARY KEY, batch_item_id INTEGER NOT NULL REFERENCES batch_items(id),
 order_item_id INTEGER NOT NULL REFERENCES order_items(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 UNIQUE(batch_item_id,order_item_id)
);
CREATE TABLE IF NOT EXISTS deliveries (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, batch_id INTEGER NOT NULL REFERENCES batches(id),
 user_id INTEGER NOT NULL REFERENCES users(id), address TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','shipped','signed','void')),
 created_at TEXT NOT NULL, shipped_at TEXT, signed_at TEXT,
 carrier_note TEXT NOT NULL DEFAULT '', issue_note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS delivery_items (
 id INTEGER PRIMARY KEY, delivery_id INTEGER NOT NULL REFERENCES deliveries(id),
 allocation_id INTEGER NOT NULL REFERENCES allocations(id), quantity INTEGER NOT NULL CHECK(quantity>0),
 UNIQUE(delivery_id,allocation_id)
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, actor_id INTEGER NOT NULL REFERENCES users(id),
 entity TEXT NOT NULL, entity_id INTEGER NOT NULL, action TEXT NOT NULL,
 detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
 request_key TEXT PRIMARY KEY, actor_id INTEGER NOT NULL REFERENCES users(id),
 kind TEXT NOT NULL, fingerprint TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id,created_at);
CREATE INDEX IF NOT EXISTS idx_orders_batch ON orders(batch_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_receipts_item ON receipts(batch_item_id);
CREATE INDEX IF NOT EXISTS idx_allocations_order_item ON allocations(order_item_id);
CREATE INDEX IF NOT EXISTS idx_delivery_items_allocation ON delivery_items(allocation_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_user ON deliveries(user_id,status);
CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity,entity_id);
