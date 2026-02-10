import os
import shutil
import re
import psycopg2
import csv
import io
import uuid
import json
from typing import Optional, Dict
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from processor import extract_text_from_pdf, extract_text_from_docx, analyze_resume_with_ai
from auth import (
    create_access_token, create_refresh_token, verify_token, 
    register_user, login_user, get_user_by_id,
    create_guest_session, get_guest_session, update_guest_session_data,
    migrate_guest_session_to_user, extract_token_from_request, extract_guest_token_from_request
)

load_dotenv()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

# ==================== REQUEST MODELS ====================
class LoginRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str = None

class RefreshTokenRequest(BaseModel):
    refresh_token: str

DB_CONFIG = os.getenv("DATABASE_URL")

if not DB_CONFIG:
    raise ValueError("DATABASE_URL environment variable is not set") 

def get_db_connection():
    try:
        return psycopg2.connect(DB_CONFIG)
    except psycopg2.Error as e:
        print(f"Database connection error: {str(e)}")
        raise

def get_user_id_from_request(request: Request) -> Optional[str]:
    """Extract user_id from token or guest session"""
    # Try auth token first
    token = extract_token_from_request(request)
    if token:
        token_data = verify_token(token)
        if token_data:
            return token_data.get("user_id")
    
    # Try guest session
    guest_token = extract_guest_token_from_request(request)
    if guest_token:
        session = get_guest_session(guest_token)
        if session:
            return None  # Guests don't have user_id
    
    return None

# ==================== AUTH ENDPOINTS ====================

@app.post("/auth/signup")
async def signup(request: SignupRequest):
    """Register a new user"""
    try:
        user = register_user(request.email, request.password, request.full_name)
        access_token = create_access_token(user["id"], user["email"])
        refresh_token = create_refresh_token(user["id"], user["email"])
        
        return {
            "success": True,
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
async def login(request: LoginRequest):
    """Login user with email and password"""
    try:
        user = login_user(request.email, request.password)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        access_token = create_access_token(user["id"], user["email"])
        refresh_token = create_refresh_token(user["id"], user["email"])
        
        return {
            "success": True,
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@app.post("/auth/refresh")
async def refresh(request: RefreshTokenRequest):
    """Refresh access token using refresh token"""
    token_data = verify_token(request.refresh_token)
    if not token_data or token_data.get("token_type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    
    user_id = token_data.get("user_id")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    access_token = create_access_token(user_id, user["email"])
    return {
        "success": True,
        "access_token": access_token,
        "token_type": "bearer"
    }

@app.get("/auth/me")
async def get_current_user(request: Request):
    """Get current authenticated user"""
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token_data = verify_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    user = get_user_by_id(token_data.get("user_id"))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return {"success": True, "user": user}

# ==================== GUEST SESSION ENDPOINTS ====================

@app.post("/guest-session")
async def create_guest_session_endpoint():
    """Create a new guest session"""
    try:
        session_token = create_guest_session()
        return {
            "success": True,
            "session_token": session_token,
            "message": "Guest session created"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create guest session: {str(e)}")

@app.get("/guest-session/{session_token}")
async def get_guest_session_data(session_token: str):
    """Get guest session data"""
    try:
        session = get_guest_session(session_token)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        return {
            "success": True,
            "session": session
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/guest-session/{session_token}")
async def update_guest_data(session_token: str, data: Dict = None):
    """Update guest session data"""
    try:
        if data is None:
            data = {}
        success = update_guest_session_data(session_token, data)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to update session")
        
        return {
            "success": True,
            "message": "Session updated"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- WEB ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Redirect root to login page"""
    return RedirectResponse(url="/login")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page with authentication UI"""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard page"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/create-job/")
def create_job(request: Request, title: str, tag: str, requirements: str):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO jobs (job_title, job_tag, requirements, user_id) VALUES (%s, %s, %s, %s) RETURNING id",
                    (title, tag, requirements, user_id)
                )
                job_id = cur.fetchone()[0]
                conn.commit()
        return {"message": "Job created successfully", "job_id": job_id, "user_id": user_id}
    except psycopg2.IntegrityError:
        return {"error": "Job Tag already exists. Please use a unique ID."}
    except Exception as e:
        return {"error": f"Failed to create job: {str(e)}"}

@app.post("/upload/")
async def upload_resumes(request: Request, job_id: int, files: list[UploadFile] = File(...)):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        # Verify job belongs to user
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM jobs WHERE id = %s", (job_id,))
                result = cur.fetchone()
                if not result or result[0] != user_id:
                    raise HTTPException(status_code=403, detail="You don't have permission to upload to this job")
        
        os.makedirs("temp", exist_ok=True)
        count = 0
        duplicates = 0
        for file in files:
            file_path = f"temp/{file.filename}"
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            content = extract_text_from_pdf(file_path) if file.filename.endswith(".pdf") else extract_text_from_docx(file_path)

            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Check if this resume already exists for this job
                    cur.execute(
                        "SELECT id FROM resumes WHERE filename = %s AND job_id = %s",
                        (file.filename, job_id)
                    )
                    if cur.fetchone():
                        duplicates += 1
                        os.remove(file_path)
                        continue
                    
                    cur.execute(
                        "INSERT INTO resumes (filename, content, job_id, user_id) VALUES (%s, %s, %s, %s)", 
                        (file.filename, content, job_id, user_id)
                    )
                    conn.commit()
            os.remove(file_path) if os.path.exists(file_path) else None
            count += 1
        
        return {"added": count, "skipped": duplicates, "message": f"Successfully uploaded {count} resumes. ({duplicates} duplicate(s) skipped)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze-batch/")
def analyze_batch(request: Request, job_id: int):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Verify job belongs to user
                cur.execute("SELECT requirements, user_id FROM jobs WHERE id = %s", (job_id,))
                job_data = cur.fetchone()
                if not job_data:
                    return {"error": "Job not found"}
                
                if job_data[1] != user_id:
                    raise HTTPException(status_code=403, detail="You don't have permission to analyze this job")
                
                requirements = job_data[0]

                cur.execute("SELECT id, content FROM resumes WHERE job_id = %s AND user_id = %s AND match_score IS NULL", (job_id, user_id))
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROUTE 4: RANKINGS ---
@app.get("/rankings/")
def get_rankings(request: Request, job_id: int):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Verify job belongs to user
                cur.execute("SELECT id FROM jobs WHERE id = %s AND user_id = %s", (job_id, user_id))
                if not cur.fetchone():
                    raise HTTPException(status_code=403, detail="You don't have permission to view this job")
                
                cur.execute("""
                    SELECT filename, candidate_name, match_score, ai_analysis 
                    FROM resumes 
                    WHERE job_id = %s AND user_id = %s
                    ORDER BY match_score DESC
                """, (job_id, user_id))
                rows = cur.fetchall()
                return {"rankings": [{"filename": r[0], "candidate_name": r[1], "score": r[2], "summary": r[3]} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROUTE 5: EXPORT TO CSV ---
@app.get("/export-csv/")
def export_to_csv(request: Request, job_id: int):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Get job info for filename
                cur.execute("SELECT job_title, job_tag, user_id FROM jobs WHERE id = %s", (job_id,))
                job_info = cur.fetchone()
                if not job_info:
                    return {"error": "Job not found"}
                
                # Verify job belongs to user
                if job_info[2] != user_id:
                    raise HTTPException(status_code=403, detail="You don't have permission to export this job")
                
                job_title, job_tag = job_info[0], job_info[1]
                
                # Get all rankings sorted by score
                cur.execute("""
                    SELECT filename, candidate_name, match_score, ai_analysis 
                    FROM resumes 
                    WHERE job_id = %s AND user_id = %s
                    ORDER BY match_score DESC
                """, (job_id, user_id))
                rows = cur.fetchall()
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(["Rank", "Candidate Name", "Match Score (%)", "Analysis Summary", "Resume File"])
        
        # Write data rows
        for rank, (filename, name, score, summary) in enumerate(rows, 1):
            writer.writerow([rank, name, score, summary, filename])
        
        # Generate filename
        filename = f"{job_tag}_results.csv"
        
        # Return as file download
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return {"error": f"Export failed: {str(e)}"}
        
@app.delete("/delete-job/")
def delete_job(request: Request, job_id: int):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Verify job belongs to user
                cur.execute("SELECT user_id FROM jobs WHERE id = %s", (job_id,))
                result = cur.fetchone()
                if not result or result[0] != user_id:
                    raise HTTPException(status_code=403, detail="You don't have permission to delete this job")
                
                # Delete all resumes associated with this job
                cur.execute("DELETE FROM resumes WHERE job_id = %s", (job_id,))
                # Delete the job
                cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
                conn.commit()
        return {"message": "Job deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/")
def get_all_jobs(request: Request):
    try:
        # Extract user_id from token
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, job_title, job_tag, created_at FROM jobs WHERE user_id = %s ORDER BY created_at DESC",
                    (user_id,)
                )
                rows = cur.fetchall()
                return {"jobs": [{"id": r[0], "title": r[1], "tag": r[2], "date": str(r[3])} for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))