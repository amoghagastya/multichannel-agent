# DealSmart AI Demo

## What This Is
A multi-channel qualification MVP with:
- SMS agent (OpenAI Agents SDK)
- Voice inbound agent (Ultravox + Twilio)
- Shared tools + dealer config

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Install frontend dependencies:
   ```bash
   cd frontend
   npm install
   npm run build
   ```
2. Create `.env`:
   ```bash
   OPENAI_API_KEY=...
   ULTRAVOX_API_KEY=...
   ULTRAVOX_BASE_URL=https://api.ultravox.ai/api
   DEFAULT_DEALER_ID=demo_bmw
   PUBLIC_BASE_URL=https://<your-api-host>
   PUBLIC_API_URL=https://<your-api-host>
   TWILIO_ACCOUNT_SID=...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+1XXXXXXXXXX
   TWILIO_API_KEY_SID=...
   TWILIO_API_KEY_SECRET=...
   TWILIO_APP_SID=...
   ```
3. Run the webhook server:
   ```bash
   uvicorn server:app --reload --port 8000
   ```
4. Run the Streamlit app:
   ```bash
   streamlit run app.py
   ```

## Twilio + Ultravox (Inbound)
- Point your Twilio Voice webhook to `https://<your-ngrok>/incoming` (POST).
- The server creates an Ultravox call and returns TwiML to stream audio.

## In-App WebRTC (Twilio Client)
1. Create a TwiML App in Twilio Console.
2. Set its **Voice URL** to `https://<your-ngrok>/twiml` (POST).
3. Put the App SID in `TWILIO_APP_SID`.
4. Add `TWILIO_API_KEY_SID` + `TWILIO_API_KEY_SECRET` in `.env`.
5. Build the frontend (`npm run build`).
6. Open `https://<your-api-host>/webrtc/` to use the dialer.
## Dealer Config
See `data/dealer_configs/demo_bmw.json`. Add more dealership configs to scale.

## CRM Adapter
See `core/crm.py`. Implement new adapters without changing agent logic.
