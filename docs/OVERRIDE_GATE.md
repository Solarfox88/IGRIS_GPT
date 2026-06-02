# Override Gate

The Override Gate is a scoped, TTL-bound approval flow for safety-gated actions.

## Behavior

- Overrides are scoped to a specific operation or domain.
- Overrides expire automatically after a bounded TTL.
- Physical/operator approval is required before confirmation.
- Confirmed overrides are consumed and revoked.
- Audit entries are append-only and include scope, mission context, and approval metadata.

## API

- `POST /api/safety/override/request`
  - requests a new token
  - accepts `user`, `scope`, `reason`, `mission_id`, `ttl`

- `POST /api/safety/override/confirm`
  - confirms and consumes a token
  - accepts `approval_token`, `approved_by`, `scope`, `mission_id`

- `GET /api/safety/override/status`
  - returns a safe summary of active overrides

## Limits

- TTL is clamped to 15 minutes maximum.
- Confirmations fail when scope or mission context does not match.
- Expired tokens are revoked automatically.

