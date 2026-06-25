let selectedPlatform = null;

// Platform selection
document.querySelectorAll('.platform-btn').forEach(btn => {
    btn.addEventListener('click', function () {
        document.querySelectorAll('.platform-btn').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        selectedPlatform = this.dataset.platform;
        document.getElementById('inputSection').style.display = 'block';
        document.getElementById('selectedPlatform').textContent = this.textContent;
        document.getElementById('resultSection').style.display = 'none';
        document.getElementById('linkInput').value = '';
    });
});

// Start extraction
document.getElementById('submitBtn').addEventListener('click', async function () {
    const link = document.getElementById('linkInput').value.trim();
    if (!link) { alert('لطفا لینک را وارد کنید'); return; }
    if (!selectedPlatform) { alert('لطفا پلتفرم را انتخاب کنید'); return; }

    setLoading(true);
    document.getElementById('logBox').textContent = '';
    document.getElementById('resultSection').style.display = 'none';

    try {
        const res = await fetch('/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: selectedPlatform, link })
        });
        const payload = await res.json();
        if (payload.error) {
            setLoading(false);
            alert(payload.error);
            return;
        }
        await pollJob(payload.job_id);
    } catch (err) {
        setLoading(false);
        alert('خطا در ارتباط با سرور');
        console.error(err);
    }
});

async function pollJob(jobId) {
    while (true) {
        await sleep(2000);
        let data;
        try {
            const res = await fetch(`/api/status/${jobId}`);
            data = await res.json();
        } catch (_) {
            continue;
        }

        // Show live logs (last 30 lines)
        const logBox = document.getElementById('logBox');
        if (data.logs && data.logs.length) {
            logBox.textContent = data.logs.slice(-30).join('\n');
            logBox.scrollTop = logBox.scrollHeight;
        }

        if (data.status === 'done') {
            setLoading(false);
            document.getElementById('resultSection').style.display = 'block';
            document.getElementById('resultMessage').textContent = data.message;

            const container = document.getElementById('downloadLinks');
            container.innerHTML = '';
            (data.files || []).forEach(file => {
                const a = document.createElement('a');
                a.href = `/download/${file.filename}`;
                a.textContent = `دانلود ${file.name}`;
                a.download = file.name;
                container.appendChild(a);
            });
            break;
        }

        if (data.status === 'error') {
            setLoading(false);
            alert(data.error || 'خطایی رخ داد');
            break;
        }
    }
}

function setLoading(on) {
    document.getElementById('loading').style.display = on ? 'block' : 'none';
}

function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}
