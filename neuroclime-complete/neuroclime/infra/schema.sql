-- ============================================================
-- NeuroClime — Initial schema migration
-- Target: Supabase Postgres (PostGIS enabled)
-- Apply with: supabase db push   (or psql -f schema.sql)
-- ============================================================

create extension if not exists postgis;
create extension if not exists "uuid-ossp";

-- ------------------------------------------------------------
-- Core geography tables
-- ------------------------------------------------------------

create table if not exists cities (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  country_code text not null default 'IN',
  bounding_box geometry(Polygon, 4326) not null,
  created_at timestamptz not null default now()
);

create table if not exists wards (
  id uuid primary key default uuid_generate_v4(),
  city_id uuid not null references cities(id) on delete cascade,
  name text not null,
  geom geometry(MultiPolygon, 4326) not null,
  population integer,
  response_infra jsonb default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_wards_geom on wards using gist (geom);
create index if not exists idx_wards_city on wards (city_id);

create table if not exists hex_zones (
  hex_id text primary key,                -- H3 index string
  city_id uuid not null references cities(id) on delete cascade,
  ward_id uuid references wards(id) on delete set null,
  geom geometry(Polygon, 4326) not null,
  centroid geometry(Point, 4326) not null,
  static_features jsonb default '{}'::jsonb,  -- ndvi, ndbi, albedo, elevation, lcz_class, building_density
  created_at timestamptz not null default now()
);
create index if not exists idx_hexzones_geom on hex_zones using gist (geom);
create index if not exists idx_hexzones_centroid on hex_zones using gist (centroid);
create index if not exists idx_hexzones_city on hex_zones (city_id);
create index if not exists idx_hexzones_ward on hex_zones (ward_id);

-- ------------------------------------------------------------
-- Users
-- ------------------------------------------------------------

create table if not exists users (
  id uuid primary key references auth.users(id) on delete cascade,
  role text not null default 'citizen' check (role in ('citizen','authority','admin')),
  jurisdiction_ward_ids uuid[] default '{}',
  preferred_language text default 'en',
  home_hex_id text references hex_zones(hex_id),
  work_hex_id text references hex_zones(hex_id),
  created_at timestamptz not null default now()
);

-- ------------------------------------------------------------
-- Raw ground-truth & satellite data
-- ------------------------------------------------------------

create table if not exists sensor_readings (
  id bigserial primary key,
  source text not null check (source in ('CPCB','IMD','MAHAVEDH')),
  station_id text not null,
  hex_id text references hex_zones(hex_id) on delete set null,
  recorded_at timestamptz not null,
  temperature_c numeric,
  humidity_pct numeric,
  wind_speed_ms numeric,
  wind_dir_deg numeric,
  ingested_at timestamptz not null default now()
);
create index if not exists idx_sensor_hex_time on sensor_readings (hex_id, recorded_at);
create index if not exists idx_sensor_station_time on sensor_readings (station_id, recorded_at);

create table if not exists satellite_features (
  id bigserial primary key,
  hex_id text not null references hex_zones(hex_id) on delete cascade,
  source text not null check (source in ('INSAT3D','MOD11A1','ERA5_LAND')),
  recorded_at timestamptz not null,
  lst_c numeric,
  era5_temp_c numeric,
  era5_humidity_pct numeric,
  era5_wind_speed_ms numeric,
  era5_wind_dir_deg numeric
);
create index if not exists idx_satfeat_hex_time on satellite_features (hex_id, recorded_at);

-- ------------------------------------------------------------
-- Model output cache (hot read path)
-- ------------------------------------------------------------

create table if not exists predictions (
  id bigserial primary key,
  hex_id text not null references hex_zones(hex_id) on delete cascade,
  model_version text not null,
  generated_at timestamptz not null,
  horizon_hours smallint not null check (horizon_hours in (0,1,3,6)),
  valid_at timestamptz not null,
  pred_temp_c numeric not null,
  pred_temp_uncertainty_c numeric,
  pred_humidity_pct numeric,
  heat_index_c numeric,
  risk_band text check (risk_band in ('safe','caution','danger','extreme'))
);
create index if not exists idx_predictions_hex_valid on predictions (hex_id, valid_at);
create index if not exists idx_predictions_generated on predictions (generated_at);

-- ------------------------------------------------------------
-- App-facing tables
-- ------------------------------------------------------------

create table if not exists alerts (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references users(id) on delete cascade,
  hex_id text not null references hex_zones(hex_id),
  triggered_at timestamptz not null default now(),
  risk_band text,
  delivered boolean default false,
  channel text check (channel in ('push','sms','email'))
);

create table if not exists scenarios (
  id uuid primary key default uuid_generate_v4(),
  created_by uuid references users(id) on delete set null,
  hex_id text not null references hex_zones(hex_id),
  baseline_features jsonb,
  modified_features jsonb,
  predicted_delta_temp_c numeric,
  created_at timestamptz not null default now(),
  notes text
);

create table if not exists reports (
  id uuid primary key default uuid_generate_v4(),
  generated_by uuid references users(id) on delete set null,
  ward_id uuid references wards(id) on delete set null,
  period_start timestamptz,
  period_end timestamptz,
  file_url text,
  format text check (format in ('pdf','csv')),
  created_at timestamptz not null default now()
);

create table if not exists pipeline_runs (
  id bigserial primary key,
  job_type text not null check (job_type in ('ingestion','inference','report')),
  source text,
  status text not null check (status in ('success','failure','running')),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  error_message text,
  metrics jsonb
);

-- ------------------------------------------------------------
-- Row Level Security
-- ------------------------------------------------------------

alter table users enable row level security;
create policy "users_self_access" on users
  for select using (auth.uid() = id);
create policy "users_self_update" on users
  for update using (auth.uid() = id);

alter table alerts enable row level security;
create policy "alerts_owner_only" on alerts
  for select using (auth.uid() = user_id);

alter table scenarios enable row level security;
create policy "scenarios_owner_or_authority" on scenarios
  for select using (
    auth.uid() = created_by
    or exists (
      select 1 from users u
      where u.id = auth.uid()
        and u.role in ('authority','admin')
        and (
          u.role = 'admin'
          or (select ward_id from hex_zones where hex_id = scenarios.hex_id) = any(u.jurisdiction_ward_ids)
        )
    )
  );

alter table reports enable row level security;
create policy "reports_jurisdiction_scope" on reports
  for select using (
    exists (
      select 1 from users u
      where u.id = auth.uid()
        and (u.role = 'admin' or reports.ward_id = any(u.jurisdiction_ward_ids))
    )
  );

-- Public, non-sensitive environmental data: readable by anyone (writes locked to service role)
alter table predictions enable row level security;
create policy "predictions_public_read" on predictions
  for select using (true);

alter table hex_zones enable row level security;
create policy "hexzones_public_read" on hex_zones
  for select using (true);

alter table wards enable row level security;
create policy "wards_public_read" on wards
  for select using (true);

alter table cities enable row level security;
create policy "cities_public_read" on cities
  for select using (true);

-- sensor_readings / satellite_features / pipeline_runs: no public policy —
-- only the service_role key (ingestion/inference backend) can read/write these.
alter table sensor_readings enable row level security;
alter table satellite_features enable row level security;
alter table pipeline_runs enable row level security;
