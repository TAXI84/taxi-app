import os
import uuid
from datetime import date
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests

app = FastAPI(title="TaxiCPAM", version="1.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration de la clé API Mistral depuis le dashboard Render
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

courses_db = {}

alerts_db = [
    {
        "id": str(uuid.uuid4()),
        "titre": "Prescription médicale de transport obligatoire",
        "contenu": (
            "Toute facturation CPAM de transport assis (taxi conventionné) exige une"
            " prescription médicale de transport valide. Sans ordonnance, le dossier"
            " est refusé."
        ),
        "categorie": "facturation",
        "date_application": "2024-01-01",
        "niveau": "national",
        "lu": False,
    },
    {
        "id": str(uuid.uuid4()),
        "titre": "Codes transport et distance",
        "contenu": (
            "Le code de transport doit correspondre à la distance réelle. Un"
            " écart code / km est un motif classique de rejet ou de contrôle"
            " CPAM. Vérifie avant envoi NOEMIE."
        ),
        "categorie": "conformité",
        "date_application": "2024-01-01",
        "niveau": "national",
        "lu": False,
    },
    {
        "id": str(uuid.uuid4()),
        "titre": "Identité patient (NIR) complète",
        "contenu": (
            "Le numéro de sécurité sociale (NIR) doit être exact et complet."
            " NIR manquant ou erroné = rejet fréquent à la liquidation."
        ),
        "categorie": "dossier",
        "date_application": "2024-01-01",
        "niveau": "national",
        "lu": False,
    },
]

TARIFS = {
    "T1": {"min": 0, "max": 50, "base": 25.0, "km": 1.20, "label": "0 à 50 km"},
    "T2": {
        "min": 50,
        "max": 100,
        "base": 45.0,
        "km": 1.10,
        "label": "50 à 100 km",
    },
    "T3": {
        "min": 100,
        "max": 200,
        "base": 80.0,
        "km": 1.00,
        "label": "100 à 200 km",
    },
    "T4": {
        "min": 200,
        "max": 9999,
        "base": 120.0,
        "km": 0.90,
        "label": "200 km et plus",
    },
    "T5": {
        "min": 0,
        "max": 9999,
        "base": 35.0,
        "km": 1.50,
        "label": "région parisienne",
    },
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
    chauffeur_email: Optional[str] = None
    chauffeur_nom: Optional[str] = None


def suggest_code(km: float) -> str:
    if km < 50:
        return "T1"
    if km < 100:
        return "T2"
    if km < 200:
        return "T3"
    return "T4"


def obtenir_conseil_mistral_anonyme(
    km: float, code: str, compatible: bool, alertes: list, montant: float
) -> str:
    """Agent Mistral AI - Strictement RGPD : Traite uniquement des données anonymes."""
    if not MISTRAL_API_KEY:
        # Fallback local si la clé n'est pas renseignée
        if compatible:
            return (
                f"Code {code} cohérent avec {km} km. Montant estimé {montant}"
                " €."
            )
        else:
            suggested = suggest_code(km)
            return (
                f"Change le code en {suggested} (adapté à {km} km). Sinon la"
                " CPAM risque de rejeter la facture."
            )

    prompt = f"""
    Tu es l'agent copilote expert en facturation CPAM B2 pour les chauffeurs de taxi conventionnés.
    Analyse anonyme du dossier de course :
    - Distance : {km} km
    - Code transport choisi : {code}
    - Statut de conformité : {'Conforme' if compatible else 'Risque de refus'}
    - Montant estimé : {montant} €
    - Alertes de validation : {', '.join(alertes) if alertes else 'Aucune'}

    Rédige un conseil synthétique, direct, concis et professionnel pour le chauffeur (maximum 2 phrases).
    Si le dossier est conforme, valide le code et confirme l'absence de risque.
    S me dossier présente une erreur de code transport, indique clairement le code recommandé à corriger.
    Ne mentionne jamais de nom ou d'informations personnelles.
    """

    try:
        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "mistral-tiny",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=4,
        )
        if response.status_code == 200:
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        pass

    # Fallback si erreur de réseau avec l'API Mistral
    if compatible:
        return (
            f"Code {code} cohérent avec {km} km. Montant estimé {montant} €."
        )
    suggested = suggest_code(km)
    return f"Code recommandé : {suggested} pour {km} km afin d'éviter un rejet CPAM."


def build_advice(code: str, km: float) -> dict:
    suggested = suggest_code(km)

    if code not in TARIFS:
        alertes = ["Code transport inconnu."]
        conseil_ia = obtenir_conseil_mistral_anonyme(
            km, code, False, alertes, 0.0
        )
        return {
            "ok": False,
            "compatible": False,
            "message": "Code transport invalide — risque de refus CPAM",
            "montant": None,
            "montant_calcule": None,
            "alertes": alertes,
            "conseil": conseil_ia,
            "code_suggere": suggested,
            "ia": "mistral-ai",
        }

    regle = TARIFS[code]

    if code == "T5":
        montant = round(regle["base"] + (km * regle["km"]), 2)
        conseil_ia = obtenir_conseil_mistral_anonyme(km, code, True, [], montant)
        return {
            "ok": True,
            "compatible": True,
            "message": "Course conforme",
            "montant": montant,
            "montant_calcule": montant,
            "alertes": [],
            "conseil": conseil_ia,
            "code_suggere": "T5",
            "ia": "mistral-ai",
        }

    if not (regle["min"] <= km <= regle["max"]):
        alertes = [
            f"Code {code} incompatible avec {km} km",
            f"{code} est réservé à : {regle['label']}.",
        ]
        conseil_ia = obtenir_conseil_mistral_anonyme(
            km, code, False, alertes, 0.0
        )
        return {
            "ok": False,
            "compatible": False,
            "message": "Risque de refus CPAM",
            "montant": None,
            "montant_calcule": None,
            "alertes": alertes,
            "conseil": conseil_ia,
            "code_suggere": suggested,
            "ia": "mistral-ai",
        }

    montant = round(regle["base"] + (km * regle["km"]), 2)
    conseil_ia = obtenir_conseil_mistral_anonyme(km, code, True, [], montant)
    return {
        "ok": True,
        "compatible": True,
        "message": "Course conforme",
        "montant": montant,
        "montant_calcule": montant,
        "alertes": [],
        "conseil": conseil_ia,
        "code_suggere": code,
        "ia": "mistral-ai",
    }


@app.get("/")
def root():
    return {
        "message": "API TaxiCPAM fonctionne",
        "docs": "/docs",
        "version": "1.5.0",
    }


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
        "chauffeur_email": (data.chauffeur_email or "").strip().lower() or None,
        "chauffeur_nom": data.chauffeur_nom,
    }
    courses_db[course_id] = course
    return course


@app.get("/courses")
def list_courses(chauffeur_email: Optional[str] = None):
    items = list(courses_db.values())
    if chauffeur_email:
        email = chauffeur_email.strip().lower()
        items = [c for c in items if (c.get("chauffeur_email") or "") == email]
    return list(reversed(items))


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
    result = build_advice(
        course["code_transport"], float(course["kilometrage"])
    )

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
        raise HTTPException(
            status_code=400, detail="La course doit être vérifiée d'abord"
        )

    course["statut"] = "paye"
    xml = (
        f'<NOEMIE version="B2">'
        f"<IDENTIFIANT>{course_id}</IDENTIFIANT>"
        f"<CODE_TRANSPORT>{course['code_transport']}</CODE_TRANSPORT>"
        f"<KILOMETRAGE>{course['kilometrage']}</KILOMETRAGE>"
        f"<MONTANT>{course.get('montant')}</MONTANT>"
        f"<NOM_PATIENT>{course['patient_prenom']}"
        f" {course['patient_nom']}</NOM_PATIENT>"
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
    alerts_db.append(
        {
            "id": str(uuid.uuid4()),
            "titre": "Rappel : contrôles CPAM sur les transports",
            "contenu": (
                "Les dossiers incomplets (ordonnance, NIR, cohérence code/km)"
                " sont prioritaires en contrôle. Vérifie chaque course avant"
                " envoi."
            ),
            "categorie": "contrôle",
            "date_application": date.today().isoformat(),
            "niveau": "national",
            "lu": False,
        }
    )
    return {"status": "ok", "count": len(alerts_db)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
