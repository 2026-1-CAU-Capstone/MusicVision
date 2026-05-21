# MusicVision API Security

This document describes the small security layer around the internal OMR API.
It intentionally avoids real secret values; keep actual keys in environment
variables or deployment secret storage.

## Inbound OMR API key

MusicVision can require callers to send:

```text
X-OMR-API-Key: <secret>
```

Configure the expected value with:

```text
OMR_API_KEY=<secret>
```

When `OMR_API_KEY` is set, every `/omr/*` endpoint requires the header:

```text
POST /omr/process
GET  /omr/jobs/{job_id}
GET  /omr/jobs/{job_id}/musicxml
GET  /omr/jobs/{job_id}/chord-assignments
```

`/health` remains unauthenticated so deployments can still perform simple health
checks.

In `APP_ENV=prod`, MusicVision fails closed if `OMR_API_KEY` is not configured.
In local development, leaving `OMR_API_KEY` empty keeps the OMR endpoints open
for convenience.

## Callback URL policy

MusicVision supports two callback modes.

### Production

Production should use a fixed callback URL owned by the Spring Boot backend:

```text
APP_ENV=prod
OMR_CALLBACK_URL=https://spring.example/internal/omr/callbacks
OMR_ALLOW_REQUEST_CALLBACK_URL=false
```

With request callbacks disabled, MusicVision rejects any submitted
`callback_url` form field and always uses `OMR_CALLBACK_URL`.

This prevents callers from making MusicVision post job results to arbitrary
URLs.

### Development

Development can allow request-supplied callback URLs:

```text
APP_ENV=dev
OMR_ALLOW_REQUEST_CALLBACK_URL=true
```

In this mode, `POST /omr/process` may include:

```text
callback_url=http://localhost:8080/omr/callbacks
```

If no request callback is supplied, MusicVision falls back to
`OMR_CALLBACK_URL` when it is configured.

## Outbound callback API key

MusicVision can authenticate its callbacks to Spring Boot with:

```text
OMR_CALLBACK_API_KEY=<secret>
```

When configured, MusicVision includes this header on callback requests:

```text
X-OMR-Callback-API-Key: <secret>
```

Spring Boot should reject callback requests that do not include the expected
header value.

## Recommended Production Settings

```text
APP_ENV=prod
OMR_API_KEY=<shared-secret-for-spring-to-call-musicvision>
OMR_CALLBACK_URL=https://spring.example/internal/omr/callbacks
OMR_CALLBACK_API_KEY=<shared-secret-for-musicvision-to-call-spring>
OMR_ALLOW_REQUEST_CALLBACK_URL=false
```

The `.env` file is ignored by git. Do not commit real API keys.
