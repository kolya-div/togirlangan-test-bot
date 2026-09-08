import { notifyTestClosed } from '../api.js'

function ScoreBar({ label, value, max }) {
    const pct = max > 0 ? Math.round((value / max) * 100) : 0
    return (
        <div className="score-bar-row">
            <span className="score-bar-label">{label}</span>
            <div className="score-bar-track">
                <div className="score-bar-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="score-bar-value">{value}/{max}</span>
        </div>
    )
}

function MistakeItem({ mistake, index }) {
    const typeLabels = {
        grammar: 'Grammatika',
        spelling: 'Imlo',
        suffix: 'Qo\'shimcha',
        word_order: 'So\'z tartibi',
        word_choice: 'So\'z tanlash',
        meaning: 'Ma\'no',
    }
    return (
        <div className="mistake-item">
            <span className="mistake-num">{index + 1}</span>
            <div className="mistake-content">
                <div className="mistake-words">
                    <span className="mistake-original">{mistake.original}</span>
                    <span className="mistake-arrow">→</span>
                    <span className="mistake-correct">{mistake.correct}</span>
                </div>
                <div className="mistake-meta">
                    <span className="mistake-type">{typeLabels[mistake.type] || mistake.type}</span>
                    {mistake.explanation_uz && (
                        <span className="mistake-explanation">{mistake.explanation_uz}</span>
                    )}
                </div>
            </div>
        </div>
    )
}

function QuestionResult({ item, index, total }) {
    const s = item.scores || {}
    const hasMistakes = item.mistakes && item.mistakes.length > 0

    return (
        <div className="result-card">
            <div className="result-card-header">
                <span className="result-card-num">{index + 1}/{total}</span>
                <span className="result-card-section">{item.question_section}.{item.question_order}</span>
                {item.score != null && (
                    <span className="result-card-score">{item.score}%</span>
                )}
            </div>

            <div className="result-card-question">{item.question_text}</div>

            <div className="result-card-section-block">
                <div className="result-card-label">Siz aytdingiz:</div>
                <div className="result-card-transcript">{item.transcript || '—'}</div>
            </div>

            {item.corrected_text && item.corrected_text !== item.transcript && (
                <div className="result-card-section-block">
                    <div className="result-card-label">Tuzatilgan:</div>
                    <div className="result-card-corrected">{item.corrected_text}</div>
                </div>
            )}

            <div className="result-card-status">
                {item.is_grammatically_correct ? (
                    <span className="status-badge status-ok">Grammatika to'g'ri</span>
                ) : (
                    <span className="status-badge status-err">Grammatik xatolar bor</span>
                )}
            </div>

            {hasMistakes && (
                <div className="result-card-section-block">
                    <div className="result-card-label">Xatolar ({item.mistakes.length}):</div>
                    <div className="mistakes-list">
                        {item.mistakes.map((m, i) => (
                            <MistakeItem key={i} mistake={m} index={i} />
                        ))}
                    </div>
                </div>
            )}

            {Object.keys(s).length > 0 && (
                <div className="result-card-section-block">
                    <div className="result-card-label">Ballar:</div>
                    <div className="scores-grid">
                        {s.grammar != null && <ScoreBar label="Grammatika" value={s.grammar} max={25} />}
                        {s.vocabulary != null && <ScoreBar label="So'z boyligi" value={s.vocabulary} max={25} />}
                        {s.pronunciation != null && <ScoreBar label="Talaffuz" value={s.pronunciation} max={20} />}
                        {s.sentence_structure != null && <ScoreBar label="Gap tuzilishi" value={s.sentence_structure} max={15} />}
                        {s.relevance != null && <ScoreBar label="Moslik" value={s.relevance} max={15} />}
                    </div>
                </div>
            )}

            {item.strengths && item.strengths.length > 0 && (
                <div className="result-card-section-block">
                    <div className="result-card-label">Kuchli tomonlar:</div>
                    <ul className="strengths-list">
                        {item.strengths.map((s, i) => <li key={i}>{s}</li>)}
                    </ul>
                </div>
            )}

            {item.feedback_uz && (
                <div className="result-card-section-block">
                    <div className="result-card-label">Umumiy fikr:</div>
                    <div className="result-card-feedback">{item.feedback_uz}</div>
                </div>
            )}
        </div>
    )
}

export default function Results({ result, resultsData, loading, onClose, attemptId }) {
    const isProcessing = result?.processing && !resultsData

    const handleClose = () => {
        const id = attemptId || resultsData?.attempt_id
        if (id) notifyTestClosed(id).catch(() => {})
        onClose()
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, width: '100%' }}>
            <div className="card" style={{ textAlign: 'center', padding: '32px 20px' }}>
                <div className="results-emoji">🎉</div>
                <div className="results-title">Test tugadi!</div>

                <div className="results-box">
                    {isProcessing ? (
                        <div className="results-processing">
                            <div style={{ fontSize: 32, marginBottom: 8 }}>⏳</div>
                            <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
                                Javoblaringiz tahlil qilinmoqda...
                            </div>
                            <div>
                                Yakuniy ball va tahlil natijalari
                                bir necha daqiqada <b>Telegram botga</b> yuboriladi.
                            </div>
                            <div style={{ marginTop: 8, fontWeight: 700 }}>
                                Yozuvlar soni: {result?.total_answers || 0}
                            </div>
                        </div>
                    ) : resultsData ? (
                        <>
                            <div className="result-row">
                                <span className="result-emoji">🏅</span>
                                <span className="result-label">Ball:</span>
                                <span className="result-value">{resultsData.total_score || 0}/{resultsData.max_score || 75}</span>
                            </div>
                            <div className="result-row">
                                <span className="result-emoji">📊</span>
                                <span className="result-label">Daraja:</span>
                                <span className="result-value">{resultsData.level || 'B1 talabiga yetmadi'}</span>
                            </div>
                            <div className="result-row">
                                <span className="result-emoji">📝</span>
                                <span className="result-label">Jami javoblar:</span>
                                <span className="result-value">{resultsData.results?.length || 0}</span>
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="result-row">
                                <span className="result-emoji">🏅</span>
                                <span className="result-label">Ball:</span>
                                <span className="result-value">{result?.score || 0}/{result?.max_score || 75}</span>
                            </div>
                            <div className="result-row">
                                <span className="result-emoji">📊</span>
                                <span className="result-label">Daraja:</span>
                                <span className="result-value">{result?.level || 'B1 talabiga yetmadi'}</span>
                            </div>
                            <div className="result-row">
                                <span className="result-emoji">📝</span>
                                <span className="result-label">Jami javoblar:</span>
                                <span className="result-value">{result?.total_answers || 0}</span>
                            </div>
                        </>
                    )}
                </div>

                <div className="note-block" style={{ marginBottom: 16 }}>
                    <span className="note-emoji">💡</span>
                    <span className="note-text">
                        Natijalarni <b>Telegram botdan</b> ham ko'rishingiz mumkin.
                    </span>
                </div>

                <button className="btn btn-primary" onClick={handleClose}>
                    Yopish <span className="btn-arrow">→</span>
                </button>
            </div>

            {loading && (
                <div className="card" style={{ textAlign: 'center', padding: 24 }}>
                    <div className="loader" style={{ margin: '0 auto 12px' }}></div>
                    <div style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>
                        Batafsil natijalar yuklanmoqda...
                    </div>
                </div>
            )}

            {resultsData && resultsData.results && resultsData.results.length > 0 && (
                <div className="results-detail-section">
                    <div className="results-detail-title">Savol bo'yicha natijalar</div>
                    {resultsData.results.map((item, i) => (
                        <QuestionResult
                            key={item.answer_id}
                            item={item}
                            index={i}
                            total={resultsData.results.length}
                        />
                    ))}
                </div>
            )}

            <div className="footer">
                <div className="footer-logo">🎓</div>
                <div className="footer-name">Evren VİP Konuşma Bot</div>
                <a href="#" className="footer-link">@evrenvip_bot</a>
            </div>
        </div>
    )
}
