# Standing Orders

Standing Orders let an operator define bounded, reusable authority for Ghost
Chimera. They are local, explicit, disabled by default, and auditable.

A standing order contains:

- `title`
- `scope`
- `objective`
- `allowed_actions`
- `approval_gates`
- optional delivery channel and target metadata

Orders do not run automatically when created. The operator must enable an order
before it can run. Running an order turns the saved scope and objective into a
normal Ghost objective and sends it through the same Console execution path as a
manual run.

## Console API

```text
GET  /api/console/standing-orders
POST /api/console/standing-orders
POST /api/console/standing-orders/{id}/enable
POST /api/console/standing-orders/{id}/disable
POST /api/console/standing-orders/{id}/run
```

Events are written to local standing-order event logs and the operator timeline.
Delivery targets are redacted in API responses.

## Console UI

Open **Remote Control** and use the **Standing Orders** panel to create, enable,
disable, and run scoped programs.
