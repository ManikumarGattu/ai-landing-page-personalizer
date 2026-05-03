from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from groq import Groq
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

API_KEY = os.getenv("GROQ_API_KEY")

if not API_KEY:
    raise Exception("GROQ_API_KEY is missing!")

client = Groq(api_key=API_KEY)

MODEL_ID = "llama3-70b-8192"


# ==============================
# HELPER FUNCTION
# ==============================
def extract_json(text: str):
    try:
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception as e:
        print("JSON ERROR:", e)
    return None


# ==============================
# MAIN API
# ==============================
@app.post("/api/personalize")
async def personalize_page(
    target_url: str = Form(...),
    ad_image: UploadFile = File(None),  # Ignored (not supported in Groq)
    ad_link: str = Form(None)
):

    if not (ad_link and ad_link.strip()):
        raise HTTPException(status_code=400, detail="Provide ad text")

    print("URL:", target_url)
    print("AD:", ad_link)

    # ==============================
    # STEP 1: SCRAPE PAGE
    # ==============================
    try:
        res = requests.get(
            target_url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        res.raise_for_status()
        soup = BeautifulSoup(res.content, "html.parser")
    except Exception as e:
        return {"success": False, "error": "Failed to fetch page"}

    headings = []
    tags = []

    for tag in soup.find_all(["h1", "h2", "h3"]):
        txt = tag.get_text(strip=True)
        if txt:
            headings.append({"type": tag.name, "text": txt})
            tags.append(tag)

    if not headings:
        return {"success": False, "error": "No headings found"}

    # ==============================
    # STEP 2: AD ANALYSIS (GROQ)
    # ==============================
    ad_prompt = f"""
Extract structured JSON from this ad:

Ad: {ad_link}

Return ONLY:
{{
 "offer": "",
 "audience": "",
 "tone": ""
}}
"""

    try:
        ad_response = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "user", "content": ad_prompt}]
        )

        ad_text = ad_response.choices[0].message.content
        print("AD RAW:", ad_text[:200])

        ad_data = extract_json(ad_text) or {
            "offer": "", "audience": "", "tone": ""
        }

    except Exception as e:
        print("AD ERROR:", e)
        ad_data = {"offer": "", "audience": "", "tone": ""}

    # ==============================
    # STEP 3: CRO ENGINE
    # ==============================
    prompt = f"""
You are a CRO expert.

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

    try:
        response = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "user", "content": prompt}]
        )

        ai_output = response.choices[0].message.content
        print("AI RAW:", ai_output[:300])

        parsed = extract_json(ai_output) or {
            "analysis": {"mismatches": []},
            "replacements": [],
            "cta": "Explore Now",
            "paragraph": "Discover more",
            "reason": "Fallback"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

    # ==============================
    # STEP 4: SAFE REPLACEMENTS
    # ==============================
    safe = []

    for item in parsed.get("replacements", []):
        old = item.get("original") or item.get("old") or ""
        new = item.get("new") or ""

        if old and new:
            safe.append({"original": old, "new": new})

    if not safe:
        safe = [{
            "original": headings[0]["text"],
            "new": parsed.get("cta", headings[0]["text"])
        }]

    parsed["replacements"] = safe

    # ==============================
    # STEP 5: APPLY CHANGES
    # ==============================
    try:
        mapping = {i["original"]: i["new"] for i in safe}

        for tag in tags:
            txt = tag.get_text(strip=True)
            if txt in mapping:
                tag.string = mapping[txt]

        h1 = soup.find(["h1", "h2"])
        if h1:
            h1.string = parsed["cta"]

        p = soup.find("p")
        if p:
            p.string = parsed["paragraph"]

        final_html = str(soup)

    except Exception:
        final_html = str(soup)

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
            "html": final_html
        }
    }


@app.get("/")
def root():
    return {"message": "Groq AI Backend Running"}