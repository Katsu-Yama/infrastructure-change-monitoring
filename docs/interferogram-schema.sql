-- Private numerical intermediate products. Anonymous/public clients cannot read.
create table if not exists public.mikawa_interferograms (
  id text primary key check (id ~ '^[a-f0-9]{32}$'),
  first_observed date not null,
  last_observed date not null,
  burst_id text not null,
  direction text not null check (direction in ('ascending', 'descending')),
  object_path text not null unique,
  content_bytes integer not null check (content_bytes > 0 and content_bytes < 5242880),
  metadata jsonb not null,
  created_at timestamptz not null default now(),
  check (last_observed > first_observed)
);
alter table public.mikawa_interferograms enable row level security;
revoke all on public.mikawa_interferograms from anon, authenticated;
grant all on public.mikawa_interferograms to service_role;

create table if not exists public.mikawa_catalog (
  aoi_id text primary key check (aoi_id = 'mikawa-jinno'),
  checked_at timestamptz not null,
  payload jsonb not null check (jsonb_typeof(payload) = 'object' and octet_length(payload::text) < 524288)
);
alter table public.mikawa_catalog enable row level security;
revoke all on public.mikawa_catalog from anon, authenticated;
grant all on public.mikawa_catalog to service_role;
