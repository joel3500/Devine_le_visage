import os
import uuid
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from openai import OpenAI
import cloudinary
import cloudinary.uploader

# ========== upload_to_cloudinary (Librairie permettant la signature exacte ) ==========================

import hashlib
import hmac
import time
from urllib.parse import urlencode

from flask_cors import CORS

# ========== Chargement des variables d'environnement ==========

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# ========== Config Flask ==========
app = Flask(__name__)

# --- CORS (origines autorisées) ---
# Lis une variable d'env optionnelle FRONTEND_ORIGINS pour autoriser ton frontend en prod
# Valeur par défaut = local dev ports 5173
allowed_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://127.0.0.1:5173, http://localhost:5173"
).split(",")

# Nettoyage des espaces fortsuitifs
allowed_origins = [o.strip() for o in allowed_origins if o.strip()]

# Autorise CORS uniquement sur l'endpoint /generate
CORS(
    app,
    resources={r"/generate": {"origins": allowed_origins}},
    supports_credentials=False
)


FRONTEND_ORIGINS='https://joel3500.github.io, http://127.0.0.1:5173, http://localhost:5173'
# FRONTEND_ORIGINS='https://joel3500.github.io/Devine_le_visage/index, http://127.0.0.1:5173, http://localhost:5173'

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ========== Fonctions IA ==========

def upload_to_cloudinary(file, public_id):
    timestamp = int(time.time())
    folder = "visages_parents"
    params = {
        "folder": folder,
        "overwrite": "1",
        "public_id": public_id,
        "timestamp": timestamp,
        "unique_filename": "0",
        "use_filename": "1"
    }

    # Étape critique : l’ordre doit être alphabétique par clé
    sorted_params = dict(sorted(params.items()))
    to_sign = urlencode(sorted_params, doseq=True)
    to_sign = to_sign.replace('%2C', ',')  # Cloudinary veut des virgules, pas %2C
    to_sign = to_sign.replace('+', '%20')  # Facultatif

    # Supprimer tous les encodages URL non supportés (parfois nécessaire)
    to_sign = to_sign.replace('%3A', ':')

    signature = hmac.new(
        os.environ["CLOUDINARY_API_SECRET"].encode("utf-8"),
        msg=to_sign.encode("utf-8"),
        digestmod=hashlib.sha1
    ).hexdigest()

    # Ajouter la signature et l’API key
    upload_params = dict(sorted_params)
    upload_params["signature"] = signature
    upload_params["api_key"] = os.environ["CLOUDINARY_API_KEY"]

    result = cloudinary.uploader.upload(
        file,
        **upload_params
    )

    return result["secure_url"]

def get_parent_traits(image_url, role):
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "Tu es un expert en descriptions de portraits réalistes."
            },
            {
                "role": "user",
                "content": f"À partir de cette photo ({image_url}), décris brièvement les caractéristiques visibles comme les cheveux, yeux, teint et expression."
            }
        ],
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

def build_prompt(father_desc, mother_desc, gender):
    return (
        f"Photorealistic portrait of a 10-year-old {'boy' if gender == 'boy' else 'girl'}, "
        f"with features inherited from a father who is {father_desc}, and a mother who is {mother_desc}. "
        f"The child has a calm expression, a slight smile, and appears natural. Neutral background. High-quality."
    )

def generate_image(prompt):
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        n=1,
        size="1024x1024"
    )
    return response.data[0].url

# ========== Endpoint principal ==========

@app.route("/generate", methods=["POST"])
def generate_child():
    father_file = request.files.get("father")
    mother_file = request.files.get("mother")
    gender = request.form.get("gender", "girl")

    if not (father_file and mother_file):
        return jsonify({"error": "Les deux fichiers image sont requis."}), 400

    if not (allowed_file(father_file.filename) and allowed_file(mother_file.filename)):
        return jsonify({"error": "Formats autorisés : JPG, JPEG, PNG"}), 400

    try:
        # Upload vers Cloudinary
        father_url = upload_to_cloudinary(father_file, "father")
        mother_url = upload_to_cloudinary(mother_file, "mother")

        # Analyse GPT-4 Vision
        father_desc = get_parent_traits(father_url, "père")
        mother_desc = get_parent_traits(mother_url, "mère")

        # Création du prompt
        prompt = build_prompt(father_desc, mother_desc, gender)

        # Génération des images
        images = [generate_image(prompt) for _ in range(5)]

        return jsonify({"images": images})

    except Exception as e:
        # Log complet côté serveur  ( en local )
        print("Erreur :", str(e))
        import traceback
        traceback.print_exc()  # 👈 pour afficher toute la pile d'erreur

        # Log complet côté serveur  ( en dev sur Render )
        logging.error("Erreur /generate: %s\n%s", str(e), traceback.format_exc())
        # Message clair côté client
        return jsonify({"error": str(e)}), 500  # 👈 utile pour debug

# optionnel mais pratique pour Render
@app.get("/health")
def health():
    return {"ok": True}, 200

# ========== Lancement local ==========
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
