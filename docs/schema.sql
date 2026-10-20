-- Apply once to a dedicated Supabase project, via apply_migration / SQL editor.
-- Only published, non-personal monitoring reports are public.
create table if not exists public.mikawa_reports (
  report_month date primary key check (extract(day from report_month) = 1),
  generated_at timestamptz not null,
  last_observed date not null,
  input_digest text not null check (input_digest ~ '^[a-f0-9]{64}$'),
  published boolean not null default true,
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  constraint mikawa_report_size check (octet_length(payload::text) < 8388608)
);
alter table public.mikawa_reports enable row level security;
revoke all on public.mikawa_reports from anon, authenticated;
grant select on public.mikawa_reports to anon, authenticated;
grant all on public.mikawa_reports to service_role;
create policy mikawa_public_reports on public.mikawa_reports
  for select to anon, authenticated using (published = true);

create or replace function public.publish_mikawa_report(document jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  month_key date;
begin
  if document->>'schema_version' is distinct from '1'
     or document->'aoi'->>'id' is distinct from 'mikawa-jinno'
     or jsonb_typeof(document->'points') is distinct from 'array'
     or jsonb_array_length(document->'points') = 0
     or document->>'input_digest' is null then
    raise exception 'Invalid report';
  end if;
  month_key := ((document->>'report_month') || '-01')::date;
  insert into public.mikawa_reports(report_month, generated_at, last_observed, input_digest, payload)
    values(month_key, (document->>'generated_at')::timestamptz,
      (document->>'last_observed')::date, document->>'input_digest', document)
    on conflict (report_month) do update set generated_at = excluded.generated_at,
      last_observed = excluded.last_observed, input_digest = excluded.input_digest,
      payload = excluded.payload;
  -- Bound retention to 24 monthly snapshots. Never remove other projects' data.
  delete from public.mikawa_reports where report_month < month_key - interval '23 months';
  return jsonb_build_object('report_month', month_key, 'stored', true);
end;
$$;
revoke all on function public.publish_mikawa_report(jsonb) from public, anon, authenticated;
grant execute on function public.publish_mikawa_report(jsonb) to service_role;
