# engine.py
"""
Expert rule engine for T2DM treatment recommendations with dosage guidance.
- Rules are based on ADA 2025 pharmacologic strategy (user-provided).
- Each Rule includes dosage and dosage_reason fields and optional guideline_text.
- Safe handling of missing inputs (None).
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, Any, List, Tuple, Optional

def safe_num(x: Any) -> Optional[float]:
    """Convert input to float if possible; return None for empty/invalid."""
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None

def truthy_flag(x: Any) -> bool:
    """Interpret many possible truthy values returned by NHANES or UI."""
    return x in (1, True, "1", "yes", "Yes", "YES", "Y", "y", "true", "True")

@dataclass
class Rule:
    id: str
    description: str
    condition: Callable[[Dict[str, Any]], bool]  # function(patient) -> bool
    recommendation: str
    dosage: str = ""          # human-readable dosage guidance
    dosage_reason: str = ""   # why this dosage / titration is recommended
    priority: int = 100       # lower numbers = higher priority
    guideline_ref: str = ""
    guideline_text: str = ""

    def applies(self, patient: Dict[str, Any]) -> bool:
        try:
            return bool(self.condition(patient))
        except Exception:
            return False

@dataclass
class ExpertEngine:
    rules: List[Rule] = field(default_factory=list)

    def evaluate(self, patient):
        fired_rules = []

        # First evaluate all normal rules EXCEPT fallback
        for r in self.rules:
            if r.id != "R_FALLBACK" and r.applies(patient):
                fired_rules.append(r)

        # If nothing fired → use fallback rule
        if len(fired_rules) == 0:
            fallback = next((r for r in self.rules if r.id == "R_FALLBACK"), None)
            if fallback:
                fired_rules.append(fallback)

        # Sort by priority
        fired_rules.sort(key=lambda r: r.priority)

        # Convert to dict for UI
        recs = [r.recommendation for r in fired_rules]
        expl = [r.__dict__ for r in fired_rules]

        return recs, expl

# ---------- Rule definitions based on provided ADA guidance ----------
def make_ada_rules() -> List[Rule]:
    rules: List[Rule] = []

    # Helper lambdas for readability
    get_a1c = lambda p: safe_num(p.get("lbxgh"))
    get_glucose = lambda p: safe_num(p.get("lbxsgl") or p.get("lbxglu") or p.get("lbxglt"))
    get_eGFR = lambda p: safe_num(p.get("vnegfr"))
    get_albumin = lambda p: safe_num(p.get("urxums") or p.get("urxuma"))
    get_bmi = lambda p: safe_num(p.get("bmi"))
    on_metformin = lambda p: "metformin" in (str(p.get("rxddrug") or "").lower())
    on_insulin = lambda p: truthy_flag(p.get("diq050"))
    have_diabetes = lambda p: truthy_flag(p.get("diq010"))

    # ----- Insulin initiation for severe hyperglycemia (highest priority) -----
    rules.append(Rule(
        id="R_INSULIN_SEVERE",
        description="Severe hyperglycemia or catabolism -> suggest initiating insulin.",
        condition=lambda p: (
            have_diabetes(p) and (
                (get_a1c(p) is not None and get_a1c(p) > 10.0) or
                (get_glucose(p) is not None and get_glucose(p) >= 300.0) or
                (p.get("catabolic_signs") is True)
            )
        ),
        recommendation="Initiate insulin therapy (basal-first strategy).",
        dosage="Start basal insulin 10 units once daily or 0.1–0.2 units/kg/day; titrate every 3 days by 10% or 2–4 units until fasting glucose target reached.",
        dosage_reason="Start low to reduce hypoglycemia risk; weight-based initial dose provides reasonable starting point; titrate frequently until morning targets are achieved.",
        priority=1,
        guideline_ref="ADA 5.1, 9.23",
        guideline_text="Initiate insulin when A1C >10% or plasma glucose ≥300 mg/dL, or clinical features of catabolism. Titrate per fasting glucose targets and patient safety."
    ))

    # ----- Metformin safety / contraindication rules (high priority for renal) -----
    rules.append(Rule(
        id="R_METFORMIN_CONTRA",
        description="Metformin contraindication or caution based on eGFR thresholds.",
        condition=lambda p: have_diabetes(p) and (get_eGFR(p) is not None and get_eGFR(p) < 30.0),
        recommendation="Avoid initiating metformin; stop metformin if eGFR <30.",
        dosage="Do not start; if current user has eGFR <30 stop metformin. If eGFR 30–45 consider dose reduction (e.g., 500–1000 mg/day) and monitoring.",
        dosage_reason="Reduced renal clearance increases risk of lactic acidosis; dose adjustments or discontinuation per renal function.",
        priority=2,
        guideline_ref="ADA metformin & CKD",
        guideline_text="Avoid initiating metformin if eGFR <45 mL/min/1.73 m2 and stop if <30; adjust dosing and monitor renal function."
    ))

    # ----- Advanced CKD prefer GLP-1 RA (when SGLT2 glycemic effect reduced) -----
    rules.append(Rule(
        id="R_CKD_ADVANCED",
        description="Advanced CKD (eGFR <30) -> prefer GLP-1 RA for glycemic/weight benefit.",
        condition=lambda p: have_diabetes(p) and (get_eGFR(p) is not None and get_eGFR(p) < 30.0),
        recommendation="Prefer GLP-1 receptor agonist (e.g., semaglutide) when glycemic therapy needed; avoid relying on SGLT2i for glycemic lowering.",
        dosage="Semaglutide: start 0.25 mg weekly → increase to 0.5 mg weekly after 4 weeks → target 1.0 mg weekly (label-specific titration). Check product label for renal dosing adjustments as required.",
        dosage_reason="GLP-1 RAs retain efficacy for glycemia/weight in low eGFR and have lower hypoglycemia risk vs insulin/SU; titration reduces GI side effects.",
        priority=2,
        guideline_ref="ADA 9.14",
        guideline_text="In advanced CKD (eGFR <30), GLP-1 RAs are preferred for glycemic management due to lower hypoglycemia risk and cardiovascular/renal benefits."
    ))

    # ----- CKD with albuminuria or moderate eGFR decline: prefer SGLT2i (if eGFR allows) or GLP-1 -----
    rules.append(Rule(
        id="R_CKD_ALBUMINURIA",
        description="CKD with albuminuria or moderate eGFR decline -> SGLT2i or GLP-1 RA with kidney benefit.",
        condition=lambda p: have_diabetes(p) and (
            (get_eGFR(p) is not None and 20.0 <= get_eGFR(p) <= 60.0) or
            (get_albumin(p) is not None and get_albumin(p) > 30.0)
        ),
        recommendation="Use SGLT2 inhibitor if eGFR adequate; consider GLP-1 RA if SGLT2i not suitable or additional weight benefit is desired.",
        dosage="Empagliflozin 10 mg daily or Dapagliflozin 10 mg daily (follow label for minimum eGFR cutoffs and continuation criteria).",
        dosage_reason="SGLT2 inhibitors at standard doses reduce CKD progression and heart failure events when eGFR is within label-allowed range; use GLP-1 RA when SGLT2i not tolerated or for weight benefit.",
        priority=3,
        guideline_ref="ADA 9.13",
        guideline_text="In T2D with CKD (eGFR 20–60 and/or albuminuria), SGLT2 inhibitors or GLP-1 RAs with proven kidney benefit are recommended."
    ))

    # ----- Heart failure -> SGLT2i recommended -----
    rules.append(Rule(
        id="R_HF_SGLT2",
        description="Heart failure (HFrEF or HFpEF) -> recommend SGLT2 inhibitor for HF prevention/management.",
        condition=lambda p: have_diabetes(p) and truthy_flag(p.get("mcq160b")),
        recommendation="Recommend SGLT2 inhibitor (empagliflozin, dapagliflozin) for HF benefit, if eGFR allows.",
        dosage="Empagliflozin 10 mg daily or Dapagliflozin 10 mg daily; adjust/withhold if below label eGFR threshold per product monograph.",
        dosage_reason="Standard daily dosing provides cardiovascular and renal protection shown in trials; adjust for renal function and follow label.",
        priority=4,
        guideline_ref="ADA 9.11",
        guideline_text="For people with T2D and heart failure, SGLT2 inhibitors are recommended for glycemic management and to reduce HF hospitalizations."
    ))

    # ----- ASCVD -> GLP-1 RA and/or SGLT2i for CV risk reduction -----
    rules.append(Rule(
        id="R_ASCVD_CV",
        description="Established ASCVD or high ASCVD risk -> include GLP-1 RA and/or SGLT2i for CV risk reduction.",
        condition=lambda p: have_diabetes(p) and any(truthy_flag(p.get(k)) for k in ("mcq160c","mcq160e","mcq160f")),
        recommendation="Prioritize GLP-1 receptor agonist and/or SGLT2 inhibitor for CV risk reduction (irrespective of baseline A1C).",
        dosage="GLP-1 RA example: liraglutide start 0.6 mg daily → titrate to 1.2–1.8 mg daily per label. SGLT2i example: empagliflozin 10 mg daily.",
        dosage_reason="Drug classes demonstrated CV event reduction in trials at standard therapeutic doses; follow label titration to reduce side effects.",
        priority=5,
        guideline_ref="ADA 9.10",
        guideline_text="In adults with T2D and established ASCVD or high ASCVD risk, use GLP-1 RAs and/or SGLT2 inhibitors with proven CV benefit."
    ))

    # ----- Obesity target -> prioritize GLP-1 / tirzepatide ----- 
    rules.append(Rule(
        id="R_OBESITY_WEIGHT",
        description="Obesity as a treatment target -> prioritize high-efficacy weight-loss agents with glucose benefit.",
        condition=lambda p: have_diabetes(p) and (get_bmi(p) is not None and get_bmi(p) >= 30.0),
        recommendation="Consider GLP-1 RA (semaglutide, liraglutide) or tirzepatide for combined glycemic and weight benefits.",
        dosage="Semaglutide (Wegovy/Rybelsus vs Ozempic labeling differ): common GLP-1 RA dose for glycemic control: start 0.25 mg weekly → escalate to 0.5 mg then 1.0 mg weekly (per product). Tirzepatide: follow product titration schedule (e.g., start 2.5 mg weekly → escalate).",
        dosage_reason="Gradual escalation improves GI tolerability and achieves weight loss; follow product-specific titration schedules.",
        priority=6,
        guideline_ref="ADA 9.15 / 3.5",
        guideline_text="For people with T2D and obesity, prioritize agents with proven weight-loss and glycemic efficacy (tirzepatide, semaglutide)."
    ))

    # ----- On metformin and above target -> add-on guided by comorbidity ----- 
    rules.append(Rule(
        id="R_ADD_ON_METFORMIN",
        description="On metformin with inadequate control -> consider add-on based on comorbidities and goals.",
        condition=lambda p: have_diabetes(p) and on_metformin(p) and (get_a1c(p) is not None and get_a1c(p) >= 7.0),
        recommendation="Add a second-line agent guided by comorbidities: GLP-1 RA if weight/CV; SGLT2i if CKD/HF; else consider DPP-4, TZD, SU, or insulin as appropriate.",
        dosage="Choose agent-specific standard starting dose and titration (examples: empagliflozin 10 mg daily; semaglutide start 0.25 mg weekly; pioglitazone 15–30 mg daily).",
        dosage_reason="Add therapy using agents with organ benefit where indicated; start low and titrate per label and patient renal/hepatic status.",
        priority=7,
        guideline_ref="ADA 9.9/9.24",
        guideline_text="When metformin alone is insufficient, add therapy based on comorbidities and individual goals; GLP-1 RAs and SGLT2i provide organ protection where indicated."
    ))

    # ----- Insulin-treated and suboptimal control -> consider GLP-1 RA add-on ----- 
    rules.append(Rule(
        id="R_INSULIN_ADDON_GLP1",
        description="Insulin-treated patients with suboptimal control -> consider adding GLP-1 RA.",
        condition=lambda p: have_diabetes(p) and on_insulin(p) and (get_a1c(p) is not None and get_a1c(p) >= 7.5),
        recommendation="Consider adding a GLP-1 RA to basal insulin to improve A1C and reduce weight/hypoglycemia risk.",
        dosage="GLP-1 RA example: liraglutide 0.6 mg daily → increase to 1.2–1.8 mg daily per tolerance or semaglutide weekly titration; reduce basal insulin dose when adding to reduce hypoglycemia risk.",
        dosage_reason="GLP-1 RAs on top of basal insulin can reduce A1C and insulin requirements; initial basal dose reduction recommended to decrease hypoglycemia risk.",
        priority=8,
        guideline_ref="ADA 9.25",
        guideline_text="In individuals on insulin, adding a GLP-1 RA can improve glycemic control and reduce insulin requirements while lowering hypoglycemia risk."
    ))

    # ----- MASLD / MASH rules ----- 
    rules.append(Rule(
        id="R_MASLD",
        description="MASLD/MASH with overweight/obesity -> consider GLP-1 RA or dual GIP/GLP-1 RA.",
        condition=lambda p: have_diabetes(p) and truthy_flag(p.get("mcq160l")) and (get_bmi(p) is not None and get_bmi(p) >= 25.0),
        recommendation="Consider GLP-1 RA (e.g., semaglutide) or dual GIP/GLP-1 RA; for biopsy-proven MASH consider pioglitazone ± GLP-1 RA.",
        dosage="Pioglitazone: typical 15–30 mg daily; semaglutide per weekly titration. Follow specialist guidance for MASH management.",
        dosage_reason="Some agents improve hepatic steatosis and fibrosis markers; dosing follows product labeling and specialist recommendations.",
        priority=9,
        guideline_ref="ADA 9.15-9.16",
        guideline_text="For T2D with MASLD/MASH and overweight/obesity, GLP-1 RAs or dual GIP/GLP-1 RAs may improve hepatic steatosis and glycemia; pioglitazone is an option for biopsy-proven MASH."
    ))

    # ----- Cost-sensitive fallback (lower-cost options) -----
    rules.append(Rule(
        id="R_COST_CONSIDER",
        description="If cost or access barrier flagged -> propose lower-cost options with warnings.",
        condition=lambda p: have_diabetes(p) and truthy_flag(p.get("cost_barrier")),
        recommendation="Consider lower-cost options (metformin, sulfonylureas, human insulin) with documented warnings about hypoglycemia/weight gain.",
        dosage="Metformin: start 500 mg daily → titrate; Glibenclamide/Glipizide dosing per standard label (e.g., glipizide 5 mg daily); human insulin start 10 units/day or 0.1–0.2 units/kg.",
        dosage_reason="Affordable medications can lower cost burden but may increase hypoglycemia risk or weight; inform patient and monitor closely.",
        priority=200,
        guideline_ref="Cost-sensitive rules",
        guideline_text="When cost barriers exist, consider affordable medications while documenting and warning about associated risks."
    ))

    # ----- Over-basalization / de-intensification safety flag -----
    rules.append(Rule(
        id="R_OVERBASAL_FLAG",
        description="Flag possible over-basalization based on bedtime-to-morning differential or frequent hypoglycemia.",
        condition=lambda p: have_diabetes(p) and (
            (safe_num(p.get("bedtime_mgdl")) is not None and safe_num(p.get("morning_mgdl")) is not None and (safe_num(p.get("bedtime_mgdl")) - safe_num(p.get("morning_mgdl")) >= 50))
            or truthy_flag(p.get("frequent_hypoglycemia"))
        ),
        recommendation="Flag possible over-basalization; reassess insulin plan.",
        dosage="Consider reducing basal insulin dose or evaluating prandial insulin needs; individualize changes (e.g., reduce basal by 10–20% if frequent hypoglycemia).",
        dosage_reason="Large bedtime-to-morning differentials or recurrent hypoglycemia suggest excessive basal insulin; dose reduction can reduce hypoglycemia.",
        priority=30,
        guideline_ref="ADA 5.4",
        guideline_text="Large bedtime-to-morning glucose differential or frequent hypoglycemia suggests over-basalization; reassess regimen."
    ))

    # ----- Fallback default: recommend metformin + lifestyle if nothing specific -----
    rules.append(Rule(
        id="R_METFORMIN_FIRST",
        description="Default first-line agent for most adults with T2D without contraindications -> metformin.",
        condition=lambda p: have_diabetes(p) and not on_metformin(p) and (get_eGFR(p) is None or get_eGFR(p) >= 30.0),
        recommendation="Initiate metformin unless contraindicated (assess eGFR before starting).",
        dosage="Start metformin 500 mg once daily with food; titrate by 500 mg weekly up to 1500–2000 mg/day as tolerated (usual target 1500 mg/day minimum effective dose; max 2000 mg/day commonly used).",
        dosage_reason="Slow titration reduces GI adverse effects and improves adherence; renal function informs safe dosing.",
        priority=999,
        guideline_ref="ADA first-line",
        guideline_text="Metformin is the preferred initial pharmacologic agent for most adults with type 2 diabetes unless contraindicated by renal function or other factors."
    ))

    # ----- Final catch-all fallback (if patient flagged as diabetes but none else fired) -----
    rules.append(Rule(
        id="R_FALLBACK",
        description="Fallback rule when no specific ADA rule matches.",
        condition=lambda p: True,
        recommendation="Maintain lifestyle therapy and monitor. No specific pharmacologic change triggered by available inputs.",
        dosage="No medication change recommended.",
        dosage_reason="Insufficient data to trigger ADA 2025 rule.",
        priority=9999,
        guideline_ref="General",
        guideline_text="Used when patient data does not match ADA decision pathways."
    ))

    return rules

def get_engine() -> ExpertEngine:
    return ExpertEngine(make_ada_rules())

# optional: mapping helper to convert NHANES row keys to engine keys
NHANES_TO_ENGINE_KEY = {
    "BMXBMI__response": "bmi",
    "BMXWT__response": "weight",
    "BPXDAR__response": "bp_diastolic",
    "BPXSAR__response": "bp_systolic",
    "DIQ010__questionnaire": "diq010",
    "DIQ050__response": "diq050",
    "DIQ070__questionnaire": "diq070",
    "DIQ220__questionnaire": "diq220",
    "HAD7S__questionnaire": "had7s",
    "HSAGEU__demographics": "age",
    "LBDHDD__response": "lbdhdd",
    "LBDLDL__response": "lbdldl",
    "LBDSCHSI__response": "total_chol_si",
    "LBXGH__response": "lbxgh",
    "LBXGLT__response": "lbxglt",
    "LBXGLU__response": "lbxglu",
    "LBXSBU__response": "lbxsbu",
    "LBXSCR__response": "lbxscr",
    "LBXSGL__response": "lbxsgl",
    "MCQ100__questionnaire": "mcq100",
    "MCQ160B__questionnaire": "mcq160b",
    "MCQ160C__questionnaire": "mcq160c",
    "MCQ160E__questionnaire": "mcq160e",
    "MCQ160F__questionnaire": "mcq160f",
    "MCQ160L__questionnaire": "mcq160l",
    "MCQ170L__questionnaire": "mcq170l",
    "RXDDRUG__medications": "rxddrug",
    "URXUMS__response": "urxums",
    "VNEGFR__response": "vnegfr"
}

def map_nhanes_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a NHANES row (dict-like) to engine patient dict using mapping above."""
    out = {}
    for src, dst in NHANES_TO_ENGINE_KEY.items():
        out[dst] = row.get(src, None)
    return out
