from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types
import os
import json
import re
from dotenv import load_dotenv

# ==============================
# INIT
# ==============================
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
MODEL_ID = "gemini-flash-latest"


# ==============================
# MAIN API
# ==============================
@app.post("/api/personalize")
async def personalize_page(
    target_url: str = Form(...),
    ad_image: UploadFile = File(None),
    ad_link: str = Form(None)
):
    # ==============================
    # VALIDATION
    # ==============================
    if not (ad_image or (ad_link and ad_link.strip())):
        raise HTTPException(status_code=400, detail="Provide valid ad input")

    print("URL:", target_url)
    print("AD:", ad_link)

    # ==============================
    # STEP 1: FETCH PAGE
    # ==============================
    try:
        response = requests.get(
            target_url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
    except Exception:
        return {
            "success": False,
            "error": "Unable to fetch page (site may block scraping)"
        }

    headings = []
    tags = []

    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = tag.get_text(strip=True)
        if text:
            headings.append({"type": tag.name, "text": text})
            tags.append(tag)

    if not headings:
        return {
            "success": False,
            "error": "No headings found on page"
        }

    # ==============================
    # STEP 2: AD ANALYSIS
    # ==============================
    ad_prompt = """
Extract structured info from this ad.

Return JSON:
{
  "offer": "",
  "audience": "",
  "tone": ""
}
"""

    contents = [ad_prompt]

    if ad_image:
        image_bytes = await ad_image.read()
        contents.append(
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=ad_image.content_type or "image/png"
            )
        )
    else:
        contents.append(f"Ad Content: {ad_link}")

    try:
        ad_res = client.models.generate_content(
            model=MODEL_ID,
            contents=contents,
            config={"temperature": 0.3}
        )

        ad_text = ad_res.text or ""
        match = re.search(r"\{.*\}", ad_text, re.DOTALL)

        ad_data = json.loads(match.group(0)) if match else {
            "offer": "", "audience": "", "tone": ""
        }

    except Exception:
        ad_data = {"offer": "", "audience": "", "tone": ""}

    # ==============================
    # STEP 3: CRO ENGINE
    # ==============================
    prompt = f"""
You are a CRO expert.

STRICT RULES:
- No hallucination
- No fake claims
- Use only given content
- CTA must be action-driven (use words like "Start", "Get", "Claim", "Explore Now")
CTA must include urgency if offer exists (e.g., "Limited Time", "Today", "Now")
- Return valid JSON only

Ad:
{json.dumps(ad_data)}

Page:
{json.dumps(headings)}

Return:
{{
 "analysis": {{"mismatches": []}},
 "replacements": [],
 "cta": "",
 "paragraph": "",
 "reason": ""
}}
"""

    try:
        ai_res = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config={
                "temperature": 0.3,
                "top_p": 0.8,
                "top_k": 20
            }
        )

        ai_text = ai_res.text or ""
        print("AI RAW:", ai_text)

        match = re.search(r"\{.*\}", ai_text, re.DOTALL)

        if match:
            parsed = json.loads(match.group(0))
        else:
            parsed = {
                "analysis": {"mismatches": ["AI invalid output"]},
                "replacements": [],
                "cta": "Explore Now",
                "paragraph": "Discover more.",
                "reason": "Fallback used"
            }

    except Exception as e:
        print("AI ERROR:", e)
        return {
            "success": False,
            "error": "AI processing failed"
        }

    # ==============================
    # STEP 4: SAFE REPLACEMENTS
    # ==============================
    safe_replacements = []

    for item in parsed.get("replacements", []):

        original = (
            item.get("original") or
            item.get("old") or
            item.get("old_text") or
            ""
        )

        new = (
            item.get("new") or
            item.get("new_text") or
            ""
        )

        if original and new:
            safe_replacements.append({
                "original": original,
                "new": new
            })

    # Ensure at least one replacement
    if not safe_replacements:
        safe_replacements = [
            {
                "original": headings[0]["text"],
                "new": parsed.get("cta", headings[0]["text"])
            }
        ]

    parsed["replacements"] = safe_replacements

    # ==============================
    # STEP 5: DEFAULTS + NORMALIZATION
    # ==============================
    parsed.setdefault("analysis", {"mismatches": []})
    parsed.setdefault("cta", headings[0]["text"] if headings else "Explore Now")
    parsed.setdefault("paragraph", "Learn more about this offering.")
    parsed.setdefault("reason", "Improved alignment with ad intent.")

    parsed["cta"] = parsed["cta"].strip()

    parsed["paragraph"] = parsed["paragraph"].strip()

    if len(parsed["paragraph"]) > 160:
        words = parsed["paragraph"].split()
        parsed["paragraph"] = " ".join(words[:30]) + "..."

    if not parsed["paragraph"].strip():
        parsed["paragraph"] = "Explore this offering and discover more value."

    # ==============================
    # STEP 6: APPLY CRO CHANGES
    # ==============================
    original_html = str(soup)

    try:
        replacements = {}

        for item in parsed.get("replacements", []):
            original = item.get("original", "").strip()
            new = item.get("new", "")

            if original and new:
                replacements[original] = new

        for tag in tags:
            txt = tag.get_text(strip=True)
            if txt in replacements:
                tag.string = replacements[txt]

        # Replace main heading (h1 or h2)
        main_heading = soup.find(["h1", "h2"])
        if main_heading:
            main_heading.string = parsed["cta"]

        # Replace first paragraph
        p = soup.find("p")
        if p:
            p.string = parsed["paragraph"]

        # Fix relative links
        if soup.head:
            base = soup.new_tag("base", href=target_url)
            soup.head.insert(0, base)

        final_html = str(soup)

    except Exception as e:
        print("UI ERROR:", e)
        final_html = original_html

    # ==============================
    # FINAL RESPONSE
    # ==============================
    return {
        "success": True,
        "data": {
            "ad_analysis": ad_data,
            "mismatches": parsed.get("analysis", {}).get("mismatches", []),
            "replacements": parsed["replacements"],
            "cta": parsed["cta"],
            "paragraph": parsed["paragraph"],
            "reason": parsed["reason"],
            "html": final_html,
            "confidence": "High"
        }
    }


@app.get("/")
def root():
    return {"message": "AI Personalization API Running"}