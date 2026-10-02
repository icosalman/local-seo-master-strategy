# SQ Local Auditor

A roofing local SEO audit tool for SharpQuery. The strategy it checks against lives in [`docs/`](docs/). Give it a client's website and it crawls the real site, checks it against the **Roofing Local SEO Master Strategy**, and writes a report with weak points, strong points, a month-by-month action plan and the exact pages to build.

**Nothing is guessed.** Every result is a fixed rule applied to data fetched during the run, and each one shows its rule and evidence (the URL and the text found). If the tool cannot see something (rank grid, backlinks, keyword volumes, GBP posts), it marks it **Not checked** and tells you how to check it by hand.

## What it checks

| Area | Source of truth |
| --- | --- |
| Crawl and indexing: HTTPS, http/www redirects, robots.txt, sitemap, broken links, redirects, noindex, canonicals, orphan pages | The live site |
| On-page: titles, meta descriptions, H1s, URL length and format, thin pages, image alt text, internal links, mobile viewport | The live site, thresholds from the On-page Checklist |
| Site structure: every page in the master silo map (Repair, Replacement, Storm and Insurance, Commercial, Exteriors, Service Areas, About) found or missing | URL and H1 pattern match, with the matched URL shown |
| Cities: dedicated city pages and Service x City combo pages for the cities you give | The live site |
| Local signals and NAP: phone numbers and where they appear, click-to-call, address, map embed, GBP link, social and directory links | The live site |
| Schema: LocalBusiness / RoofingContractor fields, FAQPage, BreadcrumbList, Service, invalid JSON-LD | The live site |
| Trust and E-E-A-T: license, insurance, warranty, financing, free inspection, emergency, BBB, years, manufacturer brands and certifications (quoted) | The live site |
| Conversion: forms and call buttons on the homepage and service pages | The live site |
| Speed: Lighthouse scores, lab metrics, real-user Core Web Vitals | Google PageSpeed Insights API |
| GBP: name, primary type, rating, reviews, phone, website, hours, status, NAP match | Google Places API (optional key) |
| Competitors: top results per city with rating, reviews and primary type, client position, review gap | Google Places API (optional key) |

## Install (one time)

You need Python 3.10 or newer.

```bash
git clone https://github.com/YOUR-USERNAME/sq-local-auditor.git
cd sq-local-auditor
pip install -r requirements.txt
cp .env.example .env      # on Windows: copy .env.example .env
```

Open `.env` and add keys if you have them (both optional):

- `PAGESPEED_API_KEY`: free from Google Cloud (enable "PageSpeed Insights API"). Works without a key at low volume.
- `GOOGLE_PLACES_API_KEY`: Google Cloud, enable "Places API (New)", billing on. Google gives a monthly free allowance; check Google Maps Platform pricing before heavy use.

## Run

Easiest (asks you questions):

```bash
python -m auditor
```
On Windows you can double-click `audit.bat`.

One line with everything:

```bash
python -m auditor https://clientroofing.com --cities "Frisco, TX; Plano, TX; McKinney, TX" --name "Client Roofing LLC"
```

Useful options:

| Option | What it does |
| --- | --- |
| `--cities "A, ST; B, ST"` | Target cities. Turns on city page checks and competitor lists |
| `--name "Business Name"` | Name as on Google. Helps find the client's GBP |
| `--place-id ChIJ...` | Exact GBP place ID (most reliable match) |
| `--comp-keyword "roofer"` | Competitor search phrase (default "roofing contractor") |
| `--max-pages 500` | Crawl more pages (default 200) |
| `--no-psi` / `--no-places` | Skip PageSpeed / Places |
| `--ignore-robots` | Crawl pages robots.txt blocks. Only with the client's permission |

## Run from any device (GitHub Codespaces, no install)

Works from any PC browser, and from a phone or tablet browser.

1. Open the repo on github.com, click **Code** > **Codespaces** > **Create codespace on main**.
2. Wait for it to open (requirements install automatically).
3. In the terminal at the bottom, run: `python -m auditor`
4. Reports appear in the `reports` folder on the left. Right-click `report.html` > **Download**.

API keys in Codespaces: add `PAGESPEED_API_KEY` and `GOOGLE_PLACES_API_KEY` as Codespaces secrets
(GitHub > Settings > Codespaces > Secrets) instead of a `.env` file. Stop the codespace when done to save free hours.

## Output

Each run creates `reports/<domain>_<date>/` with:

- `report.html`: open in a browser. Weak points, strong points, action plan, pages to build, silo and city coverage, competitors, manual checks, site facts, page inventory. Print to PDF for the client.
- `action_plan.csv`: monthly tasks and pages to build; import into your tracker sheet.
- `findings.csv`: every check with rule and evidence.
- `pages.csv`: one row per URL.
- `data.json`: everything, machine readable.

Run it again every month on the same client to track progress and review counts.

## Honest limits

- Places API order is **not** the live map pack from a searcher's location. Use a rank grid (Local Falcon, BrightLocal) for real positions.
- Places API types are close to, but not identical to, GBP category names. Confirm in the GBP editor.
- Forms or content loaded only by JavaScript may not be visible to the crawler. The report says so where it matters.
- Pattern matches (pages, claims, brands) are shown with the matched URL or quote so you can confirm them. The tool reports what the site says; it cannot prove a claim is true.

## Change the rules

All rules live in `auditor/config.py`: thresholds, the expected page list, trust signal patterns, manufacturer names. Edit and re-run.

## Test

```bash
python tests/test_offline.py
```
Runs the full pipeline on a small local test site with sample API responses. No internet needed.

## Push to your GitHub

```bash
git init
git add .
git commit -m "SQ Local Auditor v1"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/sq-local-auditor.git
git push -u origin main
```
`.env` (your keys) and `reports/` are in `.gitignore`, so they never get pushed. Keep the repo private if client reports or keys might end up in it.

---

## বাংলায় দ্রুত গাইড

1. একবার: `pip install -r requirements.txt` চালান, `.env.example` কপি করে `.env` বানান, key থাকলে বসান (না থাকলেও চলবে)।
2. প্রতিবার: `python -m auditor` চালান (Windows এ `audit.bat` এ ডাবল ক্লিক)। ক্লায়েন্টের URL, শহর আর বিজনেসের নাম দিন।
3. `reports` ফোল্ডারে `report.html` খুলুন। লাল (FAIL) আর হলুদ (WARN) আগে ঠিক করুন, P1 সবার আগে।
4. "Not checked" মানে টুলের কাছে ওই ডেটা নেই, তাই কিছু অনুমান করেনি। পাশে লেখা পদ্ধতিতে নিজে চেক করুন।
5. প্রতি মাসে আবার চালান, উন্নতি আর রিভিউ সংখ্যা তুলনা করুন।
