from datetime import datetime, timezone
try:
    from .config import VAT_RATE, SERVICE_CHARGE_RATE
except ImportError:
    from config import VAT_RATE, SERVICE_CHARGE_RATE

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def clean_text(value, field, max_len=120):
    if not isinstance(value, str):
        raise ValueError(f"{field} ต้องเป็นข้อความ")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} ห้ามว่าง")
    if len(value) > max_len:
        raise ValueError(f"{field} ยาวเกินกำหนด")
    return value

def to_positive_number(value, field, allow_zero=False):
    try:
        number = float(value)
        if number < 0 or (number == 0 and not allow_zero):
            raise ValueError
        return number
    except (TypeError, ValueError):
        raise ValueError(f"{field} ต้องเป็นตัวเลขที่ถูกต้องและไม่ติดลบ")

def to_positive_int(value, field, allow_zero=False):
    try:
        number = int(value)
        if number < 0 or (number == 0 and not allow_zero):
            raise ValueError
        return number
    except (TypeError, ValueError):
        raise ValueError(f"{field} ต้องเป็นจำนวนเต็มที่ถูกต้อง")

def calculate_bill(items, discount=0, service_rate=SERVICE_CHARGE_RATE):
    try:
        subtotal = 0.0
        for item in items:
            qty = to_positive_int(item.get("quantity", 1), "จำนวน")
            price = to_positive_number(item.get("unit_price", 0), "ราคา")
            subtotal += price * qty
        discount = to_positive_number(discount or 0, "ส่วนลด", allow_zero=True)
        service_charge = max(0.0, (subtotal - discount) * float(service_rate))
        taxable = max(0.0, subtotal - discount + service_charge)
        tax = taxable * VAT_RATE
        total = taxable + tax
        return {
            "subtotal": round(subtotal, 2), "discount": round(discount, 2),
            "service_charge": round(service_charge, 2), "tax": round(tax, 2),
            "total": round(total, 2)
        }
    except Exception as exc:
        raise ValueError(f"คำนวณบิลไม่สำเร็จ: {exc}")

def paginate(items, page=1, page_size=10):
    try:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        total = len(items)
        start = (page - 1) * page_size
        return {
            "items": items[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": max(1, (total + page_size - 1) // page_size)
        }
    except Exception as exc:
        raise ValueError(f"แบ่งหน้าไม่สำเร็จ: {exc}")

def search_filter_sort(items, query="", category="", sort="name"):
    try:
        query = (query or "").strip().lower()
        category = (category or "").strip().lower()
        result = []
        for item in items:
            name = str(item.get("name", "")).lower()
            cat = str(item.get("category", "")).lower()
            if query and query not in name:
                continue
            if category and cat != category:
                continue
            result.append(item)
        if sort == "price_asc":
            result.sort(key=lambda x: float(x.get("price", 0)))
        elif sort == "price_desc":
            result.sort(key=lambda x: float(x.get("price", 0)), reverse=True)
        else:
            result.sort(key=lambda x: str(x.get("name", "")).lower())
        return result
    except Exception as exc:
        raise ValueError(f"ค้นหา/กรอง/เรียงข้อมูลไม่สำเร็จ: {exc}")

def ensure_table_can_order(table):
    if not table:
        raise ValueError("ไม่พบโต๊ะ")
    if table.get("status") == "available":
        raise ValueError("โต๊ะยังไม่เปิดบิล ไม่สามารถรับออเดอร์ได้")
    if table.get("status") == "reserved":
        raise ValueError("โต๊ะนี้ถูกจองไว้")
    if table.get("status") not in {"occupied", "waiting_bill"}:
        raise ValueError("สถานะโต๊ะไม่พร้อมรับออเดอร์")
    return True

def normalize_options(options):
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise ValueError("ตัวเลือกเมนูต้องเป็นข้อมูลแบบ object")
    normalized = {}
    keys = list(options.keys())
    index = 0
    while index < len(keys):
        key = str(keys[index]).strip()
        value = options[keys[index]]
        if key:
            normalized[key] = value
        index += 1
    return normalized

def validate_menu_payload(data):
    name = clean_text(data.get("name"), "ชื่อเมนู", 100)
    category = clean_text(data.get("category"), "หมวดหมู่", 60)
    price = to_positive_number(data.get("price"), "ราคา")
    options = normalize_options(data.get("options"))
    return {
        "name": name, "category": category, "price": price,
        "image_url": str(data.get("image_url", "")).strip(),
        "is_out_of_stock": bool(data.get("is_out_of_stock", False)),
        "options": options
    }
