# Build with AI – How to Test & Host

## 1. Check if AI (Gemini) is working

### Option A: Run the check script (easiest)

```bash
cd backend
.\venv\Scripts\activate
python check_ai.py
```

- **SUCCESS** = Gemini is working; you can use “Build with AI”.
- **FAIL** = Fix API key (see below).

### Option B: Test from the website

1. Start the backend:
   ```bash
   cd backend
   .\venv\Scripts\activate
   python app.py
   ```
2. Open in browser: **http://127.0.0.1:5000/build-with-ai**
3. Fill the form (Business name, type, services, location, style) and click **Generate My Website**.
4. If you get a **preview page** with your business name and content → **AI is working**.
5. If you get an **error** or generic fallback content only → check backend terminal for errors and API key.

### If AI fails – check API key

1. Get a key: https://aistudio.google.com/apikey  
2. Put it in `backend/.env`:
   ```env
   GEMINI_API_KEY="your-key-here"
   ```
3. Restart the backend and run `python check_ai.py` again.

---

## 2. Hosting – what to do

You need to host **two things**: the **app (backend + form)** and the **generated sites (previews)**.

### A. Host the backend (Flask app)

- The same app serves:
  - Form: `/build-with-ai`
  - API: `/api/generate-site`
  - Generated sites: `/generated-sites/<path>`
  - Download: `/download/<slug>`

**Options:**

| Platform     | What to do |
|-------------|------------|
| **Railway / Render / Fly.io** | Deploy the repo; set **root** or **start command** to run Flask from `backend` (e.g. `cd backend && python app.py` or `gunicorn -w 1 app:app`). Set env var `GEMINI_API_KEY`. |
| **Vercel / Netlify (serverless)** | You need to turn the Flask app into a serverless API (e.g. Vercel serverless or Netlify Functions). Not direct “run app.py”. |
| **Your own VPS (Linux)** | Install Python, run `gunicorn` or `uwsgi` behind nginx; run from `backend` folder and set `GEMINI_API_KEY`. |

**Required env vars on host:**

- `GEMINI_API_KEY` – from Google AI Studio (required for AI).
- `HOSTING_PLAN_URL` – (optional) URL for “Choose a Hosting Plan” button, e.g. `https://webglow.co.uk`.

### B. Where generated sites are stored

- Right now generated sites are saved on the **same server** as the app, in the `generated-sites/` folder.
- Preview URL is: `https://your-domain.com/generated-sites/{site-name}/index.html`
- So **hosting the Flask app** also hosts the previews; no separate hosting for “preview.ourdomain.com” unless you want a separate subdomain.

### C. Optional: preview subdomain (e.g. preview.ourdomain.com)

- **Same server:** Point `preview.ourdomain.com` to the same app; use nginx (or similar) to proxy to Flask. Same URLs: `preview.ourdomain.com/generated-sites/{site-name}/index.html`.
- **Different host (e.g. Cloudflare Pages / Netlify):** You’d need to **upload** each generated site (e.g. zip from `/download/<slug>`) to a static host and then redirect or link to that URL. Your app would need extra logic to “publish” a site and return that URL. Not in the current code.

### D. Quick checklist for hosting

1. Deploy the **backend** (Flask) so it runs 24/7.
2. Set **GEMINI_API_KEY** (and optionally **HOSTING_PLAN_URL**) in the host’s environment.
3. Open **https://your-domain.com/build-with-ai** and test: submit form → see preview.
4. If you want “Choose a Hosting Plan” to go to your page, set **HOSTING_PLAN_URL** to that URL.

---

## 3. One-line summary

- **AI check:** Run `python check_ai.py` in `backend` or use the form at `http://127.0.0.1:5000/build-with-ai`.
- **Hosting:** Deploy the Flask app (e.g. Railway/Render/VPS), set `GEMINI_API_KEY` (and optional `HOSTING_PLAN_URL`); the same app serves the form, API, and generated previews.
