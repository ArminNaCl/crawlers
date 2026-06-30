let selectedPlatform = null;
let isWebview = false;
let _savedFolderPath = '';
let currentJobId = null;

// Detect running mode (browser vs pywebview window)
fetch('/api/mode').then(r => r.json()).then(d => { isWebview = d.webview; });

// Platform selection
document.querySelectorAll('.platform-btn').forEach(btn => {
    btn.addEventListener('click', function () {
        document.querySelectorAll('.platform-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        selectedPlatform = this.dataset.platform;
        document.getElementById('platformLabel').textContent = this.textContent + ' — vendor URL';
        document.getElementById('urlSection').style.display = 'block';
        document.getElementById('resultSection').style.display = 'none';
        document.getElementById('statusSection').style.display = 'none';
        document.getElementById('linkInput').value = '';
        document.getElementById('linkInput').focus();
    });
});

// Extract on Enter key
document.getElementById('linkInput').addEventListener('keydown', function (e) {
    if (e.key === 'Enter') document.getElementById('submitBtn').click();
});

// Start extraction
document.getElementById('submitBtn').addEventListener('click', async function () {
    const link = document.getElementById('linkInput').value.trim();
    if (!link) { alert('Please enter a vendor URL.'); return; }
    if (!selectedPlatform) { alert('Please select a platform first.'); return; }

    const noSkip = document.getElementById('noSkipCheckbox').checked;

    setLoading(true);
    document.getElementById('logBox').textContent = '';
    document.getElementById('resultSection').style.display = 'none';

    try {
        const res = await fetch('/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: selectedPlatform, link, no_skip: noSkip })
        });
        const payload = await res.json();
        if (payload.error) { setLoading(false); alert(payload.error); return; }
        currentJobId = payload.job_id;
        await pollJob(payload.job_id);
    } catch (err) {
        setLoading(false);
        alert('Connection error. Is the server running?');
        console.error(err);
    }
});

// Cancel running job
document.getElementById('cancelBtn').addEventListener('click', async function () {
    if (!currentJobId) return;
    this.disabled = true;
    this.textContent = 'Cancelling…';
    try {
        await fetch(`/api/cancel/${currentJobId}`, { method: 'POST' });
    } catch (_) {}
});

async function pollJob(jobId) {
    while (true) {
        await sleep(2000);
        let data;
        try {
            data = await fetch(`/api/status/${jobId}`).then(r => r.json());
        } catch (_) { continue; }

        // Show last 4 lines in the log box
        const logBox = document.getElementById('logBox');
        if (data.logs && data.logs.length) {
            logBox.textContent = data.logs.slice(-4).join('\n');
            logBox.scrollTop = logBox.scrollHeight;
        }

        if (data.status === 'done' || data.status === 'cancelled') {
            setLoading(false);
            document.getElementById('resultSection').style.display = 'block';
            document.getElementById('resultMessage').textContent = data.message;

            if (isWebview && data.downloads_dir) {
                _savedFolderPath = data.downloads_dir;
                document.getElementById('savePath').textContent = 'Saved to: ' + data.downloads_dir;
                document.getElementById('folderSection').style.display = 'block';
                document.getElementById('downloadLinks').style.display = 'none';
            } else {
                const container = document.getElementById('downloadLinks');
                container.innerHTML = '';
                container.style.display = 'block';
                document.getElementById('folderSection').style.display = 'none';
                (data.files || []).forEach(file => {
                    const a = document.createElement('a');
                    a.href = `/download/${file.filename}`;
                    a.textContent = `Download ${file.name}`;
                    a.download = file.name;
                    container.appendChild(a);
                });
            }
            break;
        }

        if (data.status === 'error') {
            setLoading(false);
            alert('Error: ' + (data.error || 'Unknown error'));
            break;
        }
    }
}

// Open save folder via pywebview JS bridge
document.getElementById('openFolderBtn').addEventListener('click', function () {
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.open_folder(_savedFolderPath).catch(console.error);
    }
});

function setLoading(on) {
    document.getElementById('statusSection').style.display = on ? 'block' : 'none';
    document.getElementById('submitBtn').disabled = on;
    const cancelBtn = document.getElementById('cancelBtn');
    cancelBtn.style.display = on ? 'inline-block' : 'none';
    cancelBtn.disabled = false;
    cancelBtn.textContent = 'Cancel';
    if (!on) currentJobId = null;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
