# itailaew — Italian Restaurant POS

ระบบจัดการร้านอาหารอิตาเลียนแบบ SPA สำหรับ Project

## Stack

- Frontend: HTML / CSS / Vanilla JavaScript
- Backend: Python Standard Library only
- API: `http.server`, `urllib.request`, `json`
- Database: Firebase Realtime Database ผ่าน REST API
- Hosting: Vercel Python Runtime
- Kitchen update: Short Polling ทุก 3 วินาที

Vercel รองรับ Python Function ที่ใช้ `BaseHTTPRequestHandler` ใน `api/index.py` โดยตรง ตามเอกสารปัจจุบันของ Vercel

## 1. สร้าง Firebase

สร้าง Firebase project และเปิด Realtime Database จาก Firebase Console

ตั้ง Database Rules ให้ client เข้าถึงไม่ได้โดยตรง เพราะโปรเจกต์นี้ให้ Python API เป็นตัวตรวจสิทธิ์:

```json
{
  "rules": {
    ".read": false,
    ".write": false
  }
}
```

สร้าง Web API Key จาก Project Settings

สร้าง Database Secret ตามวิธีที่ Firebase รองรับสำหรับ REST server authentication แล้วเก็บเป็น Environment Variable เท่านั้น ห้าม commit ลง Git

## 2. Environment Variables

ตั้งค่าบน Vercel:

```text
FIREBASE_DB_URL=https://YOUR_DATABASE.firebasedatabase.app
FIREBASE_API_KEY=YOUR_FIREBASE_WEB_API_KEY
FIREBASE_DB_SECRET=YOUR_SERVER_DATABASE_SECRET
BOOTSTRAP_SECRET=สร้างรหัสลับยาว ๆ เอง
```

Firebase Realtime Database ใช้ REST endpoint ที่ลงท้ายด้วย `.json` และรองรับ authentication ผ่าน credential/token

## 3. สร้าง Admin ครั้งแรก

หลัง deploy ให้ POST ไปที่:

```text
/api/bootstrap
```

Body:

```json
{
  "secret": "ค่าเดียวกับ BOOTSTRAP_SECRET",
  "email": "admin@itailaew.com",
  "password": "เปลี่ยนเป็นรหัสผ่านของคุณ",
  "name": "itailaew Admin"
}
```

จากนั้นลบ/เปลี่ยน `BOOTSTRAP_SECRET` หากไม่ต้องการเปิด endpoint สำหรับ bootstrap ต่อ

## 4. การสมัครสมาชิก

- Register = Customer
- Admin = สร้าง Staff
- Admin สามารถเปลี่ยน role/active status ของผู้ใช้ได้

## 5. Deploy

เชื่อม GitHub repository กับ Vercel หรือใช้ Vercel CLI

```bash
vercel
```

สำหรับ local development สามารถใช้ Vercel CLI:

```bash
vercel dev
```

หรือทดสอบเฉพาะ Python API ได้โดยตรง:

```bash
python api/index.py
```

คำสั่งนี้ถูกเตรียมไว้ให้ทำงานได้ทั้งตอน import เป็น package และตอนรันไฟล์ตรงจาก VS Code/PowerShell


เปิด `/` สำหรับหน้าเว็บ และ `/api/health` สำหรับตรวจ API

## หมายเหตุเรื่อง Rubric

โค้ดนี้ตั้งใจให้เห็นองค์ประกอบที่โจทย์ต้องการ:
- int / float / str / bool
- if / elif / else
- and / or / not
- for / while (เพิ่ม loop ฝั่ง UI และ validation ได้)
- functions มากกว่า 6
- list / dict / tuple / set
- แยก Python modules
- try / except
- JSON
- CRUD
- search / filter / sort / pagination
- Dashboard
- Audit Log
- Role-based access

## ฟีเจอร์

Admin:
- Dashboard
- Menu Management
- Staff/User Management
- Audit Logs

Staff:
- Table Management
- POS
- Split/Merge/Move Table (โครงสร้าง API รองรับการต่อยอด)
- Reservation/Queue
- Checkout/Receipt
- Kitchen Display

Customer:
- Reservation
- QR Digital Menu
- Menu Options
- Cart
- Order Tracking
- Member Points

## Local development mode (no Firebase setup needed)

เปิดใช้งานอัตโนมัติเมื่อไม่มี `FIREBASE_DB_URL` หรือ `FIREBASE_API_KEY`:

```bash
python api/index.py
```

จากนั้นเปิด `http://127.0.0.1:8000/` แล้วระบบจะแสดงหน้า Login ก่อนเสมอ

บัญชี Admin เริ่มต้นสำหรับ Local:

```text
Email: admin@itailaew.com
Password: Admin@12345
```

Register จากหน้า Login จะสร้างบัญชี Customer และข้อมูลผู้ใช้/เมนู/โต๊ะ/ออเดอร์จะเก็บใน `data/database.json` แบบถาวรบนเครื่อง

เมื่อกำหนด Firebase Environment Variables ระบบจะสลับไปใช้ Firebase Authentication + Firebase Realtime Database สำหรับ Production และข้อมูลจะเก็บบน Cloud

> Login gate เป็นการควบคุมหน้า SPA ฝั่ง Browser และ API ทุกตัวที่เป็นข้อมูลระบบจะตรวจ Authorization/Role ฝั่ง Server ซ้ำอีกชั้น
