# Safety and Production

Production use requires explicit guardrail declarations:

```bash
GHOSTCHIMERA_DEPLOYMENT_MODE=production
GHOSTCHIMERA_EXTERNAL_ISOLATION=container
GHOSTCHIMERA_SECURITY_REVIEWED=1
GHOSTCHIMERA_HUMAN_APPROVAL_REQUIRED=1
GHOSTCHIMERA_ALLOW_UNTRUSTED_INPUTS=0
```

Validate configuration before deployment:

```bash
python scripts/validate_config.py --env-file .env.production --production
```

Start from `.env.production.example`, replace the console token, and choose a real model provider before running the validator.

The validator redacts supported secret values in JSON and text output.
