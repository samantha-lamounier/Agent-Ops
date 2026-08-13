import os
import re
import json
import streamlit as st
from anthropic import Anthropic

st.set_page_config(page_title="NordLog Ops Copilot", page_icon="🚚", layout="wide")

# ---------- Design tokens (clean chat-app look, inspired by familiar LLM UIs) ----------
BG = "#FAF9F5"
SURFACE = "#FFFFFF"
BORDER = "#E8E4DB"
USER_BUBBLE = "#F0EEE6"
TEXT = "#262521"
MUTED = "#8A867C"
ACCENT = "#CC785C"      # terracotta — used for send button + "doc search" tag
ACCENT_2 = "#5B7B8C"    # muted slate blue — "db query" tag

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

.stApp {{
    background-color: {BG};
    color: {TEXT};
    font-family: 'Inter', sans-serif;
}}
.mono {{ font-family: 'IBM Plex Mono', monospace; }}
#MainMenu, footer {{ visibility: hidden; }}

/* ---- header ---- */
.brand-title {{ font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
.brand-sub {{ font-size: 12px; color: {MUTED}; letter-spacing: 0.5px; text-transform: uppercase; margin-top: 2px; }}
.brand-tag {{ font-size: 12px; color: {MUTED}; text-align: right; line-height: 1.5; }}

/* ---- chat messages, no boxy bubbles for the agent ---- */
.chat-row {{ display: flex; margin-bottom: 22px; }}
.chat-row.user {{ justify-content: flex-end; }}
.chat-row.agent {{ justify-content: flex-start; align-items: flex-start; gap: 10px; }}
.avatar {{
    width: 26px; height: 26px; border-radius: 50%;
    background: {ACCENT}; flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px;
}}
.bubble-user {{
    background: {USER_BUBBLE}; border-radius: 18px; padding: 10px 16px;
    max-width: 70%; font-size: 15px; line-height: 1.55; color: {TEXT};
}}
.agent-text {{ max-width: 78%; font-size: 15px; line-height: 1.6; padding-top: 3px; color: {TEXT}; }}

/* ---- suggestion "chips" as plain text, not boxes ---- */
div[data-testid="stHorizontalBlock"] .stButton > button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: {MUTED} !important;
    font-size: 13px !important;
    text-align: left !important;
    padding: 4px 0 !important;
    white-space: normal !important;
    height: auto !important;
}}
div[data-testid="stHorizontalBlock"] .stButton > button:hover {{
    color: {ACCENT} !important;
    text-decoration: underline;
}}

/* ---- input pill ---- */
div[data-testid="stForm"] {{
    border: 1px solid {BORDER} !important;
    border-radius: 26px !important;
    padding: 6px 6px 6px 20px !important;
    background: {SURFACE} !important;
}}
div[data-testid="stForm"] input {{
    border: none !important;
    background: transparent !important;
    font-size: 15px !important;
    box-shadow: none !important;
}}
div[data-testid="stForm"] .stButton > button {{
    background: {ACCENT} !important;
    color: #fff !important;
    border-radius: 50% !important;
    width: 38px !important; height: 38px !important;
    padding: 0 !important;
    font-size: 16px !important;
    box-shadow: none !important;
}}
div[data-testid="stForm"] .stButton > button:hover {{ opacity: 0.9; }}

/* ---- trace panel ---- */
.trace-card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 14px;
}}
.badge {{ font-size: 10px; letter-spacing: 1px; font-weight: 600; text-transform: uppercase; }}
.record {{
    background: #F5F3EC;
    border-radius: 8px;
    padding: 8px 10px;
    margin-bottom: 6px;
    font-size: 12px;
    line-height: 1.5;
}}
[data-testid="stSidebar"] {{ background-color: {SURFACE}; border-right: 1px solid {BORDER}; }}
</style>
""", unsafe_allow_html=True)

# ---------- Mock data ----------
ORDERS = [
    {"id": "NL-48213", "customer": "Retail Co", "status": "Delayed", "carrier": "BlueFreight", "eta": "2026-08-14", "delay_reason": "Customs hold at Rotterdam — hazmat documentation pending", "region": "EU"},
    {"id": "NL-48214", "customer": "Solaris Manufacturing", "status": "In Transit", "carrier": "Continental Rail", "eta": "2026-08-13", "delay_reason": None, "region": "EU"},
    {"id": "NL-51002", "customer": "Meridian Foods", "status": "Delivered", "carrier": "BlueFreight", "eta": "2026-08-09 (delivered)", "delay_reason": None, "region": "US"},
    {"id": "NL-51090", "customer": "Atlas Hardware", "status": "Exception", "carrier": "Continental Rail", "eta": "Pending investigation", "delay_reason": "Damaged pallet reported on arrival at DC3", "region": "US"},
    {"id": "NL-52210", "customer": "Kestrel Apparel", "status": "Delayed", "carrier": "Pacific Cargo", "eta": "2026-08-16", "delay_reason": "Port congestion — Singapore", "region": "APAC"},
    {"id": "NL-52255", "customer": "Union Chem Supply", "status": "In Transit", "carrier": "Pacific Cargo", "eta": "2026-08-15", "delay_reason": None, "region": "APAC (hazmat load)"},
    {"id": "NL-53310", "customer": "Retail Co", "status": "Delivered", "carrier": "BlueFreight", "eta": "2026-08-07 (delivered)", "delay_reason": None, "region": "EU"},
    {"id": "NL-53401", "customer": "Meridian Foods", "status": "Exception", "carrier": "BlueFreight", "eta": "Pending investigation", "delay_reason": "Customer requested return — item mismatch", "region": "US"},
]

DOCS = [
    {"id": "delivery_sla", "title": "Delivery SLA Policy", "body": "Standard ground shipments carry a 3-business-day delivery SLA from dispatch; expedited lanes carry a 24-hour SLA. Missed SLAs on standard lanes trigger an automatic 10% shipping credit to the customer account."},
    {"id": "damaged_goods_claim", "title": "Damaged Goods Claims", "body": "Damaged goods claims must be filed within 5 business days of delivery with photo evidence. Approved claims are reimbursed at full invoice value within 10 business days; partial damage claims are prorated by affected unit count."},
    {"id": "return_policy", "title": "Returns Policy", "body": "Customers may return unopened cases within 30 days of delivery for full credit. Opened or partial cases are accepted only if the mismatch originated on NordLog's fulfillment side, verified against the original pick manifest."},
    {"id": "hazmat_handling", "title": "Hazmat Handling", "body": "Hazmat and dangerous-goods shipments require completed UN classification paperwork before release from any customs checkpoint. Missing or incomplete hazmat documentation is the single most common cause of customs holds on EU and APAC lanes."},
    {"id": "customs_clearance_policy", "title": "Customs Clearance Escalation", "body": "Customs clearance delays of more than 48 hours automatically escalate to the Trade Compliance team, who coordinate directly with the broker. Customers are notified proactively once a shipment crosses the 48-hour threshold."},
    {"id": "refund_timeline", "title": "Refund Timeline", "body": "Approved refunds are issued to the original payment method within 7 business days of claim approval. Refunds tied to fulfillment errors are expedited to 3 business days."},
]

SUGGESTIONS = [
    "Where's order NL-52210 and why is it delayed?",
    "What's our damaged goods claim policy?",
    "NL-48213 is stuck at customs — walk me through why and what we tell the customer.",
]

SYSTEM_PROMPT = """You are the routing brain behind NordLog's internal Ops Copilot. You receive a support question plus NordLog's full order database and policy document library as JSON. Decide whether answering the question requires the ORDER DATABASE (structured facts: status, ETA, carrier, region, delay reason), the POLICY DOCS (policy language), or BOTH. Then answer using ONLY the provided data.
Respond with strict JSON only — no markdown fences, no prose outside the JSON — matching exactly this shape:
{"route": "database" | "semantic" | "both", "matched_order_ids": string[], "matched_doc_ids": string[], "answer": string}
The answer must be 2-4 sentences, written like a sharp ops teammate, citing concrete details (order id, status, eta, or exact policy terms) pulled only from matched records. If nothing in the data matches, say so plainly instead of guessing."""


def ask_copilot(question: str, client: Anthropic) -> dict:
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps({"question": question, "orders": ORDERS, "docs": DOCS})}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    clean = re.sub(r"```json|```", "", text).strip()
    return json.loads(clean)


# ---------- Session state ----------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "agent", "text": "NordLog Ops Copilot online. Ask me about an order or a policy — I'll pull whichever source has the answer."}
    ]
if "trace" not in st.session_state:
    st.session_state.trace = []

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("### Configuração")
    api_key = st.text_input("Anthropic API Key", type="password", value=os.environ.get("ANTHROPIC_API_KEY", ""))
    st.caption("A chave fica só na sessão local — não é salva.")

# ---------- Header ----------
col_logo, col_tag = st.columns([3, 2])
with col_logo:
    st.markdown("<div class='brand-title'>NordLog</div>", unsafe_allow_html=True)
    st.markdown("<div class='brand-sub'>Ops Copilot — Internal</div>", unsafe_allow_html=True)
with col_tag:
    st.markdown("<div class='brand-tag'>one question, two sources<br/>database + policy library</div>", unsafe_allow_html=True)
st.write("")

chat_col, trace_col = st.columns([1.3, 1])

# ---------- Chat column ----------
with chat_col:
    for m in st.session_state.messages:
        if m["role"] == "user":
            st.markdown(f"<div class='chat-row user'><div class='bubble-user'>{m['text']}</div></div>", unsafe_allow_html=True)
        else:
            st.markdown(
                f"<div class='chat-row agent'><div class='avatar'>🚚</div><div class='agent-text'>{m['text']}</div></div>",
                unsafe_allow_html=True,
            )

    st.write("")
    sugg_cols = st.columns(len(SUGGESTIONS))
    clicked = None
    for i, s in enumerate(SUGGESTIONS):
        if sugg_cols[i].button(s, key=f"sugg_{i}"):
            clicked = s

    with st.form("ask_form", clear_on_submit=True):
        c1, c2 = st.columns([10, 1])
        with c1:
            typed = st.text_input("pergunta", label_visibility="collapsed", placeholder="Pergunte sobre um pedido ou uma política…")
        with c2:
            submitted = st.form_submit_button("↑")

    question = clicked or (typed if submitted and typed else None)

    if question:
        if not api_key:
            st.error("Adicione sua Anthropic API key na barra lateral.")
        else:
            st.session_state.messages.append({"role": "user", "text": question})
            client = Anthropic(api_key=api_key)
            with st.spinner("roteando pergunta…"):
                try:
                    result = ask_copilot(question, client)
                    st.session_state.messages.append({"role": "agent", "text": result["answer"]})
                    matched_orders = [o for o in ORDERS if o["id"] in result.get("matched_order_ids", [])]
                    matched_docs = [d for d in DOCS if d["id"] in result.get("matched_doc_ids", [])]
                    st.session_state.trace.insert(0, {
                        "question": question,
                        "route": result.get("route", "unknown"),
                        "orders": matched_orders,
                        "docs": matched_docs,
                    })
                except Exception:
                    st.session_state.messages.append({"role": "agent", "text": "Erro ao consultar — tente reformular a pergunta."})
            st.rerun()

# ---------- Trace column ----------
with trace_col:
    st.markdown("<div style='font-weight:700;font-size:15px;margin-bottom:2px;'>Dispatch trace</div>", unsafe_allow_html=True)
    st.markdown(f"<div style='font-size:12px;color:{MUTED};margin-bottom:16px;'>how the copilot answered each question</div>", unsafe_allow_html=True)

    if not st.session_state.trace:
        st.markdown(
            f"<div style='font-size:13px;color:{MUTED};border:1px dashed {BORDER};border-radius:12px;padding:16px;'>"
            "Ask a question to see the routing decision traced here.</div>",
            unsafe_allow_html=True,
        )

    for t in st.session_state.trace:
        route = t["route"]
        if route == "database":
            badge_color, badge_label = ACCENT_2, "Database query"
        elif route == "semantic":
            badge_color, badge_label = ACCENT, "Policy search"
        else:
            badge_color, badge_label = TEXT, "Database + policy search"

        html = f"<div class='trace-card'><div class='badge' style='color:{badge_color};'>{badge_label}</div>"
        html += f"<div style='font-size:13px;color:{MUTED};margin:8px 0;'>{t['question']}</div>"
        for o in t["orders"]:
            html += f"<div class='record'><div style='color:{ACCENT_2};font-weight:600;'>{o['id']} — {o['customer']}</div>"
            html += f"<div style='color:{MUTED};margin-top:2px;'>{o['status']} · {o['carrier']} · ETA {o['eta']}</div>"
            if o.get("delay_reason"):
                html += f"<div style='color:{MUTED};margin-top:2px;'>{o['delay_reason']}</div>"
            html += "</div>"
        for d in t["docs"]:
            html += f"<div class='record'><div style='color:{ACCENT};font-weight:600;'>{d['title']}</div>"
            html += f"<div style='color:{MUTED};margin-top:2px;'>{d['body']}</div></div>"
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)
