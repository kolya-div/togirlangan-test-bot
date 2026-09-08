const API_BASE = '';

const UPLOAD_TIMEOUT_MS = 60000;

function fetchWithTimeout(url, options, timeout = UPLOAD_TIMEOUT_MS) {
    const controller = new AbortController()
    const id = setTimeout(() => controller.abort(), timeout)
    return fetch(url, { ...options, signal: controller.signal })
        .finally(() => clearTimeout(id))
}

export async function fetchQuestions() {
    const ts = Date.now()
    const res = await fetchWithTimeout(
        `${API_BASE}/api/questions?_t=${ts}`,
        {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate' },
        },
        10000
    )
    if (!res.ok) throw new Error('Savollarni yuklab bo\'lmadi')
    return res.json()
}

export async function initWebApp(initData) {
    const form = new FormData()
    form.append('init_data', initData || '')
    const res = await fetchWithTimeout(`${API_BASE}/api/init`, {
        method: 'POST',
        body: form,
    }, 15000)

    if (res.status === 401) {
        const err = new Error('Avtorizatsiya yaroqsiz. Botdan qayta oching.')
        err.status = 401
        throw err
    }
    if (!res.ok) throw new Error('Testni yuklab bo\'lmadi')
    return res.json()
}

export async function createAttempt(initData, chatId = null) {
    const form = new FormData()
    form.append('init_data', initData || '')
    // chat_id — start_param orqali kelgan ishonchsiz UX qiymati.
    // Faqat "Test yakunlandi" xabarini yuborish uchun; avtorizatsiyaga
    // ishlatilmaydi (user_id faqat init_data HMAC imzosidan olinadi).
    if (chatId != null) form.append('chat_id', String(chatId))
    const res = await fetchWithTimeout(`${API_BASE}/api/attempts`, {
        method: 'POST',
        body: form,
    }, 60000)

    if (res.status === 403) {
        const data = await res.json().catch(() => ({}))
        const err = new Error(data.detail?.message || 'Test allaqachon topshirilgan')
        err.status = 403
        err.attemptId = data.detail?.attempt_id
        err.limitReached = data.detail?.limit_reached || false
        err.attemptStatus = data.detail?.status || null
        throw err
    }

    if (!res.ok) throw new Error('Test boshlab bo\'lmadi')
    return res.json()
}

export async function uploadAnswer(attemptId, questionId, audioBlob, initData) {
    if (!audioBlob || audioBlob.size === 0) {
        throw new Error("Audio bo'sh")
    }

    const form = new FormData()
    form.append("audio", audioBlob, "answer.webm")
    form.append("init_data", initData || "")

    const res = await fetchWithTimeout(
        `${API_BASE}/api/attempts/${attemptId}/answers/${questionId}`,
        {
            method: "POST",
            body: form,
        },
        UPLOAD_TIMEOUT_MS
    )

    if (res.status === 401) {
        throw new Error("Avtorizatsiya yaroqsiz. Botdan qayta oching.")
    }

    if (res.status === 403) {
        throw new Error("Test yakunlangan. Yangi javob yuborish mumkin emas.")
    }

    if (res.status === 413) {
        throw new Error("Audio fayl juda katta")
    }

    if (res.status === 422) {
        throw new Error("Audio yuborish ma'lumotlari noto'g'ri")
    }

    if (res.status === 400) {
        throw new Error("Audio formati yaroqsiz")
    }

    if (res.status >= 500) {
        throw new Error("Server xatosi. Keyinroq urinib ko'ring")
    }

    if (!res.ok) {
        throw new Error("Audio yuklab bo'lmadi")
    }

    return res.json()
}

export async function finishAttempt(attemptId, initData) {
    const form = new FormData()
    form.append("init_data", initData || "")

    const res = await fetchWithTimeout(
        `${API_BASE}/api/attempts/${attemptId}/finish`,
        {
            method: "POST",
            body: form,
        },
        15000
    )

    if (res.status === 401) {
        throw new Error("Avtorizatsiya yaroqsiz. Botdan qayta oching.")
    }

    if (res.status === 409) {
        const data = await res.json().catch(() => ({}))
        const err = new Error(
            data.detail || "Test allaqachon yakunlangan"
        )
        err.status = 409
        throw err
    }

    if (res.status === 422) {
        throw new Error("Testni yakunlash ma'lumotlari noto'g'ri")
    }

    if (!res.ok) {
        throw new Error("Testni yakunlab bo'lmadi")
    }

    return res.json()
}

export async function notifyTestClosed(attemptId, initData) {
    const form = new FormData()
    form.append("init_data", initData || "")

    const res = await fetchWithTimeout(
        `${API_BASE}/api/attempts/${attemptId}/notify-closed`,
        {
            method: "POST",
            body: form,
        },
        15000
    )

    if (res.status === 401) {
        throw new Error("Avtorizatsiya yaroqsiz. Botdan qayta oching.")
    }

    if (!res.ok) {
        throw new Error("Xabar yuborib bo'lmadi")
    }

    return res.json()
}

export async function fetchResults(attemptId, initData) {
    const params = new URLSearchParams()
    if (initData) params.set('init_data', initData)
    const qs = params.toString()
    const res = await fetchWithTimeout(
        `${API_BASE}/api/attempts/${attemptId}/results${qs ? '?' + qs : ''}`,
        {
            cache: 'no-store',
            headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate' },
        },
        30000
    )
    if (!res.ok) throw new Error('Natijalarni yuklab bo\'lmadi')
    return res.json()
}
