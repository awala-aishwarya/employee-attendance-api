# Candidate Kit — Employee Analytics API

## Overview

A FastAPI application backed by MongoDB that provides employee attendance and analytics endpoints, including department summaries, trends, and query execution plan explanations.

## Tech Stack

- Python
- FastAPI
- MongoDB 6.0+
- PyMongo
- Pydantic
- Uvicorn

## Setup

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   ```

   Windows PowerShell:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Configure `.env` using `.env.example`. Set `MONGO_URI` and `MONGO_DB`. Never commit credentials.

4. Seed the sample database:

   ```bash
   python sample_seed.py
   ```

5. Start the application:

   ```bash
   uvicorn app.main:app --port 8000 --reload
   ```

## API Documentation

Once the server is running, open `http://127.0.0.1:8000/docs` to explore and test the API.

## Query Performance

MongoDB indexes support the application's query patterns. The explain endpoint provides execution-plan details for supported endpoints. Performance should be evaluated against representative datasets.

## Submission

The public Git repository must include:

- `app/main.py`
- `requirements.txt`
- `REVIEW.md`
- `DECISIONS.md`
- `README.md`

Do not commit `.env`, secrets, or a Dockerfile.