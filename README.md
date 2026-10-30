# Salt Fork post-use evaluation form — Flask + PostgreSQL in Docker

Online version of `แบบฟอร์มสำหรับประเมินผลหลังการใช้งาน` (ฉบับที่ 2.0, 19 ก.พ. 2569)
for the NIRB-approved field study. Runs as two Docker containers on DCNTIPPS01:

```
Participant's phone ──HTTPS──▶ Caddy (on the server) ──▶ app container :8000 ──▶ db container (PostgreSQL 18)
                                                         127.0.0.1 only           Docker network only
```

## Files

| File | Purpose |
|---|---|
| `form.html`, `thanks.html` | The form and the thank-you page. Wording unchanged from the approved questionnaire. |
| `app.py` | Flask app: serves the form, validates and saves each submission, `/export` CSV, `/healthz`. |
| `schema.sql` | The `evaluations` table. The app creates it automatically at start-up. |
| `requirements.txt`, `Dockerfile` | How the app container is built. |
| `docker-compose.yml` | Runs the app and PostgreSQL together. |
| `.env.example` | Template for the passwords file `.env`. |
| `backup.sh` | Daily database backup (run from cron). |
| `Caddyfile.example` | HTTPS reverse-proxy options for Caddy. |

## How a response is stored

Database `salt_fork`, table `evaluations`, **one row per submission**:

| Column | Type | Notes |
|---|---|---|
| `id` | number | 1, 2, 3, … in order of arrival |
| `submitted_at` | timestamp with time zone | set by the database |
| `form_version` | text | `2.0 (19 ก.พ. 2569)` |
| `usage_frequency` | text | one of the 5 options on the form |
| `sat_shape` … `sat_switch_likelihood` | 16 small integers | each must be 1–5 |
| `calibration_awareness` | text | one of the 3 options |
| `calibration_times` | integer or empty | only when "ทราบ และเคยทำแล้ว" |
| `price_agreement` | text | เห็นด้วย / ไม่เห็นด้วย |
| `suggestions` | text | optional |
| `user_agent` | text | phone/browser type, for troubleshooting |

The allowed values are enforced twice: by the app and by `CHECK` constraints in
the database, so an invalid value can never be stored.

If the database is down when someone submits, they see "please try again later"
(HTTP 503) instead of the thank-you page, so nothing is silently lost.

---

## Deploy on DCNTIPPS01

All commands run on the server over SSH unless stated otherwise.

### 1. Copy the files to the server

From **your own computer**, in the folder where you saved the zip:

```bash
scp salt-fork-survey.zip kittisak@10.228.144.143:~/
```
- `scp`: copies files over SSH (same login as `ssh`).
- `salt-fork-survey.zip`: the file to send.
- `kittisak@10.228.144.143:~/`: user `kittisak` on the server, into the home folder (`~/`).

Then on the server:

```bash
cd ~
unzip salt-fork-survey.zip
cd salt-fork-survey
```
- `cd ~`: go to your home folder.
- `unzip`: extracts the zip into a `salt-fork-survey` folder. If it says "command not found", install it with `sudo apt install unzip`.
- `cd salt-fork-survey`: go into the project folder. **All later `docker compose` commands must be run from this folder**, because that's where `docker-compose.yml` is.

### 2. Create the passwords file

```bash
cp .env.example .env
openssl rand -base64 24
openssl rand -base64 24
nano .env
chmod 600 .env
```
- `cp .env.example .env`: copies the template to `.env`, the file Docker Compose reads automatically.
- `openssl rand -base64 24`: prints a random 32-character password. Run it twice, one for `POSTGRES_PASSWORD` and one for `ADMIN_PASS`.
- `nano .env`: opens the file in a text editor. Paste the two passwords in place of `change-me-db` and `change-me`. Save with **Ctrl+O, Enter**, exit with **Ctrl+X**.
- `chmod 600 .env`: only your user can read or write the file; other users on the server can't see the passwords.

Keep `ADMIN_USER` / `ADMIN_PASS` somewhere safe: you need them to download the data.

### 3. Check that port 8000 is free

```bash
sudo ss -tlnp | grep ':8000\b'
```
- `ss -tlnp`: lists listening TCP ports (`-t` TCP, `-l` listening, `-n` numbers, `-p` which program; `-p` needs `sudo`).
- `grep ':8000\b'`: shows only port 8000.

**No output** = free. If something (e.g. the PM2 app) uses 8000, set `APP_PORT=8001` in `.env` and use 8001 everywhere below instead of 8000.

### 4. Build and start

```bash
docker compose up -d --build
```
- `docker compose up`: creates and starts the `db` and `app` containers defined in `docker-compose.yml`.
- `-d`: in the background ("detached"), so you get your prompt back.
- `--build`: builds the app image from the `Dockerfile` first. Needed the first time and after every code change.

The first run downloads `postgres:18` and `python:3.13-slim` from Docker Hub, which takes a few minutes. Later starts take seconds. Both containers restart automatically after a crash or a server reboot (`restart: unless-stopped`).

### 5. Check it's running

```bash
docker compose ps
docker compose logs app --tail 20
curl http://127.0.0.1:8000/healthz
```
- `docker compose ps`: lists this project's containers. `db` should show `healthy`, `app` should show `Up`.
- `docker compose logs app --tail 20`: last 20 lines from the app. Look for `Database schema ready`.
- `curl http://127.0.0.1:8000/healthz`: asks the app whether it can reach the database. Expected: `{"db":"ok","responses":0,"status":"ok"}`.

If `app` keeps restarting, the log says why. The most common cause is `ADMIN_PASS is not set (or is still 'change-me')`: fix `.env` and run step 4 again.

### 6. Put HTTPS in front (Caddy)

Participants must reach the form over **HTTPS** because it collects study data.

```bash
caddy version
systemctl status caddy --no-pager
```
- `caddy version`: prints Caddy's version if it's installed.
- `systemctl status caddy`: shows whether the Caddy service is running.

If Caddy isn't installed, install it from Caddy's official repository (instructions at
https://caddyserver.com/docs/install, section "Debian, Ubuntu, Raspbian"), not Ubuntu's
`caddy` package, for the same security-update reason as Mosquitto.

Choose one block from `Caddyfile.example`, add it to Caddy's config, then:

```bash
sudo nano /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```
- `sudo nano /etc/caddy/Caddyfile`: edit Caddy's config (owned by root, so `sudo`).
- `caddy validate --config …`: checks the file for mistakes without applying it.
- `sudo systemctl reload caddy`: applies the new config without stopping running sites.

Options 1 and 2 need **ports 80 and 443 forwarded from 43.209.118.141 to 10.228.144.143**
(ask NECTEC IT), so Let's Encrypt can issue the certificate.

### 7. Test, then clear the test data

Open the site on a phone, submit the form a few times, and download
`https://<your-site>/export` (log in with `ADMIN_USER` / `ADMIN_PASS`).
Open the CSV in Excel and check that Thai text displays correctly.

**Before real participants start**, delete the test rows:

```bash
docker compose exec db psql -U saltfork -d salt_fork -c "TRUNCATE evaluations RESTART IDENTITY;"
```
- `docker compose exec db`: runs a command inside the running `db` container.
- `psql -U saltfork -d salt_fork`: PostgreSQL's command-line client, as user `saltfork`, on database `salt_fork`.
- `-c "TRUNCATE evaluations RESTART IDENTITY;"`: deletes **all rows** in the table and resets `id` to start at 1 again. Run this only before launch.

---

## Backups

The database is the only copy of the responses, so back it up daily.

### Test the backup script once by hand

```bash
sudo mkdir -p /storage/backups && sudo chown kittisak /storage/backups
./backup.sh
```
- `sudo mkdir -p /storage/backups`: creates the backup folder on the `/storage` disk (separate from the system disk). `-p`: no error if it exists.
- `sudo chown kittisak /storage/backups`: makes you the owner, so the script can write there without `sudo`.
- `./backup.sh`: runs the script in the current folder. It writes `salt_fork-YYYY-MM-DD-HHMM.dump` into `/storage/backups/salt-fork/`, readable only by you, and deletes dumps older than 30 days.

Your user must be allowed to run `docker` without `sudo` (member of the `docker` group:
check with `groups`). If not, run `sudo usermod -aG docker kittisak`, then log out and in again.

### Run it every night at 02:30

```bash
crontab -e
```
- `crontab -e`: opens your personal schedule of automatic jobs (cron) in an editor. Choose `nano` if asked.

Add this line at the end, then save and exit:

```
30 2 * * * /home/kittisak/salt-fork-survey/backup.sh >> /home/kittisak/salt-fork-survey/backup.log 2>&1
```
- `30 2 * * *`: minute 30, hour 2, every day of month, every month, every weekday → 02:30 daily.
- `/home/kittisak/salt-fork-survey/backup.sh`: the full path to the script (cron needs full paths).
- `>> …/backup.log`: appends the script's output to a log file.
- `2>&1`: also sends error messages to the same log.

Check the next morning with `tail backup.log` and `ls -lh /storage/backups/salt-fork/`.

Also copy backups off the server regularly (e.g. to a NECTEC file share): if the server's
disks fail, backups on the same server are lost too.

### Restore from a backup

```bash
docker compose exec -T db pg_restore -U saltfork -d salt_fork --clean --if-exists < /storage/backups/salt-fork/salt_fork-2026-11-01-0230.dump
```
- `exec -T`: runs inside the `db` container without a terminal, so the file can be fed in with `<`.
- `pg_restore`: PostgreSQL's restore tool for `--format=custom` dumps.
- `--clean --if-exists`: drops the current table before recreating it from the dump. **This replaces the current data** with the backup's contents.
- `< /storage/…dump`: feeds the backup file into the command.

---

## Getting the data

- **CSV for analysis:** `https://<your-site>/export` (Basic Auth). UTF-8 with BOM so Thai opens
  correctly in Excel. `submitted_at` is in Bangkok time (`+07:00`).
- **Quick summary straight from the database:**

  ```bash
  docker compose exec db psql -U saltfork -d salt_fork -c "SELECT count(*) AS n, round(avg(sat_accuracy),2) AS accuracy, round(avg(sat_shape),2) AS shape FROM evaluations;"
  ```
  - `psql … -c "SELECT …"`: runs one SQL query and prints the result.
  - `count(*)`: number of responses. `avg(sat_accuracy)`: average score for that item, `round(…, 2)` to 2 decimals.

## Updating the app later

After changing `app.py` or the HTML files, copy them to the server and run:

```bash
docker compose up -d --build
```
This rebuilds only the app image and replaces the app container. The database container and
its data are not touched.

## Important cautions

- **Never run `docker compose down -v`.** The `-v` deletes the `pg_data` volume, i.e. all
  responses. Plain `docker compose down` (no `-v`) is safe: it stops and removes the
  containers but keeps the data.
- `POSTGRES_PASSWORD` in `.env` is used only when the database is created the first time.
  Changing it afterwards does not change the database password and the app will fail to log in.
- The database has no `ports:` mapping, so it can't be reached from outside the server, only by
  the app container.
- Responses are anonymous (no participant code). If they must be linked to enrollment records,
  a `participant_code` field has to be added to the form, the table and the ethics documents.
