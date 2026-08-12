import os
import re
import json
import streamlit as st
from anthropic import Anthropic

st.set_page_config(page_title="NordLog Ops Copilot", page_icon="🚚", layout="wide")

# ---------- Design tokens ----------
BG = "#141A22"
PANEL = "#1C2430"
PANEL_RAISED = "#232D3A"
AMBER = "#F2A93B"
TEAL = "#45C4B0"
TEXT = "#EDEFF2"
MUTED = "#8D97A3"
HAIRLINE = "#2E3949"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

.stApp {{
    background-color: {BG};
    color: {TEXT};
    font-family: 'Inter', sans-serif;
}}
.display {{
    font-family: 'Barlow Condensed', sans-serif !important;
    letter-spacing: 0.5px;
}}
.mono {{ font-family: 'IBM Plex Mono', monospace; }}

.stub {{
    position: relative;
    border-left: 2px dashed {HAIRLINE};
    padding: 14px 14px 14px 20px;
    background: {PANEL};
    border-radius: 0 8px 8px 0;
    margin-bottom: 14px;
}}
.stub::before {{
    content: '';
    position: absolute;
    left: -6px;
    top: -6px;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: {BG};
    border: 2px dashed {HAIRLINE};
}}
.badge {{ font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
.record {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    background: {PANEL_RAISED};
    border-radius: 6px;
    padding: 8px 10px;
    margin-bottom: 6px;
}}
[data-testid="stChatMessage"] {{ background: transparent; }}
[data-testid="stSidebar"] {{ background-color: {PANEL}; }}
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
    st.markdown("<div class='display' style='font-size:28px;font-weight:700;'>NORDLOG</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='mono' style='font-size:11px;color:{MUTED};'>OPS COPILOT — INTERNAL</div>", unsafe_allow_html=True)
with col_tag:
    st.markdown(f"<div class='mono' style='font-size:11px;color:{MUTED};text-align:right;'>one question, two sources<br/>database + policy library</div>", unsafe_allow_html=True)
st.divider()

chat_col, trace_col = st.columns([1.3, 1])

# ---------- Chat column ----------
with chat_col:
    for m in st.session_state.messages:
        with st.chat_message("assistant" if m["role"] == "agent" else "user"):
            st.write(m["text"])

    st.write("")
    st.caption("Sugestões:")
    sugg_cols = st.columns(len(SUGGESTIONS))
    clicked = None
    for i, s in enumerate(SUGGESTIONS):
        if sugg_cols[i].button(s, key=f"sugg_{i}", use_container_width=True):
            clicked = s

    with st.form("ask_form", clear_on_submit=True):
        typed = st.text_input("Pergunte sobre um pedido ou uma política…", label_visibility="collapsed", placeholder="Pergunte sobre um pedido ou uma política…")
        submitted = st.form_submit_button("Enviar")

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
    st.markdown("<div class='display' style='font-size:16px;font-weight:600;'>DISPATCH TRACE</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='mono' style='font-size:11px;color:{MUTED};margin-bottom:16px;'>how the copilot answered each question</div>", unsafe_allow_html=True)

    if not st.session_state.trace:
        st.markdown(
            f"<div class='mono' style='font-size:12px;color:{MUTED};border:1px dashed {HAIRLINE};border-radius:8px;padding:16px;'>"
            "Ask a question to see the routing decision traced here.</div>",
            unsafe_allow_html=True,
        )

    for t in st.session_state.trace:
        route = t["route"]
        if route == "database":
            badge_color, badge_label = TEAL, "DB QUERY"
        elif route == "semantic":
            badge_color, badge_label = AMBER, "DOC SEARCH"
        else:
            badge_color, badge_label = TEXT, "DB + DOC SEARCH"

        html = f"<div class='stub'><div class='badge' style='color:{badge_color};'>{badge_label}</div>"
        html += f"<div style='font-size:13px;color:{MUTED};margin:8px 0;'>{t['question']}</div>"
        for o in t["orders"]:
            html += f"<div class='record'><div style='color:{TEAL};font-weight:600;'>{o['id']} — {o['customer']}</div>"
            html += f"<div style='color:{MUTED};margin-top:2px;'>{o['status']} · {o['carrier']} · ETA {o['eta']}</div>"
            if o.get("delay_reason"):
                html += f"<div style='color:{MUTED};margin-top:2px;'>{o['delay_reason']}</div>"
            html += "</div>"
        for d in t["docs"]:
            html += f"<div class='record'><div style='color:{AMBER};font-weight:600;'>{d['title']}</div>"
            html += f"<div style='color:{MUTED};margin-top:2px;'>{d['body']}</div></div>"
        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)
