# Employee Analytics API

## Overview

A FastAPI application backed by MongoDB that provides employee management, attendance tracking, and analytics endpoints, including department summaries, attendance trends, late-arrival leaderboards, and query execution plan explanations.

## Tech Stack

- Python
- FastAPI
- MongoDB 6.0+
- PyMongo
- Pydantic
- Uvicorn

## Setup

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file using `.env.example` as a reference. Configure `MONGO_URI` and `MONGO_DB` with your MongoDB connection details.

Never commit credentials or your `.env` file to version control.

### 4. Seed the sample database

Verify that `MONGO_DB` points to the intended database before running the seed script.

```powershell
python sample_seed.py
```

### 5. Start the application

```powershell
uvicorn app.main:app --port 8000 --reload
```

## API Documentation

Once the application is running, open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) to explore the available endpoints and send test requests.

The health endpoint is available at `/health`.

## Query Performance

MongoDB indexes support the application's query patterns. The explain endpoint provides execution-plan details for supported endpoints. Query performance should be evaluated using representative datasets and execution statistics.

## Submission

The public Git repository should include:

- `app/main.py`
- `requirements.txt`
- `REVIEW.md`
- `DECISIONS.md`
- `README.md`

Do not commit `.env` files, API keys, passwords, database credentials, virtual environments, or other sensitive information.
