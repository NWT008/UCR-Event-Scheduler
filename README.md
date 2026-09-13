# UCR-Scheduler

> **Intelligent Room Booking & Event Scheduling Agent for UC Riverside (UCR 25Live)**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Google ADK](https://img.shields.io/badge/Google_ADK-2.2%2B-4285F4.svg?logo=google)](https://github.com/google/adk)
[![Discord.py](https://img.shields.io/badge/discord.py-2.7%2B-5865F2.svg?logo=discord)](https://discordpy.readthedocs.io/)
[![Playwright](https://img.shields.io/badge/playwright-Chromium-45ba4b.svg?logo=playwright)](https://playwright.dev/)

`ucr-scheduler` is an AI-powered conversational agent and automation tool designed to streamline booking study spaces, classrooms, and event facilities at the University of California, Riverside. It connects directly with UCR's official scheduling portal, **25Live** (`reserve.ucr.edu`), replacing tedious multi-step form entry with a guided Discord questionnaire, automated room validation, visual booking previews, and secure authentication.

---

## 🚀 Key Features

- **Conversational Discord Scheduling**: Start a booking session anytime using the `/schedule` slash command. The bot walks you through a guided 13-step questionnaire to collect required event parameters.
- **Zero-Password-Exposure Authentication**:
  - Users authenticate directly against UCR's official Single Sign-On (`auth.ucr.edu`) with Duo MFA.
  - The bot never sees, prompts for, or stores student NetID passwords.
  - Session cookies are encrypted at rest using **AES-256-GCM AEAD** bound strictly to each user's unique Discord ID.
  - Supports both automated browser login and direct cookie import (via DevTools or Cookie-Editor).
- **Campus Building & Acronym Resolution**: Automatically maps campus shorthand and nicknames (e.g., `WCH`, `MSE`, `SSC`, `Chung`, `Student Success Center`) to official 25Live building codes and room identifiers.
- **Real-Time Validation & Conflict Checks**:
  - Validates dates, operating hours (e.g., Student Recreation Center 6:00 AM – 12:00 AM policies), and time validity.
  - Queries 25Live live calendars to verify room availability before booking submission.
  - Verifies sponsoring organizations and event types against the user's authorized profile.
- **AI-Powered Event Polishing**: Uses Gemini via Google ADK to refine and professionally format event descriptions and special instructions for campus room managers.
- **Visual Playwright Verification**: Automates filling the 25Live wizard and renders an exact visual screenshot preview of the reservation summary into Discord, featuring interactive **Confirm Booking** and **Cancel** buttons.
- **Interactive Drag-and-Drop Calendar**: Provides a web UI (`/select_time` powered by FullCalendar) allowing users to drag and select start/end times visually. Selected time slots automatically sync with the active Discord session.
- **Developer Mock Mode**: Built-in mock mode (`USE_MOCK_25LIVE=True`) enables full end-to-end development, testing, and UI preview without requiring live UCR credentials or placing real reservations.
- **A2A Protocol & Google ADK Integration**: Implements the Agent-to-Agent (A2A) protocol and Google ADK runner for scalable multi-agent interoperability and cloud observability.

---

## 🔮 Future Capabilities & Roadmap

> [!NOTE]
> **More features will be added to what the bot is currently capable of as development continues.**

Planned enhancements and upcoming capabilities include:

- **Recurring & Multi-Date Reservations**: Support for scheduling recurring meetings (e.g., weekly club meetings, bi-weekly workshops) across full academic quarters.
- **Smart Room Recommendation Engine**: Suggest alternate available rooms based on headcount, required AV equipment, and layout preferences when a preferred room is unavailable.
- **In-Discord Reservation Management**: View active bookings, check approval status, modify details, or cancel pending reservations directly using `/my-bookings` and `/cancel`.
- **Calendar Integrations**: One-click `.ics` export and direct sync with Google Calendar and Microsoft Outlook for confirmed reservations.
- **Live Approval Notifications**: Automated background polling to alert users via Discord DM as soon as UCR room managers and event approvers approve or update a reservation request.
- **Multi-Room & Equipment Add-Ons**: Support for reserving complex multi-room suites and specialized campus equipment packages.

---

## 📂 Project Structure

```
ucr-scheduler/
├── app/
│   ├── agent.py               # ADK agent definition and tools (availability & reservation tools)
│   ├── booking.py             # Playwright automation engine for 25Live wizard & calendar scraping
│   ├── building_aliases.py    # UCR campus building mappings, acronyms, and alias resolution
│   ├── db.py                  # SQLite database layer for encrypted sessions & cached selections
│   ├── discord_bot.py         # Discord bot client, slash commands (/login, /schedule), and questionnaire
│   ├── fast_api_app.py        # FastAPI server (SSO login portal, calendar picker, A2A endpoints)
│   ├── login_helper.py        # Interactive Playwright login & Duo MFA capture workflow
│   ├── security.py            # Pydantic schemas, AES-256-GCM encryption, and input sanitization
│   ├── app_utils/             # ADK helper utilities and A2A route adapters
│   └── resources/             # Local caches for campus locations, event types, and organizations
├── tests/
│   ├── unit/                  # Unit tests for validation, security, and alias resolution
│   ├── integration/           # Integration tests for API and booking flows
│   └── eval/                  # Agent evaluation scripts, test traces, and grade configs
├── artifacts/                 # Generated screenshots, test traces, and run artifacts
├── .env.example               # Template for environment configuration
├── pyproject.toml             # Project dependencies and tool settings
├── Makefile                   # Common shortcuts for tests, evals, and linting
└── GEMINI.md                  # Development guidelines and agent operational rules
```

---

## 📋 Prerequisites

Before running the application, ensure you have:

- **Python**: Version `3.11` to `3.13`
- **uv**: Fast Python package manager ([Installation Guide](https://docs.astral.sh/uv/getting-started/installation/))
- **Google Cloud SDK** or a **Gemini API Key**: For LLM-based description refinement and Google ADK tooling
- **Discord Bot Token**: A registered Discord application bot with the **Message Content Intent** enabled ([Discord Developer Portal](https://discord.com/developers/applications))
- **Playwright Chromium**: Browser binaries for 25Live automation

---

## ⚙️ Configuration

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd ucr-scheduler
   ```

2. **Create your environment file**:
   ```bash
   cp .env.example .env
   ```

3. **Configure the environment variables in `.env`**:
   ```env
   # --- Vertex AI / Gemini API Configuration ---
   GOOGLE_GENAI_USE_VERTEXAI=true
   GOOGLE_CLOUD_PROJECT=your-gcp-project-id
   GOOGLE_CLOUD_LOCATION=global

   # Or use Google AI Studio:
   # GEMINI_API_KEY=your_gemini_api_key_here

   # --- Discord Bot Configuration ---
   DISCORD_BOT_TOKEN=your_discord_bot_token_here

   # --- Security & Encryption ---
   # Generate a secure 32+ character random string for production
   COOKIE_ENCRYPTION_KEY=dev_key_only_change_in_production_123456

   # --- Development Modes ---
   # Set to True for local testing without placing real 25Live reservations
   USE_MOCK_25LIVE=True
   ```

---

## 🛠️ Installation & Setup

1. **Install dependencies**:
   ```bash
   uv sync
   ```

2. **Install Playwright browsers**:
   ```bash
   uv run playwright install chromium
   ```

3. **Verify code quality & tests**:
   ```bash
   uv run pytest tests/unit tests/integration
   ```

---

## 🏃 Running the Application

### 1. Launch the Backend Server & Discord Bot

The FastAPI application manages the authentication gateway, visual calendar selector, and automatically starts the Discord bot background task:

```bash
uv run uvicorn app.fast_api_app:app --host 0.0.0.0 --port 8000 --reload
```

Once started:
- **FastAPI API & Docs**: `http://localhost:8000/docs`
- **Authentication Gateway**: `http://localhost:8000/login?discord_id=<YOUR_DISCORD_ID>`
- **Discord Bot**: Connects to your Discord server and syncs slash commands (`/login`, `/schedule`).

### 2. Using the Discord Bot

1. **Authenticate (`/login`)**:
   - Run `/login` in your Discord server.
   - Click the link to open the local authentication gateway in your browser.
   - Choose **Option 1** (launches Chromium for UCR NetID login & Duo push) or **Option 2** (paste your active `WSSESSIONID` cookie). In mock mode, simply click **Complete Mock Login**.
   - Your session is encrypted and securely stored.

2. **Start Booking (`/schedule`)**:
   - Run `/schedule` in any channel where the bot is present.
   - Answer the guided questions (location, event title, description, headcount, start/end dates, AV needs, etc.).
   - If prompted for times, you can type the date/time or use the drag-and-drop calendar link.
   - Inspect the Playwright screenshot preview sent directly to the channel.
   - Click **Confirm Booking** to finalize the reservation or **Cancel** to abort.

---

## 🔒 Security & Privacy Architecture

- **Zero-Trust Credential Handling**: Neither student passwords nor Duo 2FA tokens are ever processed by the bot application. Authentication occurs strictly on official UCR Shibboleth SSO pages (`auth.ucr.edu`).
- **AES-256-GCM AEAD Encryption**: Session cookies are encrypted at rest using AES-GCM with authenticated additional data (AAD) binding each session key strictly to the user's Discord ID.
- **Input Sanitization & Injection Defense**: All user inputs pass through regex-based sanitizers and prompt injection detection before reaching the underlying LLM or Playwright form filler.

---

## 🧪 Testing & Evaluation

- **Run all unit and integration tests**:
  ```bash
  uv run pytest tests/
  ```
- **Run linting and style checks**:
  ```bash
  uv run ruff check .
  ```
- **Evaluate Agent Traces**:
  ```bash
  make generate-traces
  make grade
  ```

---

## 📄 License

This project is licensed under the Apache License, Version 2.0. See the individual source files for copyright notices.
