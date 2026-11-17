# Leafwise

A plant-care assistant with a responsive frontend and a FastAPI backend. Ask general questions about plant care, or upload a leaf photo for a preliminary disease and treatment suggestion.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn FirstProject:app --reload
```

The default provider is Gemini using `gemini-3.5-flash-lite`, a supported image model with a free tier subject to Google's limits. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey), then put it in your local `.env` as `GEMINI_API_KEY=...`. If you already have a `.env`, add or update those lines without replacing your existing file. `.env` is excluded by `.gitignore`; keep the key on the server and do not commit it. Free-tier availability and rate limits can change.

The configured provider handles both photo analysis and text questions. To use OpenRouter instead, set `AI_PROVIDER=openrouter` and configure `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`. Restart the server after changing `.env`.

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The page shows whether the selected provider is configured. After uploading a photo, the plant-check panel below the upload card shows progress, results, or a clear error. Provider requests time out after 45 seconds.

Plant photos and submitted questions are sent to the configured provider when a key is set. AI results are suggestions, not confirmed diagnoses. A single photo cannot reliably predict when a plant will die, so the app avoids an exact death-date promise and only shows a rough severe-decline estimate when the AI has a basis for one. Consult a local agricultural expert for serious or unclear crop issues.
