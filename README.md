---
title: Jobright Scraper
emoji: 🔍
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
license: mit
---

# Jobright Scraper

Scrapes job listings from Jobright and pushes them to Supabase.
Triggered hourly via GitHub Actions.

## Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | None | Health check |
| POST | `/scrape/all` | `x-api-key` | Start full scrape run |
| POST | `/scrape/stop` | `x-api-key` | Stop running scraper |
| GET | `/status` | `x-api-key` | Scraper status |

## Required Secrets (HF Space → Settings → Variables and secrets)

| Name | Description |
|------|-------------|
| `WEBHOOK_SECRET` | Shared secret for API auth |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anon key |
| `EMAIL` | Supabase auth email |
| `PASSWORD` | Supabase auth password |
