import streamlit as st
import json
import base64
import os
import pickle

from openai import OpenAI
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

st.set_page_config(page_title="AI Email Assistant", layout="wide")

st.title("AI Email Assistant Dashboard")
st.markdown("AI Email Assistant — drafts replies for unread emails (review before sending)")
st.caption("Review, approve, and generate AI-powered email replies")

client = OpenAI()
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# ---------------- SESSION STATE ----------------
if "emails" not in st.session_state:
    st.session_state.emails = []

if "seen_ids" not in st.session_state:
    st.session_state.seen_ids = set()

if "service" not in st.session_state:
    st.session_state.service = None


# ---------------- SAFE MODE ----------------
safe_mode = st.toggle("Safe Mode (no auto-mark read / no drafts unless approved)", value=True)


# ---------------- AUTH ----------------
def get_creds():
    creds = None

    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": st.secrets["GOOGLE_CLIENT_ID"],
            "client_secret": st.secrets["GOOGLE_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"]
        }
    },
    SCOPES
)

auth_url, _ = flow.authorization_url(prompt="consent")
st.link_button("Authorize Gmail", auth_url)

code = st.text_input("Paste authorization code here")

if not code:
    st.stop()

flow.fetch_token(code=code)
creds = flow.credentials

        with open("token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return creds


# ---------------- FETCH + PROCESS EMAILS ----------------
def fetch_emails():
    creds = get_creds()
    service = build("gmail", "v1", credentials=creds)

    results = service.users().messages().list(
        userId="me",
        maxResults=5,
        q="is:unread"
    ).execute()

    messages = results.get("messages", [])

    processed = []

    for msg in messages:

        if msg["id"] in st.session_state.seen_ids:
            continue

        email_data = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="full"
        ).execute()

        headers = email_data["payload"]["headers"]

        subject = next(h["value"] for h in headers if h["name"] == "Subject")
        sender = next(h["value"] for h in headers if h["name"] == "From")
        snippet = email_data.get("snippet", "")

        email_text = f"""
From: {sender}
Subject: {subject}
Body: {snippet}
"""

        response = client.responses.create(
            model="gpt-5.2",
            input=f"""
You are an AI email assistant.

Return ONLY valid JSON:
{{
  "category": "spam | support | inquiry | other",
  "reply": "string"
}}

Email:
{email_text}
"""
        )

        try:
            result = json.loads(response.output_text)
        except:
            result = {"reply": "ERROR: invalid model output", "category": "unknown"}

        processed.append({
            "id": msg["id"],
            "subject": subject,
            "sender": sender,
            "reply": result["reply"],
            "category": result.get("category", "unknown")
        })

        st.session_state.seen_ids.add(msg["id"])

    return processed, service


# ---------------- RUN BUTTON ----------------
if st.button("Scan Inbox"):

    st.session_state.emails = []
    st.write("Scanning inbox...")

    emails, service = fetch_emails()
    st.session_state.emails = emails
    st.session_state.service = service

    st.success(f"Loaded {len(emails)} emails")


# ---------------- UI DASHBOARD ----------------
st.divider()

st.metric("Emails Loaded", len(st.session_state.emails))

if st.session_state.emails:

    for email in st.session_state.emails:

        with st.container(border=True):

            st.subheader(email["subject"])
            st.text(f"From: {email['sender']}")
            st.write(f"Category: {email['category']}")

            with st.expander("AI Reply (click to view)"):
                st.write(email["reply"] or "No reply generated")

            col1, col2 = st.columns(2)

            approve = col1.button("Approve", key=f"approve_{email['id']}")
            reject = col2.button("Reject", key=f"reject_{email['id']}")

            if approve:

                service = st.session_state.service

                message = {
                    "message": {
                        "raw": base64.urlsafe_b64encode(
                            f"To: {email['sender']}\nSubject: Re: {email['subject']}\n\n{email['reply']}".encode("utf-8")
                        ).decode("utf-8")
                    }
                }

                service.users().drafts().create(
                    userId="me",
                    body=message
                ).execute()

                if not safe_mode:
                    service.users().messages().modify(
                        userId="me",
                        id=email["id"],
                        body={"removeLabelIds": ["UNREAD"]}
                    ).execute()

                st.success("Draft created")

            if reject:
                st.info("Skipped")

else:
    st.info("Click Scan Inbox to load emails")
