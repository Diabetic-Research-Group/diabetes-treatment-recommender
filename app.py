# app.py
import streamlit as st
from engine import get_engine, map_nhanes_row
import pandas as pd

st.set_page_config(page_title="T2DM Treatment Expert System", layout="centered")
st.title("Explainable Expert System — Type 2 Diabetes Treatment")

st.markdown("Enter patient data (optional fields can be left blank). Click **Get Recommendation** to view the suggested treatment. Click **Show Explanation** to reveal guideline-based reasoning and guideline text.")

# Small helper to transform empty strings to None
def maybe_none(val):
    if val is None:
        return None
    if isinstance(val, str) and val.strip() == "":
        return None
    return val

with st.form("patient_form"):
    col1, col2 = st.columns(2)
    with col1:
        age = st.number_input("Age (years)", min_value=0, max_value=120, value=60)
        bmi = st.number_input("BMI (kg/m^2) (optional)", min_value=0.0, max_value=100.0, value=28.0, step=0.1)
        have_diabetes = st.checkbox("Patient has diagnosed Type 2 Diabetes", value=True)
        hbA1c = st.text_input("HbA1c (%) (optional)", value="7.5")
        fasting_glu = st.text_input("Fasting glucose (mg/dL) (optional)", value="")
        ogtt = st.text_input("2-hr OGTT (mg/dL) (optional)", value="")
    with col2:
        egfr = st.text_input("eGFR (ml/min/1.73m^2) (optional)", value="")
        albumin = st.text_input("Urine albumin (mg/L) (optional)", value="")
        creat = st.text_input("Serum creatinine (mg/dL) (optional)", value="")
        ldl = st.text_input("LDL (mg/dL) (optional)", value="")
    st.write("Comorbidities / meds (check boxes or enter text):")
    col3, col4 = st.columns(2)
    with col3:
        hf = st.checkbox("History of heart failure (HF)")
        chd = st.checkbox("Coronary heart disease (CHD)")
        mi = st.checkbox("History of myocardial infarction (MI)")
        stroke = st.checkbox("History of stroke")
    with col4:
        liver = st.checkbox("History of liver condition (MASLD/MASH)")
        on_insulin = st.checkbox("Currently on insulin")
        on_pills = st.checkbox("Taking diabetic pills")
        rxddrug = st.text_input("Current medications (comma-separated, e.g., metformin, liraglutide)", value="")
    cost_barrier = st.checkbox("Cost / access barrier (if yes, system will consider lower-cost options)")
    # Optional flags clinicians may want to enter
    catabolic = st.checkbox("Evidence of catabolism (weight loss, ketosis, hypertriglyceridemia)")
    frequent_hypo = st.checkbox("Frequent hypoglycemia (flag)")

    submitted = st.form_submit_button("Get Recommendation")

# Map inputs to engine keys, allow empty -> None
def build_patient_dict():
    patient = {
        "age": age,
        "bmi": maybe_none(bmi),
        "lbxgh": maybe_none(hbA1c) if hbA1c != "" else None,
        "lbxglu": maybe_none(fasting_glu) if fasting_glu != "" else None,
        "lbxglt": maybe_none(ogtt) if ogtt != "" else None,
        "vnegfr": maybe_none(egfr) if egfr != "" else None,
        "urxums": maybe_none(albumin) if albumin != "" else None,
        "lbxscr": maybe_none(creat) if creat != "" else None,
        "lbdldl": maybe_none(ldl) if ldl != "" else None,
        "mcq160b": 1 if hf else 0,
        "mcq160c": 1 if chd else 0,
        "mcq160e": 1 if mi else 0,
        "mcq160f": 1 if stroke else 0,
        "mcq160l": 1 if liver else 0,
        "diq010": 1 if have_diabetes else 0,
        "diq050": 1 if on_insulin else 0,
        "diq070": 1 if on_pills else 0,
        "rxddrug": rxddrug.lower(),
        "cost_barrier": 1 if cost_barrier else 0,
        "catabolic_signs": True if catabolic else False,
        "frequent_hypoglycemia": 1 if frequent_hypo else 0
    }
    return patient

if submitted:
    patient = build_patient_dict()
    engine = get_engine()
    recs, expl = engine.evaluate(patient)

    st.subheader("Treatment Recommendation")
    if len(recs) == 0:
        st.info(
            "No rule fired. Please check inputs. "
            "(If patient does have T2D, ensure 'Doctor told you have diabetes' is set in the dataset mapping or engine input.)"
        )
    else:
        for i, r in enumerate(recs, 1):
            st.markdown(f"**{i}. {r}**")

        # Use an expander to show explanations (recommended for Streamlit)
        with st.expander("Show Explanation and Guideline Text"):
            st.subheader("Explanation Based on Fired Rules")
            for e in expl:
                if e["id"] != "R_FALLBACK":
                    st.markdown(f"### Rule: {e['id']}")
                    st.write(f"**Reason (short):** {e['description']}")
                    st.write(f"**Recommendation:** {e['recommendation']}")

                    if e.get("dosage") and e["dosage"].strip() != "":
                        st.write(f"**Recommended dosage:** {e['dosage']}")

                    if e.get("dosage_reason") and e["dosage_reason"].strip() != "":
                        st.info(f"**Why this dosage?** {e['dosage_reason']}")
                    
                    st.write(f"**Guideline reference:** {e['guideline_ref']}")
                    if e.get("guideline_text"):
                        st.info(e["guideline_text"])
                    st.markdown("---")

