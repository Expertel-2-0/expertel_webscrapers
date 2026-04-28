import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from google import genai
from google.genai import types

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

CAPTCHA_PROMPT = """
Transcribe the visible text in this image.
Rules:
- Only the text, nothing else
- No explanations, comments, or additional formatting
- Only use standard ASCII characters (a-z, A-Z, 0-9)
- Convert all superscripts and subscripts to regular characters (e.g., ³ → 3, ₂ → 2)
- No special unicode characters
- If there is no text, respond with an empty string
- No spaces in the midle of the string
- If we get a result like for example "3L D3 S 8" you should return "3LD3S8"
- If we get a result like for example "4ZNK N6R7" you should return "4ZNKN6R7"
"""


def extract_text_from_image(image_path: Path) -> str:
    """Extract text from an image using Gemini."""

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    image_data = image_path.read_bytes()

    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(image_path.suffix.lower(), "image/jpeg")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_data, mime_type=media_type),
            CAPTCHA_PROMPT,
        ],
    )

    return response.text


def process_images_folder(folder_name: str = "imagenes") -> dict:
    """Procesa todas las imágenes en una carpeta del proyecto."""

    # Ruta relativa al directorio del script
    script_dir = Path(__file__).parent
    images_folder = script_dir / folder_name

    if not images_folder.exists():
        images_folder.mkdir()
        print(f"Folder '{folder_name}' created. Add images and run again.")
        return {}

    extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    images = [f for f in images_folder.iterdir() if f.suffix.lower() in extensions]

    if not images:
        print(f"No images in '{folder_name}'")
        return {}

    results = {}
    for image_path in images:
        print(f"Processing: {image_path.name}")
        results[image_path.name] = extract_text_from_image(image_path)

    return results


if __name__ == "__main__":
    image_path = Path("captcha_screenshots/captcha_20251229_170438.png")
    result = extract_text_from_image(image_path)
    print(f"Extracted text: {result}")
