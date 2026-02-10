/**
 * Guest Mode Client-Side Implementation
 * Handles local data persistence and guest-to-auth migration
 * 
 * This module manages:
 * - Local storage of guest data
 * - Guest data sync with server
 * - Automatic migration to authenticated account
 */

class GuestModeManager {
    constructor() {
        this.storageKey = 'hr_app_guest_data';
        this.sessionKey = 'hr_app_guest_session';
        this.isGuest = localStorage.getItem('is_guest') === 'true';
        this.guestSessionToken = localStorage.getItem('guest_session_token');
    }

    // ==================== INITIALIZATION ====================

    /**
     * Initialize guest mode on page load
     */
    async initializeGuestMode() {
        if (!this.isGuest) return;

        // Load existing guest data
        const guestData = this.getGuestData();

        // Sync with server if needed
        if (this.guestSessionToken) {
            await this.syncGuestDataWithServer(guestData);
        }

        return guestData;
    }

    // ==================== DATA MANAGEMENT ====================

    /**
     * Get all guest data from localStorage
     */
    getGuestData() {
        const data = localStorage.getItem(this.storageKey);
        return data ? JSON.parse(data) : {
            jobs: [],
            resumes: [],
            analyses: [],
            last_updated: null
        };
    }

    /**
     * Save guest data to localStorage
     */
    saveGuestData(guestData) {
        guestData.last_updated = new Date().toISOString();
        localStorage.setItem(this.storageKey, JSON.stringify(guestData));
    }

    /**
     * Add new job to guest data
     */
    addJobAsGuest(title, tag, requirements) {
        const guestData = this.getGuestData();
        const newJob = {
            id: this.generateLocalId('job'),
            title,
            tag,
            requirements,
            created_at: new Date().toISOString(),
            status: 'local'
        };
        guestData.jobs.push(newJob);
        this.saveGuestData(guestData);
        return newJob;
    }

    /**
     * Add resume to guest data
     */
    addResumeAsGuest(jobId, filename, content, extractedText) {
        const guestData = this.getGuestData();
        const newResume = {
            id: this.generateLocalId('resume'),
            job_id: jobId,
            filename,
            content: extractedText,  // Store extracted text
            file_size: content.size,
            candidate_name: null,
            match_score: null,
            ai_analysis: null,
            created_at: new Date().toISOString(),
            status: 'local'
        };
        guestData.resumes.push(newResume);
        this.saveGuestData(guestData);
        return newResume;
    }

    /**
     * Update resume with AI analysis (local)
     */
    updateResumeAnalysisAsGuest(resumeId, candidateName, score, analysis) {
        const guestData = this.getGuestData();
        const resume = guestData.resumes.find(r => r.id === resumeId);

        if (resume) {
            resume.candidate_name = candidateName;
            resume.match_score = score;
            resume.ai_analysis = analysis;
            resume.updated_at = new Date().toISOString();
            this.saveGuestData(guestData);
        }

        return resume;
    }

    /**
     * Get jobs for guest
     */
    getGuestJobs() {
        return this.getGuestData().jobs;
    }

    /**
     * Get resumes for specific job (guest)
     */
    getGuestResumesForJob(jobId) {
        return this.getGuestData().resumes.filter(r => r.job_id === jobId);
    }

    // ==================== SERVER SYNC ====================

    /**
     * Sync guest data with server (if session token exists)
     */
    async syncGuestDataWithServer(guestData) {
        if (!this.guestSessionToken) return;

        try {
            const response = await fetch('/guest-session/update', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Guest-Session': this.guestSessionToken
                },
                body: JSON.stringify(guestData)
            });

            if (!response.ok) {
                console.warn('Failed to sync guest data with server');
            }
        } catch (error) {
            console.error('Error syncing guest data:', error);
            // Continue anyway - guest data is persisted locally
        }
    }

    // ==================== MIGRATION TO AUTH ====================

    /**
     * Migrate all guest data to authenticated user account
     * Called after user completes signup
     */
    async migrateGuestDataToAuth(authToken) {
        if (!this.isGuest || !this.guestSessionToken) {
            console.log('Not in guest mode, skipping migration');
            return null;
        }

        try {
            const guestData = this.getGuestData();

            const response = await fetch('/migrate-guest-data', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${authToken}`
                },
                body: JSON.stringify({
                    guest_session_token: this.guestSessionToken,
                    data: guestData
                })
            });

            if (!response.ok) {
                throw new Error(await response.text());
            }

            const result = await response.json();

            // Clear guest data after successful migration
            this.clearGuestData();

            console.log(`Migration successful: ${result.migrated_jobs} jobs, ${result.migrated_resumes} resumes`);
            return result;
        } catch (error) {
            console.error('Error migrating guest data:', error);
            throw error;
        }
    }

    /**
     * Clear all guest data after migration
     */
    clearGuestData() {
        localStorage.removeItem(this.storageKey);
        localStorage.removeItem(this.sessionKey);
        localStorage.removeItem('guest_session_token');
        localStorage.removeItem('is_guest');
        this.isGuest = false;
        this.guestSessionToken = null;
    }

    // ==================== UTILITIES ====================

    /**
     * Generate local ID for offline items
     */
    generateLocalId(type) {
        return `${type}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }

    /**
     * Export guest data as JSON
     */
    exportGuestData() {
        const guestData = this.getGuestData();
        const dataStr = JSON.stringify(guestData, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);

        const link = document.createElement('a');
        link.href = url;
        link.download = `guest_data_${new Date().toISOString()}.json`;
        link.click();

        URL.revokeObjectURL(url);
    }

    /**
     * Import guest data from JSON file
     */
    importGuestData(file) {
        const reader = new FileReader();

        reader.onload = (event) => {
            try {
                const guestData = JSON.parse(event.target.result);
                this.saveGuestData(guestData);
                console.log('Guest data imported successfully');
            } catch (error) {
                console.error('Error importing guest data:', error);
            }
        };

        reader.readAsText(file);
    }

    /**
     * Get guest session info
     */
    getSessionInfo() {
        return {
            isGuest: this.isGuest,
            sessionToken: this.guestSessionToken,
            dataSize: new Blob([JSON.stringify(this.getGuestData())]).size,
            lastUpdated: this.getGuestData().last_updated
        };
    }

    /**
     * Check if guest data would exceed storage limits
     */
    checkStorageCapacity(additionalData = 0) {
        try {
            const currentData = JSON.stringify(this.getGuestData());
            const totalSize = new Blob([currentData]).size + additionalData;
            const limitMB = 5; // Reasonable limit for localStorage
            const limitBytes = limitMB * 1024 * 1024;

            return {
                available: totalSize < limitBytes,
                currentMB: (totalSize / 1024 / 1024).toFixed(2),
                limitMB: limitMB,
                percentUsed: ((totalSize / limitBytes) * 100).toFixed(1)
            };
        } catch (error) {
            console.error('Error checking storage:', error);
            return { available: true };
        }
    }
}

// ==================== GLOBAL INSTANCE ====================

// Create global instance
const guestManager = new GuestModeManager();

// ==================== INTEGRATION WITH UI ====================

/**
 * Example integration with UI functions
 * Add these to your existing dashboard functions
 */

// Override createNewJob for guest mode
const originalCreateJob = window.createNewJob;
window.createNewJob = async function () {
    const isGuest = localStorage.getItem('is_guest') === 'true';

    if (isGuest) {
        const title = document.getElementById('job-title').value.trim();
        const tag = document.getElementById('job-tag-input').value.trim();
        const reqs = document.getElementById('job-requirements').value.trim();

        if (!title || !tag || !reqs) {
            alert("⚠️ All fields are required");
            return;
        }

        // Save locally
        const newJob = guestManager.addJobAsGuest(title, tag, reqs);

        alert(`✓ Job saved locally (ID: ${newJob.id})`);

        // Clear form
        document.getElementById('job-title').value = '';
        document.getElementById('job-tag-input').value = '';
        document.getElementById('job-requirements').value = '';

        // Refresh UI
        loadJobsForGuest();
        return;
    }

    // Fall back to original function for authenticated users
    if (originalCreateJob) {
        return originalCreateJob.call(this);
    }
};

// Load jobs for guest user
async function loadJobsForGuest() {
    const jobs = guestManager.getGuestJobs();
    const jobList = document.getElementById('job-list');
    jobList.innerHTML = "";

    if (jobs.length > 0) {
        jobs.forEach((job, index) => {
            const row = document.createElement('tr');
            row.className = 'fade-in-up';
            row.style.animationDelay = `${index * 0.05}s`;
            row.innerHTML = `
                <td><span class="text-mono text-bold" style="color: var(--color-primary);">${job.id.substr(-8)}</span></td>
                <td>${escapeHtml(job.title)}</td>
                <td style="display: flex; gap: 8px;">
                    <button class="btn-custom btn-secondary-custom btn-sm-custom" 
                            onclick="selectGuestJob('${job.id}')">
                        Select
                    </button>
                    <button class="btn-custom btn-sm-custom" 
                            onclick="deleteGuestJob('${job.id}')"
                            style="background-color: var(--color-danger); color: white; border: none;">
                        Delete
                    </button>
                </td>
            `;
            jobList.appendChild(row);
        });
    } else {
        jobList.innerHTML = `
            <tr>
                <td colspan="3">
                    <div class="empty-state">
                        <div class="empty-state-icon">📋</div>
                        <div class="empty-state-title">No jobs created yet</div>
                        <div class="empty-state-description">Create your first position above</div>
                    </div>
                </td>
            </tr>
        `;
    }
}

function selectGuestJob(jobId) {
    document.getElementById('job-id-display').value = jobId;
    refreshTableForGuest(jobId);
}

function deleteGuestJob(jobId) {
    if (!confirm(`Are you sure you want to delete this job? This will also delete all associated resumes.`)) {
        return;
    }

    const guestData = guestManager.getGuestData();
    guestData.jobs = guestData.jobs.filter(j => j.id !== jobId);
    guestData.resumes = guestData.resumes.filter(r => r.job_id !== jobId);
    guestManager.saveGuestData(guestData);

    loadJobsForGuest();
    alert('✓ Job deleted successfully');
}

function refreshTableForGuest(jobId) {
    const resumes = guestManager.getGuestResumesForJob(jobId);
    const table = document.getElementById('leaderboard');
    table.innerHTML = "";

    if (resumes.length > 0) {
        resumes.forEach((resume, index) => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${index + 1}</td>
                <td>${escapeHtml(resume.candidate_name || 'Not Analyzed')}</td>
                <td>${resume.match_score || 'Pending'}</td>
                <td>${escapeHtml(resume.ai_analysis || 'Click Analyze')}</td>
                <td>${escapeHtml(resume.filename)}</td>
            `;
            table.appendChild(row);
        });
    } else {
        table.innerHTML = `
            <tr>
                <td colspan="5" style="text-align: center;">
                    No resumes uploaded yet. Upload files to get started.
                </td>
            </tr>
        `;
    }
}

/**
 * Show prompt to upgrade from guest to account
 */
function showUpgradePrompt() {
    const isGuest = localStorage.getItem('is_guest') === 'true';

    if (isGuest) {
        const message = `
            You're currently in Guest Mode. Your data is stored locally on this browser.
            
            Create an account to:
            ✓ Access from any device
            ✓ Save your work permanently
            ✓ Collaborate with team members
            
            Create Account Now?
        `;

        if (confirm(message)) {
            window.location.href = '/login';
        }
    }
}

// Export guestManager for use in other scripts
window.guestManager = guestManager;
