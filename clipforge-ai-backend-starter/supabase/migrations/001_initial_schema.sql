-- ClipForge AI initial schema.
-- Apply through Supabase SQL Editor or Supabase CLI.
create extension if not exists pgcrypto;

create type public.project_status as enum (
  'draft', 'uploading', 'uploaded', 'analyzing', 'ready', 'failed'
);

create type public.job_status as enum (
  'queued', 'processing', 'completed', 'failed'
);

create table public.projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 120),
  status public.project_status not null default 'draft',
  original_filename text,
  original_storage_path text,
  original_mime_type text,
  original_size_bytes bigint check (original_size_bytes is null or original_size_bytes >= 0),
  duration_seconds numeric(12,3) check (duration_seconds is null or duration_seconds >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.clip_suggestions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  title text not null,
  rationale text,
  start_seconds numeric(12,3) not null check (start_seconds >= 0),
  end_seconds numeric(12,3) not null check (end_seconds > start_seconds),
  score numeric(5,2) check (score is null or (score >= 0 and score <= 100)),
  transcript_excerpt text,
  created_at timestamptz not null default now()
);

create table public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  job_type text not null check (job_type in ('analyze_video', 'render_clip')),
  status public.job_status not null default 'queued',
  input jsonb not null default '{}'::jsonb,
  output jsonb,
  error_message text,
  attempts integer not null default 0 check (attempts >= 0),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create table public.generated_clips (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  suggestion_id uuid references public.clip_suggestions(id) on delete set null,
  storage_path text not null,
  duration_seconds numeric(12,3),
  aspect_ratio text not null default '9:16',
  caption_style text not null default 'clean',
  created_at timestamptz not null default now()
);

create index projects_user_id_created_at_idx on public.projects(user_id, created_at desc);
create index clip_suggestions_project_id_idx on public.clip_suggestions(project_id);
create index processing_jobs_status_created_at_idx on public.processing_jobs(status, created_at);
create index generated_clips_project_id_idx on public.generated_clips(project_id);

alter table public.projects enable row level security;
alter table public.clip_suggestions enable row level security;
alter table public.processing_jobs enable row level security;
alter table public.generated_clips enable row level security;

create policy "Users can read own projects"
on public.projects for select
using (auth.uid() = user_id);

create policy "Users can create own projects"
on public.projects for insert
with check (auth.uid() = user_id);

create policy "Users can update own projects"
on public.projects for update
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

create policy "Users can delete own projects"
on public.projects for delete
using (auth.uid() = user_id);

create policy "Users can read suggestions for own projects"
on public.clip_suggestions for select
using (
  exists (
    select 1 from public.projects p
    where p.id = project_id and p.user_id = auth.uid()
  )
);

create policy "Users can read jobs for own projects"
on public.processing_jobs for select
using (
  exists (
    select 1 from public.projects p
    where p.id = project_id and p.user_id = auth.uid()
  )
);

create policy "Users can read clips for own projects"
on public.generated_clips for select
using (
  exists (
    select 1 from public.projects p
    where p.id = project_id and p.user_id = auth.uid()
  )
);

-- NOTE: API routes using the service-role key bypass RLS. Those routes must
-- verify the signed-in user and ownership before every read/write.
