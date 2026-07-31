from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date
from typing import Optional, List
import uuid
import os

app = FastAPI(title="TaxiCPAM", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

courses_db = {}
alerts_db = []

TARIFS = {
    "T1": {"min": 0, "max": 50, "base": 25.0, "km": 1.20, "label": "0 à 50 km"},
    "T2": {"min": 50, "max": 100, "base": 45.0, "km": 1.10, "label": "50 à 100 km"},
    "T3": {"min": 100, "max": 200, "base": 80.0, "km": 1.00, "label": "100 à 200 km"},
    "T4": {"min": 200, "max": 9999, "base": 120.0, "km": 0.90, "label": "200 km et plus"},
    "T5": {"min": 0, "max": 9999, "base": 35.0, "km": 1.50, "label": "région parisienne"},
}


class CourseCreate(BaseModel):
    patient_nom: str
    patient_prenom: str = "—"
    patient_num_ss: Optional[str] = None
    patient_adresse: Optional[str] = None
    date: date
    lieu_depart: str
    lieu_arrivee: str
    kilometrage: float
    code_transport: str


def suggest_code(km: float) -> str:
    if km < 50:
        return "T1"
    if km < 100:
        return "T2"
    if km < 200:
        return "T3"
    return "T4"


def build_advice(code: str, km: float) -> dict:
    suggested = suggest_code(km)
    alertes: List[str] = []

    if code not in TARIFS:
        return {
            "ok": False,
            "compatible": False,
            "message": "Code transport invalide — risque de refus CPAM",
            "montant": None,
            "montant_calcule": None,
            "alertes": ["Code transport inconnu."],
            "conseil": f"Utilise le code {suggested} pour {km} km ({TARIFS[suggested]['label']}).",
            "code_suggere": suggested,
            "ia": "anti-rejet",
        }

    regle = TARIFS[code]

    if code == "T5":
        montant = round(regle["base"] + (km * regle["km"]), 2)
        return {
            "ok": True,
            "compatible": True,
            "message": "Course conforme",
            "montant": montant,
            "montant_calcule": montant,
            "alertes": [],
            "conseil": "Code T5 (Paris) accepté. Vérifie que le trajet est bien en région parisienne.",
            "code_suggere": "T5",
            "ia": "anti-rejet",
        }

    if not (regle["min"] <= km <= regle["max"]):
        return {
            "ok": False,
            "compatible": False,
            "message": "Risque de refus CPAM",
            "montant": None,
            "montant_calcule": None,
            "alertes": [
                f"Code {code} incompatible avec {km} km",
                f"{code} est réservé à : {regle['label']}.",
            ],
            "conseil": (
                f"Change le code en {suggested} (adapté à {km} km — {TARIFS[suggested]['label']}). "
                f"Sinon la CPAM peut refuser la facture."
            ),
            "code_suggere": suggested,
            "ia": "anti-rejet",
        }

    montant = round(regle["base"] + (km * regle["km"]), 2)
    return {
        "ok": True,
        "compatible": True,
        "message": "Course conforme",
        "montant": montant,
        "montant_calcule": montant,
        "alertes": [],
        "conseil": f"Code {code} cohérent avec {km} km. Montant estimé {montant} €.",
        "code_suggere": code,
        "ia": "anti-rejet",
    }


@app.get("/")
def root():
    return {"message": "API TaxiCPAM fonctionne", "docs": "/docs", "version": "1.2.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/courses")
def create_course(data: CourseCreate):
    course_id = str(uuid.uuid4())
    course = {
        "id": course_id,
        "patient_nom": data.patient_nom,
        "patient_prenom": data.patient_prenom,
        "patient_num_ss": data.patient_num_ss,
        "patient_adresse": data.patient_adresse,
        "date": data.date.isoformat(),
        "lieu_depart": data.lieu_depart,
        "lieu_arrivee": data.lieu_arrivee,
        "kilometrage": data.kilometrage,
        "code_transport": data.code_transport.upper(),
        "statut": "brouillon",
        "montant": None,
        "montant_total": None,
    }
    courses_db[course_id] = course
    return course


@app.get("/courses")
def list_courses():
    return list(reversed(list(courses_db.values())))


@app.get("/courses/{course_id}")
def get_course(course_id: str):
    if course_id not in courses_db:
        raise HTTPException(status_code=404, detail="Course non trouvée")
    return courses_db[course_id]


@app.delete("/courses/{course_id}")
def delete_course(course_id: str):
    if course_id not in courses_db:
        raise HTTPException(status_code=404, detail="Course non trouvée")
    del courses_db[course_id]
    return {"ok": True, "message": "Course supprimée"}


@app.post("/courses/{course_id}/verify")
def verify_course(course_id: str):
    if course_id not in courses_db:
        raise HTTPException(status_code=404, detail="Course non trouvée")

    course = courses_db[course_id]
    code = course["code_transport"]
    km = float(course["kilometrage"])
    result = build_advice(code, km)

    if result["ok"]:
        course["montant"] = result["montant"]
        course["montant_total"] = result["montant"]
        course["statut"] = "verifie"

    return result


def _generate_invoice(course_id: str):
    if course_id not in courses_db:
        raise HTTPException(status_code=404, detail="Course non trouvée")

    course = courses_db[course_id]
    if course["statut"] not in ("verifie", "paye"):
        raise HTTPException(status_code=400, detail="La course doit être vérifiée d'abord")

    course["statut"] = "paye"
    xml = (
        f"<NOEMIE version=\"B2\">"
        f"<IDENTIFIANT>{course_id}</IDENTIFIANT>"
        f"<CODE_TRANSPORT>{course['code_transport']}</CODE_TRANSPORT>"
        f"<KILOMETRAGE>{course['kilometrage']}</KILOMETRAGE>"
        f"<MONTANT>{course.get('montant')}</MONTANT>"
        f"<NOM_PATIENT>{course['patient_prenom']} {course['patient_nom']}</NOM_PATIENT>"
        f"</NOEMIE>"
    )
    course["facture_xml"] = xml
    return {
        "message": "Facture générée",
        "patient": f"{course['patient_prenom']} {course['patient_nom']}",
        "montant": course.get("montant"),
        "pdf_url": f"/fake-pdf/{course_id}.pdf",
        "xml": xml,
    }


@app.post("/courses/{course_id}/generate-invoice")
def generate_invoice(course_id: str):
    return _generate_invoice(course_id)


@app.post("/courses/{course_id}/generate")
def generate_invoice_alias(course_id: str):
    return _generate_invoice(course_id)


@app.get("/alerts")
def list_alerts():
    return list(reversed(alerts_db))


@app.post("/alerts/refresh")
def refresh_alerts():
    alerts_db.append({
        "id": str(uuid.uuid4()),
        "titre": "Veille réglementaire — mise à jour",
        "contenu": "Scraping simulé. Aucun changement critique détecté.",
        "categorie": "obligations",
        "date_application": date.today().isoformat(),
        "niveau": "national",
        "lu": False,
    })
    return {"status": "scraping lancé", "count": len(alerts_db)}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
