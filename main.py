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
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from processor import extract_text_from_pdf, extract_text_from_docx, analyze_resume_with_ai
from auth import (
    create_access_token, create_refresh_token, verify_token, 
    register_user, login_user, get_user_by_id,
    extract_token_from_request
)

load_dotenv()

app = FastAPI(title="HR Recruitment App", version="1.0.0")

# ==================== CORS CONFIGURATION ====================
# Enable CORS for all origins during development, restrict in production
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== STATIC FILES ====================
# Mount static files for CSS, JS, images, etc.
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# ==================== HEALTH & STATUS ENDPOINTS ====================

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "hr-recruitment-app"}

@app.get("/favicon.ico")
async def favicon():
    """Favicon endpoint - returns a simple response to prevent 404 logs"""
    # You can replace this with an actual favicon file path if available
    return FileResponse("static/favicon.ico") if os.path.exists("static/favicon.ico") else JSONResponse({"message": "No favicon"})

@app.get("/debug/token")
async def debug_token(request: Request):
    """Debug endpoint to verify token extraction and verification"""
    import base64
    
    token = extract_token_from_request(request)
    
    debug_info = {
        "token_found": token is not None,
        "token_length": len(token) if token else 0,
        "headers_received": dict(request.headers),
    }
    
    if token:
        debug_info["token_first_20_chars"] = token[:20] + "..." if len(token) > 20 else token
        debug_info["token_last_20_chars"] = "..." + token[-20:] if len(token) > 20 else token
        
        # Try to decode
        try:
            padding_needed = 4 - (len(token) % 4)
            if padding_needed != 4:
                token_padded = token + '=' * padding_needed
            else:
                token_padded = token
            
            token_bytes = base64.b64decode(token_padded, validate=True)
            token_str = token_bytes.decode('utf-8')
            payload = json.loads(token_str)
            
            debug_info["decode_success"] = True
            debug_info["payload"] = payload
            
            # Now verify
            token_data = verify_token(token)
            debug_info["token_valid"] = token_data is not None
            debug_info["token_data"] = token_data if token_data else "VERIFICATION FAILED"
        except Exception as e:
            debug_info["decode_success"] = False
            debug_info["decode_error"] = str(e)
            debug_info["token_valid"] = False
            debug_info["token_data"] = f"DECODE ERROR: {str(e)}"
    else:
        debug_info["token_valid"] = False
        debug_info["token_data"] = "NO TOKEN FOUND"
    
    return debug_info

@app.get("/debug/token-test")
async def debug_token_test():
    """Test token creation and verification round-trip"""
    test_user_id = str(uuid.uuid4())
    test_email = "test@example.com"
    
    # Create tokens
    access_token = create_access_token(test_user_id, test_email)
    refresh_token = create_refresh_token(test_user_id, test_email)
    
    # Verify tokens
    access_data = verify_token(access_token)
    refresh_data = verify_token(refresh_token)
    
    return {
        "test_user_id": test_user_id,
        "test_email": test_email,
        "access_token": {
            "created": access_token[:30] + "..." + access_token[-10:] if len(access_token) > 40 else access_token,
            "length": len(access_token),
            "verification": access_data if access_data else "FAILED",
        },
        "refresh_token": {
            "created": refresh_token[:30] + "..." + refresh_token[-10:] if len(refresh_token) > 40 else refresh_token,
            "length": len(refresh_token),
            "verification": refresh_data if refresh_data else "FAILED",
        },
        "roundtrip_success": access_data is not None and refresh_data is not None
    }

# ==================== REQUEST MODELS ====================
class LoginRequest(BaseModel):
    email: str
    password: str

class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str = None

class CreateJobRequest(BaseModel):
    job_title: str
    job_tag: str
    requirements: str

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



# ==================== AUTH ENDPOINTS ====================

@app.post("/auth/signup")
async def signup(request: SignupRequest):
    """Register a new user"""
    try:
        # Validate email format
        if not request.email or "@" not in request.email:
            raise HTTPException(status_code=400, detail="Invalid email format")
        
        if not request.password or len(request.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
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
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "already exists" in error_msg.lower():
            raise HTTPException(status_code=409, detail="Email already registered")
        raise HTTPException(status_code=400, detail=error_msg)

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
    try:
        token = extract_token_from_request(request)
        if not token:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        token_data = verify_token(token)
        if not token_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        user_id = token_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token - no user_id")
        
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Return user data directly (not wrapped in success/user structure)
        # The frontend expects: {id, email, full_name, ...}
        return {
            "id": user.get("id"),
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "created_at": str(user.get("created_at")) if user.get("created_at") else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

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
async def create_job(request: Request, job_data: CreateJobRequest):
    try:
        # Validate inputs
        if not job_data.job_title or not job_data.job_title.strip():
            raise HTTPException(status_code=400, detail="Job title cannot be empty")
        if not job_data.job_tag or not job_data.job_tag.strip():
            raise HTTPException(status_code=400, detail="Job tag cannot be empty")
        if not job_data.requirements or not job_data.requirements.strip():
            raise HTTPException(status_code=400, detail="Requirements cannot be empty")
        
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
                    (job_data.job_title, job_data.job_tag, job_data.requirements, user_id)
                )
                job_id = cur.fetchone()[0]
                conn.commit()
        return {"success": True, "message": "Job created successfully", "job_id": job_id, "user_id": user_id}
    except HTTPException:
        raise
    except psycopg2.IntegrityError as e:
        error_msg = str(e)
        if "job_tag" in error_msg:
            raise HTTPException(status_code=409, detail="Job tag already exists. Please use a unique tag.")
        raise HTTPException(status_code=409, detail="Database conflict error")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create job: {str(e)}")

@app.post("/upload/")
async def upload_resumes(request: Request, job_id: int, files: list[UploadFile] = File(...)):
    try:
        # Validate inputs
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")
        
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
        errors = []
        
        for file in files:
            try:
                file_path = f"temp/{file.filename}"
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

                # Extract text based on file type
                if file.filename.endswith(".pdf"):
                    content = extract_text_from_pdf(file_path)
                elif file.filename.endswith((".docx", ".doc")):
                    content = extract_text_from_docx(file_path)
                else:
                    errors.append(f"{file.filename}: Unsupported file type")
                    os.remove(file_path)
                    continue

                if not content or not content.strip():
                    errors.append(f"{file.filename}: Could not extract text from file")
                    os.remove(file_path)
                    continue

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
                count += 1
                
            except Exception as file_error:
                errors.append(f"{file.filename}: {str(file_error)}")
            finally:
                if os.path.exists(file_path):
                    os.remove(file_path)
        
        response_data = {
            "success": count > 0,
            "added": count, 
            "skipped": duplicates,
            "message": f"Successfully uploaded {count} resumes. ({duplicates} duplicate(s) skipped)"
        }
        
        if errors:
            response_data["errors"] = errors
        
        if count == 0 and duplicates == 0:
            raise HTTPException(
                status_code=400, 
                detail=f"No resumes were uploaded. Errors: {'; '.join(errors)}" if errors else "No files processed"
            )
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload error: {str(e)}")

@app.post("/analyze-batch/")
async def analyze_batch(request: Request, job_id: int):
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
                    raise HTTPException(status_code=404, detail="Job not found")
                
                if job_data[1] != user_id:
                    raise HTTPException(status_code=403, detail="You don't have permission to analyze this job")
                
                requirements = job_data[0]

                cur.execute("SELECT id, content FROM resumes WHERE job_id = %s AND user_id = %s AND match_score IS NULL", (job_id, user_id))
                rows = cur.fetchall()
                
                if not rows:
                    return {"status": "Complete", "analyzed": 0, "message": "No unanalyzed resumes found"}
                
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROUTE 4: RANKINGS ---
@app.get("/resumes/")
async def get_resumes(request: Request, job_id: int):
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
                    SELECT id, filename, candidate_name, match_score, ai_analysis 
                    FROM resumes 
                    WHERE job_id = %s AND user_id = %s
                    ORDER BY created_at DESC
                """, (job_id, user_id))
                rows = cur.fetchall()
                return {"resumes": [{"id": r[0], "filename": r[1], "candidate_name": r[2], "score": r[3], "analyzed": r[4] is not None} for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/rankings/")
async def get_rankings(request: Request, job_id: int):
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
                    ORDER BY match_score DESC NULLS LAST
                """, (job_id, user_id))
                rows = cur.fetchall()
                return {"rankings": [{"filename": r[0], "candidate_name": r[1], "score": r[2], "summary": r[3]} for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- ROUTE 5: EXPORT TO CSV ---
@app.get("/export-csv/")
async def export_to_csv(request: Request, job_id: int):
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
                    raise HTTPException(status_code=404, detail="Job not found")
                
                # Verify job belongs to user
                if job_info[2] != user_id:
                    raise HTTPException(status_code=403, detail="You don't have permission to export this job")
                
                job_title, job_tag = job_info[0], job_info[1]
                
                # Get all rankings sorted by score
                cur.execute("""
                    SELECT filename, candidate_name, match_score, ai_analysis 
                    FROM resumes 
                    WHERE job_id = %s AND user_id = %s
                    ORDER BY match_score DESC NULLS LAST
                """, (job_id, user_id))
                rows = cur.fetchall()
        
        # Create CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow(["Rank", "Candidate Name", "Match Score (%)", "Analysis Summary", "Resume File"])
        
        # Write data rows
        for rank, (filename, name, score, summary) in enumerate(rows, 1):
            writer.writerow([rank, name or "Unknown", score or "N/A", summary or "Not analyzed", filename])
        
        # Generate filename
        filename = f"{job_tag}_results.csv"
        
        # Return as file download
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")
        
@app.delete("/delete-job/")
async def delete_job(request: Request, job_id: int):
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
        return {"message": "Job deleted successfully", "job_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/")
async def get_all_jobs(request: Request):
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
                # Return properties with names matching what frontend expects
                return {"jobs": [{"id": r[0], "job_title": r[1], "job_tag": r[2], "created_at": str(r[3])} for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))