# AttendX security model

## Assets
- Attendance records (they decide exam eligibility — a high-value target for students)
- Face templates (biometric data; cannot be rotated like a password)
- Medical evidence PDFs attached to disputes
- Credentials for students, faculty, admins and classroom devices

## Adversaries considered
| Adversary | Goal | Main controls |
|---|---|---|
| Student | Mark self/friends present, read others' records, edit attendance | Session-derived identity, per-route RBAC + ownership, enrolment checks in SQL, liveness, duplicate-face blocking |
| Faculty member | Act on courses they don't teach | Course ownership on every lecture/override/dispute/export call |
| Network attacker on campus Wi-Fi | Steal sessions | HttpOnly + SameSite=Strict cookie, Secure flag behind HTTPS, HSTS, token digest at rest |
| Malicious website | CSRF, clickjacking, DNS rebinding | CSRF token (HMAC), SameSite=Strict, `frame-ancestors 'none'`, Host allow-list, closed CORS |
| Stored-XSS payload in a name/reason | Hijack a teacher/admin session | Escape-by-default templating, strict CSP without `unsafe-inline`, HttpOnly cookie |
| Database leak | Reuse passwords / sessions / faces | scrypt hashes, session token digests, AES-256-GCM templates with per-student AAD, keys outside the DB |
| Online guesser | Brute-force accounts or device PINs | Lockout with exponential back-off, per-IP limits, uniform errors and timing, no default credentials |
| Malicious upload | Script execution, file smuggling, path traversal | PDF structure scan (incl. object streams), random names outside web root, owner-scoped download, sandbox CSP |

## Controls by layer
**Transport / browser** — CSP `default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`,
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP same-origin,
restrictive Permissions-Policy, `Cache-Control: no-store` for API/HTML, HSTS when served over HTTPS,
TrustedHost allow-list, request-body cap (6 MB), chunked uploads refused.

**Authentication** — `core/auth.py`, `api/routers/auth.py`. Opaque 256-bit tokens; SHA-256 digest stored;
30-minute idle / 12-hour absolute expiry (12-hour idle for classroom kiosks); revoke on logout, password change,
admin reset and PIN change; newest 5 sessions per account kept. Forced password change gates every route
except `/auth/{me,session,logout,change-password}`.

**Passwords & PINs** — `core/security.py`. scrypt N=2^15 r=8 p=1, 16-byte salt, versioned format,
`hmac.compare_digest`, dummy verification for unknown users and locked accounts. Policy: ≥10 chars, 3 of 4
character classes, not common, must not contain the user's ID. PINs: 6–12 digits, not sequential/repetitive.
One-time passwords expire after 72 h.

**Authorization** — `require(...)` role dependency on every non-public route plus `assert_self`,
`assert_course_access`, `assert_classroom_access`, `assert_lecture_access`. Non-owners get 403/404 without
learning whether a resource exists. `tests/test_security.py::test_every_endpoint_requires_a_session` walks the
OpenAPI spec so a new unprotected route fails CI.

**Biometrics** — templates are `AXF1 | nonce | AES-256-GCM(ciphertext+tag)` with AAD `attendx-face:<student_id>`.
The data key lives in `ATTENDX_DATA_KEY` or `instance/data.key` (0600), never in the database. Admins can erase a
template; the camera only loads templates of students enrolled in the running course.

**Integrity** — attendance inserts are conditional on enrolment (and on an active lecture for the camera path);
`UNIQUE(student_id, lecture_id)`; dispute approval + attendance write in one transaction; all writes audited.

**Auditing** — `audit_log` records sign-ins (success/failure/lockout), denied requests, CSRF rejections, password
issuance/changes, overrides, disputes, exports, uploads, PIN changes, CSV imports and duplicate-face blocks.
The admin **Overview → Security** panel summarises the last 24 hours.

## Operational guidance
- Put the API behind HTTPS (e.g. Caddy/nginx) before exposing it beyond localhost; set `ATTENDX_COOKIE_SECURE=true`
  and add the public hostname to `ATTENDX_ALLOWED_HOSTS`.
- Back up `instance/data.key` (or `ATTENDX_DATA_KEY`) separately from database backups.
- Delete `instance/initial_admin_password.txt` after the first sign-in.
- Rate limits are per process; run a single API worker or move limits to a shared store before scaling out.

## Known limitations
- Liveness is heuristic (motion + blink); a high-quality video replay or 3D mask is out of scope.
- The recognition process trusts the local camera; a compromised classroom PC can inject frames.
- In-memory rate limiting resets on restart (account lockouts are persisted in the database).

## Reporting
Please report vulnerabilities privately to the maintainers rather than opening a public issue.
