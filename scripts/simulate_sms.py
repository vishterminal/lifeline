"""Pretend to be the Android SMS forwarder.

Usage:
  python scripts/simulate_sms.py <ingest-token> "TNEB: Your electricity bill of Rs.1840.00 is due on 30 Sep" [sender] [base_url]
"""
import sys

import httpx

token, text = sys.argv[1], sys.argv[2]
sender = sys.argv[3] if len(sys.argv) > 3 else "VM-TNEBLT"
base = sys.argv[4] if len(sys.argv) > 4 else "http://localhost:8000"
r = httpx.post(f"{base}/api/ingest/sms", json={"sender": sender, "text": text}, headers={"X-Ingest-Token": token})
print(r.status_code, r.text)
