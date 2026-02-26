-- HR Recruitment App - Supabase Database Schema
-- This schema includes all tables needed for user authentication, job management, 
-- resume processing, and AI analysis results

-- ==================== USERS TABLE ====================
-- Stores registered user accounts with authentication
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create index on email for faster lookups
CREATE INDEX idx_users_email ON users(email);

-- ==================== JOBS TABLE ====================
-- Stores job postings created by recruiters
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY,
    job_title TEXT NOT NULL,
    job_tag TEXT UNIQUE NOT NULL,
    requirements TEXT NOT NULL,
    user_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Create indexes for jobs
CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_job_tag ON jobs(job_tag);
CREATE INDEX idx_jobs_created_at ON jobs(created_at DESC);

-- ==================== RESUMES TABLE ====================
-- Stores uploaded resumes and their AI analysis results
CREATE TABLE resumes (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    content TEXT NOT NULL,
    job_id INTEGER NOT NULL,
    user_id UUID NOT NULL,
    candidate_name TEXT,
    match_score INTEGER,
    ai_analysis TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    -- Prevent duplicate resume uploads for the same job
    UNIQUE(filename, job_id)
);

-- Create indexes for resumes
CREATE INDEX idx_resumes_job_id ON resumes(job_id);
CREATE INDEX idx_resumes_user_id ON resumes(user_id);
CREATE INDEX idx_resumes_match_score ON resumes(match_score DESC);
CREATE INDEX idx_resumes_candidate_name ON resumes(candidate_name);

-- ==================== OPTIONAL: AUDIT LOG TABLE ====================
-- (Optional) For tracking resume analysis events
CREATE TABLE resume_analysis_log (
    id SERIAL PRIMARY KEY,
    resume_id INTEGER NOT NULL,
    analyzed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    raw_ai_output TEXT,
    FOREIGN KEY (resume_id) REFERENCES resumes(id) ON DELETE CASCADE
);

CREATE INDEX idx_analysis_log_resume_id ON resume_analysis_log(resume_id);

-- ==================== ROW LEVEL SECURITY (RLS) POLICIES ====================
-- Enable RLS on tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE resume_analysis_log ENABLE ROW LEVEL SECURITY;

-- Users can only view their own profile
CREATE POLICY "users_select_own" ON users
    FOR SELECT USING (auth.uid() = id);

-- Users can only update their own profile
CREATE POLICY "users_update_own" ON users
    FOR UPDATE USING (auth.uid() = id);

-- Users can only insert (signup)
CREATE POLICY "users_insert_self" ON users
    FOR INSERT WITH CHECK (auth.uid() = id);

-- Users can only view their own jobs
CREATE POLICY "jobs_select_own" ON jobs
    FOR SELECT USING (auth.uid() = user_id);

-- Users can only create jobs for themselves
CREATE POLICY "jobs_insert_own" ON jobs
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Users can only update their own jobs
CREATE POLICY "jobs_update_own" ON jobs
    FOR UPDATE USING (auth.uid() = user_id);

-- Users can only delete their own jobs
CREATE POLICY "jobs_delete_own" ON jobs
    FOR DELETE USING (auth.uid() = user_id);

-- Users can only view resumes for their jobs
CREATE POLICY "resumes_select_own" ON resumes
    FOR SELECT USING (auth.uid() = user_id);

-- Users can only insert resumes for their jobs
CREATE POLICY "resumes_insert_own" ON resumes
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- Users can only update resumes for their jobs
CREATE POLICY "resumes_update_own" ON resumes
    FOR UPDATE USING (auth.uid() = user_id);

-- Users can only delete resumes for their jobs
CREATE POLICY "resumes_delete_own" ON resumes
    FOR DELETE USING (auth.uid() = user_id);

-- Users can only view analysis logs for their resumes
CREATE POLICY "analysis_log_select_own" ON resume_analysis_log
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM resumes 
            WHERE resumes.id = resume_analysis_log.resume_id 
            AND resumes.user_id = auth.uid()
        )
    );
