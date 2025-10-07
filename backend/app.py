import os
import io
import base64
import logging
import traceback
from pathlib import Path
from typing import List

from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS

# --- 1) dotenv (local uniquement, inoffensif en prod) ---
try:
    from dotenv import load_dotenv
    load_dotenv()  # charge backend/.env quand tu lances python app.py
except Exception:
    pass

# --- 2) OpenAI ---
try:
    from openai import OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
except Exception:
    client = None

# --- 3) Cloudinary ---
import cloudinary
import cloudinary.uploader as cldu

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    api_key=os.getenv("CLOUDINARY_API_KEY", ""),
    api_secret=os.getenv("CLOUDINARY_API_SECRET", ""),
    secure=True
)

# --- Répertoires front (pour servir l'UI en local si tu veux) ---
BASE_DIR = Path(__file__).resolve().parent            # .../backend
FRONT_DIR = (BASE_DIR / ".." / "frontend").resolve()  # .../frontend

# --- Switchs d'environnement ---
SERVE_FRONT = os.getenv("SERVE_FRONT", "false").lower() == "true"   # local: true / Render: false
DEBUG_MODE  = os.getenv("DEBUG", "false").lower() == "true"         # local: true / Render: false

OPENAI_IMAGE_SIZE = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024")  # '1024x1024' | '1024x1536' | '1536x1024' | 'auto'
OPENAI_IMAGE_COUNT = int(os.getenv("OPENAI_IMAGE_COUNT", "10"))

# --- Création Flask ---
if SERVE_FRONT:
    app = Flask(__name__, static_folder=str(FRONT_DIR), static_url_path="/front")
else:
    app = Flask(__name__)

# --- Debug & logs ---
app.config["DEBUG"] = DEBUG_MODE
app.config["PROPAGATE_EXCEPTIONS"] = DEBUG_MODE
logging.basicConfig(level=logging.DEBUG if DEBUG_MODE else logging.INFO)

# --- CORS autorisés (GitHub Pages + local) ---
allowed_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173,http://localhost:5173,https://joel3500.github.io"
).split(",")
allowed_origins = [o.strip() for o in allowed_origins if o.strip()]
CORS(app, resources={r"/generate": {"origins": allowed_origins}})

# --- Taille maximale des uploads (ex: 10 Mo) ---
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# =========================================================
# Helpers
# =========================================================

def _ensure_keys():
    missing = []
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not cloudinary.config().cloud_name:
        missing.append("CLOUDINARY_CLOUD_NAME")
    if not cloudinary.config().api_key:
        missing.append("CLOUDINARY_API_KEY")
    if not cloudinary.config().api_secret:
        missing.append("CLOUDINARY_API_SECRET")
    if missing:
        raise RuntimeError(f"Variables d'environnement manquantes: {', '.join(missing)}")

def _upload_to_cloudinary_from_bytes(image_bytes: bytes, public_id_prefix: str = "devine"):
    """Upload un buffer d'image à Cloudinary et retourne l'URL sécurisée."""
    resp = cldu.upload(
        io.BytesIO(image_bytes),
        folder="devine_le_visage",
        public_id=None,
        overwrite=True,
        resource_type="image"
    )
    return resp.get("secure_url")

def _openai_generate_images(prompt: str, n: int = 10, size: str = "512x512") -> List[bytes]:
    """
    Génère N images (bytes) via OpenAI gpt-image-1.
    NB: l'API renvoie du base64 ; on boucle pour N résultats.
    """
    if client is None:
        raise RuntimeError("Client OpenAI non initialisé (clé absente ?)")

    results = []
    for _ in range(n):
        res = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size=size
        )
        # res.data[0].b64_json
        b64 = res.data[0].b64_json
        results.append(base64.b64decode(b64))
    return results

# =============================================================
# Routes FRONT (seulement quand SERVE_FRONT=true, i.e. local)
# =============================================================
if SERVE_FRONT:
    @app.get("/")
    def index():
        idx = FRONT_DIR / "index.html"
        if not idx.exists():
            abort(404, description="index.html introuvable dans /frontend")
        return send_from_directory(FRONT_DIR, "index.html")

    @app.get("/<path:path>")
    def serve_static(path: str):
        target = FRONT_DIR / path
        if target.is_file():
            return send_from_directory(FRONT_DIR, path)
        if (FRONT_DIR / "index.html").exists():
            return send_from_directory(FRONT_DIR, "index.html")
        abort(404)

# =========================================================
# API
# =========================================================
@app.post("/generate")
def generate_child():
    try:
        _ensure_keys()

        # 1) Récup fichiers & options
        father = request.files.get("father")
        mother = request.files.get("mother")
        gender = request.form.get("gender")  # "man" | "woman" | None
        age_raw = request.form.get("age")
        
        # Validation de l'age
        if age_raw is None or age_raw == "":
            return jsonify({"error": "Âge requis (0 à 50)."}), 400
        
        try:
            age = int(age_raw)
        except ValueError:
            return jsonify({"error": "Âge invalide (doit être un entier)."}), 400
        
        if age < 0 or age > 50:
            return jsonify({"error": "Âge hors plage (0 à 50)."}), 400

        # Validation des photos du pere et de la mere
        if not father or not mother:
            raise ValueError("Images 'father' et 'mother' requises.")

        # 2) Uploader les photos parents dans Cloudinary (pour traçabilité / prompt)
        up_father = cldu.upload(father, folder="devine_le_visage/parents", resource_type="image")
        up_mother = cldu.upload(mother, folder="devine_le_visage/parents", resource_type="image")
        father_url = up_father.get("secure_url")
        mother_url = up_mother.get("secure_url")

        # 3) Construire le prompt pour OpenAI
        #    L’API images ne "fusionne" pas réellement deux visages.
        #    On donne une consigne descriptive ; les URLs aident à contextualiser le style/traits,
        #    mais le résultat reste une génération.
        # Remplace entièrement ton bloc base_prompt par ceci :
        base_prompt = (
            "Because of a fun, recreational activity for large families who want to discover the wonders of AI, "
            "generate a photorealistic portrait of a person whose facial features may be:\n"
            "- either only the father's;\n"
            "- or only the mother's;\n"
            "- or a plausible mix of both parents;\n"
            "- or some of the father's features combined with some of the mother's features.\n"
            "- Maintain neutral lighting and a studio background;\n"
            "- No text or watermark. Center the face, shoulders up;\n"
            "- Skin color should depend on the parent's skin color;\n"
            "- The hair shape should depend either on father's hair shape, either on mother's hair shape, either afro, either long hair; "
            f"Parent references: {father_url} and {mother_url}. "
        )

        # Ajoute la phrase d’âge (et adapte au genre si tu veux)
        if gender in ("boy", "garcon", "garçon", "man", "male", "m"):
            base_prompt += f"The boy/man is about {age} years old."
        elif gender in ("girl", "fille", "woman", "female", "w", "f"):
            base_prompt += f"The girl/woman is about {age} years old."
        else:
            base_prompt += f"The person is about {age} years old."

        # 4) Générer des images (N=10) avec OpenAI
        generated_bytes = _openai_generate_images(base_prompt, n=OPENAI_IMAGE_COUNT, size=OPENAI_IMAGE_SIZE)

        # 5) Uploader les résultats dans Cloudinary et retourner des URLs
        urls: List[str] = []
        for img_bytes in generated_bytes:
            url = _upload_to_cloudinary_from_bytes(img_bytes, public_id_prefix="devine_child")
            urls.append(url)

        return jsonify({"images": urls}), 200

    except Exception as e:
        logging.error("Erreur /generate: %s\n%s", str(e), traceback.format_exc())
        if DEBUG_MODE:
            return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500
        return jsonify({"error": "Erreur lors du traitement. Réessaie plus tard."}), 500


@app.get("/health")
def health():
    return {"ok": True}, 200


# ================= Lancement local =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # app.run(host="127.0.0.1", port=port, debug=DEBUG_MODE)
    app.run(host="0.0.0.0", port=port, debug=False)  # En prod (sur Render)
