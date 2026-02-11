# engine.py
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Any, List, Tuple, Optional

# Load JSON data files (relative path 'data/')
BASE_DIR = os.path.dirname(__file__)
DRUGS_PATH = os.path.join(BASE_DIR, "data", "drugs.json")
THRESHOLDS_PATH = os.path.join(BASE_DIR, "data", "thresholds.json")

with open(DRUGS_PATH, "r", encoding="utf-8") as f:
    DRUGS = json.load(f)

with open(THRESHOLDS_PATH, "r", encoding="utf-8") as f:
    THRESHOLDS = json.load(f)

def safe_num(x: Any) -> Optional[float]:
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
    return x in (1, True, "1", "yes", "Yes", "YES", "Y", "y", "true", "True")

@dataclass
class Rule:
    id: str
    description: str
    condition: Callable[[Dict[str, Any]], bool]
    recommendation: str
    dosage: str = ""
    dosage_reason: str = ""
    priority: int = 100
    guideline_ref: str = ""
    guideline_text: str = ""
    explanation: str = ""  # medicine explanation from JSON if applicable

    def applies(self, patient: Dict[str, Any]) -> bool:
        try:
            return bool(self.condition(patient))
        except Exception:
            return False

@dataclass
class ExpertEngine:
    rules: List[Rule] = field(default_factory=list)

    def evaluate(self, patient: Dict[str, Any]) -> Tuple[List[str], List[Dict[str, Any]]]:
        fired_rules: List[Rule] = []
        # Evaluate all except fallback
        for r in self.rules:
            if r.id != THRESHOLDS["overrides"]["fallback_rule_id"] and r.applies(patient):
                fired_rules.append(r)

        # If none fired, use fallback
        if len(fired_rules) == 0:
            fallback = next((r for r in self.rules if r.id == THRESHOLDS["overrides"]["fallback_rule_id"]), None)
            if fallback:
                fired_rules.append(fallback)

        # Sort by priority
        fired_rules.sort(key=lambda r: r.priority)

        # Prepare outputs
        recs = [r.recommendation for r in fired_rules]
        expl = []
        for r in fired_rules:
            expl.append({
                "id": r.id,
                "description": r.description,
                "recommendation": r.recommendation,
                "dosage": r.dosage,
                "dosage_reason": r.dosage_reason,
                "guideline_ref": r.guideline_ref,
                "guideline_text": r.guideline_text,
                "explanation": r.explanation
            })
        return recs, expl

# Build rules programmatically using thresholds + drugs
def make_rules() -> List[Rule]:
    rules: List[Rule] = []

    # helpers
    get_a1c = lambda p: safe_num(p.get("lbxgh"))
    get_glu = lambda p: safe_num(p.get("lbxsgl") or p.get("lbxglu") or p.get("lbxglt"))
    get_egfr = lambda p: safe_num(p.get("vnegfr"))
    get_bmi = lambda p: safe_num(p.get("bmi"))
    on_metformin = lambda p: "metformin" in (str(p.get("rxddrug") or "").lower())
    on_insulin = lambda p: truthy_flag(p.get("diq050"))
    have_diabetes = lambda p: truthy_flag(p.get("diq010"))

    # Insulin initiation rule (use thresholds)
    ins_thresh = THRESHOLDS["insulin_initiation"]
    rules.append(Rule(
        id="R_INSULIN_SEVERE",
        description="Severe hyperglycemia or catabolism -> initiate insulin per algorithm.",
        condition=lambda p: have_diabetes(p) and (
            (get_a1c(p) is not None and get_a1c(p) > ins_thresh["a1c_threshold_pct"]) or
            (get_glu(p) is not None and get_glu(p) >= ins_thresh["glucose_threshold_mgdl"]) or
            (p.get(ins_thresh["catabolic_flag_field"]) is True)
        ),
        recommendation="Initiate insulin therapy (basal-first).",
        dosage=f"Start basal {THRESHOLDS['basal']['start_units']} units once daily or {THRESHOLDS['basal']['start_units_per_kg_min']}–{THRESHOLDS['basal']['start_units_per_kg_max']} units/kg/day; titrate {THRESHOLDS['basal']['titration_increment_units']} units every {THRESHOLDS['basal']['titration_units_every_n_days']} days until fasting target.",
        dosage_reason="Start at a low basal dose (absolute or weight-based) to limit hypoglycemia and titrate frequently toward fasting glucose target; reduce dose by 10–20% if unexplained hypoglycemia.",
        priority=1,
        guideline_ref="ADA insulin algorithm",
        guideline_text="Initiate insulin when A1C >10% or plasma glucose ≥300 mg/dL, or catabolic features present. Titrate per fasting glucose.",
        explanation="Insulin recommended when severe hyperglycemia or catabolic features are present; see dosing algorithm for basal initiation and titration."
    ))

    # Metformin initial / default rule
    mf = DRUGS.get("metformin", {})
    rules.append(Rule(
        id="R_METFORMIN_FIRST",
        description="Default first-line: metformin unless contraindicated by eGFR.",
        condition=lambda p: have_diabetes(p) and not on_metformin(p) and (get_egfr(p) is None or get_egfr(p) >= THRESHOLDS["metformin"]["egfr_start_cutoff"]),
        recommendation="Initiate metformin unless contraindicated (assess eGFR before starting).",
        dosage=mf.get("start_dose", ""),
        dosage_reason="Start low and titrate to minimize GI adverse effects; monitor renal function and B12 over time.",
        priority=50,
        guideline_ref="ADA first-line",
        guideline_text="Metformin is preferred initial pharmacologic agent for most adults with T2D unless contraindicated by renal function.",
        explanation=mf.get("explanation", "")
    ))

    # Metformin contraindication due to eGFR
    rules.append(Rule(
        id="R_METFORMIN_CONTRA",
        description="Avoid or adjust metformin based on eGFR.",
        condition=lambda p: have_diabetes(p) and (get_egfr(p) is not None and get_egfr(p) < THRESHOLDS["metformin"]["egfr_continue_cutoff"]),
        recommendation="Do not start metformin / stop if eGFR below cutoff.",
        dosage="If eGFR < 30 mL/min/1.73 m2: stop metformin. If eGFR 30–45 consider dose reduction and monitoring.",
        dosage_reason="Metformin accumulation risk with low eGFR; discontinue if <30 and dose reduce with caution at 30–45.",
        priority=10,
        guideline_ref="ADA metformin & CKD",
        guideline_text="Avoid initiating metformin if eGFR <45; stop if eGFR <30.",
        explanation=mf.get("explanation", "")
    ))

    # SGLT2i for HF/CKD or albuminuria
    sgl = DRUGS.get("empagliflozin", {})
    rules.append(Rule(
        id="R_HF_SGLT2",
        description="Heart failure -> recommend SGLT2 inhibitor for HF benefit if eGFR allows.",
        condition=lambda p: have_diabetes(p) and truthy_flag(p.get("mcq160b")),
        recommendation="Recommend SGLT2 inhibitor (empagliflozin/dapagliflozin) for HF benefit if eGFR allows.",
        dosage=sgl.get("start_dose", ""),
        dosage_reason="Standard doses used in HF trials (e.g., empagliflozin 10 mg daily) provide HF and renal benefit; follow label eGFR limits.",
        priority=20,
        guideline_ref="ADA heart failure guidance",
        guideline_text="SGLT2 inhibitors recommended for people with T2D and HF to reduce hospitalization.",
        explanation=sgl.get("explanation", "")
    ))

    # CKD with albuminuria rule (SGLT2 if eGFR ok else GLP-1)
    rules.append(Rule(
        id="R_CKD_ALBUMINURIA",
        description="CKD with albuminuria or moderate eGFR decline -> SGLT2i preferred if eGFR adequate; else consider GLP-1 RA.",
        condition=lambda p: have_diabetes(p) and (
            (get_egfr(p) is not None and 20.0 <= get_egfr(p) <= 60.0) or
            (safe_num(p.get("urxums") or p.get("urxuma")) is not None and safe_num(p.get("urxums") or p.get("urxuma")) > 30.0)
        ),
        recommendation="Use SGLT2 inhibitor if eGFR adequate; consider GLP-1 RA if SGLT2i not suitable.",
        dosage=sgl.get("start_dose", ""),
        dosage_reason="SGLT2 inhibitors have kidney-protective and CV benefits when eGFR in allowed range; GLP-1 RA is alternative for weight/CV benefit.",
        priority=25,
        guideline_ref="ADA CKD guidance",
        guideline_text="SGLT2 inhibitors or GLP-1 RAs with kidney benefit recommended in T2D with CKD/albuminuria.",
        explanation=sgl.get("explanation", "")
    ))

    # ASCVD: prefer GLP-1 and/or SGLT2
    glp = DRUGS.get("liraglutide", {})
    rules.append(Rule(
        id="R_ASCVD_CV",
        description="ASCVD present -> prioritize GLP-1 RA and/or SGLT2i for CV risk reduction.",
        condition=lambda p: have_diabetes(p) and any(truthy_flag(p.get(k)) for k in ("mcq160c", "mcq160e", "mcq160f")),
        recommendation="Prioritize GLP-1 RA and/or SGLT2 inhibitor for cardiovascular risk reduction.",
        dosage=glp.get("start_dose", ""),
        dosage_reason="Trials demonstrating CV risk reduction used standard GLP-1 and SGLT2 doses; titrate per label.",
        priority=30,
        guideline_ref="ADA ASCVD guidance",
        guideline_text="In adults with T2D and ASCVD or high ASCVD risk, use GLP-1 RA and/or SGLT2 inhibitors with proven CV benefit.",
        explanation=glp.get("explanation", "")
    ))

    # Obesity -> prioritize GLP-1 / tirzepatide
    tir = DRUGS.get("tirzepatide", {})
    rules.append(Rule(
        id="R_OBESITY_WEIGHT",
        description="Obesity as a treatment target -> consider GLP-1 RA / tirzepatide.",
        condition=lambda p: have_diabetes(p) and (get_bmi(p) is not None and get_bmi(p) >= 30.0),
        recommendation="Consider GLP-1 RA (semaglutide/liraglutide) or tirzepatide for weight and glycemic benefit.",
        dosage=tir.get("start_dose", ""),
        dosage_reason="Titrate per label to improve tolerability and maximize weight-loss & glycemic benefit.",
        priority=40,
        guideline_ref="ADA obesity guidance",
        guideline_text="For people with T2D and obesity, prioritize agents with proven weight-loss and glycemic efficacy.",
        explanation=tir.get("explanation", "")
    ))

    # Insulin add-on for people already on insulin with suboptimal control -> consider GLP1 add-on
    rules.append(Rule(
        id="R_INSULIN_ADDON_GLP1",
        description="On insulin with suboptimal control -> consider adding GLP-1 RA.",
        condition=lambda p: have_diabetes(p) and on_insulin(p) and (get_a1c(p) is not None and get_a1c(p) >= 7.5),
        recommendation="Consider adding a GLP-1 RA to basal insulin (reduce basal dose when adding).",
        dosage=glp.get("start_dose", ""),
        dosage_reason="Adding GLP-1 reduces A1C and weight and can allow reduction of basal insulin to limit hypoglycemia.",
        priority=60,
        guideline_ref="ADA insulin+GLP-1 guidance",
        guideline_text="Adding GLP-1 RA to basal insulin can improve control and reduce insulin requirements.",
        explanation=glp.get("explanation", "")
    ))

    # Cost-sensitive fallback
    rules.append(Rule(
        id="R_COST_CONSIDER",
        description="Cost or access barrier flagged -> propose lower-cost options with warnings.",
        condition=lambda p: have_diabetes(p) and truthy_flag(p.get("cost_barrier")),
        recommendation="Consider lower-cost agents (metformin, sulfonylurea, human insulin) and counsel about risks.",
        dosage="Metformin per usual titration; glimepiride start 1–2 mg daily and titrate; human insulin start 10 units or 0.1–0.2 units/kg.",
        dosage_reason="Lower-cost options available but have trade-offs like hypoglycemia or weight gain; monitor closely.",
        priority=500,
        guideline_ref="Cost-sensitive approach",
        guideline_text="Use affordable meds when cost is a major barrier while documenting risks and monitoring carefully.",
        explanation="Affordable therapies may be used when cost is a major barrier; discuss hypoglycemia and monitoring."
    ))

    # Over-basalization flag
    rules.append(Rule(
        id="R_OVERBASAL_FLAG",
        description="Flag possible over-basalization when bedtime-to-morning delta is large or frequent hypoglycemia.",
        condition=lambda p: have_diabetes(p) and (
            (safe_num(p.get("bedtime_mgdl")) is not None and safe_num(p.get("morning_mgdl")) is not None and (safe_num(p.get("bedtime_mgdl")) - safe_num(p.get("morning_mgdl")) >= THRESHOLDS["basal"]["overbasal_delta_mgdl"])) or
            truthy_flag(p.get("frequent_hypoglycemia"))
        ),
        recommendation="Possible over-basalization — reassess insulin strategy (consider GLP-1 RA or prandial insulin rather than more basal).",
        dosage="If over-basalization suspected, stop increasing basal; consider reducing basal by 10–20% and address postprandial excursions.",
        dosage_reason="Large bedtime-morning differences or recurrent hypoglycemia indicate excessive basal insulin; joint strategies (reduce basal or add prandial/GLP1) may be better.",
        priority=80,
        guideline_ref="ADA over-basalization guidance",
        guideline_text="Large bedtime-morning differentials or frequent hypoglycemia suggest over-basalization; reassess regimen.",
        explanation="Check basal dosing relative to patient glycemic patterns and consider alternative strategies."
    ))

    # Final fallback rule (never fires unless no other rule applies)
    rules.append(Rule(
        id=THRESHOLDS["overrides"]["fallback_rule_id"],
        description="Fallback when no other rule applies: lifestyle & reassessment.",
        condition=lambda p: False,
        recommendation="Lifestyle modification, education, and reassess in 3–6 months; consider metformin if appropriate.",
        dosage="N/A",
        dosage_reason="Used only when no other specific guideline-driven rule applies.",
        priority=1000,
        guideline_ref="ADA core principles",
        guideline_text="Lifestyle therapy is foundational and pharmacotherapy should be individualized.",
        explanation="Recommend lifestyle changes and reassessment; this fallback appears only when no specific pharmacologic rule applies."
    ))

    return rules

def get_engine() -> ExpertEngine:
    return ExpertEngine(make_rules())
