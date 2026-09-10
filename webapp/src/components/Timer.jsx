export default function Timer({ timeLeft, phase, formatTime, prepSeconds, answerSeconds }) {
    const isPrep = phase === 'prep'
    const isRecord = phase === 'record'
    const maxSeconds = isPrep ? prepSeconds : answerSeconds
    const percentage = maxSeconds > 0 ? ((maxSeconds - timeLeft) / maxSeconds) * 100 : 0
    const dashOffset = 339.292 - (339.292 * percentage) / 100

    return (
        <div className={`timer-section ${isPrep ? 'prep' : 'rec'}`}>
            <div className={`timer-circle ${isPrep ? 'prep' : 'rec'}`}>
                <svg
                    width="120"
                    height="120"
                    viewBox="0 0 120 120"
                    style={{ position: 'absolute', inset: 0, transform: 'rotate(-90deg)' }}
                >
                    <circle
                        cx="60"
                        cy="60"
                        r="54"
                        fill="none"
                        stroke="#D4DDD5"
                        strokeWidth="4"
                    />
                    <circle
                        cx="60"
                        cy="60"
                        r="54"
                        fill="none"
                        stroke={isPrep ? '#22C55E' : '#16A34A'}
                        strokeWidth="4"
                        strokeLinecap="round"
                        strokeDasharray="339.292"
                        strokeDashoffset={dashOffset}
                        style={{ transition: 'stroke-dashoffset 1s linear' }}
                    />
                </svg>
                <span className="timer-value">{formatTime(timeLeft)}</span>
            </div>

            <div className={`timer-status ${isPrep ? 'prep' : ''}`}>
                {isPrep ? '📋 TAYYORLANISH' : '🎙️ KONUŞMA — Yozib olinmoqda'}
            </div>

            {isRecord && (
                <div className="timer-bottom-bar">
                    <span className="timer-label">Timer: {formatTime(timeLeft)}</span>
                    <span className="rec-dot">
                        <span className="dot"></span>
                        KAYIT
                    </span>
                </div>
            )}

            {isRecord && (
                <div className="waveform-bar">
                    {Array.from({ length: 18 }, (_, i) => (
                        <div key={i} className="wave-line" style={{ animationDelay: `${(i * 0.07)}s` }}></div>
                    ))}
                </div>
            )}
        </div>
    )
}
