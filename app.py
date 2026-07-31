from fastapi import FastAPI
from pydantic import BaseModel
from datetime import date
import uuid

app = FastAPI(title="TaxiCPAM")

# Base de données en mémoire
courses_db = {}

# Modèle pour créer une course
class CourseCreate(BaseModel):
    patient_nom: str
    patient_prenom: str
    date: date
    lieu_depart: str
    lieu_arrivee: str
    kilometrage: float
    code_transport: str  # T1, T2, T3, T4, T5

# Route pour créer une course
@app.post("/courses")
def create_course(data: CourseCreate):
    course_id = str(uuid.uuid4())
    course = {
        "id": course_id,
        "patient_nom": data.patient_nom,
        "patient_prenom": data.patient_prenom,
        "date": data.date.isoformat(),
        "lieu_depart": data.lieu_depart,
        "lieu_arrivee": data.lieu_arrivee,
        "kilometrage": data.kilometrage,
        "code_transport": data.code_transport.upper(),
        "statut": "brouillon",
        "montant": None
    }
    courses_db[course_id] = course
    return course

# Route pour lister toutes les courses
@app.get("/courses")
def list_courses():
    return list(courses_db.values())

# Route pour vérifier une course et calculer le prix
@app.post("/courses/{course_id}/verify")
def verify_course(course_id: str):
    if course_id not in courses_db:
        return {"error": "Course non trouvée"}
    
    course = courses_db[course_id]
    code = course["code_transport"]
    km = course["kilometrage"]
    
    tarifs = {
        "T1": {"min": 0, "max": 50, "base": 25.0, "km": 1.20},
        "T2": {"min": 50, "max": 100, "base": 45.0, "km": 1.10},
        "T3": {"min": 100, "max": 200, "base": 80.0, "km": 1.00},
        "T4": {"min": 200, "max": 9999, "base": 120.0, "km": 0.90},
        "T5": {"min": 0, "max": 9999, "base": 35.0, "km": 1.50},
    }
    
    if code not in tarifs:
        return {"ok": False, "message": "Code transport invalide"}
    
    regle = tarifs[code]
    if not (regle["min"] <= km <= regle["max"]):
        return {"ok": False, "message": f"Code {code} incompatible avec {km} km"}
    
    montant = regle["base"] + (km * regle["km"])
    course["montant"] = montant
    course["statut"] = "verifie"
    return {"ok": True, "message": "Course conforme", "montant": montant}

# Route pour générer la facture
@app.post("/courses/{course_id}/generate")
def generate_invoice(course_id: str):
    if course_id not in courses_db:
        return {"error": "Course non trouvée"}
    
    course = courses_db[course_id]
    if course["statut"] != "verifie":
        return {"error": "La course doit être vérifiée d'abord"}
    
    course["statut"] = "paye"
    return {
        "message": "Facture générée",
        "patient": f"{course['patient_prenom']} {course['patient_nom']}",
        "montant": course["montant"]
    }

# Route santé
@app.get("/")
def root():
    return {"message": "API TaxiCPAM fonctionne"}