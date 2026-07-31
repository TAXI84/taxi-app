from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional, List
import uuid

app = FastAPI(title="TaxiCPAM", version="1.0.0")

# ========== CORS (OBLIGATOIRE pour HTML local / file:// / localhost) ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev : toutes origines (localhost, file://, GitHub Pages…)
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base de données en mémoire (perdue au redémarrage Render free)
courses_db = {}
alerts_db = []


class CourseCreate(BaseModel):
    patient_nom: str
    patient_prenom: str = "—"
    patient_num_ss: Optional[str] = None
    patient_adresse: Optional[str] = None
    date: date
    lieu_depart: str
    lieu_arrivee: str
    kilometrage: float
    code_transport: str  # T1..T5


TARIFS = {
    "T1": {"min": 0, "max": 50, "base": 25.0, "km": 1.20},
    "T2": {"min": 50, "max": 100, "base": 45.0, "km": 1.10},
    "T3": {"min": 100, "max": 200, "base": 80.0, "km": 1.00},
    "T4": {"min": 200, "max": 9999, "base": 120.0, "km": 0.90},
    "T5": {"min": 0, "max": 9999, "base": 35.0, "km": 1.50},
}


@app.get("/")
def root():
    return {"message": "API TaxiCPAM fonctionne", "docs": "/docs"}


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
        "montant_total": None,  # alias pour le front
    }
    courses_db[course_id] = course
    return course


@app.get("/courses")
def list_courses():
    # plus récentes en premier
    return list(reversed(list(courses_db.values())))


@app.post("/courses/{course_id}/verify")
def verify_course(course_id: str):
    if course_id not in courses_db:
        raise HTTPException(status_code=404, detail="Course non trouvée")

    course = courses_db[course_id]
    code = course["code_transport"]
    km = float(course["kilometrage"])

    if code not in TARIFS:
        return {
            "ok": False,
            "compatible": False,
            "message": "Code transport invalide",
            "montant": None,
            "montant_calcule": None,
            "alertes": ["Code transport invalide"],
        }

    regle = TARIFS[code]
    # T5 (Paris) : pas de contrainte km stricte
    if code != "T5" and not (regle["min"] <= km <= regle["max"]):
        msg = f"Code {code} incompatible avec {km} km"
        return {
            "ok": False,
            "compatible": False,
            "message": msg,
            "montant": None,
            "montant_calcule": None,
            "alertes": [msg],
        }

    montant = round(regle["base"] + (km * regle["km"]), 2)
    course["montant"] = montant
    course["montant_total"] = montant
    course["statut"] = "verifie"

    return {
        "ok": True,
        "compatible": True,
        "message": "Course conforme",
        "montant": montant,
        "montant_calcule": montant,
        "alertes": [],
    }


@app.post("/courses/{course_id}/generate-invoice")
@app.post("/courses/{course_id}/generate")  # alias DeepSeek
def generate_invoice(course_id: str):
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


@app.get("/alerts")
def list_alerts():
    return list(reversed(alerts_db))


@app.post("/alerts/refresh")
def refresh_alerts():
    alerts_db.append({
        "id": str(uuid.uuid4()),
        "titre": "Veille réglementaire — mise à jour",
        "contenu": "Scraping simulé exécuté (Légifrance / FNTI). Aucun changement critique détecté.",
        "categorie": "obligations",
        "date_application": date.today().isoformat(),
        "niveau": "national",
        "lu": False,
    })
    return {"status": "scraping lancé", "count": len(alerts_db)}
