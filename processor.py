import fitz
import docx
from groq import Groq
import time
import os
from dotenv import load_dotenv

load_dotenv()

def extract_text_from_pdf(file_path):
    text=""
    with fitz.open(file_path) as doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_text_from_docx(file_path):
    doc=docx.Document(file_path)
    full_text=[]
    for para in doc.paragraphs:
        full_text.append(para.text)
    return "\n".join(full_text)


client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def analyze_resume_with_ai(resume_text, job_description):
    target_model = "llama-3.3-70b-versatile"
    
    prompt = f"""
You are a Senior Technical Recruiter with expertise in talent acquisition and gap analysis. Evaluate this candidate with EXTREME RIGOR and SPECIFICITY.

### CRITICAL EVALUATION CRITERIA:
1. **Exact Skill Match (0-30 points):**
   - Do they have ALL "must-have" skills listed in requirements? (Check explicitly)
   - Deduct heavily for missing core technologies
   - Give full points only for 100% match

2. **Experience Level Alignment (0-20 points):**
   - Count years of experience in EXACT role type
   - Junior (0-2 years) vs Mid (3-5 years) vs Senior (5+ years)
   - Deduct significantly if overqualified or underqualified

3. **Quantifiable Impact & Achievements (0-25 points):**
   - Look for numbers: revenue, team size, performance improvements
   - Vague descriptions = low score
   - Strong metrics and scale = high score

4. **Culture & Red Flags (0-15 points):**
   - Job hopping patterns?
   - Unexplained gaps?
   - Misaligned career trajectory?
   - Any concerning patterns deduct heavily

5. **Specific Technical Depth (0-10 points):**
   - Evidence of deep expertise in key technologies?
   - Training, certifications, or specialized knowledge?

### DATA INPUTS:
JOB REQUIREMENTS:
{job_description}

RESUME TEXT:
{resume_text}

### SCORING RULES (STRICT):
- Scores MUST vary significantly between candidates (0, 15, 28, 35, 42, 51, 58, 65, 72, 79, 88, 95)
- NO rounding to neat numbers like 40, 60, 80
- If missing even ONE "must-have" skill, cap score at 45 maximum
- If perfect match, score should be 75+
- If minimal experience, score should be below 30
- Score reflects TRUE capability match, not politeness

### RESPONSE FORMAT (MAINTAIN EXACTLY):
NAME: [Full Name from resume, or "Unknown" if not found]
SCORE: [Single integer 0-100, NO decimals or symbols]
SUMMARY: [2-3 sentences: (1) Key strengths & match points, (2) Critical gaps or weaknesses, (3) Explicit hiring recommendation]

IMPORTANT: Be CRITICAL and SPECIFIC. Differentiate between candidates clearly.
"""

    for attempt in range(3):
        try:
            chat_completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=target_model,
            )
            return chat_completion.choices[0].message.content
        except Exception as e:
            if "429" in str(e):
                print(f"Rate Limit hit. Waiting 10s...")
                time.sleep(10)
                continue
            else:
                return f"NAME: Unknown\nSCORE: 0\nSUMMARY: Error: {str(e)}"
    return "NAME: Unknown\nSCORE: 0\nSUMMARY: Failed after retries."