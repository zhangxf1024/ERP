"""Transactional business rules. Money is integer cents; inventory is integer units."""
import hashlib
import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .db import atomic, get_db


class BusinessError(ValueError):
    pass


def now():
    return datetime.now().isoformat(timespec="seconds")


def code(prefix, at=None):
    stamp = datetime.fromisoformat(at) if at else datetime.now()
    return f"{prefix}-{stamp:%y%m%d}-{uuid4().hex[:8].upper()}"


def integer(value, minimum=1, maximum=9999):
    try:
        text = str(value)
        result = int(text)
        if str(result) != text.strip() or not minimum <= result <= maximum:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise BusinessError(f"请输入 {minimum} 至 {maximum} 之间的整数。") from None


def clean(value, label, limit=300, required=True):
    value = str(value or "").strip()
    if (required and not value) or len(value) > limit:
        raise BusinessError(f"{label}不能为空，且不能超过 {limit} 个字符。" if required else f"{label}不能超过 {limit} 个字符。")
    return value


def cents(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > 100000 or amount * 100 != (amount * 100).to_integral_value():
            raise InvalidOperation
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise BusinessError("价格须大于 0、最多两位小数，且不超过 100000 元。") from None


def tier_price(tiers, quantity):
    tiers = json.loads(tiers) if isinstance(tiers, str) else tiers
    return max((t for t in tiers if t[0] <= quantity), key=lambda t: t[0])[1]


def require(conn, actor, role=None):
    user = conn.execute("SELECT * FROM users WHERE id=? AND active=1", (actor,)).fetchone()
    if not user or (role and user["role"] != role):
        raise BusinessError("当前账号无权执行此操作。")
    return user


def event(conn, actor, entity, identity, action, detail, at=None):
    conn.execute("INSERT INTO events(actor_id,entity,entity_id,action,detail,created_at) VALUES(?,?,?,?,?,?)",
                 (actor, entity, identity, action, detail, at or now()))


def command(actor, kind, key, payload, action, role=None):
    key = clean(key, "操作编号", 100)
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    try:
        with atomic() as conn:
            require(conn, actor, role)
            prior = conn.execute("SELECT * FROM requests WHERE request_key=?", (key,)).fetchone()
            if prior:
                if prior["actor_id"] != actor or prior["kind"] != kind or prior["fingerprint"] != fingerprint:
                    raise BusinessError("操作编号已使用，请刷新页面后重试。")
                return json.loads(prior["result"])
            result = action(conn)
            conn.execute("INSERT INTO requests VALUES(?,?,?,?,?)", (key, actor, kind, fingerprint, json.dumps(result)))
            return result
    except sqlite3.IntegrityError as exc:
        raise BusinessError("数据冲突：商品编码或到货凭证可能重复。请刷新后检查。") from exc
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc):
            raise BusinessError("系统正在处理其他操作，请稍后重试。") from exc
        raise


def set_cart(actor, product_id, quantity):
    quantity = integer(quantity, 0)
    with atomic() as conn:
        require(conn, actor, "buyer")
        product = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
        if not product and quantity:
            raise BusinessError("商品已下架或不存在。")
        if not quantity:
            conn.execute("DELETE FROM cart_items WHERE user_id=? AND product_id=?", (actor, product_id))
        else:
            conn.execute("INSERT INTO cart_items VALUES(?,?,?,?) ON CONFLICT(user_id,product_id) DO UPDATE SET quantity=excluded.quantity,quoted_price=excluded.quoted_price",
                         (actor, product_id, quantity, product["price"]))


def update_cart(actor, product_id, quantity, mode, key):
    quantity = integer(quantity, 0)
    def action(conn):
        target = quantity
        if mode == "add":
            previous = conn.execute("SELECT quantity FROM cart_items WHERE user_id=? AND product_id=?", (actor, product_id)).fetchone()
            target += previous[0] if previous else 0
        set_cart(actor, product_id, target)
        return product_id
    return command(actor, "cart", key, [product_id, quantity, mode], action, "buyer")


def _order(conn, actor, items, address, note, at=None):
    if not items or len(items) > 100:
        raise BusinessError("订单须包含 1 至 100 种商品。")
    address = clean(address, "收货地址", 200)
    note = clean(note, "订单备注", required=False)
    validated, seen = [], set()
    for item in items:
        pid = integer(item["product_id"], maximum=2147483647)
        if pid in seen:
            raise BusinessError("同一商品不能在订单中重复出现。")
        seen.add(pid)
        product = conn.execute("SELECT * FROM products WHERE id=? AND active=1", (pid,)).fetchone()
        qty = integer(item["quantity"])
        if not product:
            raise BusinessError("购物车中有商品已下架，请移除后重试。")
        if product["price"] != int(item["quoted_price"]):
            raise BusinessError(f"{product['name']} 价格已变化，请在购物车更新数量以确认新价格。")
        validated.append((product, qty))
    cursor = conn.execute("INSERT INTO orders(code,user_id,address,note,created_at,total) VALUES(?,?,?,?,?,?)",
                          (code("SO", at), actor, address, note, at or now(), sum(p["price"] * q for p, q in validated)))
    oid = cursor.lastrowid
    for p, qty in validated:
        conn.execute("INSERT INTO order_items(order_id,product_id,sku,name,unit,price,quantity) VALUES(?,?,?,?,?,?,?)",
                     (oid, p["id"], p["sku"], p["name"], p["unit"], p["price"], qty))
    event(conn, actor, "order", oid, "创建订单", f"{len(validated)} 种商品，地址已保存为订单快照", at)
    return oid


def create_order(actor, items, address, note, key, at=None):
    return command(actor, "order", key, [items, address, note],
                   lambda c: _order(c, actor, items, address, note, at), "buyer")


def checkout(actor, address, note, key):
    def action(conn):
        items = [dict(r) for r in conn.execute("SELECT * FROM cart_items WHERE user_id=? ORDER BY product_id", (actor,))]
        oid = _order(conn, actor, items, address, note)
        conn.execute("DELETE FROM cart_items WHERE user_id=?", (actor,))
        return oid
    return command(actor, "checkout", key, [address, note], action, "buyer")


def cancel_order(actor, oid, key):
    def action(conn):
        order = conn.execute("SELECT * FROM orders WHERE id=? AND user_id=?", (oid, actor)).fetchone()
        if not order or order["batch_id"] or order["cancelled"]:
            raise BusinessError("仅能取消本人尚未合单的有效订单。")
        conn.execute("UPDATE orders SET cancelled=1 WHERE id=?", (oid,))
        event(conn, actor, "order", oid, "取消订单", "买家在采购合单前取消")
        return oid
    return command(actor, "cancel", key, oid, action, "buyer")


def merge_orders(actor, order_ids, name, expected_date, note, key, at=None):
    ids = sorted(set(integer(x, maximum=2147483647) for x in order_ids))
    if not ids:
        raise BusinessError("请至少选择一张待合单订单。")
    name = clean(name, "采购批次名称", 80)
    try:
        date.fromisoformat(expected_date)
    except (ValueError, TypeError):
        raise BusinessError("请填写有效的预计到货日期。") from None
    note = clean(note, "批次备注", required=False)
    def action(conn):
        placeholders = ",".join("?" for _ in ids)
        orders = conn.execute(f"SELECT * FROM orders WHERE id IN ({placeholders}) AND cancelled=0 AND batch_id IS NULL", ids).fetchall()
        if len(orders) != len(ids):
            raise BusinessError("部分订单已取消或已合单，请刷新订单列表。")
        lines = conn.execute(f"SELECT oi.*,p.tiers FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id IN ({placeholders}) ORDER BY oi.id", ids).fetchall()
        groups, baseline = {}, 0
        for line in lines:
            baseline += line["quantity"] * tier_price(line["tiers"], line["quantity"])
            group = groups.setdefault(line["product_id"], dict(line) | {"quantity": 0})
            group["quantity"] += line["quantity"]
        merged = sum(g["quantity"] * tier_price(g["tiers"], g["quantity"]) for g in groups.values())
        bid = conn.execute("INSERT INTO batches(code,name,supplier,created_at,expected_date,note,baseline_cost,merged_cost,original_lines,order_count) VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (code("PO", at), name, "青禾校园物资供应中心（模拟）", at or now(), expected_date, note, baseline, merged, len(lines), len(ids))).lastrowid
        for g in groups.values():
            conn.execute("INSERT INTO batch_items(batch_id,product_id,sku,name,unit,quantity,unit_cost,tiers) VALUES(?,?,?,?,?,?,?,?)",
                         (bid, g["product_id"], g["sku"], g["name"], g["unit"], g["quantity"], tier_price(g["tiers"], g["quantity"]), g["tiers"]))
        conn.execute(f"UPDATE orders SET batch_id=? WHERE id IN ({placeholders})", [bid] + ids)
        for oid in ids:
            event(conn, actor, "order", oid, "加入采购批次", f"批次 #{bid}", at)
        event(conn, actor, "batch", bid, "采购订单合并", f"{len(ids)} 张订单 / {len(lines)} 行需求 → {len(groups)} 行采购；模拟节省 ¥{(baseline-merged)/100:.2f}", at)
        return bid
    return command(actor, "merge", key, [ids, name, expected_date, note], action, "admin")


def receive(actor, item_id, quantity, reference, note, key, at=None):
    quantity = integer(quantity, maximum=9999999)
    reference = clean(reference, "到货凭证号", 80)
    note = clean(note, "验收备注", required=False)
    def action(conn):
        item = conn.execute("SELECT * FROM batch_items WHERE id=?", (item_id,)).fetchone()
        if not item:
            raise BusinessError("采购明细不存在。")
        received = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM receipts WHERE batch_item_id=?", (item_id,)).fetchone()[0]
        if received + quantity > item["quantity"]:
            raise BusinessError("累计到货数量不能超过本批次采购数量。")
        conn.execute("INSERT INTO receipts(batch_item_id,quantity,reference,created_at,note) VALUES(?,?,?,?,?)",
                     (item_id, quantity, reference, at or now(), note))
        conn.execute("UPDATE batches SET version=version+1 WHERE id=?", (item["batch_id"],))
        event(conn, actor, "batch", item["batch_id"], "采购到货验收", f"{item['sku']} +{quantity}{item['unit']} · 凭证 {reference} · {note}", at)
        return item["batch_id"]
    return command(actor, "receive", key, [item_id, quantity, reference, note], action, "admin")


def allocation_plan(conn, bid, policy):
    if policy not in ("fifo", "fair"):
        raise BusinessError("分配策略无效。")
    if not conn.execute("SELECT id FROM batches WHERE id=?", (bid,)).fetchone():
        raise BusinessError("采购批次不存在。")
    plan = []
    for item in conn.execute("SELECT * FROM batch_items WHERE batch_id=? ORDER BY id", (bid,)).fetchall():
        received = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM receipts WHERE batch_item_id=?", (item["id"],)).fetchone()[0]
        allocated = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM allocations WHERE batch_item_id=?", (item["id"],)).fetchone()[0]
        available = received - allocated
        demands = [dict(r) for r in conn.execute("""SELECT oi.id AS order_item_id,oi.quantity,oi.name,oi.unit,o.code AS order_code,
            u.display_name,o.created_at,COALESCE(a.quantity,0) AS allocated
            FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN users u ON u.id=o.user_id
            LEFT JOIN allocations a ON a.order_item_id=oi.id AND a.batch_item_id=?
            WHERE o.batch_id=? AND oi.product_id=? ORDER BY o.created_at,o.id,oi.id""",
            (item["id"], bid, item["product_id"]))]
        for d in demands:
            d["remaining"] = d["quantity"] - d["allocated"]
        total = sum(d["remaining"] for d in demands)
        if available < 0 or available > total:
            raise BusinessError("数量守恒校验失败，请联系管理员核查数据。")
        values = [0] * len(demands)
        if policy == "fifo":
            left = available
            for i, d in enumerate(demands):
                values[i] = min(left, d["remaining"])
                left -= values[i]
        elif total:
            values = [available * d["remaining"] // total for d in demands]
            remainders = [available * d["remaining"] % total for d in demands]
            ranked = sorted(range(len(demands)), key=lambda i: (-remainders[i], i))
            for i in ranked[:available - sum(values)]:
                values[i] += 1
        for d, qty in zip(demands, values):
            plan.append(d | {"batch_item_id": item["id"], "quantity_new": qty, "shortage": d["remaining"] - qty})
    return plan


def allocate(actor, bid, policy, version, key, at=None):
    version = integer(version, 0, 2147483647)
    def action(conn):
        batch = conn.execute("SELECT * FROM batches WHERE id=?", (bid,)).fetchone()
        if not batch or batch["version"] != version:
            raise BusinessError("到货或分配数据已变化，请重新预览后确认。")
        plan = allocation_plan(conn, bid, policy)
        if not sum(p["quantity_new"] for p in plan):
            raise BusinessError("没有新的可分配到货数量。")
        for p in plan:
            if p["quantity_new"]:
                conn.execute("INSERT INTO allocations(batch_item_id,order_item_id,quantity) VALUES(?,?,?) ON CONFLICT(batch_item_id,order_item_id) DO UPDATE SET quantity=quantity+excluded.quantity",
                             (p["batch_item_id"], p["order_item_id"], p["quantity_new"]))
        conn.execute("UPDATE batches SET version=version+1 WHERE id=?", (bid,))
        event(conn, actor, "batch", bid, "确认到货分配", f"策略：{'先到先得' if policy == 'fifo' else '按剩余需求比例'}；本轮分配 {sum(p['quantity_new'] for p in plan)} 件", at)
        return bid
    return command(actor, "allocate", key, [bid, policy, version], action, "admin")


def generate_deliveries(actor, bid, key, at=None):
    def action(conn):
        if not conn.execute("SELECT id FROM batches WHERE id=?", (bid,)).fetchone():
            raise BusinessError("批次不存在。")
        lines = conn.execute("""SELECT a.id,a.quantity,o.user_id,o.address,
            COALESCE((SELECT SUM(di.quantity) FROM delivery_items di JOIN deliveries d ON d.id=di.delivery_id
            WHERE di.allocation_id=a.id AND d.status!='void'),0) AS reserved
            FROM allocations a JOIN batch_items bi ON bi.id=a.batch_item_id JOIN order_items oi ON oi.id=a.order_item_id
            JOIN orders o ON o.id=oi.order_id WHERE bi.batch_id=? ORDER BY o.user_id,o.address,a.id""", (bid,)).fetchall()
        groups = {}
        for line in lines:
            quantity = line["quantity"] - line["reserved"]
            if quantity > 0:
                groups.setdefault((line["user_id"], line["address"]), []).append((line["id"], quantity))
        if not groups:
            raise BusinessError("没有尚未生成配送单的分配数量；请先到货并分配。")
        ids = []
        for (uid, address), items in groups.items():
            did = conn.execute("INSERT INTO deliveries(code,batch_id,user_id,address,created_at) VALUES(?,?,?,?,?)",
                               (code("DO", at), bid, uid, address, at or now())).lastrowid
            ids.append(did)
            for aid, qty in items:
                conn.execute("INSERT INTO delivery_items(delivery_id,allocation_id,quantity) VALUES(?,?,?)", (did, aid, qty))
            event(conn, actor, "delivery", did, "生成配送单", f"来自采购批次 #{bid}；按买家和地址拆单", at)
        event(conn, actor, "batch", bid, "配送订单拆解", f"本轮新增 {len(ids)} 张配送单", at)
        return ids
    return command(actor, "deliveries", key, bid, action, "admin")


def change_delivery(actor, did, operation, note, key, at=None):
    note = clean(note, "操作说明", required=operation in ("void", "issue"))
    def action(conn):
        user = require(conn, actor)
        delivery = conn.execute("SELECT * FROM deliveries WHERE id=?", (did,)).fetchone()
        if not delivery:
            raise BusinessError("配送单不存在。")
        if operation in ("ship", "void"):
            if user["role"] != "admin" or delivery["status"] != "ready":
                raise BusinessError("只有管理员可以发出或作废待发货配送单。")
            if operation == "ship":
                conn.execute("UPDATE deliveries SET status='shipped',shipped_at=?,carrier_note=? WHERE id=?", (at or now(), note, did))
            else:
                conn.execute("UPDATE deliveries SET status='void',carrier_note=? WHERE id=?", (note, did))
        elif operation in ("sign", "issue"):
            if user["role"] != "buyer" or delivery["user_id"] != actor or delivery["status"] != "shipped":
                raise BusinessError("只有收货买家可以签收或反馈运输中的配送单。")
            if operation == "sign":
                conn.execute("UPDATE deliveries SET status='signed',signed_at=? WHERE id=?", (at or now(), did))
            else:
                conn.execute("UPDATE deliveries SET issue_note=? WHERE id=?", (note, did))
        else:
            raise BusinessError("未知配送操作。")
        labels = {"ship": "确认发货", "void": "作废配送单", "sign": "买家签收", "issue": "收货问题反馈"}
        event(conn, actor, "delivery", did, labels[operation], note or "状态已更新", at)
        return did
    return command(actor, "delivery-state", key, [did, operation, note], action)


def save_product(actor, pid, data, key):
    values = {k: clean(data.get(k), label, limit) for k, label, limit in
              [("sku", "SKU", 40), ("name", "名称", 80), ("category", "分类", 40), ("unit", "单位", 12), ("description", "描述", 500)]}
    values["price"] = cents(data.get("price"))
    tiers = [[1, cents(data.get("base_cost"))]]
    for i in (1, 2):
        threshold, cost = data.get(f"threshold{i}"), data.get(f"cost{i}")
        if threshold or cost:
            threshold = integer(threshold, 2, 999999)
            cost = cents(cost)
            if threshold <= tiers[-1][0] or cost > tiers[-1][1]:
                raise BusinessError("采购阶梯门槛须递增，采购单价须不增加。")
            tiers.append([threshold, cost])
    values["tiers"] = json.dumps(tiers)
    values["active"] = 1 if data.get("active") == "1" else 0
    def action(conn):
        if pid:
            if not conn.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone():
                raise BusinessError("商品不存在。")
            conn.execute("UPDATE products SET sku=:sku,name=:name,category=:category,unit=:unit,description=:description,price=:price,tiers=:tiers,active=:active WHERE id=:id", values | {"id": pid})
            identity = pid
        else:
            identity = conn.execute("INSERT INTO products(sku,name,category,unit,description,price,tiers,active) VALUES(:sku,:name,:category,:unit,:description,:price,:tiers,:active)", values).lastrowid
        event(conn, actor, "product", identity, "更新商品" if pid else "新增商品", values["sku"] + " · 历史订单价格保持不变")
        return identity
    return command(actor, "product", key, [pid, values], action, "admin")
