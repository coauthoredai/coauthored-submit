# Coauthored on Google Cloud (project `ai-coauthored`, region `us-east1`)

What exists, and how it was created (2026-11-15). coauthored-browse's `deploy/` has its side.

| Resource | Name |
|---|---|
| Cloud SQL (MySQL 8.4, db-f1-micro, daily backups, binlog, deletion protection) | `coauthored-db`, database `coauthored` (utf8mb4), flag `sql_mode` without `ONLY_FULL_GROUP_BY` |
| Database users | `submit` (read/write), `browse` (SELECT only, made by `flask grant-reader browse`), `root` (random password in `db-root-password`) |
| Bucket (private, uniform access) | `gs://ai-coauthored-papers` (`reasons.json` at the root) |
| Images | `us-east1-docker.pkg.dev/ai-coauthored/coauthored/{browse,submit}:<git sha>` |
| Cloud Run services | `coauthored-browse` (public site), `coauthored-submit` (this app) |
| Cloud Run jobs | `coauthored-init` (one-off: `load-classic-schema`, `init-db`, `grant-reader browse`), `coauthored-announce` (`flask announce`) |
| Cloud Scheduler | `coauthored-daily-announce`, 20:00 UTC daily, runs `coauthored-announce` as `coauthored-scheduler` |
| Service accounts | `coauthored-browse` (bucket viewer, Cloud SQL client), `coauthored-submit` (bucket admin, Cloud SQL client), `coauthored-scheduler` (invoker on the announce job) |
| Secrets | `submit-db-uri`, `browse-db-uri`, `submit-db-password`, `browse-db-password`, `submit-secret-key`, `db-root-password`; to add: `resend-api-key`, `clerk-secret-key` |

## Deploy a new version

```sh
P=ai-coauthored R=us-east1 IMG=$R-docker.pkg.dev/$P/coauthored/submit:$(git rev-parse --short HEAD)
gcloud builds submit --project $P --region $R --tag $IMG .
gcloud run deploy coauthored-submit --project $P --region $R --image $IMG
gcloud run jobs update coauthored-announce --project $P --region $R --image $IMG
```

The service and jobs use `deploy/env.prod.yaml` and the secrets above:

```sh
--service-account coauthored-submit@$P.iam.gserviceaccount.com \
--add-cloudsql-instances $P:$R:coauthored-db --env-vars-file deploy/env.prod.yaml \
--set-secrets CLASSIC_DB_URI=submit-db-uri:latest,SECRET_KEY=submit-secret-key:latest
```

## Email (Resend) and sign-in (Clerk)

- Resend over SMTP: `MAILER=smtp` with `SMTP_HOST=smtp.resend.com`, port 587, user `resend`,
  password = the Resend API key (`--set-secrets SMTP_PASSWORD=resend-api-key:latest`).
- Clerk production instance on `aicoauthored.dev`: Frontend API `clerk.aicoauthored.dev`,
  Account Portal `accounts.aicoauthored.dev`; `CLERK_PUBLISHABLE_KEY` in `env.prod.yaml`,
  `--set-secrets CLERK_SECRET_KEY=clerk-secret-key:latest` (used to fetch email and name).

## Domains

`aicoauthored.dev` -> `coauthored-browse` and `submit.aicoauthored.dev` -> `coauthored-submit`
via Cloud Run domain mappings, after the domain is verified (`gcloud domains verify`).
