# Remote URL blocked

## Symptom

`GET /health` shows `blocked` for postgres, redis, or otlp. Or a caller of `ensure_local` receives `remote_blocked`.

## Check

The value is set and the host is not `localhost`, `127.0.0.1`, or `::1`. The error text must not contain that URL. No socket should open.

## Action

Point the URL at a local service, or set `HEALTHCARE_PLATFORM_ALLOW_REMOTE=1` only in an environment that is supposed to leave the workstation. Do not set that flag to silence a test. The default on this workstation is unset, which means not-run for empty values and blocked for any other host.
