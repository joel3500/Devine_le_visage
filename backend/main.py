import os
from openai import OpenAI
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# === INPUTS ===
father_url = "https://res.cloudinary.com/demo/image/upload/w_600,h_800,c_fill/face_left.jpg"
mother_url = "https://res.cloudinary.com/demo/image/upload/w_600,h_800,c_fill/face_right.jpg"

gender = "girl"  # ou "boy"

# === GPT-4 VISION : extraire les descriptions ===
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

# === Construction du prompt ===
def build_prompt(father_desc, mother_desc, gender):
    return (
        f"Photorealistic portrait of a 10-year-old {'boy' if gender == 'boy' else 'girl'}, "
        f"with features inherited from a father who is {father_desc}, and a mother who is {mother_desc}. "
        f"The child has a calm expression, a slight smile, and appears natural. Neutral background. High-quality."
    )

# === Génération d’image avec DALL·E 3 ===
def generate_image(prompt):
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        n=1,
        size="1024x1024"
    )
    return response.data[0].url

# === Processus complet ===
if __name__ == "__main__":
    father_desc = get_parent_traits(father_url, "père")
    mother_desc = get_parent_traits(mother_url, "mère")

    print("\n📌 Description père :", father_desc)
    print("📌 Description mère :", mother_desc)

    prompt = build_prompt(father_desc, mother_desc, gender)
    print("\n🧠 Prompt utilisé :", prompt)

    image_url = generate_image(prompt)
    print("\n🖼️ Image générée :", image_url)
