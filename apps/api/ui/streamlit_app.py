import streamlit as st
import requests
import time
import streamlit.components.v1 as components
import io
import json
import base64
from datetime import datetime

# Try to import reportlab for PDF generation. If unavailable, we will fallback to text (but auto-download expects PDF).
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# ------------------------------------------------------------
# PAGE CONFIG
# ------------------------------------------------------------
st.set_page_config(page_title="CURASENSE", page_icon="⚕️", layout="wide")

# ------------------------------------------------------------
# CUSTOM CSS
# ------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

body, [class*="stAppViewContainer"] {
    background: linear-gradient(160deg, #0E1614 0%, #060A0A 100%) !important;
    color: #ECFDF5 !important;
    font-family: 'Inter', sans-serif !important;
}

h1 {
    color: #7FFFD4 !important;
    font-weight: 700;
    text-align: center;
    animation: fadeIn 1s ease-out;
}

@keyframes fadeIn {
    0% {opacity:0; transform: translateY(10px);}
    100% {opacity:1; transform: translateY(0);}
}

div[data-testid="stVerticalBlock"] {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(127,255,212,0.12);
    border-radius: 18px;
    backdrop-filter: blur(14px);
    padding: 28px;
    box-shadow: 0 4px 25px rgba(0,0,0,0.35);
}

textarea, input, select {
    background: rgba(255,255,255,0.04) !important;
    border-radius: 10px !important;
    color: #EAFBF5 !important;
    border: 1px solid rgba(127,255,212,0.13) !important;
}

div.stButton > button {
    background: linear-gradient(135deg, #7FFFD4 0%, #4FE3C1 100%);
    border: none;
    border-radius: 12px;
    font-weight: 600;
    color: #00150F;
    padding: 0.75em 1.6em;
    font-size: 1.05em;
    box-shadow: 0 0 14px rgba(127,255,212,0.25);
}
div.stButton > button:hover {
    transform: scale(1.03);
    box-shadow: 0 0 22px rgba(127,255,212,0.45);
}

.small-note { color: #BEECD8; font-size:13px; margin-top:6px; }

footer{visibility:hidden;}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# TITLE
# ------------------------------------------------------------
placeholder = st.empty()
time.sleep(0.2)
placeholder.title("⚕️ CURASENSE — AI Symptom Screener & Triage Assistant")
st.caption("Empowering Healthcare with AI-Driven Symptom Analysis and Triage Recommendations")
st.caption("Educational tool, not a diagnosis. If severely unwell, seek immediate medical attention.")
st.write("---")

# ------------------------------------------------------------
# API URL (backend)
# ------------------------------------------------------------
API_URL = "http://127.0.0.1:8000/api/v1/triage"

# ------------------------------------------------------------
# Report helpers
# ------------------------------------------------------------
def build_report_dict(data, user_name, symptoms, age, sex, chronic):
    report = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "user_name": user_name or None,
            "age_range": age,
            "sex": sex,
            "chronic_conditions": chronic,
            "symptoms_text": symptoms,
            "trace_id": data.get("trace_id")
        },
        "summary": {
            "urgency": data.get("urgency"),
            "red_flags": data.get("red_flags", []),
            "advice": data.get("advice", {})
        },
        "conditions": []
    }
    for c in data.get("conditions", []):
        cond = {
            "name": c.get("name"),
            "final_score": c.get("final_score"),
            "risk_score": c.get("risk_score"),
            "rationale": c.get("rationale"),
            "kb": c.get("kb"),
            "missing_symptoms": c.get("missing_symptoms"),
            "follow_up_question": c.get("follow_up_question"),
            "dbpedia": c.get("dbpedia")
        }
        report["conditions"].append(cond)
    return report

def make_pdf_bytes_with_emoji(report: dict) -> bytes:
    """
    Generate a PDF with an emoji '⚕️' as a header logo and a footer.
    Note: emoji rendering depends on system fonts and may show as monochrome or missing glyphs on some systems.
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab not installed")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 18 * mm
    x = margin
    y = height - margin

    # Draw a left emoji and title (attempt)
    try:
        # Large emoji (may render as fallback glyph depending on fonts)
        c.setFont("Helvetica-Bold", 28)
        c.drawString(x, y, "⚕️")
    except Exception:
        # fallback: draw a small rounded square emblem similar to before
        c.setFillColorRGB(0.29, 0.67, 0.99)
        c.roundRect(x, y - 18*mm, 18*mm, 18*mm, 4*mm, fill=1, stroke=0)

    # Title
    title_x = x + 24 * mm
    c.setFont("Helvetica-Bold", 16)
    c.setFillColorRGB(0.05, 0.3, 0.25)
    c.drawString(title_x, y - 6, "CURASENSE - Symptom Analysis Report")
    y -= 18 * mm

    # Meta
    c.setFont("Helvetica", 9)
    meta = report.get("meta", {})
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.drawString(x, y, f"Generated: {meta.get('generated_at')}")
    y -= 6 * mm
    if meta.get("user_name"):
        c.drawString(x, y, f"Name: {meta.get('user_name')}")
        y -= 5 * mm
    c.drawString(x, y, f"Age Range: {meta.get('age_range')}    Sex: {meta.get('sex')}")
    y -= 6 * mm
    c.drawString(x, y, f"Symptoms: {meta.get('symptoms_text')[:200]}")
    y -= 9 * mm

    # Summary
    summary = report.get("summary", {})
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Summary")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x, y, f"Urgency: {summary.get('urgency')}")
    y -= 5 * mm
    red_flags = summary.get("red_flags", [])
    if red_flags:
        c.drawString(x, y, "Red flags: " + ", ".join(red_flags)[:140])
        y -= 6 * mm

    y -= 4 * mm

    # Top conditions
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "Top Conditions")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for cond in report.get("conditions", []):
        if y < margin + 30:
            # footer on this page
            c.setFont("Helvetica", 8)
            c.drawCentredString(width / 2, 10 * mm, "© 2025 CURASENSE | Educational use only.")
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 9)

        c.drawString(x, y, f"- {cond.get('name')} (score: {cond.get('final_score')})")
        y -= 5 * mm
        if cond.get("rationale"):
            c.drawString(x + 6*mm, y, f"Reason: {str(cond.get('rationale'))[:140]}")
            y -= 5 * mm
        kb = cond.get("kb")
        if kb:
            c.drawString(x + 6*mm, y, f"KB urgency: {kb.get('urgency')} | severity: {kb.get('severity_score')}")
            y -= 5 * mm
        ms = cond.get("missing_symptoms") or []
        if ms:
            c.drawString(x + 6*mm, y, "Missing: " + ", ".join(ms)[:140])
            y -= 6 * mm

        y -= 2 * mm

    # final footer
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 10 * mm, "© 2025 CURASENSE | Educational use only.")
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.read()

# ------------------------------------------------------------
# INPUT UI - keep user inputs persistent across reruns
# ------------------------------------------------------------
with st.container():
    st.header("Describe your symptoms :")

    # persist UI fields
    if "ui_name" not in st.session_state:
        st.session_state.ui_name = ""
    if "ui_symptoms" not in st.session_state:
        st.session_state.ui_symptoms = ""
    if "ui_age" not in st.session_state:
        st.session_state.ui_age = "18-40"
    if "ui_sex" not in st.session_state:
        st.session_state.ui_sex = "Male"
    if "ui_chronic" not in st.session_state:
        st.session_state.ui_chronic = []

    user_name = st.text_input("Your Name ", placeholder="e.g., John Doe", value=st.session_state.ui_name)
    symptoms = st.text_area("Type your symptoms here:", placeholder="e.g., fever, headache, nausea", value=st.session_state.ui_symptoms)
    age = st.selectbox("Age Range", ["<18", "18-40", "40-60", "60+"], index=["<18", "18-40", "40-60", "60+"].index(st.session_state.ui_age) if st.session_state.ui_age in ["<18", "18-40", "40-60", "60+"] else 1)
    sex = st.radio("Gender", ["Male", "Female", "Other"], index=["Male","Female","Other"].index(st.session_state.ui_sex) if st.session_state.ui_sex in ["Male","Female","Other"] else 0, horizontal=True)
    chronic = st.multiselect("Chronic Conditions", ["Diabetes", "Hypertension", "Asthma", "None"], default=st.session_state.ui_chronic)

    # store UI inputs back into session_state
    st.session_state.ui_name = user_name
    st.session_state.ui_symptoms = symptoms
    st.session_state.ui_age = age
    st.session_state.ui_sex = sex
    st.session_state.ui_chronic = chronic

    # ANALYZE
    if st.button("Analyze My Symptoms"):
        if not symptoms.strip():
            st.warning("Please enter your symptoms before analyzing.")
            st.stop()

        with st.spinner("⚙️ Analyzing your symptoms..."):
            try:
                payload = {
                    "text": symptoms,
                    "age_range": age,
                    "sex": sex,
                    "chronic_conditions": chronic,
                    "user_name": user_name.strip() if user_name else None
                }
                response = requests.post(API_URL, json=payload, timeout=60)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                st.error(f"API error: {e}")
                st.stop()

        # store analysis persistently
        st.session_state["last_response"] = data
        st.session_state["last_inputs"] = {
            "user_name": user_name,
            "symptoms": symptoms,
            "age": age,
            "sex": sex,
            "chronic": chronic
        }
        # rerun to display results from session_state
        st.rerun()

# -------------------------
# show results if available
# -------------------------
if st.session_state.get("last_response"):
    data = st.session_state["last_response"]
    inputs = st.session_state.get("last_inputs", {})
    user_name = inputs.get("user_name")
    symptoms = inputs.get("symptoms")
    age = inputs.get("age")
    sex = inputs.get("sex")
    chronic = inputs.get("chronic", [])

    # Greeting
    if user_name:
        st.markdown(f"### 👋 Hello, **{user_name}**")
        st.write("Here is your AI - personalized symptom analysis:")
        st.write("---")

    # RED FLAG
    if data.get("urgency") == "emergency" or data.get("red_flags"):
        components.html("""
<div style="
    padding:20px;
    border-radius:12px;
    background:rgba(255,0,0,0.18);
    border:1px solid rgba(255,80,80,0.45);
    color:#ffe6e6;
    font-weight:700;
    font-size:18px;
">
🚨 <strong>RED FLAG — SEEK EMERGENCY CARE</strong><br><br>
We detected symptoms that require immediate medical attention.
</div>
""", height=150)
        st.subheader("❗ Critical Findings")
        for flag in data.get("red_flags", []):
            st.write(f"- **{flag}**")
    else:
        # severity badges etc.
        high_severity_badge = """
<span style="
    display:inline-flex;
    align-items:center;
    background: rgba(255, 0, 0, 0.22);
    padding:8px 16px;
    border-radius:50px;
    color:#FFB3B3;
    font-weight:600;
    border:2px solid rgba(255, 70, 70, 0.5);
    box-shadow: 0 0 10px rgba(255, 40, 40, 0.3),
        0 -2px 4px rgba(255, 40, 40, 0.15);
">🔴 HIGH SEVERITY</span>
"""
        moderate_severity_badge = """
<span style="
    display:inline-flex;
    align-items:center;
    background: rgba(255, 165, 0, 0.18);
    padding:8px 16px;
    border-radius:50px;
    color:#FFDCA3;
    font-weight:600;
    border:2px solid rgba(255, 180, 80, 0.5);
    box-shadow: 0 0 10px rgba(255, 40, 40, 0.3),
        0 -2px 4px rgba(255, 40, 40, 0.15);
">🟠 MODERATE SEVERITY</span>
"""
        low_severity_badge = """
<span style="
    display:inline-flex;
    align-items:center;
    background: rgba(127,255,212,0.15);
    padding:8px 16px;
    border-radius:50px;
    color:#7FFFD4;
    font-weight:600;
    border:2px solid rgba(127,255,212,0.4);
    box-shadow: 0 0 10px rgba(127,255,212,0.3),
        0 -2px 4px rgba(127,255,212,0.15);
">🟢 LOW SEVERITY</span>
"""

        st.markdown("## 🧠 AI Analysis — Possible Conditions")
        conditions = data.get("conditions", [])
        if not conditions:
            st.info("No conditions could be identified. Try adding more detail.")
        else:
            for idx, c in enumerate(conditions):
                name = c.get("name", "Unknown")
                final_score = c.get("final_score", 0)
                try:
                    pct = int(float(final_score) * 100) if final_score <= 1 else int(float(final_score))
                except Exception:
                    pct = 0

                badge = (
                    high_severity_badge if pct >= 80
                    else moderate_severity_badge if pct >= 50
                    else low_severity_badge
                )

                components.html(f"""
                <div style='margin-bottom:8px;'>
                    <h3 style="color:#7FFFD4; margin-bottom:4px;">🔹 {name}</h3>
                    {badge}
                </div>
                """, height=80)

                COMMON_BOX_STYLE = """
<div style="
    background: rgba(0, 123, 255, 0.12);
    padding: 14px 18px;
    border-left: 4px solid #4FA3FF;
    border-radius: 10px;
    margin-top: 10px;
    color: #D7EAFF;
    font-size: 15px;
">
{content}
</div>
"""
                st.write("**Confidence Level:**")
                st.progress(pct)
                st.write(f"**Final Score:** {pct}%")

                if c.get("risk_score") is not None:
                    st.write(f"**Risk Score:** {c['risk_score']}")

                kb = c.get("kb")
                if kb:
                    st.write(f"**Urgency :** {kb.get('urgency')}")
                    if c.get("kb") and c["kb"].get("common_symptoms"):
                        common_text = ", ".join(c["kb"]["common_symptoms"])
                        st.markdown(COMMON_BOX_STYLE.format(content=f"<strong>Common Symptoms:</strong> {common_text}"), unsafe_allow_html=True)

                fq = c.get("follow_up_question")
                if fq:
                    st.write("**Follow-up Question:** " + fq.get("text", ""))

                db = c.get("dbpedia")
                if db and isinstance(db, dict) and db.get("matched"):
                    st.markdown("**Condition Info (DBpedia):**")
                    abstract = db.get("abstract", "")
                    if abstract:
                        st.write(abstract[:500] + ("..." if len(abstract) > 500 else ""))

                st.markdown("---")

        # urgency badge
        urgency = (data.get("urgency") or "routine").upper()
        if urgency == "EMERGENCY":
            color, bg, icon = "#ff8080", "rgba(255,0,0,0.25)", "🚨"
        elif urgency == "URGENT":
            color, bg, icon = "#ffcc80", "rgba(255,165,0,0.15)", "⚠️"
        else:
            color, bg, icon = "#7FFFD4", "rgba(127,255,212,0.12)", "🩺"

        components.html(f"""
        <div style="
            margin-top:20px;
            padding:14px;
            border-radius:10px;
            background:{bg};
            border-left:6px solid {color};
            color:{color};
            font-weight:600;
            font-size:17px;
        ">
        {icon} URGENCY LEVEL: {urgency}
        </div>
        """, height=80)

        # advice
        st.markdown("## 📌 Medical Advice")
        advice = data.get("advice", {})
        st.subheader("🩺 Self-care Suggestions")
        for tip in advice.get("selfcare", []):
            st.write(f"- {tip}")
        st.subheader("⚠️ When to Seek Help")
        for tip in advice.get("escalate_when", []):
            st.write(f"- {tip}")

    # ---------------------- Prepare Report -> auto-download PDF ----------------------
    st.markdown("### 📥 Download Report")
    st.write("Click **Prepare Report** to build a printable report (it will download automatically).", unsafe_allow_html=True)
    if st.button("Prepare Report", key="auto_prepare"):
        # require reportlab
        if not REPORTLAB_AVAILABLE:
            st.error("PDF generation requires the 'reportlab' package. Please install: pip install reportlab")
        else:
            try:
                report = build_report_dict(data, user_name, symptoms, age, sex, chronic)
                pdf_bytes = make_pdf_bytes_with_emoji(report)
                trace = report["meta"].get("trace_id") or datetime.utcnow().strftime("%Y%m%d%H%M%S")
                fname = f"curasense_report_{trace}.pdf"

                # create base64
                b64 = base64.b64encode(pdf_bytes).decode()
                # HTML to trigger automatic download of the PDF data url
                html = f"""
                <html>
                <body>
                <a id="dl" href="data:application/pdf;base64,{b64}" download="{fname}"></a>
                <script>
                // auto click the anchor to start download
                document.getElementById('dl').click();
                // optionally close the iframe or show a tiny message
                </script>
                </body>
                </html>
                """
                # embed the HTML to trigger download
                components.html(html, height=0)
                st.success("Report prepared and (should be) downloading. If nothing happens, browser may block automatic downloads — check popup settings.")
            except Exception as e:
                st.error(f"Failed to prepare/download report: {e}")

# ------------------------------------------------------------
# FOOTER
# ------------------------------------------------------------
st.write("---")
st.write("<p style='text-align:center;color:#A6FFCE;'>© 2025 <b>CURASENSE</b> | Educational use only.</p>", unsafe_allow_html=True)
