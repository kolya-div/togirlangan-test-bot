from pydantic import BaseModel


class QuestionSchema(BaseModel):
    id: int
    section: str
    order_number: int
    text: str
    preparation_seconds: int
    answer_seconds: int
    image_path: str | None = None
    pro_points: str | None = None
    con_points: str | None = None


class AnswerUploadSchema(BaseModel):
    attempt_id: int
    question_id: int
    filename: str


class EvaluationSchema(BaseModel):
    score: int
    level: str
    mistakes: list[dict]
    strengths: list[str]
    feedback_uz: str
    feedback_tr: str


class AnswerResultSchema(BaseModel):
    answer_id: int
    question_id: int
    question_text: str
    question_section: str
    question_order: int
    max_points: int | None
    transcript: str
    corrected_text: str
    is_grammatically_correct: bool
    mistakes: list[dict]
    scores: dict
    score_reasons: list[dict]
    strengths: list[str]
    feedback_uz: str
    feedback_tr: str
    score: int | None


class AttemptResultSchema(BaseModel):
    attempt_id: int
    total_score: int | None
    max_score: int
    level: str | None
    status: str
    results: list[AnswerResultSchema]