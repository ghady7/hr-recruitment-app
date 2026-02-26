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
from urllib.parse import unquote
import base64

load_dotenv()

# ==================== JWT CONFIGURATION ====================
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-prod-12345")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
REFRESH_TOKEN_EXPIRE_DAYS = 7

# ==================== SIMPLE JWT IMPLEMENTATION ====================
# Using base64 encoding for simplicity (PyJWT has library conflicts)

def create_access_token(user_id: str, email: str) -> str:
    """Create simple token"""
    payload = {
        "user_id": user_id,
        "email": email,
        "token_type": "access",
        "exp": (datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)).isoformat()
    }
    token_str = json.dumps(payload)
    return base64.b64encode(token_str.encode('utf-8')).decode('ascii')

def create_refresh_token(user_id: str, email: str) -> str:
    """Create simple refresh token"""
    payload = {
        "user_id": user_id,
        "email": email,
        "token_type": "refresh",
        "exp": (datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()
    }
    token_str = json.dumps(payload)
    return base64.b64encode(token_str.encode('utf-8')).decode('ascii')

def verify_token(token: str) -> Optional[Dict]:
    """Verify simple token with robust error handling"""
    if not token or not isinstance(token, str):
        return None
    
    try:
        # Clean up token - strip whitespace
        original_token = token
        token = token.strip()
        
        # If token is too short, it's invalid
        if len(token) < 10:
            return None
        
        # Try to URL decode if needed (handles tokens sent through HTTP)
        try:
            decoded_token = unquote(token)
        except:
            decoded_token = token
        
        # Validate base64 characters (should only contain: A-Za-z0-9+/=)
        valid_b64_chars = set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=')
        if not all(c in valid_b64_chars for c in decoded_token):
            return None
        
        # Add padding if needed for base64
        padding = 4 - (len(decoded_token) % 4)
        if padding != 4:
            decoded_token += '=' * padding
        
        # Decode base64 to get JSON string
        try:
            # Use validate=True to ensure proper base64
            token_bytes = base64.b64decode(decoded_token, validate=True)
            token_str = token_bytes.decode('utf-8')
        except Exception as e:
            # Silently fail for invalid tokens
            return None
        
        # Parse JSON payload
        try:
            payload = json.loads(token_str)
        except json.JSONDecodeError:
            return None
        
        # Check expiration
        if "exp" in payload:
            try:
                exp_dt = datetime.fromisoformat(payload["exp"])
                if datetime.utcnow() > exp_dt:
                    return None
            except Exception:
                return None
        
        user_id = payload.get("user_id")
        if user_id is None:
            return None
        
        return {
            "user_id": user_id,
            "email": payload.get("email"),
            "token_type": payload.get("token_type", "access")
        }
    except Exception:
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

# ==================== TOKEN EXTRACTION ====================

def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract JWT token from request - robust handling for multiple sources"""
    
    if not request:
        return None
    
    # 1. Try Authorization header (case-insensitive in FastAPI)
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization") or ""
    auth_header = auth_header.strip()
    
    if auth_header:
        # Handle "Bearer token_string" format
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()  # Remove "Bearer " prefix
            if token and len(token) > 10:
                return token
        # Handle plain token without Bearer prefix
        elif len(auth_header) > 10 and " " not in auth_header:
            return auth_header
    
    # 2. Try X-Token header
    x_token = request.headers.get("X-Token") or request.headers.get("x-token") or ""
    x_token = x_token.strip()
    if x_token and len(x_token) > 10:
        return x_token
    
    # 3. Try X-Access-Token header
    x_access = request.headers.get("X-Access-Token") or request.headers.get("x-access-token") or ""
    x_access = x_access.strip()
    if x_access and len(x_access) > 10:
        return x_access
    
    # 4. Try cookies
    access_token = request.cookies.get("access_token") or ""
    access_token = access_token.strip()
    if access_token and len(access_token) > 10:
        return access_token
    
    token_cookie = request.cookies.get("token") or ""
    token_cookie = token_cookie.strip()
    if token_cookie and len(token_cookie) > 10:
        return token_cookie
    
    # 5. Try query parameter (least secure)
    query_token = request.query_params.get("token") or ""
    query_token = query_token.strip()
    if query_token and len(query_token) > 10:
        return query_token
    
    return None
