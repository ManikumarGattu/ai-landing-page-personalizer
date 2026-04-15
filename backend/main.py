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

# Gemini Client
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

# ✅ Stable model
MODEL_ID = "models/gemini-2.0-flash"


# ==============================
# HELPER FUNCTION
# ==============================
def extract_json(text: str):
    """Safely extract JSON from AI response"""
    try:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print("JSON PARSE ERROR:", e)
    return None


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
        res = requests.get(
            target_url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US,en;q=0.9"
            }
        )
        res.raise_for_status()
        soup = BeautifulSoup(res.content, "html.parser")
    except Exception as e:
        print("SCRAPE ERROR:", str(e))
        return {
            "success": False,
            "error": "Failed to fetch page"
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

Return ONLY JSON:
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
            contents=contents
        )

        ad_text = ad_res.text or ""
        print("AD AI RAW:", ad_text[:300])

        ad_data = extract_json(ad_text) or {
            "offer": "",
            "audience": "",
            "tone": ""
        }

    except Exception as e:
        print("AD AI ERROR:", str(e))
        ad_data = {"offer": "", "audience": "", "tone": ""}

    # ==============================
    # STEP 3: CRO ENGINE
    # ==============================
    prompt = f"""
You are a CRO expert.

STRICT RULES:
- No hallucination
- Use only given data
- CTA must be action-oriented (Get, Claim, Start, Explore Now)
- Add urgency if offer exists

Ad:
{json.dumps(ad_data)}

Page:
{json.dumps(headings)}

Return ONLY JSON:
{{
 "analysis": {{"mismatches": []}},
 "replacements": [],
 "cta": "",
 "paragraph": "",
 "reason": ""
}}
"""

    print("PROMPT:", prompt[:400])

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )

        ai_output = response.text or ""
        print("AI RAW:", ai_output[:400])

        parsed = extract_json(ai_output) or {
            "analysis": {"mismatches": ["AI returned invalid JSON"]},
            "replacements": [],
            "cta": "Explore Now",
            "paragraph": "Discover more.",
            "reason": "Fallback used"
        }

    except Exception as e:
        print("AI ERROR:", str(e))
        return {
            "success": False,
            "error": str(e)
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
                "original": original.strip(),
                "new": new.strip()
            })

    if not safe_replacements:
        safe_replacements = [
            {
                "original": headings[0]["text"],
                "new": parsed.get("cta", headings[0]["text"])
            }
        ]

    parsed["replacements"] = safe_replacements

    # ==============================
    # STEP 5: NORMALIZATION
    # ==============================
    parsed.setdefault("analysis", {"mismatches": []})
    parsed.setdefault("cta", headings[0]["text"])
    parsed.setdefault("paragraph", "Learn more about this offering.")
    parsed.setdefault("reason", "Improved alignment with ad intent.")

    parsed["cta"] = parsed["cta"].strip()
    parsed["paragraph"] = parsed["paragraph"].strip()

    # Limit paragraph length
    if len(parsed["paragraph"]) > 180:
        parsed["paragraph"] = " ".join(parsed["paragraph"].split()[:30]) + "..."

    if not parsed["paragraph"]:
        parsed["paragraph"] = "Explore more and discover value."

    # ==============================
    # STEP 6: APPLY CRO CHANGES
    # ==============================
    original_html = str(soup)

    try:
        replacements_map = {
            r["original"]: r["new"]
            for r in parsed["replacements"]
        }

        for tag in tags:
            txt = tag.get_text(strip=True)
            if txt in replacements_map:
                tag.string = replacements_map[txt]

        # Replace main heading
        main_heading = soup.find(["h1", "h2"])
        if main_heading:
            main_heading.string = parsed["cta"]

        # Replace paragraph
        p = soup.find("p")
        if p:
            p.string = parsed["paragraph"]

        # Fix relative links
        if soup.head:
            base = soup.new_tag("base", href=target_url)
            soup.head.insert(0, base)

        final_html = str(soup)

    except Exception as e:
        print("HTML ERROR:", str(e))
        final_html = original_html

    # ==============================
    # FINAL RESPONSE
    # ==============================
    return {
        "success": True,
        "data": {
            "ad_analysis": ad_data,
            "mismatches": parsed["analysis"]["mismatches"],
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