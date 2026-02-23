# Local development: use session pooler (same as Render)

So that localhost behaves like Render and works with tenants that use session pooler URLs, use the **session pooler** connection string for the **master** DB in your local environment.

## 1. Set `DATABASE_URL` to the session pooler (master project)

In your **local** `.env` (e.g. `pharmasight/.env` or `pharmasight/backend/.env`), set:

```env
DATABASE_URL=postgresql://postgres.PROJECT_REF:YOUR_PASSWORD@aws-1-eu-west-1.pooler.supabase.com:5432/postgres
```

- Replace **PROJECT_REF** with your **master** Supabase project ref (e.g. `kwvkkbofubsjiwqlqakt` for pharmasightsolutions’s project).
- Replace **YOUR_PASSWORD** with the database password for that project.
- Use the **Session pooler** URI from the master project: Supabase Dashboard → Project Settings → Database → Connect → **Session pooler**.

So local and Render both use the same style of URL (session pooler) for the master DB.

## 2. Default tenant row in `public.tenants`

The “Default (Development)” tenant in the master DB should have `database_url` set to that **same** session pooler URL (same as `DATABASE_URL`). Then:

- “Default” tenant resolution (e.g. for storage or when no tenant header is sent) will match.
- You can keep a single connection style (session pooler) everywhere.

## 3. Tenant rows (e.g. Harte)

Each **client** tenant should have `database_url` = that **client’s** session pooler URL (from that client’s Supabase project), with username `postgres.CLIENT_PROJECT_REF`. No change needed if you already store session pooler URLs per tenant.

## 4. If you keep direct URL locally

If you leave `DATABASE_URL` as the **direct** URL (e.g. `db.xxx.supabase.co:5432`) locally, the app will still treat it as the **same DB** as a tenant row that has the **session pooler** URL for the same project (by comparing Supabase project ref). So the “Default” tenant can be found even when one side is direct and the other is pooler. For consistency and to avoid surprises, we still recommend using the session pooler for `DATABASE_URL` locally.

## Summary

| Where        | What to use |
|-------------|-------------|
| Local `.env` `DATABASE_URL` | Session pooler URL for the **master** project (same as Render). |
| `public.tenants` Default row | Same session pooler URL as `DATABASE_URL`. |
| `public.tenants` client rows | Session pooler URL for **that** client’s Supabase project (`postgres.CLIENT_REF@...`). |

This way localhost and Render use the same session pooler and behavior matches.
