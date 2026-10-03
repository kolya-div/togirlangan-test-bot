import { useRef, useEffect, useCallback, useState } from 'react'
import { uploadAnswer } from '../api.js'

const MIN_AUDIO_BYTES = 1024
const UPLOAD_TIMEOUT_MS = 60000
// Tarmoq uzilishida javob yo'qolmasligi uchun: 1s, 2s, 4s, 8s kutib
// qayta urinish (~15s oyna). Oldin 2 × 1s edi — qisqa uzilishda ham
// javob jimgina tashlab yuborilardi.
const MAX_RETRIES = 4
const RETRY_BASE_DELAY_MS = 1000

const PREFERRED_MIME_TYPES = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
]

function getSupportedMimeType() {
    if (typeof MediaRecorder === 'undefined') return ''
    for (const mime of PREFERRED_MIME_TYPES) {
        if (MediaRecorder.isTypeSupported(mime)) return mime
    }
    return ''
}

export const MIC_CONSTRAINTS = {
    audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: 48000,
    },
}

function isLive(stream) {
    return !!stream && stream.active &&
        stream.getAudioTracks().some(t => t.readyState === 'live')
}

function cleanupStream(stream) {
    if (stream && stream.active) {
        stream.getTracks().forEach(t => {
            try { t.stop() } catch (_) {}
        })
    }
}

export default function AudioRecorder({
    attemptId,
    questionId,
    initData,
    onUploaded,
    registerStop,
    onStopping,
    onError,
    // Test boshida bir marta olingan mikrofon (har savolda qayta ruxsat
    // so'ralmaydi). U App'ga tegishli — bu komponent uni yopmaydi.
    sharedStream,
}) {
    const mediaRecorder = useRef(null)
    const audioChunks = useRef([])
    const streamRef = useRef(null)
    const stoppedRef = useRef(false)
    const mountedRef = useRef(false)
    // "To'xtatish" bosildi — javob yuborilmoqda (tugma o'rniga holat ko'rsatiladi)
    const [sending, setSending] = useState(false)

    const cleanup = useCallback(() => {
        if (streamRef.current !== sharedStream) cleanupStream(streamRef.current)
        streamRef.current = null
    }, [sharedStream])

    useEffect(() => {
        mountedRef.current = true
        return () => {
            mountedRef.current = false
            stoppedRef.current = true
            cleanup()
        }
    }, [cleanup])

    const handleUploadResult = useCallback((result) => {
        if (!mountedRef.current) return
        onUploaded?.(result)
    }, [onUploaded])

    const failAndSkip = useCallback((msg) => {
        if (!mountedRef.current) return
        cleanup()
        onError?.(msg)
    }, [cleanup, onError])

    const uploadWithRetry = useCallback(async (
    attemptId,
    questionId,
    blob,
    retries = 0
) => {
    try {
        return await uploadAnswer(
            attemptId,
            questionId,
            blob,
            initData
        )
    } catch (err) {
        // BUG FIX: `stoppedRef.current` shu nuqtada normal oqimda HAR DOIM
        // `true` bo'ladi — chunki `stopRecording()` uni `recorder.stop()`
        // chaqirishdan oldin belgilaydi, `onstop` (va shu yuklash) esa faqat
        // o'shandan keyin ishga tushadi. Shuning uchun `!stoppedRef.current`
        // sharti retry'ni hech qachon ishga tushirmas edi — bitta tarmoq
        // uzilishi javobni butunlay yo'qotardi. Komponent haqiqatan
        // unmount bo'lganini `mountedRef.current` allaqachon to'g'ri
        // tekshiradi, shuning uchun shu yerda faqat o'shani ishlatamiz.
        if (
            retries < MAX_RETRIES &&
            mountedRef.current &&
            err?.retryable !== false
        ) {
            await new Promise(r => setTimeout(r, RETRY_BASE_DELAY_MS * 2 ** retries))

            return uploadWithRetry(
                attemptId,
                questionId,
                blob,
                retries + 1
            )
        }

        throw err
    }
}, [initData])

    const startRecording = useCallback(async () => {
        if (stoppedRef.current) return

        let stream = isLive(sharedStream) ? sharedStream : null
        if (!stream) {
            try {
                stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS)
            } catch (err) {
                if (!mountedRef.current) return
                failAndSkip('Mikrofon xatosi')
                return
            }
        }

        if (!mountedRef.current) {
            if (stream !== sharedStream) cleanupStream(stream)
            return
        }

        streamRef.current = stream
        const mimeType = getSupportedMimeType()
        // 64 kbit/s — telefon mikrofonidan aniqroq yozuv (standart ~32 kbit/s)
        const options = mimeType ? { mimeType, audioBitsPerSecond: 64000 } : { audioBitsPerSecond: 64000 }
        let recorder

        try {
            recorder = new MediaRecorder(stream, options)
        } catch (_) {
            try {
                recorder = new MediaRecorder(stream)
            } catch (e) {
                failAndSkip('Audio yozish qurilmasi ishlamayapti')
                return
            }
        }

        mediaRecorder.current = recorder
        audioChunks.current = []

        recorder.ondataavailable = (e) => {
            if (e.data && e.data.size > 0) audioChunks.current.push(e.data)
        }

        recorder.onstop = async () => {
            if (!mountedRef.current) {
                cleanup()
                return
            }

            const blob = new Blob(audioChunks.current, {
                type: recorder.mimeType || 'audio/webm',
            })
            audioChunks.current = []

            if (blob.size < MIN_AUDIO_BYTES) {
                cleanup()
                handleUploadResult({ success: true, skipped: true })
                return
            }

            try {
                const result = await uploadWithRetry(attemptId, questionId, blob)
                cleanup()
                handleUploadResult(result)
            } catch (err) {
                if (!mountedRef.current) return
                failAndSkip('Audio yuklashda xatolik')
            }
        }

        recorder.onerror = () => {
            if (!mountedRef.current) return
            failAndSkip('Yozishda xatolik yuz berdi')
        }

        try {
            recorder.start(1000)
        } catch (_) {
            failAndSkip('Yozishni boshlab bo\'lmadi')
        }
    }, [attemptId, questionId, cleanup, handleUploadResult, uploadWithRetry, failAndSkip])

    useEffect(() => {
        startRecording()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const stopRecording = useCallback(() => {
        if (stoppedRef.current) return
        stoppedRef.current = true
        // Darhol ko'rinadigan javob: yuklash sekin tarmoqda bir necha soniya
        // davom etadi — oldin bu vaqtda ekran o'zgarmas va tugma
        // "ishlamayapti" bo'lib ko'rinardi (ayniqsa oxirgi savolda).
        if (mountedRef.current) setSending(true)
        onStopping?.()

        const recorder = mediaRecorder.current
        if (recorder && recorder.state !== 'inactive') {
            try {
                recorder.stop()
            } catch (_) {
                cleanup()
                handleUploadResult({ success: true })
            }
        } else {
            cleanup()
            handleUploadResult({ success: true })
        }
    }, [cleanup, handleUploadResult, onStopping])

    useEffect(() => {
        registerStop?.(stopRecording)
    }, [registerStop, stopRecording])

    return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
            <div style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: sending ? '#9CA3AF' : '#16A34A',
                animation: sending ? 'none' : 'pulse 1s infinite',
            }} />
            {sending ? (
                <div className="phase-status uploading" style={{ margin: 0 }}>
                    Javob yuborilmoqda...
                </div>
            ) : (
                <button className="btn btn-danger" onClick={stopRecording}>
                    To'xtatish
                </button>
            )}
        </div>
    )
}
