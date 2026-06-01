from app.models.schemas import AnalysisResult

_sessions: dict[str, AnalysisResult] = {}


def save(result: AnalysisResult) -> None:
    _sessions[result.session_id] = result


def get(session_id: str) -> AnalysisResult | None:
    return _sessions.get(session_id)


def delete(session_id: str) -> bool:
    return _sessions.pop(session_id, None) is not None
