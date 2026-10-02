# itailaew — Rubric Mapping

## Mandatory Project Requirements
1. Register/Login + roles: admin, staff, customer
2. CRUD + validation
3. Search, filter, sort, pagination
4. Dashboard/report
5. Audit logs
6. Vercel deployment structure

## Python Rubric
- Standard Library only
- `int`, `float`, `str`, `bool`
- `if/elif/else`, `and/or/not`
- `for` and `while`
- 6+ functions with parameters/returns
- `list`, `dict`, `set` (and tuple-compatible structures)
- 2+ `.py` modules
- `try/except`
- JSON data structures
- no traceback shown to users

## Roles
### Admin
Dashboard, Menu Management, User/Staff Management, Audit Logs, full business visibility.

### Staff
Tables, POS, Split/Merge/Move Table, Reservation/Queue, Checkout/Receipt, Kitchen Display.

### Customer
Reservation, QR Menu, Menu Options, Cart/Order Tracking, Member Points.

## Security
- Firebase Authentication REST API verifies identity.
- Backend checks role before protected API operations.
- Firebase Realtime Database is accessed server-side using an environment secret.
- Client never receives the database secret.
- Customer cannot access admin/staff endpoints through URL manipulation.

## Database
Production data: Firebase Realtime Database.
Local reference/seed: `data/database.json`.
