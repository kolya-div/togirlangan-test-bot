export default function QuestionCard({ question, questionNumber, totalQuestions, progressPercent }) {
    const images = question.image_path ? question.image_path.split('|') : []
    const pros = question.pro_points ? question.pro_points.split('\n') : []
    const cons = question.con_points ? question.con_points.split('\n') : []
    const hasDebate = pros.length > 0 || cons.length > 0
    const rowsCount = Math.max(pros.length, cons.length)

    return (
        <div className="question-card">
            <div className="question-panel">
                <span className="q-label">Soru #{questionNumber}</span>
                <div className="question-progress-bar">
                    <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${progressPercent}%` }}></div>
                    </div>
                    <span>{questionNumber}/{totalQuestions}</span>
                </div>
            </div>
            <div className="question-body-card">
                {question.max_points != null && (
                    <div className="ball-badge">⭐ {question.max_points} ball</div>
                )}

                {question.text && (
                    <div className="question-text">{question.text}</div>
                )}

                {!question.text && images.length > 0 && !hasDebate && (
                    <div className="image-caption">Bu resimde ne görüyorsunuz?</div>
                )}

                {images.map(src => (
                    <img
                        key={src}
                        src={`/audios/${src}`}
                        alt="Savol rasmi"
                        className="question-image"
                    />
                ))}

                {hasDebate && (
                    <div className="debate-table">
                        <div className="dt-row dt-head">
                            <div className="dt-cell pro">🟢 Lehine</div>
                            <div className="dt-cell con">🔴 Aleyhine</div>
                        </div>
                        {Array.from({ length: rowsCount }, (_, i) => (
                            <div className="dt-row" key={i}>
                                <div className="dt-cell">{pros[i] || ''}</div>
                                <div className="dt-cell">{cons[i] || ''}</div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    )
}
