import os
import shutil
import re
import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from processor import extract_text_from_pdf, extract_text_from_docx, analyze_resume_with_ai

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

DB_CONFIG = os.getenv("DATABASE_URL")

if not DB_CONFIG:
    raise ValueError("DATABASE_URL environment variable is not set") 

def get_db_connection():
    try:
        return psycopg2.connect(DB_CONFIG)
    except psycopg2.Error as e:
        print(f"Database connection error: {str(e)}")
        raise  

# --- WEB ROUTE ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/create-job/")
def create_job(title: str, tag: str, requirements: str):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO jobs (job_title, job_tag, requirements) VALUES (%s, %s, %s) RETURNING id",
                    (title, tag, requirements)
                )
                job_id = cur.fetchone()[0]
                conn.commit()
        return {"message": "Job created successfully", "job_id": job_id}
    except psycopg2.IntegrityError:
        return {"error": "Job Tag already exists. Please use a unique ID."}
    except Exception as e:
        return {"error": f"Failed to create job: {str(e)}"}

@app.post("/upload/")
async def upload_resumes(job_id: int, files: list[UploadFile] = File(...)):
    os.makedirs("temp", exist_ok=True)
    count = 0
    for file in files:
        file_path = f"temp/{file.filename}"
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        content = extract_text_from_pdf(file_path) if file.filename.endswith(".pdf") else extract_text_from_docx(file_path)

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO resumes (filename, content, job_id) VALUES (%s, %s, %s)", 
                    (file.filename, content, job_id)
                )
                conn.commit()
        os.remove(file_path)
        count += 1
    return {"message": f"Successfully uploaded {count} resumes."}

@app.post("/analyze-batch/")
def analyze_batch(job_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT requirements FROM jobs WHERE id = %s", (job_id,))
            job_data = cur.fetchone()
            if not job_data:
                return {"error": "Job not found"}
            
            requirements = job_data[0]

            cur.execute("SELECT id, content FROM resumes WHERE job_id = %s AND match_score IS NULL", (job_id,))
            rows = cur.fetchall()
            
            processed_count = 0
            for res_id, content in rows:
                raw_ai_output = analyze_resume_with_ai(content, requirements)
                
                name_match = re.search(r"NAME:\s*(.*)", raw_ai_output)
                score_match = re.search(r"SCORE:\s*(\d+)", raw_ai_output)
                summary_match = re.search(r"SUMMARY:\s*(.*)", raw_ai_output, re.DOTALL)

                ext_name = name_match.group(1).strip() if name_match else "Unknown"
                ext_score = int(score_match.group(1)) if score_match else 0
                ext_summary = summary_match.group(1).strip() if summary_match else raw_ai_output

                cur.execute(
                    "UPDATE resumes SET candidate_name = %s, match_score = %s, ai_analysis = %s WHERE id = %s",
                    (ext_name, ext_score, ext_summary, res_id)
                )
                processed_count += 1
            
            conn.commit()
    return {"status": "Complete", "analyzed": processed_count}

# --- ROUTE 4: RANKINGS ---
@app.get("/rankings/")
def get_rankings(job_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT filename, candidate_name, match_score, ai_analysis 
                FROM resumes 
                WHERE job_id = %s 
                ORDER BY match_score DESC
            """, (job_id,))
            rows = cur.fetchall()
            return {"rankings": [{"filename": r[0], "candidate_name": r[1], "score": r[2], "summary": r[3]} for r in rows]}
        
@app.get("/jobs/")
def get_all_jobs():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, job_title, job_tag, created_at FROM jobs ORDER BY created_at DESC")
            rows = cur.fetchall()
            return {"jobs": [{"id": r[0], "title": r[1], "tag": r[2], "date": str(r[3])} for r in rows]}