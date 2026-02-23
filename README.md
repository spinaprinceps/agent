# Indian Sign Language (ISL) Service MVP

This application provides a two-way communication service for Deaf users using Gemini 2.0 Flash to interpret ISL video and orchestrate service requests (Food, Transport, Appointments).

## Project Structure
- `backend/`: FastAPI application with Vertex AI (Gemini 2.0 Flash) integration.
- `frontend/`: React (Vite + TS) application with Three.js ISL Avatar.

## Setup

### Prerequisites
- Python installed (with `uv`)
- Node.js installed (with `npm`)
- Google Cloud Project with Vertex AI enabled

### Backend Setup
1. Navigate to `backend/`
2. Update `.env` with your `GOOGLE_PROJECT_ID` and `GOOGLE_LOCATION`.
3. Install dependencies:
   ```bash
   uv sync
   ```
4. Run the server:
   ```bash
   uv run python -m uvicorn main:app --reload --port 8080
   ```

### Frontend Setup
1. Navigate to `frontend/`
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev
   ```

## Key Flows
1. **Deaf User**: Press "Sign Now", record sign (~8s), press "Process ISL Request".
2. **Analysis**: Gemini 2.0 Flash analyzes video for transcription + intent.
3. **Response**: 3D Avatar (Three.js) sequences signature animations to respond.
4. **Service Provider**: Use VoiceControls to communicate back via text/simulated voice.
5. **Success**: When service is confirmed, agent outputs "WORK_DONE" and avatar shows success state.
