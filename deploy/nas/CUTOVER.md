# NAS production cutover — 2026-09-29 KST

- Source Render service srv-daluaue7bikc73ak99e0 suspended at 00:25 KST. Connector confirmed suspended; source HTTP returned 503. Source DB preserved.
- Final clone created a separate database trustmap_final_20260929. Original NAS staging database preserved.
- Final backup and restore succeeded. All public table counts AND row-content fingerprints matched frozen source.
- Customer 1036; customer_task 1172; inventory 592; user 4; account_request 2; email_verification 4.
- App switched to final database; original session secret and live Resend settings copied privately. Admin bootstrap credentials remain blank.
- First daily backup succeeded: BACKUP_OK 20260928T153104Z. Backups stay on NAS volume; this is not off-device disaster recovery.
- Cafe24 apex A now 222.100.153.67; www CNAME now trustflow.co.kr. Resend records preserved. Public DNS confirmed both.
- Both HTTPS hostnames /health returned 200 with certificate verification enabled. Health reports database connected.
- Browser https://trustflow.co.kr/signup rendered enabled email verification and approval workflow.
- Anonymous /customers and /manager returned 302 to /login.
- No test email sent and no production test account created. Actual post-migration staff mail delivery not independently verified.
- DSM managed renewal certificate issuance submitted; final issuance/binding still needs verification. Existing imported certificate remains valid through 2026-12-27.
- Added isolated https-redirect service (no app env or DB) on loopback 18081. Both apex and www HTTP reverse proxies return 308 to https://trustflow.co.kr preserving path/query; verified /signup for both. HTTPS /signup still returns 200 with valid TLS.
- DSM managed-renewal request did not produce a new certificate after reload. Existing valid imported certificate remains active. Automatic renewal is NOT verified; resolve before 2026-12-27. Do not repeatedly reissue certificates or weaken certificate checks.
- Existing hourly mail-check automation was already disabled; its reference prompt was updated for NAS cutover while preserving disabled state. No continuous monitoring is currently promised.

## Recovery precautions
Do not simply resume old Render after NAS accepts writes: synchronize newer NAS data first. Never delete original source database, staging database or final backup during stabilization. Old one-off clone containers refuse existing databases/backups; their refusal is expected on project rebuild, not a web-service failure.

## Active files
/volume1/docker/trustmap-stage/compose.yaml matches compose.production.json. Private db.env and app-stage.env are stored only on NAS/private workspace, not Git. Image trustmap-nas:preflight corresponds to tested app code; prepared maintenance entry point is not active in that image.
