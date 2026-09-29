# pdf-link-extractor

Vercel Python function that extracts embedded hyperlinks from a PDF
(the real `linkedin.com/in/...` / `github.com/...` URLs behind link
annotations, not just the visible "LinkedIn" text) — built to replace
the ngrok `/extract-links` step in the Resume_Classifier_AI_Agent n8n
workflow.

## Repo layout — upload it exactly like this
```
pdf-link-extractor/          <- repo root
├── api/
│   └── extract-links.py
├── requirements.txt
├── vercel.json
└── README.md
```
The `api/` folder name and the file's location inside it matter —
that's how Vercel finds the function. Everything else can sit flat in
the root.

## 1. Create the repo on GitHub (web UI, no git CLI)
1. Go to https://github.com/new
2. Name it `pdf-link-extractor` (or anything), keep it **Public** or
   **Private** — either works with Vercel — and click **Create repository**.
3. On the empty repo page, click **uploading an existing file**.
4. Drag in `requirements.txt`, `vercel.json`, and `README.md` at the
   root, then click **Commit changes**.
5. To get `extract-links.py` into `api/`: click **Add file → Create
   new file**, and in the filename box type:
   ```
   api/extract-links.py
   ```
   Typing the `api/` prefix makes GitHub create the folder for you.
   Paste the contents of `extract-links.py` into the editor, then
   **Commit changes**.
   (Uploading a whole folder by drag-and-drop only works if your OS
   lets you drag a folder into the browser — Chrome and Edge support
   this: drag the `api` folder itself onto the upload page and it
   preserves the path.)

## 2. Deploy on Vercel
1. Go to https://vercel.com/new
2. Click **Import Git Repository**, connect your GitHub account if
   asked, and pick `pdf-link-extractor`.
3. Framework preset: leave as **Other**. Root Directory: leave as `.`.
   No build command needed — Vercel reads `vercel.json` and treats
   `api/extract-links.py` as a Python Serverless Function automatically.
4. Click **Deploy**.

Every future commit to `main` (whether pushed via git or edited
directly on github.com) auto-redeploys.

Your endpoint:
```
https://<project-name>.vercel.app/extract-links
```
(also reachable at `/api/extract-links`).

## 3. Test it
```bash
curl -X POST https://<project-name>.vercel.app/extract-links \
  -H "Content-Type: application/pdf" \
  --data-binary @resume.pdf
```

## 4. Point the n8n HTTP Request node at it
- Method: `POST`
- URL: `https://<project-name>.vercel.app/extract-links` (no leading/trailing spaces)
- Send Body: ON
- Body Content Type: `n8n Binary File`
- Input Data Field Name: `resume`

Response shape:
```json
{
  "links": ["https://in.linkedin.com/in/...", "https://github.com/..."],
  "link_count": 2,
  "annotations": [{"page": 1, "url": "...", "text": "LinkedIn"}],
  "text_urls": [],
  "pages": 1
}
```
`links` is what the AI Agent prompt reads via `{{ $json.links }}`.

## Notes / limits
- Vercel's request body cap is ~4.5 MB — fine for resumes, not large
  scanned PDFs.
- The HTTP Request node's current URL has a leading space
  (`" https://be8b-..."`) — retype it when you swap in the new URL.
- `Code in JavaScript1` in the workflow just sets `myNewField = 1` and
  isn't used downstream; safe to delete and wire Webhook directly into
  HTTP Request + Extract from File.
