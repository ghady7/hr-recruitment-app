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
    You are a professional HR Recruiter. 
    Task: 
    1. Extract the Candidate's Full Name from the resume.
    2. Compare the resume against the job requirements provided.
    
    JOB REQUIREMENTS:
    {job_description}
    
    RESUME TEXT:
    {resume_text}
    
    YOUR RESPONSE MUST FOLLOW THIS EXACT FORMAT:
    NAME: [Candidate Full Name]
    SCORE: [Number 0-100]
    SUMMARY: [2-3 sentences explaining why]
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