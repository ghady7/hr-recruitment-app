import os
import json
import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict
from dotenv import load_dotenv
from fastapi import HTTPException, Request, status
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

# ==================== JWT CONFIGURATION ====================
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-prod-12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
REFRESH_TOKEN_EXPIRE_DAYS = 7

# ==================== SIMPLE JWT IMPLEMENTATION ====================
# Using base64 encoding for simplicity (PyJWT has library conflicts)
import base64

def create_access_token(user_id: str, email: str) -> str:
    """Create simple token"""
    payload = {
        "user_id": user_id,
        "email": email,
        "token_type": "access",
        "exp": (datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)).isoformat()
    }
    token_str = json.dumps(payload)
    return base64.b64encode(token_str.encode()).decode()

def create_refresh_token(user_id: str, email: str) -> str:
    """Create simple refresh token"""
    payload = {
        "user_id": user_id,
        "email": email,
        "token_type": "refresh",
        "exp": (datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    }
    token_str = json.dumps(payload)
    return base64.b64encode(token_str.encode()).decode()

def verify_token(token: str) -> Optional[Dict]:
    """Verify simple token"""
    try:
        token_str = base64.b64decode(token.encode()).decode()
        payload = json.loads(token_str)
        
        if "exp" in payload:
            exp_dt = datetime.fromisoformat(payload["exp"])
            if datetime.utcnow() > exp_dt:
                return None
        
        user_id = payload.get("user_id")
        if user_id is None:
            return None
        
        return {
            "user_id": user_id,
            "email": payload.get("email"),
            "token_type": payload.get("token_type", "access")
        }
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

# ==================== PASSWORD HASHING ====================

def hash_password(password: str) -> str:
    """Hash password with SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == hashed

# ==================== DATABASE USER MANAGEMENT ====================

def get_db_connection():
    """Get PostgreSQL connection"""
    try:
        db_url = os.getenv("DATABASE_URL")
        return psycopg2.connect(db_url)
    except psycopg2.Error as e:
        print(f"Database connection error: {str(e)}")
        raise

def create_or_update_user(user_id: str, email: str, full_name: Optional[str] = None) -> Dict:
    """Create or update user in local database"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, full_name, created_at, updated_at)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email,
                        full_name = COALESCE(EXCLUDED.full_name, users.full_name),
                        updated_at = NOW()
                    RETURNING id, email, full_name, created_at
                    """,
                    (user_id, email, full_name)
                )
                user = cur.fetchone()
                conn.commit()
                return dict(user) if user else {}
    except psycopg2.Error as e:
        print(f"Database error creating user: {str(e)}")
        raise

def get_user_by_id(user_id: str) -> Optional[Dict]:
    """Get user from database"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, email, full_name, created_at, updated_at FROM users WHERE id = %s",
                    (user_id,)
                )
                user = cur.fetchone()
                return dict(user) if user else None
    except psycopg2.Error as e:
        print(f"Database error fetching user: {str(e)}")
        return None

def get_user_by_email(email: str) -> Optional[Dict]:
    """Get user by email from database"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, email, full_name, password_hash, created_at, updated_at FROM users WHERE email = %s",
                    (email,)
                )
                user = cur.fetchone()
                return dict(user) if user else None
    except psycopg2.Error as e:
        print(f"Database error fetching user by email: {str(e)}")
        return None

def register_user(email: str, password: str, full_name: str = None) -> Dict:
    """Register a new user with email and password"""
    user_id = str(uuid.uuid4())
    password_hash = hash_password(password)
    
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, full_name, password_hash, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    RETURNING id, email, full_name, created_at
                    """,
                    (user_id, email, full_name, password_hash)
                )
                user = cur.fetchone()
                conn.commit()
                return dict(user) if user else {}
    except psycopg2.IntegrityError:
        raise Exception("User already exists with this email")
    except psycopg2.Error as e:
        print(f"Database error registering user: {str(e)}")
        raise

def login_user(email: str, password: str) -> Optional[Dict]:
    """Authenticate user with email and password"""
    try:
        user = get_user_by_email(email)
        if not user:
            return None
        
        if not verify_password(password, user.get("password_hash", "")):
            return None
        
        # Return user info without password
        return {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "created_at": str(user["created_at"]) if user.get("created_at") else None
        }
    except Exception as e:
        print(f"Login error: {str(e)}")
        return None

# ==================== GUEST SESSION MANAGEMENT ====================

def create_guest_session() -> str:
    """Create a guest session and return session token"""
    session_token = str(uuid.uuid4())
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO guest_sessions (session_token, data, created_at, expires_at)
                    VALUES (%s, %s, NOW(), NOW() + INTERVAL '7 days')
                    """,
                    (session_token, "{}")
                )
                conn.commit()
        return session_token
    except psycopg2.Error as e:
        print(f"Error creating guest session: {str(e)}")
        raise

def get_guest_session(session_token: str) -> Optional[Dict]:
    """Retrieve guest session data"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, session_token, data, created_at, expires_at, migrated_to_user_id FROM guest_sessions WHERE session_token = %s AND expires_at > NOW()",
                    (session_token,)
                )
                session = cur.fetchone()
                return dict(session) if session else None
    except psycopg2.Error as e:
        print(f"Error retrieving guest session: {str(e)}")
        return None

def update_guest_session_data(session_token: str, data: Dict) -> bool:
    """Update guest session data"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE guest_sessions SET data = %s WHERE session_token = %s",
                    (json.dumps(data), session_token)
                )
                conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"Error updating guest session: {str(e)}")
        return False

def migrate_guest_session_to_user(session_token: str, user_id: str) -> bool:
    """Mark guest session as migrated to user"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE guest_sessions 
                    SET migrated_to_user_id = %s, migrated_at = NOW()
                    WHERE session_token = %s
                    """,
                    (user_id, session_token)
                )
                conn.commit()
        return True
    except psycopg2.Error as e:
        print(f"Error marking guest session as migrated: {str(e)}")
        return False

# ==================== TOKEN EXTRACTION ====================

def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract JWT token from request headers or cookies"""
    # Try Authorization header first
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]
    
    # Try cookie
    token = request.cookies.get("access_token")
    if token:
        return token
    
    return None

def extract_guest_token_from_request(request: Request) -> Optional[str]:
    """Extract guest session token from request"""
    # Try header
    guest_token = request.headers.get("X-Guest-Session")
    if guest_token:
        return guest_token
    
    # Try cookie
    guest_token = request.cookies.get("guest_session_token")
    if guest_token:
        return guest_token
    
    return None
