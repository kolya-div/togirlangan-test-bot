import { useState, useEffect, useRef, useCallback } from 'react'
import QuestionCard from './components/QuestionCard.jsx'
import Timer from './components/Timer.jsx'
import AudioRecorder from './components/AudioRecorder.jsx'
import { fetchQuestions, createAttempt, uploadAnswer, finishAttempt, initWebApp } from './api.js'

function formatTime(sec) {
    const m = Math.floor(sec / 60).toString().padStart(2, '0')
    const s = (sec % 60).toString().padStart(2, '0')
    return `${m}:${s}`
}

const FINISH_MAX_RETRIES = 3
const FINISH_RETRY_DELAY = 3000

export default function App() {
    const [questions, setQuestions] = useState([])
    const [current, setCurrent] = useState(-1)
    const [phase, setPhase] = useState('idle')
    const [timeLeft, setTimeLeft] = useState(0)
    const [attemptId, setAttemptId] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    // Natijalar foydalanuvchiga ko'rsatilmaydi (faqat admin .docx da) —
    // test tugagach faqat "javoblaringiz qabul qilindi" ekrani chiqadi.
    const [finished, setFinished] = useState(false)
    const [attemptStatus, setAttemptStatus] = useState(null)
    const [startingTest, setStartingTest] = useState(false)
    const [entryDialog, setEntryDialog] = useState(null)

    // Avtorizatsiya: user_id faqat Telegram imzosi bilan tasdiqlangan
    // initData dan (backend POST /api/init orqali) olinadi. Frontend
    // initDataUnsafe ga ishonmaydi.
    const tg = window.Telegram?.WebApp
    const initData = typeof tg?.initData === 'string' ? tg.initData : ''
    const [initChecked, setInitChecked] = useState(false)
    const [initUser, setInitUser] = useState(null)
    const [initRejected, setInitRejected] = useState(false)

    const timerRef = useRef(null)
    const stopRecorderRef = useRef(null)
    const mountedRef = useRef(true)

    useEffect(() => {
        mountedRef.current = true
        return () => { mountedRef.current = false }
    }, [])

    useEffect(() => {
        tg?.expand()
        tg?.ready()

        // ★ Route guard: Test komponenti hech qachon backend tasdig'isiz
        // render bo'lmaydi. Mount bo'lishi bilan avtorizatsiya + status
        // tekshiriladi; finished/processing bo'lsa test ko'rsatilmaydi.
        initWebApp(initData)
            .then(init => {
                if (!mountedRef.current) return
                setInitUser(init.user_id)

                const status = init.status
                if (status === 'finished' || status === 'processing') {
                    setInitChecked(true)
                    setFinished(true)
                    setLoading(false)
                    return
                }
                if (status === 'active') {
                    // Test allaqachon boshlangan — "Testni boshlash" tugmasi
                    // faqat bir marta ishlatiladi. Qayta kirish mumkin emas.
                    setInitChecked(true)
                    setAttemptStatus('active')
                    setLoading(false)
                    // Questions xali yuklab olinadi, lekin test ko'rsatilmaydi
                } else {
                    // No attempt yoki registered=False
                    setInitChecked(true)
                    setLoading(false)
                }
            })
            .catch(err => {
                if (!mountedRef.current) return
                setInitChecked(true)
                setLoading(false)
                if (err.status === 401) {
                    setInitRejected(true)
                    setError('Avtorizatsiya yaroqsiz yoki eskirgan. Botdan qayta oching.')
                } else {
                    setError(err.message)
                }
            })

        let retries = 0
        const maxRetries = 3

        const loadQuestions = () => {
            fetchQuestions()
                .then(data => {
                    if (!mountedRef.current) return
                    if (!data || data.length === 0) {
                        throw new Error('Savollar topilmadi')
                    }
                    setQuestions(data)
                    setLoading(false)
                })
                .catch(err => {
                    if (!mountedRef.current) return
                    retries++
                    if (retries < maxRetries) {
                        setTimeout(loadQuestions, 1500)
                    } else {
                        setError(err.message)
                        setLoading(false)
                    }
                })
        }

        loadQuestions()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    const startTest = async () => {
        if (startingTest) return
        setStartingTest(true)

        try {
            // start_param imzolanmagan va ishonchsiz — chat_id faqat
            // UX ("Test yakunlandi" xabari) uchun ishlatiladi, avtorizatsiya
            // qaroriga aslo ishlatilmaydi.
            const startParam = tg?.initDataUnsafe?.start_param
            const chatId = startParam ? Number(startParam) || null : null
            const attempt = await createAttempt(initData, chatId)
            if (!mountedRef.current) return
            setAttemptId(attempt.id)

            if (attempt.status === 'finished' || attempt.status === 'processing') {
                setFinished(true)
                return
            }

            // active — qayta kirish/progressni tekshirish
            setAttemptId(attempt.id)
            const answered = new Set(attempt.answered_question_ids || [])
            const nextIndex = questions.findIndex(q => !answered.has(q.id))

            if (answered.size === 0) {
                // Javob yozilmagan — yangidan boshlash xavfsiz
                setCurrent(0)
                setPhase('prep')
                return
            }

            if (nextIndex === -1) {
                // Barcha savollarga javob berilgan — yakunlash kerak
                setEntryDialog({ mode: 'finish', attemptId: attempt.id })
                return
            }

            // Qayta kirish — testni boshidan boshlatmaymiz
            setEntryDialog({ mode: 'continue', nextIndex })
        } catch (e) {
            if (!mountedRef.current) return
            if (e.limitReached) {
                if (e.attemptStatus === 'active') {
                    // Test boshlangan (0 javob bo'lsa ham) — qayta boshlab bo'lmaydi
                    setError('Siz allaqachon bu testni boshlagansiz. Qayta kirish mumkin emas.')
                } else {
                    setFinished(true)
                }
            } else if (e.message.includes('403') || e.message.includes('allaqachon')) {
                setFinished(true)
            } else {
                setError(e.message)
            }
        } finally {
            if (mountedRef.current) setStartingTest(false)
        }
    }

    const startTimer = useCallback((seconds, onDone) => {
        let remaining = seconds
        setTimeLeft(remaining)
        clearInterval(timerRef.current)
        timerRef.current = setInterval(() => {
            remaining--
            setTimeLeft(remaining)
            if (remaining <= 0) {
                clearInterval(timerRef.current)
                onDone()
            }
        }, 1000)
    }, [])

    useEffect(() => {
        if (phase === 'prep' && current >= 0) {
            startTimer(questions[current].preparation_seconds, () => {
                setPhase('record')
            })
        }
        if (phase === 'record' && current >= 0) {
            startTimer(questions[current].answer_seconds, () => {
                stopRecorderRef.current?.()
            })
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [phase, current])

    const moveToNextQuestion = useCallback(() => {
        clearInterval(timerRef.current)
        if (current + 1 < questions.length) {
            setCurrent(prev => prev + 1)
            setPhase('prep')
        } else {
            finishTest()
        }
    }, [current, questions.length, attemptId])

    const finishTest = useCallback(async (attemptIdOverride = null, retryCount = 0) => {
        const aid = attemptIdOverride ?? attemptId
        clearInterval(timerRef.current)
        setPhase('uploading')

        try {
            await finishAttempt(aid, initData)
            if (!mountedRef.current) return
            setFinished(true)
        } catch (e) {
            if (!mountedRef.current) return

            // 409 — allaqachon tugallangan
            if (e.message.includes('409')) {
                setFinished(true)
                return
            }

            // Avtomatik qayta urinish
            if (retryCount < FINISH_MAX_RETRIES) {
                await new Promise(r => setTimeout(r, FINISH_RETRY_DELAY))
                finishTest(aid, retryCount + 1)
            } else {
                setError('Testni yakunlab bo\'lmadi. Iltimos, botga /start yozing.')
            }
        }
    }, [attemptId, initData])

    const handleRecordingStop = useCallback(() => {
        moveToNextQuestion()
    }, [moveToNextQuestion])

    const handleRecordingError = useCallback(() => {
        // Xato bo'lsa — avtomatik keyingi savolga o't (skip qil)
        moveToNextQuestion()
    }, [moveToNextQuestion])

    if (loading) {
        return (
            <div className="center">
                <div className="loader"></div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="app-wrapper">
                <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                    <div style={{ fontSize: 40, marginBottom: 12 }}>❌</div>
                    <div style={{ fontWeight: 700, color: 'var(--danger)', fontSize: 16 }}>{error}</div>
                </div>
            </div>
        )
    }

    if (finished) {
        return (
            <div className="app-wrapper">
                <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                    <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
                    <div style={{ fontWeight: 700, fontSize: 16 }}>Test yakunlandi!</div>
                    <div style={{ color: 'var(--text-secondary)', marginTop: 8 }}>
                        Javoblaringiz qabul qilindi. Rahmat!
                    </div>
                    <button
                        className="btn btn-outline"
                        style={{ marginTop: 16, width: '100%' }}
                        onClick={() => tg?.close()}
                    >
                        Yopish
                    </button>
                </div>
            </div>
        )
    }

    if (attemptStatus === 'active' && !finished) {
        // Test allaqachon boshlangan — qayta kirish taqiqlanadi
        return (
            <div className="app-wrapper">
                <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                    <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
                    <div style={{ fontWeight: 700, fontSize: 16 }}>
                        Siz allaqachon bu testni boshlagansiz.
                    </div>
                    <div style={{ color: 'var(--text-secondary)', marginTop: 8 }}>
                        "Testni boshlash" tugmasi faqat bir marta ishlatilishi mumkin.
                    </div>
                    <button
                        className="btn btn-outline"
                        style={{ marginTop: 16, width: '100%' }}
                        onClick={() => tg?.close()}
                    >
                        Yopish
                    </button>
                </div>
            </div>
        )
    }

    if (entryDialog) {
        if (entryDialog.mode === 'continue') {
            return (
                <div className="app-wrapper">
                    <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                        <div style={{ fontSize: 40, marginBottom: 12 }}>⚠️</div>
                        <div style={{ fontWeight: 700, fontSize: 16 }}>
                            Siz allaqachon testni boshlagansiz.
                        </div>
                        <div style={{ color: 'var(--text-secondary)', marginTop: 8 }}>
                            Testning yozilmagan qismidan davom ettiriladi.
                        </div>
                        <button
                            className="btn btn-primary"
                            style={{ marginTop: 16, width: '100%' }}
                            onClick={() => {
                                setCurrent(entryDialog.nextIndex)
                                setPhase('prep')
                                setEntryDialog(null)
                            }}
                        >
                            Testni davom ettirish <span className="btn-arrow">→</span>
                        </button>
                        <button
                            className="btn btn-outline"
                            style={{ marginTop: 8, width: '100%' }}
                            onClick={() => tg?.close()}
                        >
                            Yopish
                        </button>
                    </div>
                </div>
            )
        }

        if (entryDialog.mode === 'finish') {
            const started = !!entryDialog.started
            return (
                <div className="app-wrapper">
                    <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                        {started ? (
                            <>
                                <div className="loader"></div>
                                <div style={{ fontWeight: 700, fontSize: 16, marginTop: 12 }}>
                                    Javoblar yuborilmoqda...
                                </div>
                            </>
                        ) : (
                            <>
                                <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
                                <div style={{ fontWeight: 700, fontSize: 16 }}>
                                    Siz barcha savollarga javob berdingiz.
                                </div>
                                <div style={{ color: 'var(--text-secondary)', marginTop: 8 }}>
                                    Javoblaringizni yuborish uchun testni yakunlang.
                                </div>
                                <button
                                    className="btn btn-primary"
                                    style={{ marginTop: 16, width: '100%' }}
                                    onClick={() => {
                                        setEntryDialog({ mode: 'finish', attemptId: entryDialog.attemptId, started: true })
                                        finishTest(entryDialog.attemptId)
                                    }}
                                >
                                    Testni yakunlash
                                </button>
                                <button
                                    className="btn btn-outline"
                                    style={{ marginTop: 8, width: '100%' }}
                                    onClick={() => tg?.close()}
                                >
                                    Yopish
                                </button>
                            </>
                        )}
                    </div>
                </div>
            )
        }
    }

    if (current === -1) {
        return (
            <div className="app-wrapper">
                <div className="header">
                    <div className="header-logo">🎙️</div>
                    <h1>Turk Tili Speaking Test</h1>
                    <div className="subtitle">Milliy sertifikat darslari</div>
                </div>

                <div className="card">
                    <div className="bullet-list">
                        <div className="bullet-list-title">SINAV TARTIBI</div>
                        <div className="bullet-item">
                            <span className="bullet-dot">•</span>
                            <div>
                                <span className="bullet-label">Tayyorlanish — </span>
                                <span className="bullet-desc">Savolni o'qib tayyorlanish vaqti</span>
                            </div>
                        </div>
                        <div className="bullet-item">
                            <span className="bullet-dot">•</span>
                            <div>
                                <span className="bullet-label">Yozib olish — </span>
                                <span className="bullet-desc">Javobingizni ovozda yozib yuboring</span>
                            </div>
                        </div>
                        <div className="bullet-item">
                            <span className="bullet-dot">•</span>
                            <div>
                                <span className="bullet-label">Yakunlash — </span>
                                <span className="bullet-desc">Javoblaringiz tekshirish uchun yuboriladi</span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="note-block">
                    <span className="note-emoji">🎧</span>
                    <span className="note-text">
                        <b>Muhim:</b> Testni boshlashdan oldin <b>mikrofon</b> ruxsatini bering.
                        Barcha savollarga <b>ovozda javob</b> bering.
                    </span>
                </div>

                <div className="alert-warning">
                    <div className="alert-icon"></div>
                    <div className="alert-text">
                        Savollar soni: {questions.length} ta
                    </div>
                </div>

                <button
                    className="btn btn-primary"
                    onClick={startTest}
                    disabled={startingTest}
                    style={{
                        opacity: startingTest ? 0.6 : 1,
                        cursor: startingTest ? 'not-allowed' : 'pointer',
                    }}
                >
                    {startingTest ? (
                        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                            <span className="loader" style={{ width: 16, height: 16, borderWidth: 2 }}></span>
                            Yuklanmoqda...
                        </span>
                    ) : (
                        <>Testni boshlash <span className="btn-arrow">→</span></>
                    )}
                </button>

                <div className="footer">
                    <div className="footer-logo">🎓</div>
                    <div className="footer-name">Step Academy</div>
                    <a href="#" className="footer-link">@stepacademy</a>
                    <div className="footer-dev">dasturchi: @Kpakona</div>
                </div>
            </div>
        )
    }

    const q = questions[current]
    const totalQuestions = questions.length
    const progressPercent = ((current) / totalQuestions) * 100

    return (
        <div className="app-wrapper">
            {/* Progress Steps */}
            <div className="progress-steps">
                {questions.map((_, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center' }}>
                        <div className={`step-circle ${i < current ? 'done' : ''} ${i === current ? 'active' : ''}`}>
                            {i < current ? '✓' : i + 1}
                        </div>
                        {i < questions.length - 1 && (
                            <div className={`step-line ${i < current ? 'done' : ''}`}></div>
                        )}
                    </div>
                ))}
            </div>

            {/* Question Card */}
            <QuestionCard
                question={q}
                questionNumber={current + 1}
                totalQuestions={totalQuestions}
                progressPercent={progressPercent}
            />

            {/* Timer */}
            <Timer
                timeLeft={timeLeft}
                phase={phase}
                formatTime={formatTime}
                prepSeconds={q.preparation_seconds}
                answerSeconds={q.answer_seconds}
            />

            {/* Phase Status */}
            {phase === 'prep' && (
                <div className="phase-status prep">
                    Tayyorlanish — Savolni o'qing
                </div>
            )}

            {phase === 'record' && (
                <>
                    <div className="phase-status record">
                        Ovoz yozilmoqda...
                    </div>
                    <AudioRecorder
                        attemptId={attemptId}
                        questionId={q.id}
                        initData={initData}
                        onUploaded={handleRecordingStop}
                        registerStop={(fn) => { stopRecorderRef.current = fn }}
                        onError={handleRecordingError}
                    />
                </>
            )}

            {phase === 'uploading' && (
                <div className="phase-status uploading">
                    Yuklanmoqda...
                </div>
            )}
        </div>
    )
}
