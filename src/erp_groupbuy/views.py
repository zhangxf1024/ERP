import csv
import io
import json
from datetime import date, timedelta

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from . import queries as q
from . import services as s
from .auth import login_required, role_required
from .db import get_db, row, rows, scalar

bp = Blueprint("main", __name__)


@bp.app_context_processor
def shared():
    return {"delivery_labels": q.DELIVERY_LABELS, "order_labels": q.ORDER_LABELS,
            "cart_count": scalar("SELECT COALESCE(SUM(quantity),0) FROM cart_items WHERE user_id=?", (g.user["id"],)) if getattr(g, "user", None) else 0}


@bp.errorhandler(s.BusinessError)
def business_error(error):
    # A rendered 400 keeps invalid operations visible without trusting Referer URLs.
    return render_template("error.html", code=400, message=str(error)), 400


def key():
    return request.form.get("request_key", "")


def own(found):
    if not found:
        abort(404)
    if g.user["role"] != "admin" and found["user_id"] != g.user["id"]:
        abort(403)
    return found


@bp.get("/")
@login_required
def index():
    return redirect(url_for("main.dashboard" if g.user["role"] == "admin" else "main.shop"))


@bp.get("/dashboard")
@role_required("admin")
def dashboard():
    return render_template("dashboard.html", **q.dashboard())


@bp.get("/shop")
@login_required
def shop():
    term = request.args.get("q", "").strip()[:100]
    category = request.args.get("category", "")
    products = rows("SELECT * FROM products WHERE active=1 AND (name LIKE ? OR sku LIKE ? OR description LIKE ?) AND (?='' OR category=?) ORDER BY category,id", (f"%{term}%", f"%{term}%", f"%{term}%", category, category))
    return render_template("shop.html", products=products, categories=rows("SELECT DISTINCT category FROM products WHERE active=1 ORDER BY category"), term=term, category=category)


@bp.get("/cart")
@role_required("buyer")
def cart():
    items = q.cart(g.user["id"])
    return render_template("cart.html", items=items, total=sum(x["quantity"] * x["quoted_price"] for x in items))


@bp.post("/cart/<int:pid>")
@role_required("buyer")
def cart_update(pid):
    qty = s.integer(request.form.get("quantity"), 0)
    s.update_cart(g.user["id"], pid, qty, request.form.get("mode", "set"), key())
    flash("购物车已更新；单价按最新商品价格确认。", "success")
    return redirect(url_for("main.shop" if request.form.get("mode") == "add" else "main.cart"))


@bp.post("/checkout")
@role_required("buyer")
def checkout():
    oid = s.checkout(g.user["id"], request.form.get("address"), request.form.get("note"), key())
    flash("订单提交成功，等待采购合单。", "success")
    return redirect(url_for("main.order_detail", oid=oid))


@bp.get("/orders")
@login_required
def orders():
    found = q.orders(None if g.user["role"] == "admin" else g.user["id"])
    status, term = request.args.get("status", ""), request.args.get("q", "").strip()
    found = [o for o in found if (not status or o["status"] == status) and (not term or term.lower() in (o["code"] + o["display_name"] + o["note"]).lower())]
    return render_template("orders.html", orders=found, status=status, term=term)


@bp.get("/orders/<int:oid>")
@login_required
def order_detail(oid):
    order = own(q.order(oid))
    return render_template("order.html", order=order, deliveries=q.deliveries(oid=oid), events=q.history("order", oid))


@bp.post("/orders/<int:oid>/cancel")
@role_required("buyer")
def cancel_order(oid):
    s.cancel_order(g.user["id"], oid, key())
    flash("订单已取消。", "success")
    return redirect(url_for("main.order_detail", oid=oid))


@bp.route("/batches/new", methods=["GET", "POST"])
@role_required("admin")
def new_batch():
    if request.method == "POST":
        bid = s.merge_orders(g.user["id"], request.form.getlist("order_ids"), request.form.get("name"), request.form.get("expected_date"), request.form.get("note"), key())
        flash("采购合单成功，成本与价格阶梯已存档。", "success")
        return redirect(url_for("main.batch_detail", bid=bid))
    return render_template("batch_new.html", orders=q.orders(pending=True), tomorrow=(date.today() + timedelta(days=2)).isoformat())


@bp.get("/batches")
@role_required("admin")
def batches():
    return render_template("batches.html", batches=q.batches())


@bp.get("/batches/<int:bid>")
@role_required("admin")
def batch_detail(bid):
    batch = q.batch(bid)
    if not batch:
        abort(404)
    conn = get_db()
    fifo = s.allocation_plan(conn, bid, "fifo")
    fair = s.allocation_plan(conn, bid, "fair")
    return render_template("batch.html", batch=batch, comparisons=list(zip(fifo, fair)), deliveries=q.deliveries(bid=bid),
                           receipts=rows("SELECT r.*,bi.name,bi.unit FROM receipts r JOIN batch_items bi ON bi.id=r.batch_item_id WHERE bi.batch_id=? ORDER BY r.id DESC", (bid,)),
                           events=q.history("batch", bid), orders=rows("SELECT id,code FROM orders WHERE batch_id=?", (bid,)))


@bp.post("/batches/<int:bid>/receive")
@role_required("admin")
def receive(bid):
    item_id = s.integer(request.form.get("item_id"), maximum=2147483647)
    item = row("SELECT batch_id FROM batch_items WHERE id=?", (item_id,))
    if not item or item["batch_id"] != bid:
        abort(404)
    s.receive(g.user["id"], item_id, request.form.get("quantity"), request.form.get("reference"), request.form.get("note"), key())
    flash("到货验收已记录，可重新预览分配方案。", "success")
    return redirect(url_for("main.batch_detail", bid=bid))


@bp.post("/batches/<int:bid>/allocate")
@role_required("admin")
def allocate(bid):
    s.allocate(g.user["id"], bid, request.form.get("policy"), request.form.get("version"), key())
    flash("分配已确认；可生成配送单。", "success")
    return redirect(url_for("main.batch_detail", bid=bid))


@bp.post("/batches/<int:bid>/deliveries")
@role_required("admin")
def generate_deliveries(bid):
    ids = s.generate_deliveries(g.user["id"], bid, key())
    flash(f"已新增 {len(ids)} 张配送单；已有配送数量不会重复生成。", "success")
    return redirect(url_for("main.batch_detail", bid=bid))


@bp.get("/deliveries")
@login_required
def deliveries():
    status = request.args.get("status", "")
    found = q.deliveries(None if g.user["role"] == "admin" else g.user["id"])
    return render_template("deliveries.html", deliveries=[d for d in found if not status or d["status"] == status], status=status)


@bp.get("/deliveries/<int:did>")
@login_required
def delivery_detail(did):
    delivery = own(q.delivery(did))
    return render_template("delivery.html", delivery=delivery, events=q.history("delivery", did))


@bp.post("/deliveries/<int:did>/<operation>")
@login_required
def delivery_action(did, operation):
    s.change_delivery(g.user["id"], did, operation, request.form.get("note"), key())
    flash("配送状态已更新。", "success")
    return redirect(url_for("main.delivery_detail", did=did))


@bp.get("/products")
@role_required("admin")
def products():
    return render_template("products.html", products=rows("SELECT * FROM products ORDER BY active DESC,category,id"))


@bp.route("/products/new", methods=["GET", "POST"], defaults={"pid": None})
@bp.route("/products/<int:pid>/edit", methods=["GET", "POST"])
@role_required("admin")
def product_edit(pid):
    product = row("SELECT * FROM products WHERE id=?", (pid,)) if pid else None
    if pid and not product:
        abort(404)
    if request.method == "POST":
        s.save_product(g.user["id"], pid, request.form.to_dict(), key())
        flash("商品已保存；已提交的订单和采购批次保持原价格快照。", "success")
        return redirect(url_for("main.products"))
    return render_template("product_edit.html", product=product, tiers=json.loads(product["tiers"]) if product else [[1, 0]])


@bp.get("/exports/<kind>.csv")
@role_required("admin")
def export(kind):
    if kind == "orders":
        header = ["订单号", "买家", "部门", "状态", "销售金额(元)", "商品数量", "已分配", "已发货", "已签收", "地址", "下单时间"]
        data = [
            [
                o["code"], o["display_name"], o["department"], o["status_label"],
                f"{o['total']/100:.2f}", o["quantity"], o["allocated"],
                o["shipped"], o["signed"], o["address"], o["created_at"],
            ]
            for o in q.orders()
        ]
    elif kind == "batches":
        header = ["采购单", "名称", "订单数", "原订单行数", "合并采购行数", "独立采购成本(元)", "合并采购成本(元)", "模拟节省(元)", "到货数量", "采购数量"]
        data = [
            [
                b["code"], b["name"], b["order_count"], b["original_lines"],
                len(b["lines"]), f"{b['baseline_cost']/100:.2f}",
                f"{b['merged_cost']/100:.2f}", f"{b['saving']/100:.2f}",
                b["received"], b["quantity"],
            ]
            for b in q.batches()
        ]
    else:
        abort(404)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(header)
    # Prevent spreadsheet formula injection from names, notes, and addresses.
    writer.writerows([["'" + str(v) if str(v).lstrip().startswith(("=", "+", "-", "@")) else v for v in r] for r in data])
    return Response("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="erp-{kind}.csv"'})
