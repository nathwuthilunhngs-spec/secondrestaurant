import json
from datetime import datetime, timezone, timedelta
import uuid
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

try:
    from .config import (
        RESTAURANT_NAME, RESTAURANT_TAGLINE, POLL_INTERVAL_SECONDS,
        BOOTSTRAP_SECRET, is_configured, is_local_mode
    )
    from .firebase import get, put, patch, post, delete, FirebaseError
    from .auth import (
        firebase_signup, firebase_signin, verify_id_token, require_user, require_role,
        safe_email, validate_password, create_profile, get_profile, list_users,
        update_user_role, set_user_active, AuthError
    )
    from .biz_logic import (
        now_iso, clean_text, to_positive_number, to_positive_int, calculate_bill,
        paginate, search_filter_sort, ensure_table_can_order, validate_menu_payload,
        parse_reservation_dt, find_reservation_conflict
    )
except ImportError:
    # Supports `python api/index.py` from the project root as well as package imports on Vercel.
    from config import (
        RESTAURANT_NAME, RESTAURANT_TAGLINE, POLL_INTERVAL_SECONDS,
        BOOTSTRAP_SECRET, is_configured, is_local_mode
    )
    from firebase import get, put, patch, post, delete, FirebaseError
    from auth import (
        firebase_signup, firebase_signin, verify_id_token, require_user, require_role,
        safe_email, validate_password, create_profile, get_profile, list_users,
        update_user_role, set_user_active, AuthError
    )
    from biz_logic import (
        now_iso, clean_text, to_positive_number, to_positive_int, calculate_bill,
        paginate, search_filter_sort, ensure_table_can_order, validate_menu_payload,
        parse_reservation_dt, find_reservation_conflict
    )

PUBLIC_GETS = {"/api/health", "/api/config"}

def new_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def json_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length > 2_000_000:
        raise ValueError("ข้อมูลที่ส่งมามีขนาดใหญ่เกินไป")
    raw = handler.rfile.read(length).decode("utf-8") if length else "{}"
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("ข้อมูลต้องเป็น JSON object")
    return data

def response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)

def error_response(handler, status, message):
    response(handler, status, {"ok": False, "message": str(message)})

def audit(profile, action, target_type, target_id, detail=""):
    try:
        entry = {
            "id": new_id("log"), "user_id": profile.get("id"), "user_name": profile.get("name"),
            "role": profile.get("role"), "action": action, "target_type": target_type,
            "target_id": target_id, "detail": detail, "timestamp": now_iso()
        }
        post("audit_logs", entry)
    except Exception:
        pass

def find_by_id(collection, item_id):
    data = get(collection) or {}
    if isinstance(data, dict):
        item = data.get(item_id)
        if item:
            return item
        for value in data.values():
            if isinstance(value, dict) and value.get("id") == item_id:
                return value
    return None

def find_table_by_number(table_number):
    tables = get("tables") or {}
    if isinstance(tables, dict):
        for value in tables.values():
            if isinstance(value, dict) and str(value.get("table_number")) == str(table_number).strip():
                return value
    return None

def require_staff(profile):
    require_role(profile, "admin", "staff")
def expire_overdue_reservations():
    reservations = get("reservations") or {}
    if not isinstance(reservations, dict):
        return
    now = datetime.now()
    for res in reservations.values():
        if not isinstance(res, dict) or res.get("status") not in {"waiting", "confirmed"}:
            continue
        try:
            when = parse_reservation_dt(res.get("datetime"))
        except ValueError:
            continue
        if now <= when + timedelta(minutes=15):
            continue
        patch(f"reservations/{res.get('id')}", {"status": "expired", "expired_at": now_iso()})
        table = find_table_by_number(res.get("table_number"))
        if table and not table.get("current_order_id") and table.get("status") != "available":
            patch(f"tables/{table['id']}", {"status": "available", "claimed_by": None, "current_order_id": None})

def build_order_items(raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("ออเดอร์ต้องมีรายการอาหาร")
    final_items = []
    for raw in raw_items:
        menu = find_by_id("menus", raw.get("menu_id"))
        if not menu:
            raise ValueError("ไม่พบเมนู")
        if menu.get("is_out_of_stock"):
            raise ValueError(f"เมนู {menu.get('name')} หมด")
        qty = to_positive_int(raw.get("quantity", 1), "จำนวน")
        selected_options = raw.get("options") or {}
        if not isinstance(selected_options, dict):
            raise ValueError("ตัวเลือกเมนูไม่ถูกต้อง")
        extra_price = 0.0
        normalized_selected = {}
        for group, selected in selected_options.items():
            if group == "note":
                normalized_selected[group] = str(selected).strip()[:300]
                continue
            definitions = (menu.get("options") or {}).get(group, [])
            if not isinstance(definitions, list):
                continue
            found = None
            for definition in definitions:
                if isinstance(definition, dict):
                    if str(definition.get("name")) == str(selected):
                        found = definition
                        break
                elif str(definition) == str(selected):
                    found = {"name": definition, "price": 0}
                    break
            if found is None:
                raise ValueError(f"ตัวเลือก {group} ไม่ถูกต้อง")
            normalized_selected[group] = found.get("name")
            extra_price += float(found.get("price", 0) or 0)
        final_items.append({
            "menu_id": menu["id"], "name": menu["name"], "unit_price": round(float(menu["price"]) + extra_price, 2),
            "base_price": float(menu["price"]), "quantity": qty, "options": normalized_selected
        })
    return final_items

def public_menu_list():
    data = get("menus") or {}
    return [v for v in data.values() if isinstance(v, dict)] if isinstance(data, dict) else []

class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_OPTIONS(self):
        response(self, 204, {})

    def serve_static(self, path):
        try:
            public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
            clean_path = path.lstrip("/") or "index.html"
            if ".." in clean_path.split("/"):
                return error_response(self, 400, "เส้นทางไฟล์ไม่ถูกต้อง")
            file_path = os.path.abspath(os.path.join(public_dir, clean_path))
            if not file_path.startswith(public_dir + os.sep):
                return error_response(self, 403, "ไม่อนุญาตให้เข้าถึงไฟล์นี้")
            if not os.path.isfile(file_path):
                file_path = os.path.join(public_dir, "index.html")
            with open(file_path, "rb") as handle:
                body = handle.read()
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"} else ""))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            return error_response(self, 404, "ไม่พบหน้าเว็บ")

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            # Local server also serves the SPA so `python api/index.py` is a one-command run.
            if not path.startswith("/api/"):
                return self.serve_static(path)
            if path == "/api/health":
                return response(self, 200, {"ok": True, "restaurant": RESTAURANT_NAME, "database_configured": is_configured()})
            if path == "/api/config":
                return response(self, 200, {"ok": True, "restaurant": RESTAURANT_NAME, "tagline": RESTAURANT_TAGLINE, "poll_interval": POLL_INTERVAL_SECONDS})

            profile, _ = require_user(self.headers)

            if path == "/api/me":
                return response(self, 200, {"ok": True, "user": profile})

            if path == "/api/recommended-menus":
                orders = get("orders") or {}
                counts = {}
                if isinstance(orders, dict):
                    for order in orders.values():
                        if not isinstance(order, dict):
                            continue
                        for item in order.get("items", []):
                            menu_id = item.get("menu_id")
                            if menu_id:
                                counts[menu_id] = counts.get(menu_id, 0) + int(item.get("quantity", 0) or 0)
                menus = []
                for menu in public_menu_list():
                    if menu.get("id") in counts:
                        menus.append({**menu, "ordered_count": counts[menu["id"]]})
                menus.sort(key=lambda item: (-item["ordered_count"], str(item.get("name", ""))))
                return response(self, 200, {"ok": True, "items": menus[:3]})

            if path == "/api/menus":
                query = qs.get("q", [""])[0]
                category = qs.get("category", [""])[0]
                sort = qs.get("sort", ["name"])[0]
                page = qs.get("page", ["1"])[0]
                page_size = qs.get("page_size", ["8"])[0]
                menus = search_filter_sort(public_menu_list(), query, category, sort)
                return response(self, 200, {"ok": True, **paginate(menus, page, page_size)})

            if path == "/api/customer/tables":
                require_role(profile, "customer")
                expire_overdue_reservations()
                tables = get("tables") or {}
                values = list(tables.values()) if isinstance(tables, dict) else []
                return response(self, 200, {"ok": True, "tables": values})
            if path.startswith("/api/customer/table-games/"):
                require_role(profile, "customer")
                game_id = path.rsplit("/", 1)[-1]
                game = find_by_id("table_games", game_id)
                if not game or profile.get("id") not in game.get("players", []):
                    return error_response(self, 404, "ไม่พบเกมเลือกโต๊ะ")
                return response(self, 200, {"ok": True, "game": game})
            if path == "/api/tables":
                require_staff(profile)
                expire_overdue_reservations()
                tables = get("tables") or {}
                values = list(tables.values()) if isinstance(tables, dict) else []
                return response(self, 200, {"ok": True, "tables": values})

            if path == "/api/reservations":
                expire_overdue_reservations()
                reservations = get("reservations") or {}
                values = list(reservations.values()) if isinstance(reservations, dict) else []
                if profile.get("role") == "customer":
                    values = [r for r in values if r.get("customer_id") == profile.get("id")]
                return response(self, 200, {"ok": True, "reservations": values})

            if path.startswith("/api/orders/") and path.endswith("/bill"):
                order_for_bill = find_by_id("orders", path.split("/")[-2])
                if profile.get("role") == "customer":
                    if not order_for_bill or order_for_bill.get("customer_id") != profile.get("id"):
                        return error_response(self, 404, "ไม่พบบิลของคุณ")
                else:
                    require_staff(profile)
                order = find_by_id("orders", path.split("/")[-2])
                if not order or order.get("status") in ("closed", "merged"):
                    return error_response(self, 404, "ไม่พบออเดอร์หรือบิลถูกปิดแล้ว")
                discount = to_positive_number(qs.get("discount", ["0"])[0] or 0, "ส่วนลด", allow_zero=True)
                bill = calculate_bill(order.get("items", []), discount)
                return response(self, 200, {"ok": True, "order": order, "bill": bill})

            if path == "/api/orders":
                orders = get("orders") or {}
                values = list(orders.values()) if isinstance(orders, dict) else []
                if profile.get("role") == "customer":
                    values = [o for o in values if o.get("customer_id") == profile.get("id")]
                return response(self, 200, {"ok": True, "orders": values})

            if path == "/api/kitchen":
                require_staff(profile)
                kitchen = get("kitchen") or {}
                values = list(kitchen.values()) if isinstance(kitchen, dict) else []
                values.sort(key=lambda x: x.get("timestamp", ""))
                return response(self, 200, {"ok": True, "items": values})

            if path == "/api/users":
                require_role(profile, "admin")
                return response(self, 200, {"ok": True, "users": list_users()})

            if path == "/api/audit-logs":
                require_role(profile, "admin")
                logs = get("audit_logs") or {}
                values = list(logs.values()) if isinstance(logs, dict) else []
                values.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
                return response(self, 200, {"ok": True, "logs": values})

            if path == "/api/dashboard":
                require_role(profile, "admin")
                orders = get("orders") or {}
                values = [o for o in orders.values() if isinstance(o, dict)] if isinstance(orders, dict) else []
                closed = [o for o in values if o.get("status") == "closed"]
                total_sales = round(sum(float(o.get("total", 0)) for o in closed), 2)
                today = now_iso()[:10]
                today_sales = round(sum(float(o.get("total", 0)) for o in closed if str(o.get("closed_at", "")).startswith(today)), 2)
                sold = {}
                for order in closed:
                    for item in order.get("items", []):
                        name = item.get("name", "Unknown")
                        sold[name] = sold.get(name, 0) + int(item.get("quantity", 0))
                best = sorted([{"name": k, "quantity": v} for k, v in sold.items()], key=lambda x: x["quantity"], reverse=True)[:8]
                # Daily sales for the last 7 days (oldest -> newest)
                daily = {}
                for i in range(6, -1, -1):
                    daily[(datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")] = 0.0
                for o in closed:
                    day = str(o.get("closed_at", ""))[:10]
                    if day in daily:
                        daily[day] = round(daily[day] + float(o.get("total", 0)), 2)
                sales_7d = [{"date": k, "total": v} for k, v in daily.items()]
                open_orders = len([o for o in values if o.get("status") not in ("closed", "merged")])
                avg_bill = round(total_sales / len(closed), 2) if closed else 0.0
                # Tables by status
                tables = get("tables") or {}
                table_values = [t for t in tables.values() if isinstance(t, dict)] if isinstance(tables, dict) else []
                table_status = {"available": 0, "occupied": 0, "waiting_bill": 0, "reserved": 0}
                for t in table_values:
                    st = t.get("status", "available")
                    table_status[st] = table_status.get(st, 0) + 1
                # Reservations
                reservations = get("reservations") or {}
                res_values = [r for r in reservations.values() if isinstance(r, dict)] if isinstance(reservations, dict) else []
                res_status = {}
                for r in res_values:
                    st = r.get("status", "waiting")
                    res_status[st] = res_status.get(st, 0) + 1
                res_today = len([r for r in res_values if str(r.get("datetime", "")).startswith(today)])
                # Users by role
                users = list_users()
                user_roles = {"admin": 0, "staff": 0, "customer": 0}
                for u in users:
                    user_roles[u.get("role", "customer")] = user_roles.get(u.get("role", "customer"), 0) + 1
                inactive_users = len([u for u in users if u.get("active") is False])
                return response(self, 200, {
                    "ok": True, "today_sales": today_sales, "total_sales": total_sales,
                    "closed_orders": len(closed), "best_sellers": best,
                    "open_orders": open_orders, "avg_bill": avg_bill, "sales_7d": sales_7d,
                    "tables": {"total": len(table_values), **table_status},
                    "reservations": {"total": len(res_values), "today": res_today, "by_status": res_status},
                    "users": {"total": len(users), "inactive": inactive_users, **user_roles},
                })

            return error_response(self, 404, "ไม่พบ API ที่ร้องขอ")
        except AuthError as exc:
            return error_response(self, 403, str(exc))
        except ValueError as exc:
            return error_response(self, 400, str(exc))
        except Exception as exc:
            return error_response(self, 500, "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่")

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            data = json_body(self)

            if path == "/api/auth/register":
                email = str(data.get("email", "")).strip().lower()
                password = data.get("password")
                name = str(data.get("name", "")).strip()
                if not safe_email(email):
                    raise ValueError("อีเมลไม่ถูกต้อง")
                if not validate_password(password):
                    raise ValueError("รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร")
                if not name:
                    raise ValueError("กรุณากรอกชื่อ")
                auth = firebase_signup(email, password)
                profile = create_profile(auth["localId"], email, name, "customer", password=password)
                return response(self, 201, {"ok": True, "message": "สมัครสมาชิกสำเร็จ", "token": auth["idToken"], "user": profile})

            if path == "/api/auth/login":
                email = str(data.get("email", "")).strip().lower()
                password = data.get("password")
                if not safe_email(email) or not isinstance(password, str):
                    raise ValueError("กรุณากรอกอีเมลและรหัสผ่าน")
                auth = firebase_signin(email, password)
                profile = get_profile(auth["localId"])
                return response(self, 200, {"ok": True, "message": "เข้าสู่ระบบสำเร็จ", "token": auth["idToken"], "user": profile})

            if path == "/api/bootstrap":
                if not BOOTSTRAP_SECRET or data.get("secret") != BOOTSTRAP_SECRET:
                    return error_response(self, 403, "Bootstrap secret ไม่ถูกต้อง")
                email = str(data.get("email", "")).strip().lower()
                password = data.get("password")
                name = str(data.get("name", "itailaew Admin")).strip()
                if not safe_email(email) or not validate_password(password):
                    raise ValueError("ข้อมูล Admin ไม่ถูกต้อง")
                auth = firebase_signup(email, password)
                profile = create_profile(auth["localId"], email, name, "admin", password=password)
                return response(self, 201, {"ok": True, "message": "สร้าง Admin สำเร็จ", "user": profile})

            profile, _ = require_user(self.headers)

            if path == "/api/menus":
                require_role(profile, "admin")
                menu = validate_menu_payload(data)
                menu["id"] = new_id("menu")
                menu["created_at"] = now_iso()
                put(f"menus/{menu['id']}", menu)
                audit(profile, "CREATE_MENU", "menu", menu["id"], menu["name"])
                return response(self, 201, {"ok": True, "menu": menu})

            if path == "/api/users/staff":
                require_role(profile, "admin")
                email = str(data.get("email", "")).strip().lower()
                password = data.get("password")
                name = str(data.get("name", "")).strip()
                if not safe_email(email) or not validate_password(password) or not name:
                    raise ValueError("ข้อมูล Staff ไม่ถูกต้อง")
                auth = firebase_signup(email, password)
                staff = create_profile(auth["localId"], email, name, "staff", password=password)
                audit(profile, "CREATE_STAFF", "user", staff["id"], email)
                return response(self, 201, {"ok": True, "user": staff})

            if path == "/api/orders":
                require_staff(profile)
                table_id = clean_text(data.get("table_id"), "โต๊ะ", 50)
                table = find_by_id("tables", table_id)
                if not table:
                    raise ValueError("ไม่พบโต๊ะ")
                if table.get("status") == "reserved":
                    raise ValueError("โต๊ะนี้ถูกตั้งสถานะจองไว้ กรุณาจัดลูกค้าเข้านั่งก่อน")
                final_items = build_order_items(data.get("items"))
                existing = find_by_id("orders", table["current_order_id"]) if table.get("current_order_id") else None
                if existing and existing.get("status") not in ("closed", "merged"):
                    # Table already has an open bill: add the new items to it
                    order_id = existing["id"]
                    all_items = existing.get("items", []) + final_items
                    bill = calculate_bill(all_items, existing.get("discount", 0))
                    patch(f"orders/{order_id}", {"items": all_items, **bill})
                    order = {**existing, "items": all_items, **bill}
                else:
                    order_id = new_id("order")
                    bill = calculate_bill(final_items, 0)
                    order = {
                        "id": order_id, "table_id": table_id, "table_number": table.get("table_number"),
                        "customer_id": data.get("customer_id"), "items": final_items, **bill,
                        "status": "open", "created_by": profile["id"], "created_at": now_iso()
                    }
                    put(f"orders/{order_id}", order)
                    patch(f"tables/{table_id}", {"status": "occupied", "current_order_id": order_id})
                for item in final_items:
                    kid = new_id("kit")
                    put(f"kitchen/{kid}", {
                        "id": kid, "order_id": order_id, "order_item_id": f"{order_id}_{item['menu_id']}",
                        "menu_name": item["name"], "options": item["options"],
                        "table_number": table.get("table_number"), "quantity": item["quantity"],
                        "status": "pending", "timestamp": now_iso()
                    })
                audit(profile, "CREATE_ORDER", "order", order_id, f"table={table_id}")
                return response(self, 201, {"ok": True, "order": order})

            if path == "/api/orders/split":
                require_staff(profile)
                order_id = clean_text(data.get("order_id"), "Order ID", 80)
                order = find_by_id("orders", order_id)
                if not order or order.get("status") == "closed":
                    raise ValueError("ไม่พบออเดอร์หรือบิลถูกปิดแล้ว")
                selected_ids = data.get("item_indexes")
                new_table_id = clean_text(data.get("new_table_id"), "โต๊ะใหม่", 50)
                new_table = find_by_id("tables", new_table_id)
                if not isinstance(selected_ids, list) or not selected_ids:
                    raise ValueError("กรุณาเลือกรายการที่ต้องการแยก")
                if not new_table or new_table.get("status") != "available":
                    raise ValueError("โต๊ะใหม่ต้องว่าง")
                items = order.get("items", [])
                selected = [items[int(i)] for i in selected_ids if 0 <= int(i) < len(items)]
                if not selected:
                    raise ValueError("ไม่พบรายการที่ต้องการแยก")
                remaining = [item for i, item in enumerate(items) if i not in [int(x) for x in selected_ids]]
                new_id_value = new_id("order")
                new_bill = calculate_bill(selected, 0)
                new_order = {**new_bill, "id": new_id_value, "table_id": new_table_id,
                             "table_number": new_table.get("table_number"), "customer_id": order.get("customer_id"),
                             "items": selected, "status": "open", "created_by": profile["id"], "created_at": now_iso(),
                             "split_from": order_id}
                put(f"orders/{new_id_value}", new_order)
                old_bill = calculate_bill(remaining, order.get("discount", 0))
                patch(f"orders/{order_id}", {"items": remaining, **old_bill})
                patch(f"tables/{new_table_id}", {"status": "occupied", "current_order_id": new_id_value})
                audit(profile, "SPLIT_BILL", "order", order_id, f"new={new_id_value}")
                return response(self, 200, {"ok": True, "new_order": new_order})

            if path == "/api/customer/tables/claim":
                require_role(profile, "customer")
                table_id = clean_text(data.get("table_id"), "โต๊ะ", 50)
                table = find_by_id("tables", table_id)
                if not table:
                    raise ValueError("ไม่พบโต๊ะ")
                claimed_by = table.get("claimed_by")
                if table.get("status") == "reserved":
                    raise ValueError("โต๊ะนี้มีการจองไว้ กรุณาเลือกโต๊ะอื่น")
                if claimed_by == profile.get("id"):
                    return response(self, 200, {"ok": True, "table": table, "claimed": True})
                if table.get("status") == "available":
                    patch(f"tables/{table_id}", {"status": "occupied", "claimed_by": profile["id"]})
                    table = {**table, "status": "occupied", "claimed_by": profile["id"]}
                    audit(profile, "CLAIM_TABLE", "table", table_id)
                    return response(self, 200, {"ok": True, "table": table, "claimed": True})
                if claimed_by and claimed_by != profile.get("id"):
                    games = get("table_games") or {}
                    active = None
                    if isinstance(games, dict):
                        for g in games.values():
                            if isinstance(g, dict) and g.get("table_id") == table_id and g.get("status") == "playing" and profile.get("id") in g.get("players", []):
                                active = g
                                break
                    if active:
                        return error_response(self, 409, {"code": "TABLE_GAME", "game": active})
                    game = {"id": new_id("game"), "table_id": table_id, "table_number": table.get("table_number"),
                            "players": [claimed_by, profile["id"]], "choices": {}, "round": 1, "status": "playing", "created_at": now_iso()}
                    put(f"table_games/{game['id']}", game)
                    return error_response(self, 409, {"code": "TABLE_GAME", "game": game})
                raise ValueError("โต๊ะนี้ยังไม่พร้อมให้เลือก")
            if path.startswith("/api/customer/table-games/") and path.endswith("/choice"):
                require_role(profile, "customer")
                game_id = path.split("/")[-2]
                game = find_by_id("table_games", game_id)
                if not game or profile.get("id") not in game.get("players", []):
                    raise ValueError("ไม่พบเกมเลือกโต๊ะ")
                choice = data.get("choice")
                if choice not in {"rock", "paper", "scissors"}:
                    raise ValueError("ตัวเลือกเกมไม่ถูกต้อง")
                choices = dict(game.get("choices", {}))
                choices[profile["id"]] = choice
                game["choices"] = choices
                if len(choices) >= 2:
                    p1, p2 = game["players"][:2]
                    c1, c2 = choices.get(p1), choices.get(p2)
                    if c1 == c2:
                        game["choices"] = {}
                        game["round"] = int(game.get("round", 1)) + 1
                        game["result"] = "tie"
                    else:
                        wins = {("rock", "scissors"), ("scissors", "paper"), ("paper", "rock")}
                        winner = p1 if (c1, c2) in wins else p2
                        game["winner"] = winner
                        game["result"] = "winner"
                        game["status"] = "finished"
                        table = find_by_id("tables", game["table_id"])
                        if table and winner == p2:
                            patch(f"tables/{game['table_id']}", {"claimed_by": winner})
                            if table.get("current_order_id"):
                                patch(f"orders/{table['current_order_id']}", {"customer_id": winner})
                put(f"table_games/{game_id}", game)
                return response(self, 200, {"ok": True, "game": game})
            if path == "/api/customer/orders":
                require_role(profile, "customer")
                table_id = clean_text(data.get("table_id"), "โต๊ะ", 50)
                table = find_by_id("tables", table_id)
                if not table:
                    raise ValueError("ไม่พบโต๊ะ")
                if table.get("claimed_by") not in (None, profile.get("id")):
                    raise ValueError("โต๊ะนี้ถูกเลือกโดยลูกค้าคนอื่น")
                if table.get("status") == "reserved":
                    raise ValueError("โต๊ะนี้ถูกจองไว้")
                final_items = build_order_items(data.get("items"))
                existing = find_by_id("orders", table.get("current_order_id")) if table.get("current_order_id") else None
                if existing and existing.get("status") not in ("closed", "merged"):
                    order_id = existing["id"]
                    all_items = existing.get("items", []) + final_items
                    bill = calculate_bill(all_items, existing.get("discount", 0))
                    patch(f"orders/{order_id}", {"items": all_items, "customer_id": profile["id"], **bill})
                    order = {**existing, "items": all_items, "customer_id": profile["id"], **bill}
                else:
                    order_id = new_id("order")
                    bill = calculate_bill(final_items, 0)
                    order = {"id": order_id, "table_id": table_id, "table_number": table.get("table_number"),
                             "customer_id": profile["id"], "items": final_items, **bill, "status": "open",
                             "created_by": profile["id"], "created_at": now_iso(), "source": "qr"}
                    put(f"orders/{order_id}", order)
                    patch(f"tables/{table_id}", {"status": "occupied", "claimed_by": profile["id"], "current_order_id": order_id})
                for item in final_items:
                    kid = new_id("kit")
                    put(f"kitchen/{kid}", {"id": kid, "order_id": order_id, "order_item_id": f"{order_id}_{item['menu_id']}",
                         "menu_name": item["name"], "options": item["options"], "table_number": table.get("table_number"),
                         "quantity": item["quantity"], "status": "pending", "timestamp": now_iso()})
                return response(self, 201, {"ok": True, "order": order})
            if path == "/api/tables/move":
                require_staff(profile)
                old_id = clean_text(data.get("old_table_id"), "โต๊ะเดิม", 50)
                new_table_id = clean_text(data.get("new_table_id"), "โต๊ะใหม่", 50)
                old_table = find_by_id("tables", old_id)
                new_table = find_by_id("tables", new_table_id)
                if not old_table or not new_table:
                    raise ValueError("ไม่พบโต๊ะที่ระบุ")
                if old_table.get("status") == "available":
                    raise ValueError("โต๊ะเดิมยังไม่มีออเดอร์")
                if new_table.get("status") != "available":
                    raise ValueError("โต๊ะใหม่ไม่ว่าง")
                order_id = old_table.get("current_order_id")
                patch(f"tables/{old_id}", {"status": "available", "current_order_id": None})
                patch(f"tables/{new_table_id}", {"status": "occupied", "current_order_id": order_id})
                if order_id:
                    patch(f"orders/{order_id}", {"table_id": new_table_id, "table_number": new_table.get("table_number")})
                audit(profile, "MOVE_TABLE", "table", old_id, f"to={new_table_id}")
                return response(self, 200, {"ok": True, "message": "ย้ายโต๊ะสำเร็จ"})

            if path == "/api/tables/merge":
                require_staff(profile)
                source_id = clean_text(data.get("source_table_id"), "โต๊ะต้นทาง", 50)
                target_id = clean_text(data.get("target_table_id"), "โต๊ะปลายทาง", 50)
                source = find_by_id("tables", source_id)
                target = find_by_id("tables", target_id)
                if not source or not target:
                    raise ValueError("ไม่พบโต๊ะ")
                if not source.get("current_order_id") or not target.get("current_order_id"):
                    raise ValueError("ต้องมีออเดอร์ทั้งสองโต๊ะก่อนรวมโต๊ะ")
                source_order = find_by_id("orders", source["current_order_id"])
                target_order = find_by_id("orders", target["current_order_id"])
                merged_items = target_order.get("items", []) + source_order.get("items", [])
                bill = calculate_bill(merged_items, target_order.get("discount", 0))
                patch(f"orders/{target_order['id']}", {"items": merged_items, **bill, "merged_table_ids": [source_id, target_id]})
                patch(f"orders/{source_order['id']}", {"status": "merged", "merged_into": target_order["id"]})
                patch(f"tables/{source_id}", {"status": "available", "current_order_id": None})
                audit(profile, "MERGE_TABLE", "table", target_id, f"source={source_id}")
                return response(self, 200, {"ok": True, "message": "รวมโต๊ะสำเร็จ", "order_id": target_order["id"]})

            if path == "/api/reservations":
                expire_overdue_reservations()
                name = clean_text(data.get("customer_name"), "ชื่อ", 100)
                phone = clean_text(data.get("phone"), "เบอร์โทร", 30)
                if not phone.isdigit():
                    raise ValueError("เบอร์โทรต้องเป็นตัวเลขเท่านั้น")
                table_number = clean_text(data.get("table_number"), "โต๊ะ", 20)
                when_text = clean_text(data.get("datetime"), "เวลา", 10)
                try:
                    when = parse_reservation_dt(when_text)
                except ValueError:
                    raise ValueError("กรุณาระบุเวลาในรูปแบบ HH:MM")
                if when.date() != datetime.now().date():
                    raise ValueError("ระบบรับจองเฉพาะวันนี้เท่านั้น")
                minimum_time = datetime.now() + timedelta(minutes=30)
                if when < minimum_time:
                    raise ValueError("กรุณาจองล่วงหน้าอย่างน้อย 30 นาที")
                if not find_table_by_number(table_number):
                    raise ValueError("ไม่พบโต๊ะที่เลือก")
                existing_res = get("reservations") or {}
                existing_list = list(existing_res.values()) if isinstance(existing_res, dict) else []
                clash = find_reservation_conflict(existing_list, table_number, when)
                if clash:
                    raise ValueError(f"โต๊ะ {table_number} ถูกจองไว้แล้วในช่วงเวลาใกล้เคียง ({clash.get('datetime')}) กรุณาเลือกเวลาหรือโต๊ะอื่น")
                by_staff = profile.get("role") in ("admin", "staff")
                reservation = {
                    "id": new_id("res"), "customer_id": None if by_staff else profile["id"], "customer_name": name,
                    "phone": phone, "table_number": table_number, "datetime": when_text,
                    # A booking taken by staff (phone / walk-in) is confirmed immediately
                    "status": "confirmed" if by_staff else "waiting",
                    "source": "staff" if by_staff else "customer",
                    "created_by": profile["id"], "created_at": now_iso()
                }
                put(f"reservations/{reservation['id']}", reservation)
                audit(profile, "CREATE_RESERVATION", "reservation", reservation["id"], f"table={table_number} at={when_text}")
                return response(self, 201, {"ok": True, "reservation": reservation})

            return error_response(self, 404, "ไม่พบ API ที่ร้องขอ")
        except AuthError as exc:
            return error_response(self, 403, str(exc))
        except (ValueError, FirebaseError) as exc:
            return error_response(self, 400, str(exc))
        except Exception:
            return error_response(self, 500, "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่")

    def do_PATCH(self):
        try:
            path = urlparse(self.path).path
            data = json_body(self)
            profile, _ = require_user(self.headers)

            if path.startswith("/api/menus/"):
                require_role(profile, "admin")
                menu_id = path.rsplit("/", 1)[-1]
                current = find_by_id("menus", menu_id)
                if not current:
                    return error_response(self, 404, "ไม่พบเมนู")
                merged = dict(current)
                merged.update(data)
                menu = validate_menu_payload(merged)
                patch(f"menus/{menu_id}", menu)
                audit(profile, "UPDATE_MENU", "menu", menu_id, menu["name"])
                return response(self, 200, {"ok": True, "menu": {**current, **menu, "id": menu_id}})

            if path.startswith("/api/users/"):
                require_role(profile, "admin")
                uid = path.rsplit("/", 1)[-1]
                if "role" in data:
                    update_user_role(uid, data["role"])
                    audit(profile, "UPDATE_ROLE", "user", uid, str(data["role"]))
                if "active" in data:
                    set_user_active(uid, data["active"])
                    audit(profile, "UPDATE_USER_ACTIVE", "user", uid, str(data["active"]))
                return response(self, 200, {"ok": True, "message": "อัปเดตผู้ใช้สำเร็จ"})

            if path.startswith("/api/tables/"):
                require_staff(profile)
                table_id = path.rsplit("/", 1)[-1]
                allowed = {"available", "occupied", "waiting_bill", "reserved"}
                status = data.get("status")
                if status not in allowed:
                    raise ValueError("สถานะโต๊ะไม่ถูกต้อง")
                patch(f"tables/{table_id}", {"status": status})
                return response(self, 200, {"ok": True, "message": "อัปเดตโต๊ะสำเร็จ"})

            if path.startswith("/api/reservations/"):
                require_staff(profile)
                res_id = path.rsplit("/", 1)[-1]
                reservation = find_by_id("reservations", res_id)
                if not reservation:
                    return error_response(self, 404, "ไม่พบการจอง")
                new_status = data.get("status")
                transitions = {"waiting": {"confirmed", "cancelled"}, "confirmed": {"seated", "cancelled"}}
                if new_status not in transitions.get(reservation.get("status", "waiting"), set()):
                    raise ValueError("ไม่สามารถเปลี่ยนสถานะการจองนี้ได้")
                if new_status == "seated":
                    table = find_table_by_number(reservation.get("table_number"))
                    if not table:
                        raise ValueError("ไม่พบโต๊ะของการจองนี้")
                    if table.get("status") not in ("available", "reserved"):
                        raise ValueError(f"โต๊ะ {table.get('table_number')} ยังไม่ว่าง จึงจัดเข้านั่งไม่ได้")
                    patch(f"tables/{table['id']}", {"status": "occupied"})
                patch(f"reservations/{res_id}", {"status": new_status, "updated_at": now_iso(), "updated_by": profile["id"]})
                audit(profile, "UPDATE_RESERVATION", "reservation", res_id, new_status)
                return response(self, 200, {"ok": True, "message": "อัปเดตการจองสำเร็จ"})

            if path.startswith("/api/kitchen/"):
                require_staff(profile)
                item_id = path.rsplit("/", 1)[-1]
                status = data.get("status")
                if status not in {"pending", "cooking", "done"}:
                    raise ValueError("สถานะครัวไม่ถูกต้อง")
                patch(f"kitchen/{item_id}", {"status": status, "updated_at": now_iso()})
                return response(self, 200, {"ok": True, "message": "อัปเดตสถานะครัวสำเร็จ"})

            if path.startswith("/api/orders/") and path.endswith("/request-checkout"):
                require_role(profile, "customer")
                order_id = path.split("/")[-2]
                order = find_by_id("orders", order_id)
                if not order or order.get("customer_id") != profile.get("id"):
                    return error_response(self, 404, "ไม่พบบิลของคุณ")
                if order.get("status") in ("closed", "merged"):
                    raise ValueError("บิลนี้ปิดแล้ว")
                patch(f"orders/{order_id}", {"status": "waiting_bill", "checkout_requested_at": now_iso()})
                table_id = order.get("table_id")
                if table_id:
                    patch(f"tables/{table_id}", {"status": "waiting_bill"})
                return response(self, 200, {"ok": True, "message": "เรียกพนักงานเช็คบิลแล้ว"})
            if path.startswith("/api/orders/") and path.endswith("/checkout"):
                require_staff(profile)
                order_id = path.split("/")[-2]
                order = find_by_id("orders", order_id)
                if not order:
                    return error_response(self, 404, "ไม่พบออเดอร์")
                if order.get("status") in ("closed", "merged"):
                    return error_response(self, 400, "ไม่สามารถเช็คบิลซ้ำได้")
                discount = to_positive_number(data.get("discount", 0), "ส่วนลด", allow_zero=True)
                bill = calculate_bill(order.get("items", []), discount)
                closed = {**bill, "status": "closed", "closed_at": now_iso(), "closed_by": profile["id"]}
                patch(f"orders/{order_id}", closed)
                table_id = order.get("table_id")
                if table_id:
                    patch(f"tables/{table_id}", {"status": "available", "current_order_id": None, "claimed_by": None})
                customer_id = order.get("customer_id")
                if customer_id:
                    points = int(float(bill["total"]) // 100)
                    user = get_profile(customer_id)
                    patch(f"users/{customer_id}", {"member_points": int(user.get("member_points", 0)) + points})
                audit(profile, "CHECKOUT_ORDER", "order", order_id, str(bill["total"]))
                return response(self, 200, {"ok": True, "order": {**order, **closed}})

            return error_response(self, 404, "ไม่พบ API ที่ร้องขอ")
        except AuthError as exc:
            return error_response(self, 403, str(exc))
        except (ValueError, FirebaseError) as exc:
            return error_response(self, 400, str(exc))
        except Exception:
            return error_response(self, 500, "เกิดข้อผิดพลาดภายในระบบ กรุณาลองใหม่")

    def do_DELETE(self):
        try:
            path = urlparse(self.path).path
            profile, _ = require_user(self.headers)
            if path.startswith("/api/menus/"):
                require_role(profile, "admin")
                menu_id = path.rsplit("/", 1)[-1]
                if not find_by_id("menus", menu_id):
                    return error_response(self, 404, "ไม่พบเมนู")
                delete(f"menus/{menu_id}")
                audit(profile, "DELETE_MENU", "menu", menu_id)
                return response(self, 200, {"ok": True, "message": "ลบเมนูสำเร็จ"})
            return error_response(self, 404, "ไม่พบ API ที่ร้องขอ")
        except AuthError as exc:
            return error_response(self, 403, str(exc))
        except Exception:
            return error_response(self, 500, "ไม่สามารถดำเนินการได้")


def ensure_local_admin():
    """Seed a usable Admin account once in Local mode for first-time setup."""
    if not is_local_mode():
        return
    try:
        users = get("users") or {}
        if isinstance(users, dict) and any(isinstance(u, dict) and u.get("role") == "admin" for u in users.values()):
            return
        admin_email = os.environ.get("LOCAL_ADMIN_EMAIL", "admin@itailaew.com")
        admin_password = os.environ.get("LOCAL_ADMIN_PASSWORD", "Admin@12345")
        auth = firebase_signup(admin_email, admin_password)
        create_profile(auth["localId"], admin_email, "itailaew Admin", "admin", password=admin_password)
        print(f"Local Admin created: {admin_email} / {admin_password}")
    except Exception as exc:
        print(f"Local Admin seed skipped: {exc}")



if __name__ == "__main__":
    ensure_local_admin()
    # Local development only. Vercel imports `handler` and does not execute this block.
    host = "127.0.0.1"
    port = 8000
    print(f"itailaew API running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        HTTPServer((host, port), handler).serve_forever()
    except KeyboardInterrupt:
        print("\nitailaew API stopped.")
    except Exception as exc:
        print(f"ไม่สามารถเริ่ม Local API ได้: {exc}")