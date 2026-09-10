import { useRef, useEffect, useCallback } from 'react'
import { uploadAnswer } from '../api.js'

const MIN_AUDIO_BYTES = 1024
const UPLOAD_TIMEOUT_MS = 60000
const MAX_RETRIES = 2

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
    onError
}) {
    const mediaRecorder = useRef(null)
    const audioChunks = useRef([])
    const streamRef = useRef(null)
    const stoppedRef = useRef(false)
    const mountedRef = useRef(false)

    const cleanup = useCallback(() => {
        cleanupStream(streamRef.current)
        streamRef.current = null
    }, [])

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
            mountedRef.current
        ) {
            await new Promise(r => setTimeout(r, 1000))

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

        let stream
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true,
                    channelCount: 1,
                    sampleRate: 48000,
                },
            })
        } catch (err) {
            if (!mountedRef.current) return
            failAndSkip('Mikrofon xatosi')
            return
        }

        if (!mountedRef.current) {
            cleanupStream(stream)
            return
        }

        streamRef.current = stream
        const mimeType = getSupportedMimeType()
        const options = mimeType ? { mimeType } : {}
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
    }, [cleanup, handleUploadResult])

    useEffect(() => {
        registerStop?.(stopRecording)
    }, [registerStop, stopRecording])

    return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
            <div style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background: '#16A34A',
                animation: 'pulse 1s infinite',
            }} />
            <button className="btn btn-danger" onClick={stopRecording}>
                To'xtatish
            </button>
        </div>
    )
}
