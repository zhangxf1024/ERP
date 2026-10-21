"""Read models shared by HTML pages and the UTF-8 CSV exports."""
from .db import rows, row, scalar

ORDER_LABELS = {"pending": "待采购合单", "purchasing": "采购待到货", "partial": "部分履约", "ready": "已分配待发货", "shipped": "配送中", "signed": "全部签收", "cancelled": "已取消"}
DELIVERY_LABELS = {"ready": "待发货", "shipped": "配送中", "signed": "已签收", "void": "已作废"}


def order_lines(oid):
    return rows("""SELECT oi.*,
        COALESCE((SELECT SUM(a.quantity) FROM allocations a WHERE a.order_item_id=oi.id),0) AS allocated,
        COALESCE((SELECT SUM(di.quantity) FROM delivery_items di JOIN deliveries d ON d.id=di.delivery_id
          JOIN allocations a ON a.id=di.allocation_id WHERE a.order_item_id=oi.id AND d.status IN ('shipped','signed')),0) AS shipped,
        COALESCE((SELECT SUM(di.quantity) FROM delivery_items di JOIN deliveries d ON d.id=di.delivery_id
          JOIN allocations a ON a.id=di.allocation_id WHERE a.order_item_id=oi.id AND d.status='signed'),0) AS signed
        FROM order_items oi WHERE oi.order_id=? ORDER BY oi.id""", (oid,))


def decorate_order(order):
    order["lines"] = order_lines(order["id"])
    for field in ("quantity", "allocated", "shipped", "signed"):
        order[field] = sum(line[field] for line in order["lines"])
    status = "pending"
    if order["cancelled"]:
        status = "cancelled"
    elif order["batch_id"]:
        if order["signed"] == order["quantity"]:
            status = "signed"
        elif order["shipped"] == order["quantity"]:
            status = "shipped"
        elif order["allocated"] == order["quantity"] and not order["shipped"]:
            status = "ready"
        elif order["allocated"]:
            status = "partial"
        else:
            status = "purchasing"
    order["status"], order["status_label"] = status, ORDER_LABELS[status]
    return order


def orders(uid=None, pending=False):
    clauses, args = ["1=1"], []
    if uid is not None:
        clauses.append("o.user_id=?")
        args.append(uid)
    if pending:
        clauses.append("o.cancelled=0 AND o.batch_id IS NULL")
    found = rows("SELECT o.*,u.display_name,u.department,b.code AS batch_code FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN batches b ON b.id=o.batch_id WHERE " + " AND ".join(clauses) + " ORDER BY o.created_at DESC,o.id DESC", args)
    return [decorate_order(o) for o in found]


def order(oid):
    found = row("SELECT o.*,u.display_name,u.department,b.code AS batch_code FROM orders o JOIN users u ON u.id=o.user_id LEFT JOIN batches b ON b.id=o.batch_id WHERE o.id=?", (oid,))
    return decorate_order(found) if found else None


def batch_lines(bid):
    found = rows("""SELECT bi.*,
        COALESCE((SELECT SUM(r.quantity) FROM receipts r WHERE r.batch_item_id=bi.id),0) AS received,
        COALESCE((SELECT SUM(a.quantity) FROM allocations a WHERE a.batch_item_id=bi.id),0) AS allocated,
        COALESCE((SELECT SUM(di.quantity) FROM delivery_items di JOIN allocations a ON a.id=di.allocation_id
            JOIN deliveries d ON d.id=di.delivery_id WHERE a.batch_item_id=bi.id AND d.status='ready'),0) AS reserved,
        COALESCE((SELECT SUM(di.quantity) FROM delivery_items di JOIN allocations a ON a.id=di.allocation_id
            JOIN deliveries d ON d.id=di.delivery_id WHERE a.batch_item_id=bi.id AND d.status IN ('shipped','signed')),0) AS shipped,
        COALESCE((SELECT SUM(di.quantity) FROM delivery_items di JOIN allocations a ON a.id=di.allocation_id
            JOIN deliveries d ON d.id=di.delivery_id WHERE a.batch_item_id=bi.id AND d.status='signed'),0) AS signed
        FROM batch_items bi WHERE bi.batch_id=? ORDER BY bi.id""", (bid,))
    for line in found:
        line["on_hand"] = line["received"] - line["shipped"]
        line["available"] = line["received"] - line["allocated"]
        line["shortage"] = line["quantity"] - line["received"]
    return found


def batch(bid):
    found = row("SELECT * FROM batches WHERE id=?", (bid,))
    if not found:
        return None
    found["lines"] = batch_lines(bid)
    for key in ("quantity", "received", "allocated", "reserved", "shipped", "signed", "on_hand", "available", "shortage"):
        found[key] = sum(line[key] for line in found["lines"])
    found["saving"] = found["baseline_cost"] - found["merged_cost"]
    found["saving_rate"] = round(100 * found["saving"] / found["baseline_cost"], 1) if found["baseline_cost"] else 0
    found["receive_label"] = "全部到货" if found["received"] == found["quantity"] else "部分到货" if found["received"] else "待到货"
    found["fulfill_label"] = "履约完成" if found["signed"] == found["quantity"] else "履约进行中"
    return found


def batches():
    return [batch(r["id"]) for r in rows("SELECT id FROM batches ORDER BY created_at DESC,id DESC")]


def deliveries(uid=None, bid=None, oid=None):
    clauses, args = ["1=1"], []
    for val, expr in ((uid, "d.user_id=?"), (bid, "d.batch_id=?")):
        if val is not None:
            clauses.append(expr)
            args.append(val)
    if oid is not None:
        clauses.append("EXISTS(SELECT 1 FROM delivery_items di JOIN allocations a ON a.id=di.allocation_id JOIN order_items oi ON oi.id=a.order_item_id WHERE di.delivery_id=d.id AND oi.order_id=?)")
        args.append(oid)
    return rows("SELECT d.*,u.display_name,b.code AS batch_code,(SELECT SUM(quantity) FROM delivery_items WHERE delivery_id=d.id) AS quantity FROM deliveries d JOIN users u ON u.id=d.user_id JOIN batches b ON b.id=d.batch_id WHERE " + " AND ".join(clauses) + " ORDER BY d.id DESC", args)


def delivery(did):
    found = row("SELECT d.*,u.display_name,b.code AS batch_code FROM deliveries d JOIN users u ON u.id=d.user_id JOIN batches b ON b.id=d.batch_id WHERE d.id=?", (did,))
    if found:
        found["lines"] = rows("SELECT di.quantity,oi.sku,oi.name,oi.unit,o.code AS order_code,o.id AS order_id FROM delivery_items di JOIN allocations a ON a.id=di.allocation_id JOIN order_items oi ON oi.id=a.order_item_id JOIN orders o ON o.id=oi.order_id WHERE di.delivery_id=? ORDER BY di.id", (did,))
    return found


def history(entity, identity):
    return rows("SELECT e.*,u.display_name FROM events e JOIN users u ON u.id=e.actor_id WHERE e.entity=? AND e.entity_id=? ORDER BY e.id DESC", (entity, identity))


def cart(uid):
    return rows("SELECT c.*,p.name,p.sku,p.unit,p.price,p.active,p.category,p.visual,p.color FROM cart_items c JOIN products p ON p.id=c.product_id WHERE c.user_id=? ORDER BY p.category,p.id", (uid,))


def dashboard():
    all_batches = batches()
    metrics = {
        "orders": scalar("SELECT COUNT(*) FROM orders WHERE cancelled=0"),
        "pending": scalar("SELECT COUNT(*) FROM orders WHERE cancelled=0 AND batch_id IS NULL"),
        "volume": scalar("SELECT COALESCE(SUM(total),0) FROM orders WHERE cancelled=0"),
        "saving": sum(b["saving"] for b in all_batches),
        "ready": scalar("SELECT COUNT(*) FROM deliveries WHERE status='ready'"),
        "issues": scalar("SELECT COUNT(*) FROM deliveries WHERE issue_note!='' AND status='shipped'"),
        "shortage": sum(b["shortage"] for b in all_batches),
        "on_hand": sum(b["on_hand"] for b in all_batches),
    }
    categories = rows("SELECT p.category,SUM(oi.price*oi.quantity) AS value FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id WHERE o.cancelled=0 GROUP BY p.category ORDER BY value DESC")
    trend = rows("SELECT substr(created_at,1,10) AS day,SUM(total) AS value,COUNT(*) AS count FROM orders WHERE cancelled=0 GROUP BY day ORDER BY day DESC LIMIT 14")[::-1]
    recent = rows("SELECT e.*,u.display_name FROM events e JOIN users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT 8")
    return dict(metrics=metrics, batches=all_batches[:4], categories=categories, trend=trend, recent=recent, max_trend=max([r["value"] for r in trend] or [1]), max_category=max([r["value"] for r in categories] or [1]))
